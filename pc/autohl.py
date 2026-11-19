"""Surligneur à la taille du texte : pendant que le stylet survole une ligne de texte du PDF avec le surligneur
actif, son épaisseur est réglée pour que la bande ait la hauteur de la ligne (« 1 em »).

Mesuré sur la tablette : largeur de la bande (unités de page) = 30 x épaisseur du crayon.
Piloté par le PC (flux du stylet, page affichée, texte du PDF) : actif tant que le serveur tourne.
Réglage : reglages.json {"surligneur_auto": true}.
"""
import json
import queue
import statistics
import threading
import time
from pathlib import Path

import tablet

W, H = 1404, 1872
BAND_PER_THICKNESS = 30.0
FILL = 0.95                       # bande = 95 % de la hauteur des mots (comme le surlignage du Studio)
SETTINGS = Path(__file__).resolve().parent / "reglages.json"


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except Exception:
        return {}


class AutoHighlighter:
    def __init__(self, pen_stream, current, renderer):
        self.pen = pen_stream
        self.current = current
        self.renderer = renderer
        self.enabled = bool(load_settings().get("surligneur_auto", False))
        self.last = {"t": 0.0, "thickness": None, "line": None}
        self.hover = None                 # (x, y) capteur, dernier survol
        self.hover_t = 0.0
        self.lines_key = None
        self.lines = []
        self.thread = None
        if self.enabled:
            self._start()

    def set_enabled(self, on):
        self.enabled = bool(on)
        s = load_settings()
        s["surligneur_auto"] = self.enabled
        SETTINGS.write_text(json.dumps(s, indent=1))
        if self.enabled:
            self._start()

    def _start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        q = self.pen.subscribe()
        try:
            while self.enabled:
                try:
                    msg = q.get(timeout=1)
                except queue.Empty:
                    continue
                p = msg.get("p")
                if not p:
                    continue
                x, y, _pressure, flags = p
                if flags & 4 and not flags & 1:          # stylet proche, pas posé
                    self.hover, self.hover_t = (x, y), time.time()
                    if time.time() - self.last["t"] > 0.25:
                        self._evaluate()
        finally:
            self.pen.unsubscribe(q)

    def _page_lines(self, st):
        key = (st.get("doc"), st.get("page"), st.get("ver"))
        if key != self.lines_key:
            self.lines_key = key
            t = self.renderer.page_text(st["doc"], st["page"]) if st.get("doc") is not None else None
            self.lines = []
            for line in (t or {}).get("lines", []):
                x0 = min(w[0] for w in line); x1 = max(w[0] + w[2] for w in line)
                y0 = min(w[1] for w in line); y1 = max(w[1] + w[3] for w in line)
                h = statistics.median(w[3] for w in line)
                self.lines.append((x0, y0, x1, y1, h))
        return self.lines

    def _evaluate(self):
        self.last["t"] = time.time()
        st = self.current.get()
        pen = st.get("pen") or {}
        if pen.get("tool") != 18 or not isinstance(st.get("map"), list) or not self.hover:
            return
        # capteur -> écran physique -> page (correspondance écran -> page de vue.json)
        sx_, sy_ = self.hover
        px, py = sy_ / 15725 * W, (1 - sx_ / 20966) * H
        ox, oy, ax, ay, bx, by = st["map"]
        sx = ox + (ax - ox) * px / W + (bx - ox) * py / H
        sy = oy + (ay - oy) * px / W + (by - oy) * py / H
        best = None
        for x0, y0, x1, y1, h in self._page_lines(st):
            if x0 - 80 <= sx <= x1 + 80:
                d = 0 if y0 <= sy <= y1 else min(abs(sy - y0), abs(sy - y1))
                if d <= h and (best is None or d < best[0]):
                    best = (d, h, (round(y0), round(y1)))
        if best is None:
            return
        t = round(max(0.3, min(6.0, best[1] * FILL / BAND_PER_THICKNESS)), 2)
        if pen.get("thickness") is not None and abs(float(pen["thickness"]) - t) < 0.04:
            return
        # l'état du crayon (vue.json) arrive avec un peu de retard : ne pas renvoyer la même valeur en boucle
        if self.last["thickness"] == t and time.time() - self.last.get("sent", 0) < 3:
            return
        if tablet.formes_cmd({"action": "pen", "thickness": t}):
            self.last.update(thickness=t, line=best[2], sent=time.time())
