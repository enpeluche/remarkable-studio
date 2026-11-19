"""Cadrage automatique des PDF : couper les marges gauche et droite (texte plus gros sur la tablette).

Le cadrage est le « Ajuster la vue > personnalisé » de la tablette (échelle + centre, valable pour tout le
document), enregistré par Formes.qml (LibraryController.setCustomZoomFit). Seuls les PDF encore en vue par
défaut (« bestFit ») sont cadrés ; un document réglé à la main n'est jamais modifié.

Repères : PDF placé à 227 dpi, centré en x = 0, haut en y = 0 ; échelle = pixels de l'écran par unité de page.
"""
import json
import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

DPI = 30                      # rendu de mesure (basse résolution : rapide)
K = 227 / 72                  # points PDF -> unités de page
SCREEN_W, SCREEN_H = 1404, 1872
PAD = 0.03                    # marge gardée de chaque côté (fraction de la largeur du texte)
MIN_GAIN = 1.08               # en dessous de +8 % de taille, pas de cadrage


def _page_sizes(pdf):
    out = subprocess.run(["pdfinfo", "-f", "1", "-l", "100000", str(pdf)], capture_output=True, text=True,
                         timeout=60).stdout
    sizes = []
    for line in out.splitlines():
        if line.startswith("Page") and "size:" in line:
            v = line.split("size:")[1].split()
            sizes.append((float(v[0]), float(v[2])))
    return sizes


