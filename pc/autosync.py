"""Synchro automatique de la sauvegarde locale (dossier xochitl) avec la tablette, en arrière-plan.

Toutes les quelques secondes, quand la tablette répond : la tablette liste les fichiers modifiés depuis le
passage précédent (repère dans /tmp de la tablette, en mémoire : aucune écriture sur sa mémoire flash),
et seuls ceux-là sont copiés. Premier passage (ou tablette redémarrée) : synchro complète par rsync.
Comme sync.sh, rien n'est jamais supprimé localement (un document effacé sur la tablette reste sauvegardé).
"""
import subprocess
import threading
import time

from live import RM_HOST, SSH_OPTS, ssh

RM_DIR = "/home/root/.local/share/remarkable/xochitl"
MARK = "/tmp/rmv-sync-mark"


class AutoSync:
    def __init__(self, lib, local_root, interval=10, idle_interval=60, active=None):
        """active() -> True si une page du PC sert en ce moment : synchro toutes les `interval` s, sinon toutes les
        `idle_interval` s (chaque passage coûte ~0,3 s de processeur à la tablette)."""
        self.lib = lib
        self.root = local_root
        self.interval = interval
        self.idle_interval = idle_interval
        self.active = active or (lambda: True)
        self.version = 0                 # change à chaque document mis à jour (la bibliothèque se rafraîchit)
        self.last = {"t": 0, "files": 0, "docs": 0, "error": None, "full": False}
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _rsync(self, extra, files=None):
        cmd = ["rsync", "-a", "-e", "ssh " + " ".join(SSH_OPTS), *extra, f"{RM_HOST}:{RM_DIR}/", f"{self.root}/"]
        r = subprocess.run(cmd, input=files, capture_output=True, timeout=600)
        if r.returncode not in (0, 24):        # 24 : fichier disparu pendant la copie (normal)
            raise RuntimeError(r.stderr.decode(errors="replace")[-200:])

    def run_once(self):
        with self.lock:
            r = ssh(f"touch {MARK}.new; if [ -f {MARK} ]; then cd {RM_DIR} && find . -newer {MARK} -type f; "
                    f"else echo __FULL__; fi; mv {MARK}.new {MARK}", timeout=20)
            if r.returncode != 0:
                raise RuntimeError("tablette injoignable")
            out = r.stdout.decode().split("\n")
            if "__FULL__" in out:
                self._rsync([])
                self.lib.reload()
                self.version += 1
                self.last.update(full=True, files=-1, docs=len(self.lib.snapshot()))
                return
            files = sorted({f[2:] for f in out if f.startswith("./") and not f.endswith(".tmp")})
            if not files:
                self.last.update(full=False, files=0, docs=0)
                return
            self._rsync(["--files-from=-"], "\n".join(files).encode())
            uids = {f.split("/")[0].split(".")[0] for f in files}
            for uid in uids:
                self.lib.reload_one(uid)
            self.version += 1
            self.last.update(full=False, files=len(files), docs=len(uids))

    def _loop(self):
        time.sleep(3)
        while True:
            try:
                self.run_once()
                self.last.update(t=time.time(), error=None)
            except Exception as e:
                self.last["error"] = str(e)
            # attente découpée : reprend le rythme rapide dès qu'une page du PC redevient active
            end = time.time() + self.idle_interval
            start = time.time()
            while time.time() < end and not (self.active() and time.time() - start >= self.interval):
                time.sleep(1)
