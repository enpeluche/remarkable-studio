"""Vue en direct : flux du stylet (lecture seule) et suivi de la page ouverte sur la tablette."""
import json
import os
import queue
import struct
import subprocess
import threading
import time
from pathlib import Path

RM_DIR = "/home/root/.local/share/remarkable/xochitl"
USB_IP = "10.11.99.1"


def _tablet_host():
    """Adresse de la tablette : RM_HOST si donnée ; sinon l'alias « remarkable » d'une configuration SSH propre au
    projet, qui choisit à CHAQUE connexion l'USB s'il répond, sinon le Wi-Fi (adresse dans tablette.conf : wifi=…).
    Débrancher / rebrancher en cours de route fonctionne donc sans rien faire."""
    if os.environ.get("RM_HOST"):
        return os.environ["RM_HOST"], []
    here = Path(__file__).resolve().parent
    wifi = os.environ.get("RM_WIFI", "")
    conf = here / "tablette.conf"
    if not wifi and conf.exists():
        for line in conf.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "wifi":
                wifi = v.strip()
    if not wifi:
        return f"root@{USB_IP}", []
    cfg = here / ".ssh_config"
    text = (f"# généré par live.py : USB si branché, sinon Wi-Fi\n"
            f"Match originalhost remarkable exec \"timeout 1 bash -c '</dev/tcp/{USB_IP}/22' 2>/dev/null\"\n"
            f"  HostName {USB_IP}\n"
            f"Match originalhost remarkable\n"
            f"  HostName {wifi}\n"
            f"Host *\n  User root\n")
    if not cfg.exists() or cfg.read_text() != text:
        cfg.write_text(text)
    return "root@remarkable", ["-F", str(cfg)]


RM_HOST, _CFG = _tablet_host()
SSH_OPTS = [*_CFG, "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "-o", "ServerAliveInterval=5",
            "-o", "ControlMaster=auto", "-o", f"ControlPath={Path.home()}/.ssh/cm-rmstudio-%r@%h",
            "-o", "ControlPersist=120"]

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y, ABS_PRESSURE, ABS_DISTANCE = 0, 1, 24, 25
BTN_TOOL_PEN, BTN_TOOL_RUBBER, BTN_TOUCH = 320, 321, 330


def ssh(cmd, timeout=10, **kw):
    return subprocess.run(["ssh", *SSH_OPTS, RM_HOST, cmd], capture_output=True, timeout=timeout, **kw)


