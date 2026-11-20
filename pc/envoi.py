"""File d'envoi du PC vers la tablette : rien de ce que le PC demande ne se perd si la tablette est absente.

Chaque demande est enregistrée sur le disque (envoi.json, fichiers joints dans envoi/), puis exécutée dès que
possible et retirée de la file seulement quand la tablette a confirmé. Le PC et la tablette fonctionnent chacun
sans l'autre ; la tablette reste la référence pour son contenu (le PC la recopie : autosync.py).

Types :
  marks   : surligner / souligner / barrer du texte d'une page (Formes.qml, commande « marks »).
            Demande faite à l'instant sur le PC (« directe ») : la page est ouverte sur la tablette si un document
            y est affiché. Sinon (tablette absente, demande ancienne) : tracé quand la page est affichée sur la
            tablette — jamais de changement de page imposé pour un rattrapage.
  upload  : PDF / EPUB à importer (interface web USB de la tablette : USB requis).
  links   : liste des carnets liés à copier sur la tablette (seule la dernière compte).
  palette : palette de couleurs partagée (seule la dernière compte).

États : attente -> fait | abandon (raison : document ou page supprimés, fichier refusé…).
"""
import json
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import annots
import tablet

HERE = Path(__file__).resolve().parent
FILE = HERE / "envoi.json"
FILES = HERE / "envoi"
LIVE_DELAY = 60          # une demande « directe » plus ancienne devient un rattrapage (pas de changement de page)
KEEP_DONE = 7 * 86400    # entrées terminées gardées une semaine (historique), puis oubliées


