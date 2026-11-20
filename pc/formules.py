"""Formules LaTeX : rendu en image (TeX Live du PC) et envoi sur la tablette, où elles sont insérées
comme image dans la page (Formes.qml, action « placeImage » : on touche l'endroit voulu avec le stylet).
"""
import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from live import RM_HOST, SSH_OPTS

CACHE = Path(__file__).resolve().parent / ".cache" / "latex"
TABLET_DIR = "/home/root/xovi/formes"
TABLET_DPI = 226                      # résolution de l'écran de la RM2 : 1 px d'image = 1 px d'écran

PREAMBLE = r"""\documentclass[preview,border=3pt]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb,amsfonts,mathtools,bm}
\begin{document}
"""


def _doc(latex, display):
    body = latex.strip()
    if display:
        body = r"$\displaystyle " + body + "$"
    else:
        body = "$" + body + "$"
    return PREAMBLE + body + "\n\\end{document}\n"


def _error(log):
    """Premier message d'erreur lisible du journal LaTeX."""
    lines = log.splitlines()
    for i, l in enumerate(lines):
        if l.startswith("!"):
            ctx = " ".join(x.strip() for x in lines[i + 1:i + 3] if x.strip())
            return (l[1:].strip() + (" — " + ctx if ctx else ""))[:300]
    return "erreur de compilation"


def render(latex, display=True, scale=1.5):
    """Renvoie (png_bytes, largeur, hauteur) ; lève ValueError avec le message LaTeX en cas d'erreur."""
    if not latex or not latex.strip():
        raise ValueError("formule vide")
    if len(latex) > 4000:
        raise ValueError("formule trop longue")
    dpi = int(round(TABLET_DPI * max(0.5, min(6.0, float(scale)))))
    src = _doc(latex, display)
    key = hashlib.sha256(f"{dpi}|{src}".encode()).hexdigest()[:24]
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}.png"
    if not out.exists():
        with tempfile.TemporaryDirectory(prefix="rmlatex-") as tmp:
            t = Path(tmp)
            (t / "f.tex").write_text(src, encoding="utf-8")
            try:
                # pas d'exécution de commandes externes (-no-shell-escape), arrêt à la première erreur
                r = subprocess.run(["latex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "f.tex"],
                                   cwd=t, capture_output=True, timeout=20)
            except subprocess.TimeoutExpired:
                raise ValueError("compilation trop longue (20 s)")
            if r.returncode != 0 or not (t / "f.dvi").exists():
                log = (t / "f.log").read_text(errors="replace") if (t / "f.log").exists() else r.stdout.decode(errors="replace")
                raise ValueError(_error(log))
            r = subprocess.run(["dvipng", "-D", str(dpi), "-T", "tight", "-bg", "White", "-fg", "Black",
                                "-o", "f.png", "f.dvi"], cwd=t, capture_output=True, timeout=20)
            if r.returncode != 0 or not (t / "f.png").exists():
                raise ValueError("conversion en image impossible")
            out.write_bytes((t / "f.png").read_bytes())
    data = out.read_bytes()
    w, h = _png_size(data)
    return data, w, h


def _png_size(data):
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def send(latex, display=True, scale=1.5, pos=None):
    """Rend la formule, la copie sur la tablette, puis l'insère en pos (x, y écran) ou lance le placement au stylet."""
    data, w, h = render(latex, display, scale)
    name = f"formule-{hashlib.sha256(data).hexdigest()[:16]}.png"
    remote = f"{TABLET_DIR}/{name}"
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"mkdir -p {TABLET_DIR} && cat > {remote}"],
                       input=data, capture_output=True, timeout=20)
    if r.returncode != 0:
        raise RuntimeError("copie sur la tablette impossible")
    if pos is not None:
        cmd = json.dumps({"id": int(time.time() * 1000), "action": "image", "file": remote, "x": pos[0], "y": pos[1]})
    else:
        cmd = json.dumps({"id": int(time.time() * 1000), "action": "placeImage", "file": remote, "w": w, "h": h})
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, "cat > /home/root/xovi/crayons/formes-cmd.json"],
                       input=cmd.encode(), capture_output=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError("commande de placement impossible")
    return {"w": w, "h": h, "file": remote}