class PenStream:
    """Un seul processus `ssh cat /dev/input/event1` partagé par tous les navigateurs abonnés."""

    def __init__(self):
        self.subs = set()
        self.lock = threading.Lock()
        self.thread = None
        self.proc = None
        self.status = "arrêté"
        self.last_activity = 0.0
        self.touching = False
        self.touch_end = 0.0
        self.band = None          # [y min, y max] parcourus par la pointe depuis la dernière capture

    def subscribe(self):
        q = queue.Queue(maxsize=5000)
        with self.lock:
            self.subs.add(q)
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._run, daemon=True)
                self.thread.start()
        q.put({"status": self.status})
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def _emit(self, msg):
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def _set_status(self, s):
        self.status = s
        self._emit({"status": s})

    def _run(self):
        idle_since = None
        while True:
            with self.lock:
                n = len(self.subs)
            if n == 0:
                idle_since = idle_since or time.time()
                if time.time() - idle_since > 5:
                    self._set_status("arrêté")
                    return
                time.sleep(0.5)
                continue
            idle_since = None
            self._set_status("connexion")
            try:
                # la lecture s'arrête quand la connexion se ferme (fin de l'entrée -> read se termine -> kill),
                # sinon des « cat » orphelins s'accumulent sur la tablette
                self.proc = subprocess.Popen(["ssh", *SSH_OPTS, RM_HOST,
                                              "echo READY; cat /dev/input/event1 & P=$!; read _; kill $P"],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                self._read(self.proc.stdout)
            except Exception:
                pass
            finally:
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
            self._set_status("déconnecté")
            time.sleep(2)

    def _read(self, f):
        x = y = pressure = 0
        dist = 255
        touch = rubber = in_range = False
        if f.readline().strip() != b"READY":
            return
        self._set_status("connecté")
        while True:
            with self.lock:
                if not self.subs:
                    return
            buf = f.read(16)  # struct input_event (ARM 32 bits) : timeval 8 o + type, code, value
            if len(buf) < 16:
                return
            _s, _us, typ, code, val = struct.unpack("<IIHHi", buf)
            if typ == EV_ABS:
                in_range = True
                if code == ABS_X: x = val
                elif code == ABS_Y: y = val
                elif code == ABS_PRESSURE: pressure = val
                elif code == ABS_DISTANCE: dist = val
            elif typ == EV_KEY:
                if code == BTN_TOUCH: touch = bool(val)
                elif code == BTN_TOOL_RUBBER: rubber = bool(val); in_range = bool(val) or in_range
                elif code == BTN_TOOL_PEN: in_range = bool(val)
            elif typ == EV_SYN and code == 0:
                touching = touch or pressure > 40   # le flux peut démarrer au milieu d'un trait
                flags = (1 if touching else 0) | (2 if rubber else 0) | (4 if in_range else 0)
                # suivi pour la capture d'écran : pointe posée, lignes de l'écran parcourues (repère de l'image)
                now = time.time()
                if touching:
                    sy = (1 - x / 20966) * 1872
                    self.band = [min(self.band[0], sy), max(self.band[1], sy)] if self.band else [sy, sy]
                    self.touching, self.last_activity = True, now
                elif self.touching:
                    self.touching, self.touch_end = False, now
                self._emit({"p": [x, y, round(pressure / 4095, 3), flags]})


class CurrentPage:
    """Repère le document/la page modifiés en dernier sur la tablette et rapatrie ce document."""

    def __init__(self, lib, local_root: Path):
        self.lib = lib
        self.root = local_root
        self.lock = threading.Lock()
        self.cache = None
        self.t = 0

    def get(self):
        with self.lock:
            if self.cache and time.time() - self.t < 1.5:
                return self.cache
            try:
                self.cache = self._probe()
            except Exception as e:
                self.cache = {"error": f"tablette injoignable ({type(e).__name__})"}
            self.t = time.time()
            return self.cache

    def _probe(self):
        # 1) page réellement affichée, signalée par l'accroche Formes.qml (pageId + orientation).
        #    Le document contenant la page n'est recherché (grep sur tous les .content) que si la page change.
        known = getattr(self, "_page_doc", {})
        last = getattr(self, "_last_page", None)          # (uid, pid) de la dernière interrogation
        cmd = "cat /home/root/xovi/formes/vue.json 2>/dev/null; echo"
        if last:   # cas courant : même page -> une seule session SSH
            cmd += f"; stat -c %Y {RM_DIR}/{last[0]}/{last[1]}.rm {RM_DIR}/{last[0]}.content 2>/dev/null | sort -n | tail -n 1"
        vue = pid = None
        for attempt in range(2):
            r = ssh(cmd, timeout=8)
            lines = r.stdout.decode().splitlines()
            try:
                vue = json.loads(lines[0])
                pid = vue.get("pageId")
                break
            except Exception:
                # vue.json lu pendant sa réécriture (vide ou tronqué) : on relit, puis on garde la dernière lecture
                # valide plutôt que de basculer sur « document modifié en dernier » (souvent un autre document)
                if attempt == 0:
                    time.sleep(0.15)
                    continue
                good = getattr(self, "_good_vue", None)
                if r.returncode == 0 and good and time.time() - good[0] < 30:
                    vue = good[1]
                    pid = vue.get("pageId")
                    lines = [""]
        if vue and pid:
            self._good_vue = (time.time(), vue)
        if vue and pid and last and pid == last[1] and len(lines) > 1 and lines[1].strip().isdigit():
            return self._result(last[0], pid, int(lines[1]), vue)
        if vue and pid:
            uid = known.get(pid)
            if uid is None:
                g = ssh(f"grep -l '{pid}' {RM_DIR}/*.content 2>/dev/null | head -n 1", timeout=8).stdout.decode().strip()
                uid = g.rsplit("/", 1)[-1][:-len(".content")] if g.endswith(".content") else None
                if uid:
                    known[pid] = uid
                    self._page_doc = known
            if uid:
                st = ssh(f"stat -c %Y {RM_DIR}/{uid}/{pid}.rm {RM_DIR}/{uid}.content 2>/dev/null | sort -n | tail -n 1",
                         timeout=8).stdout.decode().strip()
                self._last_page = (uid, pid)
                return self._result(uid, pid, int(st or 0), vue)
        # 2) repli : document modifié en dernier
        r = ssh(f"cd {RM_DIR} && f=$(ls -t */*.rm *.metadata 2>/dev/null | head -n 1) && echo $f && stat -c %Y $f",
                timeout=8)
        out = r.stdout.decode().split()
        if r.returncode != 0 or len(out) < 2:
            return {"error": "tablette injoignable"}
        path, mtime = out[0], int(out[1])
        uid = path.split("/")[0].split(".")[0]
        page_id = path.split("/")[1][:-3] if path.endswith(".rm") else None
        return self._result(uid, page_id, mtime, None)

    def _result(self, uid, page_id, mtime, vue):
        key = (uid, mtime)
        if getattr(self, "_last_key", None) != key:
            subprocess.run(["rsync", "-a", "-e", "ssh " + " ".join(SSH_OPTS),
                            "--include", f"{uid}/", "--include", f"{uid}/**", "--include", f"{uid}.*",
                            "--include", f"{uid}.*/**", "--exclude", "*",
                            f"{RM_HOST}:{RM_DIR}/", f"{self.root}/"], capture_output=True, timeout=120)
            self.lib.reload_one(uid)
            self._last_key = key
        item = self.lib.snapshot().get(uid)
        if not item:
            return {"error": "document inconnu", "doc": uid}
        page = item.get("lastPage") or 0
        if page_id:
            ids = [p["id"] for p in item["pages"]]
            if page_id in ids:
                page = ids.index(page_id)
        out = {"doc": uid, "name": item["name"], "type": item["type"], "page": page, "pageId": page_id,
               "pageCount": item["pageCount"], "ver": mtime}
        if vue:
            out["portrait"] = bool(vue.get("portrait", True))
            out["angle"] = int(vue.get("angle", 0))
            if isinstance(vue.get("map"), list) and len(vue["map"]) == 6:
                out["map"] = vue["map"]           # écran physique -> page : coins (0,0), (1404,0), (0,1872)
            if isinstance(vue.get("pen"), dict):
                out["pen"] = vue["pen"]           # crayon actif (écrit par Formes.qml)
            if vue.get("mask"):
                out["mask"], out["cell"] = vue["mask"], int(vue.get("cell") or 24)   # cases occupées par l'interface
        return out


def sse(handler, stream: PenStream):
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    q = stream.subscribe()
    try:
        while True:
            try:
                msg = q.get(timeout=15)
            except queue.Empty:
                handler.wfile.write(b": ping\n\n")
                handler.wfile.flush()
                continue
            batch = [msg]
            deadline = time.time() + 0.02
            while time.time() < deadline:
                try:
                    batch.append(q.get(timeout=max(0, deadline - time.time())))
                except queue.Empty:
                    break
            handler.wfile.write(b"data: " + json.dumps(batch, separators=(",", ":")).encode() + b"\n\n")
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        stream.unsubscribe(q)
