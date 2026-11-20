"""Actions sur la tablette : état, ouverture à distance, liens entre documents, (ré)activation des mods xovi."""
import json
import subprocess
import threading
import time
from pathlib import Path

from live import RM_HOST, SSH_OPTS, USB_IP, ssh, note_wifi

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


def open_document(doc_id, page=-1):
    """Ouvre un document à une page. Par Formes.qml (le signal carnetsOpen de xovi-message-broker n'arrive pas) :
    fonctionne quand un document est déjà ouvert sur la tablette (Formes.qml n'écoute que dans un document)."""
    return formes_cmd({"action": "open", "doc": doc_id, "page": int(page)})


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
    # relecture demandée à Formes.qml (le signal carnetsReload n'arrive pas) ; sans document ouvert, la liste
    # est relue à la prochaine ouverture
    return {"pushed": True, "reloaded": formes_cmd({"action": "linksReload"})}


# ---------------------------------------------------------------- crayons

TABLET_PALETTE = "/home/root/crayons.json"
PALETTE_FILE = HERE / "crayons.json"     # copie locale (la tablette fait foi quand elle est connectée)


def get_palette(local=False):
    """Palette de la tablette (copiée sur le PC) ; local=True ou tablette absente : copie du PC."""
    if not local:
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


def save_palette(palette):
    """Palette enregistrée sur le PC ; copiée sur la tablette par la file d'envoi (push_palette)."""
    PALETTE_FILE.write_text(json.dumps({"palette": palette}, ensure_ascii=False, indent=1))


def push_palette():
    try:
        data = PALETTE_FILE.read_bytes()
    except OSError:
        return False
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"cat > {TABLET_PALETTE}.tmp && mv {TABLET_PALETTE}.tmp {TABLET_PALETTE}"],
                       input=data, capture_output=True, timeout=15)
    return r.returncode == 0


def upload_usb(name, data):
    """Import d'un PDF / EPUB par l'interface web USB de la tablette (Paramètres > Stockage) : la tablette
    l'importe elle-même, sans redémarrage. -> (ok, message)"""
    import hashlib
    import urllib.error
    import urllib.request
    ext = name.rsplit(".", 1)[-1].lower()
    ctype = "application/pdf" if ext == "pdf" else "application/epub+zip"
    boundary = "----rmstudio" + hashlib.sha1(data[:4096] + name.encode()).hexdigest()[:16]
    payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
               f"filename=\"{name.replace(chr(34), '')}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() \
        + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"http://{USB_IP}/upload", data=payload, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return 200 <= r.status < 300, "importé"
    except urllib.error.HTTPError as e:
        return False, f"la tablette a refusé le fichier ({e.code})"
    except Exception:
        return False, "interface web USB injoignable (Paramètres > Stockage > Interface web USB)"


FORMES_CMD = "/home/root/xovi/crayons/formes-cmd.json"


def formes_cmd(cmd, _id=None):
    """Écrit une commande pour Formes.qml (accroche dans la page affichée), ex. {"action": "build", ...}.
    Écriture atomique (fichier temporaire puis renommage) : Formes.qml relit le fichier toutes les 0,4 s."""
    cmd = dict(cmd, id=_id or int(time.time() * 1000))
    r = subprocess.run(["ssh", *SSH_OPTS, RM_HOST, f"cat > {FORMES_CMD}.tmp && mv {FORMES_CMD}.tmp {FORMES_CMD}"],
                       input=json.dumps(cmd).encode(), capture_output=True, timeout=10)
    return r.returncode == 0


FORMES_RESULT = "/home/root/xovi/formes/resultat.json"


def formes_run(cmd, timeout=45):
    """Commande de construction (marks, build) puis attente de son compte rendu, écrit par Formes.qml dans
    resultat.json : (True, message) / (False, raison). Le gabarit éventuel (injection) prend jusqu'à ~30 s."""
    cid = int(time.time() * 1000)
    if not formes_cmd(cmd, cid):
        return False, "tablette injoignable"
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.7)
        try:
            r = json.loads(ssh(f"cat {FORMES_RESULT} 2>/dev/null", timeout=8).stdout or b"{}")
        except (ValueError, subprocess.TimeoutExpired):
            continue
        if r.get("id") == cid:
            return bool(r.get("ok")), r.get("message", "")
    return False, "pas de réponse de la tablette (aucun document ouvert ?)"


def doc_is_open(uid):
    """PDF / EPUB ouvert sur la tablette ? D'après le journal de xochitl : le « travailleur » du document écrit
    « worker on <uid> now running » à l'ouverture et « … now exiting » à la fermeture (pas de travailleur pour
    un carnet). True / False d'après la dernière de ces lignes ; None si aucune trace (journal limité, gardé
    en mémoire : une ouverture ancienne a pu en sortir) ou tablette injoignable."""
    r = ssh(f"journalctl -u xochitl -b --no-pager -o cat | grep 'worker on {uid} now' | tail -n 1", timeout=20)
    if r.returncode != 0:
        return None
    last = r.stdout.decode()
    if "now running" in last:
        return True
    if "now exiting" in last:
        return False
    return None
