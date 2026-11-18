"""Dessin à distance : injecte des événements de stylet dans /dev/input/event1 (Wacom) de la tablette.

Les traits sont créés par l'application de la tablette elle-même, avec le crayon actif.
Coordonnées en pixels écran portrait (0..1404 x 0..1872).
"""
import math
import random
import struct
import subprocess
import threading
import time

from live import RM_HOST, SSH_OPTS

MAXX, MAXY = 20966, 15725        # ABS_X : axe long (vertical écran), ABS_Y : axe court
W, H = 1404, 1872
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y, ABS_PRESSURE, ABS_DISTANCE, ABS_TILT_X, ABS_TILT_Y = 0, 1, 24, 25, 26, 27
BTN_TOOL_PEN, BTN_TOUCH = 320, 330


def ev(typ, code, value):
    return struct.pack("<IIHHi", 0, 0, typ, code, value)


SYN = ev(EV_SYN, 0, 0)


def to_wacom(sx, sy, orient=0):
    """Inverse de la conversion utilisée par la vue en direct (orientation 0 = portrait RM2)."""
    u, v = sx / W, sy / H
    if orient & 1:
        u = 1 - u
    if orient & 2:
        v = 1 - v
    return round((1 - v) * MAXX), round(u * MAXY)


# Script lancé sur la tablette : écrit chaque ligne (octets échappés en octal) dans l'entrée stylet,
# et "S<µs>" fait une pause. Le cadencement se fait donc sur la tablette, pas à travers SSH
# (sinon les points arrivent par paquets et la tablette en saute une partie).
REMOTE = ('exec 3>/dev/input/event1; '
          'while IFS= read -r l; do case "$l" in S*) usleep "${l#S}";; *) printf "$l" >&3;; esac; done')


def esc(data):
    return "".join("\\%03o" % b for b in data)


class Injector:
    _lock = threading.Lock()

    def __init__(self, orient=0):
        self.orient = orient
        self.proc = None

    def _open(self):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(["ssh", *SSH_OPTS, RM_HOST, REMOTE],
                                         stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _write(self, data, pause_us=0):
        line = esc(data) + "\n"
        if pause_us:
            line += f"S{int(pause_us)}\n"
        self.proc.stdin.write(line.encode())

    def _flush(self):
        self.proc.stdin.flush()

    def stroke(self, pts, pressure=0.6, step_us=7000, hold_ms=0):
        """pts : liste de (x, y) en pixels écran. Dessine un trait continu.
        hold_ms > 0 : garde le stylet immobile à la fin (geste « dessiner et maintenir ») pour que la
        tablette remplace le trait par une forme parfaite (droite, rectangle, cercle…)."""
        if len(pts) < 2:
            return
        with self._lock:
            self._open()
            p = max(1, min(4095, round(pressure * 4095)))
            x, y = to_wacom(*pts[0], self.orient)
            # approche du stylet (survol), puis contact
            self._write(ev(EV_KEY, BTN_TOOL_PEN, 1) + ev(EV_ABS, ABS_X, x) + ev(EV_ABS, ABS_Y, y)
                        + ev(EV_ABS, ABS_DISTANCE, 10) + ev(EV_ABS, ABS_PRESSURE, 0) + SYN, 30000)
            self._write(ev(EV_ABS, ABS_DISTANCE, 0) + ev(EV_ABS, ABS_PRESSURE, p) + ev(EV_KEY, BTN_TOUCH, 1) + SYN, step_us)
            # stylet posé immobile un instant : le lissage de la tablette démarre sur le bon point
            for _ in range(4):
                self._write(ev(EV_ABS, ABS_X, x) + ev(EV_ABS, ABS_Y, y) + ev(EV_ABS, ABS_PRESSURE, p) + SYN, step_us)
            for sx, sy in pts[1:]:
                x, y = to_wacom(sx, sy, self.orient)
                self._write(ev(EV_ABS, ABS_X, x) + ev(EV_ABS, ABS_Y, y) + ev(EV_ABS, ABS_PRESSURE, p) + SYN, step_us)
            # quelques échantillons immobiles en fin de trait : le lissage de la tablette rattrape le dernier point
            for _ in range(4):
                self._write(ev(EV_ABS, ABS_X, x) + ev(EV_ABS, ABS_Y, y) + ev(EV_ABS, ABS_PRESSURE, p) + SYN, step_us)
            # maintien immobile : la tablette détecte le geste et redresse la forme
            # Maintien imitant un vrai stylet (relevé sur un enregistrement) : appui fort (pression max),
            # léger tremblement (quelques unités du capteur, < 1 px), inclinaison, ~540 échantillons/s
            # envoyés par paquets de 5 ms. (Le noyau ignore les valeurs répétées à l'identique.)
            if hold_ms:
                rnd = random.Random(x * 31 + y)
                for i in range(int(hold_ms / 5)):
                    batch = b""
                    for _ in range(3):
                        batch += (ev(EV_ABS, ABS_X, x + rnd.randint(-8, 8)) + ev(EV_ABS, ABS_Y, y + rnd.randint(-8, 8))
                                  + ev(EV_ABS, ABS_PRESSURE, int(min(4095, p + (4095 - p) * min(1, i / 20))) - rnd.randint(0, 3))
                                  + ev(EV_ABS, ABS_TILT_X, 300 + rnd.randint(-2, 2)) + ev(EV_ABS, ABS_TILT_Y, 1400)
                                  + SYN)
                    self._write(batch, 5000)
            # lever le stylet puis l'éloigner
            self._write(ev(EV_ABS, ABS_PRESSURE, 0) + ev(EV_KEY, BTN_TOUCH, 0) + SYN, 20000)
            self._write(ev(EV_ABS, ABS_DISTANCE, 255) + ev(EV_KEY, BTN_TOOL_PEN, 0) + SYN, 40000)
            self._flush()

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=120)


def densify(pts, max_step=4.0):
    """Ajoute des points intermédiaires (le tracé de la tablette aime les petits pas)."""
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / max_step))
        out += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(1, n + 1)]
    return out


def line(x0, y0, x1, y1):
    return densify([(x0, y0), (x1, y1)])


def circle(cx, cy, r, n=None, overlap=0.03):
    """Cercle fermé ; se chevauche légèrement pour masquer la jonction début/fin."""
    n = n or max(24, int(2 * math.pi * r / 4))
    end = int(n * (1 + overlap))
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(end + 1)]
