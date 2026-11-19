#!/usr/bin/env python3
"""Test complet des formes sur la tablette (droite, rectangle, cercle, ellipse, grille, polygone, axes).

À lancer avec une page de TEST ouverte (carnet ou PDF jetable), stylet éloigné de l'écran.
Le script vérifie que la page n'a pas changé entre chaque forme, oublie les gabarits (pour tester aussi leur
fabrication), construit chaque forme par la commande « build » de Formes.qml, attend la fin dans le journal
de xochitl, puis compte les éléments présents dans la zone de la forme (diag, lecture seule).

Usage : python outils/test_formes.py [--hote root@10.11.99.1] [--page <pageId attendu>] [--garder-gabarits]
Code de sortie : 0 si tout est bon.
"""
import argparse
import json
import re
import subprocess
import sys
import time

CMD = "/home/root/xovi/crayons/formes-cmd.json"
VUE = "/home/root/xovi/formes/vue.json"
ELEMS = re.compile(r"FORMES (\d+) éléments en (\d+) ms")

# formes : (nom, commande build en coordonnées de l'écran physique, zone de contrôle [x, y, w, h] écran)
FORMES = [
    ("droite", {"shape": "line", "ax": 200, "ay": 330, "bx": 600, "by": 330}, [170, 300, 460, 60]),
    ("rectangle", {"shape": "rect", "ax": 800, "ay": 250, "bx": 1200, "by": 450}, [770, 220, 460, 260]),
    ("cercle", {"shape": "circle", "ax": 400, "ay": 720, "bx": 550, "by": 720}, [220, 540, 360, 360]),
    ("ellipse", {"shape": "ellipse", "ax": 1000, "ay": 720, "bx": 1150, "by": 720, "minor": 80}, [820, 610, 360, 220]),
    ("grille", {"shape": "grid", "ax": 200, "ay": 980, "bx": 560, "by": 1280, "spacing": 60}, [170, 950, 420, 360]),
    ("polygone", {"shape": "polygon", "ax": 800, "ay": 980, "bx": 1150, "by": 1280, "sides": 6}, [770, 950, 410, 360]),
    ("axes", {"shape": "axes", "ax": 200, "ay": 1420, "bx": 700, "by": 1760, "spacing": 60}, [170, 1390, 560, 400]),
]


class Tablette:
    def __init__(self, hote):
        self.ssh = ["ssh", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/rm-test-formes-%r@%h",
                    "-o", "ControlPersist=60", hote]

    def run(self, cmd):
        return subprocess.run(self.ssh + [cmd], capture_output=True, text=True, timeout=60).stdout

    def vue(self):
        return json.loads(self.run(f"cat {VUE}"))

    def commande(self, c):
        c = dict(c, id=int(time.time() * 1000))
        self.run(f"cat > {CMD} <<'EOF'\n{json.dumps(c)}\nEOF")

    def journal(self, depuis):
        return self.run(f"journalctl -u xochitl --since '@{depuis:.0f}' --no-pager -o cat | grep FORMES")

    def maintenant(self):
        return float(self.run("date +%s"))


def attendre(t, depuis, delai):
    """Attend la fin de la construction : renvoie (lignes du journal, nombre d'éléments construits ou None)."""
    fin = time.time() + delai
    log, n = "", None
    while time.time() < fin:
        time.sleep(1.5)
        log = t.journal(depuis)
        m = ELEMS.findall(log)
        n = int(m[-1][0]) if m else None
        if re.search(r"introuvable|sélection du gabarit|FORMES erreur|regroupement : erreur", log):
            return log, n
        if "forme regroupée" in log or "abandonn" in log or "recollage raté" in log:
            return log, n
        if n is not None and (n <= 1 or "zone déjà occupée" in log):   # pas de regroupement
            return log, n
    return log, n


def zone_page(vue, rect):
    """Zone de l'écran physique [x, y, w, h] -> rectangle englobant dans la page (zoom, défilement, paysage)."""
    ox, oy, ax, ay, bx, by = vue["map"]
    pts = []
    for px, py in ((rect[0], rect[1]), (rect[0] + rect[2], rect[1]), (rect[0], rect[1] + rect[3]),
                   (rect[0] + rect[2], rect[1] + rect[3])):
        pts.append((ox + (ax - ox) * px / 1404 + (bx - ox) * py / 1872, oy + (ay - oy) * px / 1404 + (by - oy) * py / 1872))
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    return [round(x0, 1), round(y0, 1), round(max(p[0] for p in pts) - x0, 1), round(max(p[1] for p in pts) - y0, 1)]