def _ink_columns(png):
    """Bornes horizontales et verticales de l'encre d'une page (fractions de la page), ou None si vide."""
    im = Image.open(png).convert("L")
    w, h = im.size
    px = im.load()
    cols = [0] * w
    rows = [0] * h
    for y in range(h):
        for x in range(w):
            if px[x, y] < 200:
                cols[x] += 1
                rows[y] += 1
    # quelques pixels isolés (poussière d'un scan, filet) ne comptent pas
    cmin, rmin = max(1, h // 200), max(1, w // 200)
    xs = [x for x, c in enumerate(cols) if c >= cmin]
    ys = [y for y, c in enumerate(rows) if c >= rmin]
    if not xs or not ys:
        return None
    return xs[0] / w, (xs[-1] + 1) / w, ys[0] / h, (ys[-1] + 1) / h


def measure(pdf, samples=8):
    """Zone imprimée commune aux pages (fractions de la page) et taille de page, ou None."""
    sizes = _page_sizes(pdf)
    if not sizes:
        return None
    n = len(sizes)
    # format principal = le plus fréquent (un cadrage vaut pour tout le document)
    w0, h0 = statistics.mode((round(s[0]), round(s[1])) for s in sizes)
    same = lambda s: abs(s[0] - w0) <= 0.03 * w0 and abs(s[1] - h0) <= 0.03 * h0     # scans : tailles à peine différentes
    if sum(1 for s in sizes if same(s)) < 0.8 * n:
        return None                                   # formats trop mélangés : pas de cadrage commun
    if w0 > h0:
        return None                                   # page en paysage : déjà large, rien à gagner
    # pages échantillonnées, sans la première (couverture) quand il y en a assez
    idx = sorted({min(n - 1, int(i * n / samples)) for i in range(samples)} - ({0} if n > 3 else set()))
    boxes = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in idx:
            if not same(sizes[i]):
                continue                              # page d'un autre format
            base = Path(tmp) / f"p{i}"
            subprocess.run(["pdftoppm", "-f", str(i + 1), "-l", str(i + 1), "-r", str(DPI), "-gray", "-png",
                            "-singlefile", str(pdf), str(base)], capture_output=True, timeout=60)
            if base.with_suffix(".png").exists():
                b = _ink_columns(base.with_suffix(".png"))
                if b:
                    boxes.append(b)
    if not boxes:
        return None
    # union : ne jamais couper de texte sur les pages mesurées
    return {"x0": min(b[0] for b in boxes), "x1": max(b[1] for b in boxes),
            "y0": min(b[2] for b in boxes), "y1": max(b[3] for b in boxes),
            "w_pt": w0, "h_pt": h0, "pages": len(boxes)}


def framing(m):
    """Cadrage (échelle, centre, taille de page) pour une zone mesurée, ou None si le gain est trop faible."""
    W, H = m["w_pt"] * K, m["h_pt"] * K               # page en unités de page
    best = min(SCREEN_W / W, SCREEN_H / H)            # vue par défaut (page entière)
    cw = (m["x1"] - m["x0"]) * W
    scale = SCREEN_W / (cw * (1 + 2 * PAD))
    if scale < best * MIN_GAIN:
        return None
    cx = -W / 2 + (m["x0"] + m["x1"]) / 2 * W
    vis_h = SCREEN_H / scale                          # hauteur visible (unités de page)
    top = max(0.0, m["y0"] * H - cw * PAD)
    cy = top + vis_h / 2                              # haut du texte en haut de l'écran
    if (m["y1"] - m["y0"]) * H <= vis_h:              # le texte tient en hauteur : centré
        cy = (m["y0"] + m["y1"]) / 2 * H
    return {"scale": round(scale, 4), "cx": round(cx, 1), "cy": round(cy, 1), "w": round(W), "h": round(H),
            "gain": round(scale / best, 3)}


if __name__ == "__main__":       # essai : python cadrage.py fichier.pdf ...
    import sys
    for f in sys.argv[1:]:
        m = measure(Path(f))
        print(Path(f).name[:40], json.dumps(m and {k: round(v, 3) if isinstance(v, float) else v for k, v in m.items()}),
              json.dumps(m and framing(m)))


# ---------------------------------------------------------------- automatique (dans le serveur)
import threading
import time

STATE_FILE = Path(__file__).resolve().parent / "cadrage.json"
SETTINGS = Path(__file__).resolve().parent / "reglages.json"


def _load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(path)


class Cadreur:
    """Cadre les PDF de la tablette encore en « page entière » et jamais cadrés.

    cadrage.json : {uid: {"etat": "fait" | "aucun" | "envoye" | "echec", "cadrage": {...}, "t": ...}}
      - aucun  : rien à gagner (paysage, formats mélangés, marges étroites) ;
      - envoye : commande envoyée, en attente de confirmation (zoomMode « customFit » dans la sauvegarde) ;
      - fait   : confirmé ; jamais retouché ensuite, même si l'utilisateur revient en page entière ;
      - echec  : pas confirmé après 3 envois.
    """

    def __init__(self, lib, current, send):
        self.lib, self.current, self.send = lib, current, send
        self.lock = threading.Lock()
        self.last = {"t": 0, "faits": 0, "attente": 0, "erreur": None}
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def enabled(self):
        return _load(SETTINGS, {}).get("cadrage_auto", True)

    def set_enabled(self, on):
        s = _load(SETTINGS, {})
        s["cadrage_auto"] = bool(on)
        _save(SETTINGS, s)

    def _zoom_mode(self, uid):
        return _load(self.lib.root / f"{uid}.content", {}).get("zoomMode")

    def run_once(self):
        with self.lock:
            st = _load(STATE_FILE, {})
            changed = False
            # 1) confirmations : le document enregistre « customFit » (sauvegarde synchronisée)
            for uid, e in st.items():
                if e.get("etat") == "envoye":
                    if self._zoom_mode(uid) == "customFit":
                        e["etat"] = "fait"; changed = True
                    elif time.time() - e.get("t", 0) > 600:
                        # commande perdue (fichier de commandes réécrit entre-temps) : 3 essais au plus
                        e["essais"] = e.get("essais", 1) + 1
                        e["etat"] = "a_envoyer" if e["essais"] <= 3 else "echec"
                        changed = True
            # 2) mesures des nouveaux PDF (une fois par document)
            for uid, it in list(self.lib.snapshot().items()):
                if it["type"] != "pdf" or it.get("parent") == "trash" or uid in st:
                    continue
                if self._zoom_mode(uid) not in (None, "bestFit"):
                    st[uid] = {"etat": "aucun", "raison": "vue réglée à la main", "t": time.time()}; changed = True
                    continue
                pdf = self.lib.root / f"{uid}.pdf"
                if not pdf.exists():
                    continue
                try:
                    m = measure(pdf)
                    f = framing(m) if m else None
                except Exception as ex:
                    f, m = None, {"erreur": str(ex)}
                if f:
                    st[uid] = {"etat": "a_envoyer", "cadrage": f, "t": time.time()}
                else:
                    st[uid] = {"etat": "aucun", "t": time.time()}
                changed = True
                _save(STATE_FILE, st)
            # 3) envoi groupé, seulement quand un document est ouvert sur la tablette (Formes.qml écoute alors)
            todo = [(u, e) for u, e in st.items() if e["etat"] == "a_envoyer"]
            vue = self.current.get()
            if todo and not vue.get("error") and (vue.get("pen") or {}).get("doc"):
                lst = [dict(e["cadrage"], doc=u) for u, e in todo[:40]]
                lst = [{k: z[k] for k in ("doc", "scale", "cx", "cy", "w", "h")} for z in lst]
                if self.send({"action": "zoomFit", "list": lst}):
                    for u, e in todo[:40]:
                        e["etat"] = "envoye"; e["t"] = time.time()
                    changed = True
            if changed:
                _save(STATE_FILE, st)
            self.last.update(t=time.time(), faits=sum(1 for e in st.values() if e["etat"] == "fait"),
                             attente=sum(1 for e in st.values() if e["etat"] in ("a_envoyer", "envoye")))

    def _loop(self):
        time.sleep(20)
        while True:
            if self.enabled:
                try:
                    self.run_once()
                    self.last["erreur"] = None
                except Exception as e:
                    self.last["erreur"] = str(e)
            time.sleep(30)
