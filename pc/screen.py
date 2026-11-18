"""Écran réel de la tablette, en direct, en ménageant son processeur.

L'image affichée par xochitl se trouve dans sa mémoire, juste après la projection de /dev/fb0
(1404 x 1872 pixels, BGRA, à 8 octets du début de la zone). On la lit via /proc/<pid>/mem sur la
tablette, compressée (gzip -1), sur une connexion SSH permanente.

Capture pilotée par les événements (lire + compresser l'écran entier coûte ~0,45 s de processeur) :
  - pendant l'écriture : seulement la bande de lignes parcourue par la pointe (2 fois/s au plus) ;
  - à la fin d'un trait : image complète ;
  - quand la page affichée change (vue.json : page, zoom, défilement, menus) : image complète ;
  - au repos : une image de contrôle toutes les 15 s.
La boucle côté tablette met aussi à jour studio.watch : l'accroche Formes.qml ne calcule le masque
d'interface que lorsqu'un Studio regarde.
"""
import gzip
import json
import subprocess
import threading
import time
import io

from PIL import Image

from live import RM_HOST, SSH_OPTS

W, H = 1404, 1872
ROW = W * 4
FRAME = W * H * 4 + 8
BLOCKS = (FRAME + 4095) // 4096
VUE = "/home/root/xovi/formes/vue.json"

# Boucle côté tablette. Commandes (une par ligne) :
#   F            image complète          -> "taille\n" + gzip
#   B <bloc> <n> n blocs de 4 Ko à partir du bloc donné (relatif au début de la zone) -> idem
#   V            contenu de vue.json     -> "taille\n" + octets
REMOTE = (
    'while read -r c a b; do '
    'date +%s > /home/root/xovi/formes/studio.watch; '
    f'if [ "$c" = V ]; then wc -c < {VUE} 2>/dev/null || echo 0; cat {VUE} 2>/dev/null; continue; fi; '
    'P=$(pidof xochitl xochitl-libre | cut -d" " -f1); '
    'A=$(grep -A1 "/dev/fb0" /proc/$P/maps 2>/dev/null | tail -n 1 | cut -d- -f1); '
    'if [ -z "$A" ]; then echo 0; continue; fi; '
    f'if [ "$c" = B ]; then S=$a; N=$b; else S=0; N={BLOCKS}; fi; '
    'dd if=/proc/$P/mem bs=4096 skip=$((0x$A / 4096 + S)) count=$N 2>/dev/null | gzip -1 > /tmp/rmv-fb.gz; '
    'wc -c < /tmp/rmv-fb.gz; cat /tmp/rmv-fb.gz; '
    'done'
)


