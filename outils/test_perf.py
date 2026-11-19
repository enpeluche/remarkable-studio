#!/usr/bin/env python3
"""Test de performance du PC : temps de réponse du serveur et coût de l'image en direct dans le Studio.

À lancer serveur démarré (et tablette branchée pour la partie Studio). Échoue si un seuil est dépassé.
La partie Studio pilote un Chromium sans interface (paquet python « websocket-client » requis) ; sans eux,
elle est sautée.

Usage : python outils/test_perf.py [--url http://127.0.0.1:8765] [--sans-navigateur]
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

# seuils (ms)
SEUILS = {"route": 300, "page_en_cache": 150, "image_en_direct": 40}


def get(url):
    t = time.perf_counter()
    with urllib.request.urlopen(url, timeout=60) as r:
        body = r.read()
    return (time.perf_counter() - t) * 1000, body


def serveur(base):
    res = []
    state = json.loads(get(base + "/api/live/state")[1])
    doc, page = state.get("doc"), state.get("page")
    routes = [("bibliothèque", "/api/library", "route"), ("état de la tablette (page affichée)", "/api/live/state", "route"),
              ("version de la bibliothèque", "/api/library/version", "route")]
    if doc:
        get(f"{base}/api/page/{doc}/{page}")                      # remplit le cache
        routes += [("page affichée (en cache)", f"/api/page/{doc}/{page}", "page_en_cache"),
                   ("annotations du document", f"/api/annotations/{doc}", "route"),
                   ("texte de la page", f"/api/text/{doc}/{page}", "route")]
    for nom, path, seuil in routes:
        ms = min(get(base + path)[0] for _ in range(3))
        res.append((nom, ms, SEUILS[seuil]))
    return res


def studio(base):
    try:
        import websocket
    except ImportError:
        return None, "module websocket-client absent"
    exe = next((e for e in ("chromium-browser", "chromium", "google-chrome") if shutil.which(e)), None)
    if not exe:
        return None, "Chromium absent"
    tmp = tempfile.mkdtemp(prefix="perf-")
    p = subprocess.Popen([exe, "--headless=new", "--remote-debugging-port=9347", "--window-size=1400,1000",
                          f"--user-data-dir={tmp}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9347/json"))
                break
            except Exception:
                time.sleep(0.3)
        ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
        n, erreurs = [0], []

        def call(m, **pr):
            n[0] += 1
            ws.send(json.dumps({"id": n[0], "method": m, "params": pr}))
            while True:
                r = json.loads(ws.recv())
                if r.get("method") == "Runtime.exceptionThrown":
                    erreurs.append(r["params"]["exceptionDetails"].get("exception", {}).get("description", "")[:160])
                if r.get("id") == n[0]:
                    return r.get("result")

        call("Runtime.enable")
        call("Network.enable")
        call("Network.setCacheDisabled", cacheDisabled=True)
        call("Page.navigate", url=base + "/studio")
        for _ in range(60):                                       # attendre que la page du Studio soit chargée
            v = call("Runtime.evaluate", expression="typeof drawLiveFrame === 'function'", returnByValue=True)
            if v["result"].get("value"):
                break
            time.sleep(0.25)
        else:
            return {"erreur": "le Studio ne se charge pas"}, erreurs
        js = """(async () => {
          for (let i = 0; i < 40 && !(liveEl && !liveEl.hidden && frameVue.map && $('#scr').naturalWidth); i++)
            await new Promise(r => setTimeout(r, 500));
          if (!(liveEl && !liveEl.hidden)) return JSON.stringify({erreur: 'zone en direct absente'});
          liveBg.key = '';
          let t = performance.now(); drawLiveFrame(); const premiere = performance.now() - t;
          t = performance.now(); for (let i = 0; i < 10; i++) drawLiveFrame();
          return JSON.stringify({premiere, suivante: (performance.now() - t) / 10});
        })()"""
        res = call("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in res:
            return {"erreur": res["exceptionDetails"].get("exception", {}).get("description", "exception")[:200]}, erreurs
        return json.loads(res["result"].get("value") or '{"erreur": "pas de mesure"}'), erreurs
    finally:
        p.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--sans-navigateur", action="store_true")
    a = ap.parse_args()
    ok = True
    print(f"{'mesure':42s} {'ms':>7s}  seuil")
    for nom, ms, seuil in serveur(a.url):
        bon = ms <= seuil
        ok &= bon
        print(f"{nom:42s} {ms:7.0f}  {seuil}  {'' if bon else 'TROP LENT'}")
    if not a.sans_navigateur:
        r, info = studio(a.url)
        if r is None:
            print(f"Studio : sauté ({info})")
        elif "erreur" in r:
            print(f"Studio : {r['erreur']}")
            ok = False
        else:
            bon = r["suivante"] <= SEUILS["image_en_direct"]
            ok &= bon
            print(f"{'Studio : image en direct (suivantes)':42s} {r['suivante']:7.0f}  {SEUILS['image_en_direct']}  "
                  f"{'' if bon else 'TROP LENT'}")
            print(f"{'Studio : image en direct (après changement de vue)':42s} {r['premiere']:7.0f}  -")
            if info:
                ok = False
                print("Erreurs JavaScript :", *info, sep="\n  ")
    print("RÉSULTAT :", "dans les seuils" if ok else "à corriger")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