def compter(t, rect, depuis):
    t.commande({"action": "diag", "scene": zone_page(t.vue(), rect)})
    time.sleep(1.2)
    log = t.journal(depuis)
    m = re.findall(r"diag bas de page : (.*?) \| outil (\d+)", log)
    if not m:
        return None, None
    rects, outil = m[-1]
    return len(re.findall(r"QRect\(", rects)), int(outil)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hote", default="root@10.11.99.1")
    ap.add_argument("--page")
    ap.add_argument("--garder-gabarits", action="store_true")
    ap.add_argument("--formes", help="liste séparée par des virgules (par défaut toutes)")
    ap.add_argument("--effacer", action="store_true",
                    help="avant le test, efface les éléments des zones du test (page de TEST uniquement)")
    a = ap.parse_args()
    t = Tablette(a.hote)
    v0 = t.vue()
    page = a.page or v0["pageId"]
    if v0["pageId"] != page:
        sys.exit(f"page affichée {v0['pageId']} ≠ page attendue {page}")
    outil0 = v0["pen"]["tool"]
    ox, oy, ax, ay, bx, by = v0["map"]
    zoom = 1404 / max(1e-6, ((ax - ox) ** 2 + (ay - oy) ** 2) ** 0.5)
    print(f"page {page}, crayon {outil0}, zoom {zoom:.2f}, angle {v0.get('angle')}, "
          f"{'portrait' if v0.get('portrait') else 'paysage'}")
    if v0.get("mask"):
        print("(un Studio regarde : masque d'interface disponible)")
    if not a.garder_gabarits:
        t.commande({"action": "resetTemplates"})
        time.sleep(1)
    choix = set(a.formes.split(",")) if a.formes else None
    if a.effacer:
        for nom, _cmd, (x, y, w, h) in FORMES:
            if choix and nom not in choix:
                continue
            if t.vue()["pageId"] != page:
                sys.exit("ARRÊT : la page affichée a changé")
            n, _ = compter(t, [x, y, w, h], t.maintenant() - 1)
            if n:
                depuis = t.maintenant() - 1
                t.commande({"action": "deleteArea", "x0": x, "y0": y, "x1": x + w, "y1": y + h, "expect": n})
                time.sleep(4)
                print(f"{nom:10s} effacement : " + (re.findall(r"zone (?:NON )?effacée[^\x1b(]*", t.journal(depuis)) or ["?"])[-1])
    bilan = []
    for nom, cmd, zone in FORMES:
        if choix and nom not in choix:
            continue
        v = t.vue()
        if v["pageId"] != page:
            sys.exit(f"ARRÊT : la page affichée a changé ({v['pageId']})")
        if v["map"] != v0["map"]:
            sys.exit("ARRÊT : le zoom, le défilement ou l'orientation a changé pendant le test")
        avant, _ = compter(t, zone, t.maintenant() - 1)
        if avant:
            print(f"{nom:10s} zone déjà occupée ({avant} éléments) : ignorée")
            bilan.append((nom, False, "zone occupée"))
            continue
        depuis = t.maintenant() - 1
        t0 = time.time()
        t.commande(dict(cmd, action="build"))
        log, n = attendre(t, depuis, 60)
        apres, outil = compter(t, zone, depuis)
        erreurs = [l for l in log.splitlines() if re.search(r"introuvable|sélection du gabarit|erreur|abandonn|inattendu", l)]
        ok = bool(n) and apres is not None and apres >= 1 and outil == outil0 and not erreurs
        detail = f"{n} construits, {apres} dans la zone, crayon {outil}, {time.time() - t0:.1f} s"
        if "forme regroupée" in log:
            detail += ", regroupée"
        elif "recollage raté" in log:
            detail += ", NON regroupée (recollage raté, forme retracée)"
        print(f"{nom:10s} {'OK ' if ok else 'ÉCHEC'} {detail}")
        for l in erreurs:
            print("           " + re.sub(r"\x1b\[[0-9;]*m", "", l)[:200])
        bilan.append((nom, ok, detail))
    time.sleep(1.5)
    v = t.vue()
    reglage = lambda pen: {k: pen.get(k) for k in ("tool", "color", "argb", "thickness")}
    print(f"crayon final : {reglage(v['pen'])} (au départ {reglage(v0['pen'])})")
    ok = all(b[1] for b in bilan) and reglage(v["pen"]) == reglage(v0["pen"])
    print("RÉSULTAT :", "tout est bon" if ok else "des échecs")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
