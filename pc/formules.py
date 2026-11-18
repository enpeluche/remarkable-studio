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