class ScreenStream:
    def __init__(self, pen=None):
        self.pen = pen
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.proc = None
        self.thread = None
        self.raw = None                 # image brute courante (BGRA, avec les 8 octets d'en-tête)
        self.png = None
        self.meta = "{}"                # page et correspondance écran -> page AU MOMENT de la capture
        self.frame_vue = {}
        self.seq = 0
        self.last_use = 0.0
        self.boost_until = 0.0
        self.error = None
        self.stats = {"full": 0, "band": 0, "reasons": {}}

    # -- côté serveur web
    def touch(self):
        self.last_use = time.time()
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()

    def boost(self, seconds=3.0):
        """Activité prévue (forme, formule, dessin envoyé) : images complètes rapprochées quelques secondes."""
        self.boost_until = max(self.boost_until, time.time() + seconds)

    def wait_frame(self, after, timeout=20):
        self.touch()
        with self.cond:
            self.cond.wait_for(lambda: self.seq > after, timeout=timeout)
            return self.seq, self.png, self.meta

    # -- échanges avec la tablette
    def _open(self):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(["ssh", *SSH_OPTS, RM_HOST, REMOTE],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def _ask(self, line):
        self._open()
        self.proc.stdin.write(line.encode() + b"\n")
        self.proc.stdin.flush()
        n = int(self.proc.stdout.readline().strip() or 0)
        return self.proc.stdout.read(n) if n > 0 else b""

    def _read_vue(self):
        """vue.json lu juste avant l'image : l'image est posée avec la correspondance de son instant.
        Une lecture ratée (fichier en cours de réécriture) garde la précédente."""
        try:
            v = json.loads(self._ask("V") or b"null")
            if isinstance(v, dict) and v.get("pageId"):
                self.frame_vue = {k: v[k] for k in ("pageId", "map", "mask", "cell", "angle") if k in v}
        except ValueError:
            pass

    def _full(self):
        self._read_vue()
        gz = self._ask("F")
        if len(gz) <= 100:
            raise RuntimeError("écran introuvable (interface de la tablette arrêtée ?)")
        raw = gzip.decompress(gz)
        if len(raw) < FRAME:
            raise RuntimeError("image incomplète")
        self.raw = bytearray(raw[:FRAME])
        self.stats["full"] += 1
        self._publish()

    def _band(self, y0, y1):
        """Relit seulement les lignes y0..y1 (repère de l'image) et les recopie dans l'image courante."""
        if self.raw is None:
            return self._full()
        y0, y1 = max(0, int(y0)), min(H, int(y1) + 1)
        start, end = 8 + y0 * ROW, 8 + y1 * ROW
        b0, b1 = start // 4096, (end + 4095) // 4096
        gz = self._ask(f"B {b0} {b1 - b0}")
        if len(gz) <= 20:
            return
        data = gzip.decompress(gz)
        base = b0 * 4096
        seg = data[start - base:end - base]
        self.raw[start:start + len(seg)] = seg
        self.stats["band"] += 1
        self._publish()

    def _publish(self):
        im = Image.frombuffer("RGBA", (W, H), bytes(self.raw[8:8 + W * H * 4]), "raw", "BGRA", 0, 1).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "PNG", compress_level=1)
        meta = json.dumps(self.frame_vue, separators=(",", ":"))
        with self.cond:
            self.png = buf.getvalue()
            self.meta = meta
            self.seq += 1
            self.cond.notify_all()

    # -- ordonnancement
    def _run(self):
        last_full = last_band = last_vue = 0.0
        vue = None
        pending_full = True                       # première image
        end_band_done = 0.0                       # dernier trait dont la bande finale a été relue
        followup = 0.0                            # seconde image après un déplacement (page pas encore redessinée)
        vue_settle = 0.0                          # image complète quand la vue n'a plus bougé depuis 1,2 s
        while time.time() - self.last_use < 15:   # s'arrête 15 s après le dernier client
            now = time.time()
            try:
                pen = self.pen
                touching = bool(pen and pen.touching)
                quiet = (not touching) and (pen is None or now - pen.last_activity > 1.5)
                # 1) écriture : seulement la bande parcourue par la pointe, 2 fois par seconde au plus
                if touching and pen.band and now - last_band >= 0.5:
                    y0, y1 = pen.band
                    pen.band = None
                    self._band(y0 - 60, y1 + 60)
                    last_band = time.time()
                    pending_full = True           # une image complète suivra, à la prochaine pause
                # 2) fin de trait : la bande du trait (bon marché), un peu après le lever
                elif pen and not touching and pen.touch_end > end_band_done and now - pen.touch_end > 0.25:
                    end_band_done = pen.touch_end
                    if pen.band:
                        y0, y1 = pen.band
                        pen.band = None
                        self._band(y0 - 60, y1 + 60)
                        last_band = time.time()
                    pending_full = True
                # 3) la page affichée a changé (page, zoom, défilement, menus) : vue.json, presque gratuit
                if not touching and now - last_vue >= 0.5:
                    v = self._ask("V")
                    last_vue = time.time()
                    if v and v != vue:
                        if vue is not None:
                            # déplacement en cours : attendre que la vue soit stable avant de capturer
                            vue_settle = time.time() + 1.2
                            followup = time.time() + 3.0
                            self.stats["reasons"]["vue"] = self.stats["reasons"].get("vue", 0) + 1
                        vue = v
                # 4) activité annoncée (forme, formule…) ou image de contrôle au repos
                if now < self.boost_until and now - last_full >= 1.0:
                    pending_full = True
                if now - last_full >= 15:
                    pending_full = True
                # après un déplacement, la tablette redessine la page par morceaux : une image prise trop tôt
                # garde des bords sombres (droite, bas) -> seconde image une fois le dessin terminé
                if vue_settle and now >= vue_settle:
                    vue_settle = 0.0
                    pending_full = True
                if followup and now >= followup and not vue_settle:
                    followup = 0.0
                    pending_full = True
                # image complète seulement pendant une pause d'écriture (ou activité annoncée)
                if pending_full and (quiet or now < self.boost_until) and not touching:
                    self._full()
                    last_full = time.time()
                    pending_full = False
                self.error = None
            except Exception as e:
                self.error = str(e)
                if self.proc:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                    self.proc = None
                time.sleep(2)
            time.sleep(0.1)
        if self.proc:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
