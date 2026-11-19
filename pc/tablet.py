"""Actions sur la tablette : état, ouverture à distance, liens entre documents, (ré)activation des mods xovi."""
import json
import shlex
import subprocess
import threading
import time
from pathlib import Path

from live import RM_HOST, SSH_OPTS, ssh, note_wifi

HERE = Path(__file__).resolve().parent
LINKS_FILE = HERE / "carnets-lies.json"            # source de vérité, côté PC
TABLET_LINKS = "/home/root/carnets-lies.json"      # copie lue par le bouton sur la tablette
PIPE = "/run/xovi-mb"

_lock = threading.Lock()
_status = {"t": 0, "value": None}


def status(max_age=3):
    """{"usb": bool, "mods": bool} — mods = xovi lancé avec le canal de messages."""
    with _lock:
        if _status["value"] and time.time() - _status["t"] < max_age:
            return _status["value"]
        try:
            r = ssh(f"[ -p {PIPE} ] && echo mods || echo stock; echo $SSH_CONNECTION; "
                    "ip -4 addr show wlan0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2", timeout=6)
            out = r.stdout.decode().split("\n")
            # « usb » = tablette joignable (nom historique) ; link = liaison réellement utilisée
            value = {"usb": r.returncode == 0, "mods": out[0].strip() == "mods",
                     "link": ("usb" if (out[1].split() + ["", "", ""])[2].endswith("10.11.99.1") else "wifi") if r.returncode == 0 and len(out) > 1 else None}
        except Exception:
            value = {"usb": False, "mods": False}
        if value.get("link") == "usb" and len(out) > 2 and out[2].strip():
            note_wifi(out[2].strip())                # adresse Wi-Fi actuelle, relevée par l'USB
        _status.update(t=time.time(), value=value)
        return value


def _invalidate():
    with _lock:
        _status["t"] = 0


def send_signal(name, value=""):
    """Envoie un signal à l'interface via xovi-message-broker. Ne fait rien si le canal n'existe pas."""
    msg = shlex.quote(f"u{name}:{value}")
    # le test -p évite de créer un fichier ordinaire ; timeout car écrire dans un tube sans lecteur bloque
    r = ssh(f"[ -p {PIPE} ] && echo {msg} | timeout 3 tee {PIPE} >/dev/null && echo ok", timeout=10)
    return r.stdout.decode().strip() == "ok"


def open_document(doc_id, page=-1):
    return send_signal("carnetsOpen", f"{doc_id},{int(page)}")


def start_mods():
    """Relance l'interface de la tablette avec xovi (non permanent : un redémarrage revient à l'origine)."""
    r = ssh("[ -x /home/root/xovi/start ] && [ -f /home/root/xovi/exthome/qt-resource-rebuilder/carnets_lies.qmd ] "
            "&& /home/root/xovi/start >/dev/null 2>&1 && echo ok", timeout=60)
    _invalidate()
    return r.stdout.decode().strip() == "ok"


# ---------------------------------------------------------------- liens

def load_links():
    try:
        return json.loads(LINKS_FILE.read_text()).get("links", {})
    except Exception:
        return {}


def _save_links(links):
    tmp = LINKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"links": links}, ensure_ascii=False, indent=2))
    tmp.replace(LINKS_FILE)


def set_link(lib_items, a, b):
    """Relie a <-> b (b=None : supprime le lien de a). Un document n'a qu'un seul carnet lié."""
    links = load_links()
    for doc in (a, b):
        if doc and doc in links:
            old = links.pop(doc)["to"]
            if links.get(old, {}).get("to") == doc:
                links.pop(old)
    if b:
        links[a] = {"to": b, "name": lib_items[b]["name"]}
        links[b] = {"to": a, "name": lib_items[a]["name"]}
    _save_links(links)
    return links


def push_links():
    """Copie les liens sur la tablette puis demande au bouton de les relire."""
    data = json.dumps({"links": load_links()}, ensure_ascii=False).encode()
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"cat > {TABLET_LINKS}.tmp && mv {TABLET_LINKS}.tmp {TABLET_LINKS}"],
                       input=data, capture_output=True, timeout=15)
    if r.returncode != 0:
        return {"pushed": False, "reloaded": False}
    return {"pushed": True, "reloaded": send_signal("carnetsReload")}


# ---------------------------------------------------------------- crayons

TABLET_PALETTE = "/home/root/crayons.json"
PALETTE_FILE = HERE / "crayons.json"     # copie locale (la tablette fait foi quand elle est connectée)


def get_palette():
    try:
        r = ssh(f"cat {TABLET_PALETTE}", timeout=8)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            PALETTE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1))
            return data.get("palette", []), True
    except Exception:
        pass
    try:
        return json.loads(PALETTE_FILE.read_text()).get("palette", []), False
    except Exception:
        return [], False


def set_palette(palette):
    data = json.dumps({"palette": palette}, ensure_ascii=False, indent=1)
    PALETTE_FILE.write_text(data)
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"cat > {TABLET_PALETTE}.tmp && mv {TABLET_PALETTE}.tmp {TABLET_PALETTE}"],
                       input=data.encode(), capture_output=True, timeout=15)
    return r.returncode == 0


FORMES_CMD = "/home/root/xovi/crayons/formes-cmd.json"


def formes_cmd(cmd):
    """Écrit une commande pour Formes.qml (accroche dans la page affichée), ex. {"action": "build", ...}.
    Écriture atomique (fichier temporaire puis renommage) : Formes.qml relit le fichier toutes les 0,4 s."""
    cmd = dict(cmd, id=int(time.time() * 1000))
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"cat > {FORMES_CMD}.tmp && mv {FORMES_CMD}.tmp {FORMES_CMD}"],
                       input=json.dumps(cmd).encode(), capture_output=True, timeout=10)
    return r.returncode == 0
