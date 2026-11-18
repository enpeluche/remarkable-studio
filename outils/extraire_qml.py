#!/usr/bin/env python3
"""Extrait le QML embarqué dans xochitl (fichiers compressés zstd dans le binaire), pour l'étudier.

Usage : python3 outils/extraire_qml.py xochitl dossier_sortie
  (récupérer d'abord le programme : scp root@10.11.99.1:/usr/bin/xochitl xochitl)
Les fichiers sont nommés par leur position dans le binaire ; le nom réel (chemin qrc) se retrouve via
le hashtab de xovi ou par leur contenu (ex. racine « Background » + onOpened = MainView.qml).
Ce QML appartient à reMarkable : à garder pour soi, ne pas le redistribuer.
Nécessite : pip install zstandard
"""
import re
import sys
from pathlib import Path

import zstandard


def main(binary, out):
    d = Path(binary).read_bytes()
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    n = 0
    for m in re.finditer(re.escape(b"\x28\xb5\x2f\xfd"), d):          # en-tête de trame zstd
        try:
            data = zstandard.ZstdDecompressor().decompressobj().decompress(d[m.start():m.start() + 3_000_000])
        except Exception:
            continue
        if b"import " in data[:3000]:
            (out / f"{m.start():09d}.qml").write_bytes(data)
            n += 1
    print(f"{n} fichiers QML extraits dans {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