class Envoi:
    def __init__(self, lib, current, sync, upload):
        """upload(nom, données) -> (ok, message) : import par l'interface web USB (serveur)."""
        self.lib, self.current, self.sync, self.upload = lib, current, sync, upload
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.entries = self._load()
        FILES.mkdir(exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------ stockage
    def _load(self):
        try:
            return json.loads(FILE.read_text())
        except Exception:
            return []

    def _save(self):
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1))
        tmp.replace(FILE)

    def add(self, typ, **data):
        with self.lock:
            if typ in ("links", "palette"):                 # seule la dernière version compte
                for e in self.entries:
                    if e["type"] == typ and e["etat"] == "attente":
                        e.update(etat="remplace", fin=time.time())
            e = {"id": uuid.uuid4().hex[:12], "type": typ, "etat": "attente", "cree": time.time(), "essais": 0,
                 "erreur": None, **data}
            self.entries.append(e)
            self._save()
        self.wake.set()
        return e

    def add_upload(self, name, data):
        e = self.add("upload", nom=name, taille=len(data), fichier=None)
        f = FILES / f"{e['id']}{Path(name).suffix.lower()}"
        f.write_bytes(data)
        with self.lock:
            e["fichier"] = f.name
            self._save()
        self.wake.set()
        return e

    def cancel(self, eid):
        with self.lock:
            for e in self.entries:
                if e["id"] == eid and e["etat"] == "attente":
                    e.update(etat="annule", fin=time.time())
                    self._cleanup_file(e)
                    self._save()
                    return True
        return False

    def wait(self, eid, timeout):
        """Attend qu'une demande soit terminée (fait / abandon) ; renvoie l'entrée (peut être encore en attente)."""
        end = time.time() + timeout
        while time.time() < end:
            e = self.get(eid)
            if not e or e["etat"] != "attente" or e.get("en_attente_de"):
                return e
            time.sleep(0.3)
        return self.get(eid)

    def reply(self, e, timeout):
        """Réponse au navigateur : attend l'issue quelques secondes ; sinon la demande reste en file (jamais perdue)."""
        r = self.wait(e["id"], timeout) or e
        if r["etat"] == "fait":
            return {"ok": True, "id": r["id"], "message": r.get("message") or "fait"}
        if r["etat"] == "abandon":
            return {"ok": False, "id": r["id"], "error": r.get("erreur") or "abandonné"}
        attente = r.get("en_attente_de") or "la tablette"
        return {"ok": True, "queued": True, "id": r["id"], "message": f"en attente : {attente}"}

    def summary(self, doc=None):
        """File pour l'affichage : demandes en attente (et ce qu'elles attendent), abandons des dernières 24 h."""
        keep = ("id", "type", "doc", "page", "kind", "rects", "couleur", "nom", "cree", "essais", "erreur", "en_attente_de")
        with self.lock:
            sel = [e for e in self.entries if doc is None or e.get("doc") == doc]
            att = [{k: e.get(k) for k in keep} for e in sel if e["etat"] == "attente"]
            ab = [{k: e.get(k) for k in keep} for e in sel if e["etat"] == "abandon" and time.time() - e.get("fin", 0) < 86400]
        return {"attente": att, "abandons": ab}

    def get(self, eid):
        with self.lock:
            return next((dict(e) for e in self.entries if e["id"] == eid), None)

    def pending(self, doc=None):
        with self.lock:
            return [dict(e) for e in self.entries if e["etat"] == "attente" and (doc is None or e.get("doc") == doc)]

    def _cleanup_file(self, e):
        if e.get("fichier"):
            (FILES / e["fichier"]).unlink(missing_ok=True)

    # ------------------------------------------------------------ exécution
    def _loop(self):
        while True:
            self.wake.wait(timeout=5)
            self.wake.clear()
            try:
                self.run_once()
            except Exception as ex:                      # ne jamais arrêter la file
                print(f"envoi : erreur {ex}", flush=True)

    def run_once(self):
        with self.lock:
            todo = [e for e in self.entries if e["etat"] == "attente"]
            # oubli des entrées terminées anciennes
            n = len(self.entries)
            self.entries = [e for e in self.entries if e["etat"] == "attente" or time.time() - e.get("fin", e["cree"]) < KEEP_DONE]
            if len(self.entries) != n:
                self._save()
        if not todo:
            return
        st = self.current.get()
        reachable = not st.get("error")
        for e in sorted(todo, key=lambda e: e["cree"]):
            if self.get(e["id"])["etat"] != "attente":
                continue
            try:
                if e["type"] == "marks":
                    self._marks(e, st, reachable)
                elif not reachable:
                    self._note(e, "tablette non connectée")
                elif e["type"] == "links":
                    r = tablet.push_links()
                    self._done(e) if r.get("pushed") else self._retry(e, "copie impossible")
                elif e["type"] == "palette":
                    self._done(e) if tablet.push_palette() else self._retry(e, "copie impossible")
                elif e["type"] == "upload":
                    self._upload(e)
            except Exception as ex:
                self._retry(e, f"erreur : {ex}")

    def _update(self, e, **kw):
        with self.lock:
            for x in self.entries:
                if x["id"] == e["id"]:
                    x.update(kw)
                    e.update(kw)
            self._save()

    def _done(self, e, msg=None):
        self._cleanup_file(e)
        self._update(e, etat="fait", fin=time.time(), erreur=None, message=msg, en_attente_de=None)

    def _abandon(self, e, why):
        self._cleanup_file(e)
        self._update(e, etat="abandon", fin=time.time(), erreur=why, en_attente_de=None)

    def _retry(self, e, why):
        self._update(e, essais=e.get("essais", 0) + 1, erreur=why)

    def _note(self, e, waiting):
        """Rien à faire pour l'instant : on note ce qu'on attend (affiché sur le PC)."""
        if e.get("en_attente_de") != waiting:
            self._update(e, en_attente_de=waiting)

    def _upload(self, e):
        if tablet.status().get("link") != "usb":
            return self._note(e, "câble USB (l'import passe par l'interface web USB)")
        f = FILES / (e.get("fichier") or "")
        if not f.is_file():
            return self._abandon(e, "fichier introuvable")
        ok, msg = self.upload(e["nom"], f.read_bytes())
        if ok:
            self._done(e, msg)
        elif e.get("essais", 0) >= 3:
            self._abandon(e, msg)
        else:
            self._retry(e, msg)

    def _marks(self, e, st, reachable):
        item = self.lib.snapshot().get(e["doc"])
        if not item:
            return self._abandon(e, "document supprimé")
        ids = [p["id"] for p in item["pages"]]
        if e.get("page_id") and e["page_id"] in ids:
            n = ids.index(e["page_id"])
        elif e.get("page_id"):
            return self._abandon(e, "page supprimée")
        else:
            n = e["page"]
            if n >= len(ids):
                return self._abandon(e, "page supprimée")
        if not reachable:
            return self._note(e, "tablette non connectée")
        shown = st.get("doc") == e["doc"] and st.get("page") == n
        live = time.time() - e["cree"] < LIVE_DELAY and e.get("direct")
        if not shown:
            if not (st.get("pen") or {}).get("doc"):
                return self._note(e, "un document ouvert sur la tablette")
            if not live:
                return self._note(e, f"l'ouverture de la page {n + 1} sur la tablette")
            # demande directe : la page est ouverte sur la tablette
            tablet.open_document(e["doc"], n)
            end = time.time() + 10
            while time.time() < end:
                time.sleep(0.8)
                self.current.t = 0
                st = self.current.get()
                if st.get("doc") == e["doc"] and st.get("page") == n:
                    break
            else:
                return self._retry(e, "la page ne s'est pas ouverte sur la tablette")
            time.sleep(1.5)                              # bandeau de titre, rendu : affichage stabilisé
        if e.get("essais", 0) and e.get("kind") == "highlight" and self._already_there(e, n):
            return self._done(e, "déjà présent sur la tablette")
        pid = item["pages"][n]["id"]
        if e.get("kind") == "highlight" and e.get("rects"):
            # d'abord le surlignage accroché au texte, tracé sur place (rapide, vrai surlignage de la tablette) ;
            # ligne hors de l'écran ou sous l'interface : méthode du gabarit (droites copiées), qui marche partout
            ok, msg = tablet.formes_run({"action": "snapmarks", "page": pid, "tool": 18,
                                         "argb": e["pen"].get("argb"), "rects": e["rects"]})
            if ok:
                return self._done(e, msg)
            if msg == "autre page affichée":
                return self._note(e, f"l'ouverture de la page {n + 1} sur la tablette")
        cmd = {"action": "marks", "page": pid, "pen": e["pen"], "segs": e["segs"]}
        ok, msg = tablet.formes_run(cmd)
        if ok:
            self._done(e, msg)
        elif msg == "autre page affichée":               # page quittée entre-temps : pas un échec, on attend
            self._note(e, f"l'ouverture de la page {n + 1} sur la tablette")
        else:
            self._retry(e, msg)
            if e.get("essais", 0) >= 5:
                self._abandon(e, msg)

    def _already_there(self, e, n):
        """Après un essai sans réponse, la marque a peut-être été tracée quand même : la chercher dans la page
        synchronisée (pas de doublon)."""
        try:
            self.sync.run_once()
            rm = self.lib.root / e["doc"] / f"{e.get('page_id')}.rm"
            if not rm.exists():
                return False
            items, _ = annots.page_annotations(rm.read_bytes(), [], e.get("page_id", ""))
            bands = [r for a in items if a["kind"] == "highlight" for r in a["rects"]]
            for x0, y0, x1, y1, _w in e["segs"]:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if not any(bx <= cx <= bx + bw and by <= cy <= by + bh for bx, by, bw, bh in bands):
                    return False
            return bool(e["segs"])
        except Exception:
            return False
