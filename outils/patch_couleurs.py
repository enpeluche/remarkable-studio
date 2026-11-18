#!/usr/bin/env python3
"""Patch « couleurs libres » pour xochitl (reMarkable 2).

Depuis la 3.30, une fonction C++ ramène toute couleur ou épaisseur du crayon aux valeurs officielles
(couleur la plus proche, cran d'épaisseur le plus proche). Ce patch remplace le début de cette fonction
par « rien à corriger » (7 instructions ARM). Voir docs/DECOUVERTES.md.

Principe, non persistant et réversible :
  - le programme d'origine (/usr/bin/xochitl) n'est JAMAIS modifié ;
  - une COPIE patchée est déposée dans /home/root/xovi/xochitl-patch/ ;
  - elle est lancée par run.sh via un fichier de service ajouté au dossier de xovi, donc seulement quand
    les mods sont activés (xovi/start) ; un redémarrage de la tablette revient à l'origine ;
  - run.sh vérifie l'empreinte de /usr/bin/xochitl et lance l'original si elle a changé (mise à jour).

Usage :
  python3 outils/patch_couleurs.py --j-accepte-les-risques     installer
  python3 outils/patch_couleurs.py --retirer                    désinstaller
Variable RM_HOST : adresse de la tablette (défaut root@10.11.99.1).
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HOST = os.environ.get("RM_HOST", "root@10.11.99.1")
HERE = Path(__file__).resolve().parent.parent / "tablette" / "patch-couleurs"
DEST = "/home/root/xovi/xochitl-patch"
CONF = "/home/root/xovi/services/xochitl.service/xochitl-patch.conf"

# Versions connues : empreinte MD5 de /usr/bin/xochitl -> (version, adresse de la fonction, octets attendus)
VERSIONS = {
    "a491e48d1b35cc32c2ae40e468ebf8b7": ("3.30.0.111", 0x952AA4,
                                         "103092e530402de9090053e30cc092e534d04de2143092050150a0e1"),
}
# mov r3,#0 ; str r3,[r0] ; str r3,[r0,#4] ; [r0,#8] ; [r0,#12] ; [r0,#16] ; bx lr
PATCH = struct.pack("<7I", 0xE3A03000, 0xE5803000, 0xE5803004, 0xE5803008, 0xE580300C, 0xE5803010, 0xE12FFF1E)


def run(cmd, data=None):
    r = subprocess.run(cmd, input=data, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"échec : {' '.join(cmd[:3])}…\n{r.stderr.decode(errors='replace')}")
    return r.stdout


def ssh(command, data=None):
    return run(["ssh", HOST, command], data)


def installer():
    with tempfile.TemporaryDirectory() as t:
        orig = Path(t) / "xochitl"
        run(["scp", "-q", f"{HOST}:/usr/bin/xochitl", str(orig)])
        data = orig.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        if md5 not in VERSIONS:
            sys.exit(f"Version de xochitl inconnue (md5 {md5}) : patch NON appliqué.\n"
                     "Voir docs/DECOUVERTES.md pour retrouver la fonction dans une nouvelle version.")
        version, off, expected = VERSIONS[md5]
        if data[off:off + len(PATCH)].hex() != expected:
            sys.exit("Octets inattendus à l'adresse du patch : abandon.")
        patched = data[:off] + PATCH + data[off + len(PATCH):]
        print(f"xochitl {version} reconnu, copie patchée prête ({sum(a != b for a, b in zip(data, patched))} octets modifiés).")
        ssh(f"mkdir -p {DEST} && cat > {DEST}/xochitl-libre && chmod +x {DEST}/xochitl-libre", patched)
        ssh(f"cat > {DEST}/run.sh && chmod +x {DEST}/run.sh", (HERE / "run.sh").read_text().replace("@MD5@", md5).encode())
        ssh(f"mkdir -p {os.path.dirname(CONF)} && cat > {CONF}", (HERE / "xochitl-patch.conf").read_bytes())
    print("Installé. Il sera actif au prochain lancement des mods (xovi/start, qui demandera le PIN).")


def retirer():
    ssh(f"rm -f {CONF}; rm -rf {DEST}")
    print("Retiré. Relancez les mods (xovi/start) ou redémarrez la tablette pour revenir au programme d'origine.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--j-accepte-les-risques", action="store_true", help="installer le patch (voir docs/SECURITE.md)")
    ap.add_argument("--retirer", action="store_true", help="retirer le patch")
    a = ap.parse_args()
    if a.retirer:
        retirer()
    elif a.j_accepte_les_risques:
        installer()
    else:
        ap.print_help()
        sys.exit("\nRien n'a été fait : ajoutez --j-accepte-les-risques pour installer, après avoir lu docs/SECURITE.md.")