# ---------------------------------------------------------------- formule en traits (lettres pleines)
# LaTeX -> DVI -> SVG (dvisvgm --no-fonts : chaque lettre est un tracé) -> polygones -> traits :
# contour de chaque lettre + remplissage en zigzag (lignes horizontales serrées, enchaînées tant qu'elles se
# chevauchent : une chaîne ne sort jamais de la lettre). Unités : pixels de l'image au même dpi que render()
# (1 px = 1 unité de page de la tablette, comme l'image insérée).
import math
import xml.etree.ElementTree as ET

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_TOK = re.compile(r"[MmLlHhVvCcSsQqTtZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _path_polys(d, tol=0.05):
    """Tracé SVG -> liste de polygones fermés (sous-chemins), courbes aplaties."""
    toks = _TOK.findall(d)
    polys, cur, i = [], [], 0
    x = y = sx = sy = 0.0
    cmd = None
    last_c = None                               # dernier point de contrôle (S, T)

    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v

    def bez(p0, p1, p2, p3):
        n = max(2, int(math.hypot(p3[0] - p0[0], p3[1] - p0[1]) / tol / 8) + 2)
        n = min(n, 24)
        for k in range(1, n + 1):
            t = k / n; u = 1 - t
            cur.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t; i += 1
            if cmd in "Zz":
                if len(cur) > 2: polys.append(cur)
                cur = []; x, y = sx, sy; last_c = None
                continue
        rel = cmd.islower(); C = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if C == "M":
            if len(cur) > 2: polys.append(cur)
            x, y = ox + num(), oy + num(); sx, sy = x, y; cur = [(x, y)]
            cmd = "l" if rel else "L"; last_c = None
        elif C == "L":
            x, y = ox + num(), oy + num(); cur.append((x, y)); last_c = None
        elif C == "H":
            x = ox + num(); cur.append((x, y)); last_c = None
        elif C == "V":
            y = oy + num(); cur.append((x, y)); last_c = None
        elif C == "C":
            p1 = (ox + num(), oy + num()); p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            bez((x, y), p1, p2, p3); x, y = p3; last_c = p2
        elif C == "S":
            p1 = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
            p2 = (ox + num(), oy + num()); p3 = (ox + num(), oy + num())
            bez((x, y), p1, p2, p3); x, y = p3; last_c = p2
        elif C in "QT":
            if C == "Q": q = (ox + num(), oy + num())
            else: q = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
            p3 = (ox + num(), oy + num())
            bez((x, y), (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y)),
                (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1])), p3)
            x, y = p3; last_c = q
        else:
            i += 1
    if len(cur) > 2: polys.append(cur)
    return polys


def _fill(polys, step):
    """Remplissage pair-impair d'une lettre par lignes horizontales tous les `step`, enchaînées en zigzag."""
    ys = [p[1] for poly in polys for p in poly]
    if not ys: return []
    y0, y1 = min(ys), max(ys)
    edges = [(a, b) for poly in polys for a, b in zip(poly, poly[1:] + poly[:1]) if a[1] != b[1]]
    chains, active = [], []                     # active : [(chaîne, (xa, xb) du dernier segment)]
    y = y0 + step / 2
    flip = False
    while y < y1:
        xs = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    for a, b in edges if min(a[1], b[1]) <= y < max(a[1], b[1]))
        segs = [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2) if xs[k + 1] - xs[k] > step * 0.3]
        nxt = []
        for xa, xb in segs:
            m = next((c for c in active if c[1][0] < xb and xa < c[1][1] and c not in nxt), None)
            pts = [(xb, y), (xa, y)] if flip else [(xa, y), (xb, y)]
            if m:
                m[0].extend(pts); nxt.append((m[0], (xa, xb)))
                active.remove(m)
            else:
                ch = list(pts); chains.append(ch); nxt.append((ch, (xa, xb)))
        active = nxt
        flip = not flip
        y += step
    return [c for c in chains if len(c) >= 2]


def vector(latex, display=True, scale=1.5, step=1.4):
    """-> (traits [[(x, y), ...], ...], largeur, hauteur) en pixels au dpi de render() ; origine en haut à gauche."""
    if not latex or not latex.strip():
        raise ValueError("formule vide")
    dpi = TABLET_DPI * max(0.5, min(6.0, float(scale)))
    src = _doc(latex, display)
    with tempfile.TemporaryDirectory(prefix="rmlatex-") as tmp:
        t = Path(tmp)
        (t / "f.tex").write_text(src, encoding="utf-8")
        r = subprocess.run(["latex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "f.tex"],
                           cwd=t, capture_output=True, timeout=20)
        if r.returncode != 0 or not (t / "f.dvi").exists():
            log = (t / "f.log").read_text(errors="replace") if (t / "f.log").exists() else ""
            raise ValueError(_error(log))
        r = subprocess.run(["dvisvgm", "--no-fonts", "--exact-bbox", "-o", "f.svg", "f.dvi"], cwd=t,
                           capture_output=True, timeout=20)
        if not (t / "f.svg").exists():
            raise ValueError("conversion vectorielle impossible")
        root = ET.fromstring((t / "f.svg").read_bytes())
    ns = {"s": "http://www.w3.org/2000/svg"}
    XL = "{http://www.w3.org/1999/xlink}href"
    vb = [float(v) for v in root.get("viewBox").split()]
    k = dpi / 72                                 # unités du SVG (pt PostScript) -> pixels
    defs = {p.get("id"): _path_polys(p.get("d")) for p in root.iter("{http://www.w3.org/2000/svg}path") if p.get("id")}
    traits = []

    def add_glyph(polys):
        pp = [[((x - vb[0]) * k, (y - vb[1]) * k) for x, y in poly] for poly in polys]
        for poly in pp:
            traits.append(poly + [poly[0]])      # contour
        traits.extend(_fill(pp, step))

    for u in root.iter("{http://www.w3.org/2000/svg}use"):
        ref = (u.get(XL) or u.get("href") or "").lstrip("#")
        if ref in defs:
            dx, dy = float(u.get("x", 0)), float(u.get("y", 0))
            add_glyph([[(x + dx, y + dy) for x, y in poly] for poly in defs[ref]])
    for rc in root.iter("{http://www.w3.org/2000/svg}rect"):
        x, y, w, h = (float(rc.get(a, 0)) for a in ("x", "y", "width", "height"))
        add_glyph([[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]])
    return traits, vb[2] * k, vb[3] * k
