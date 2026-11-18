#!/bin/bash
# Retire les mods remarkable-studio de la tablette (xovi lui-même reste installé).
set -euo pipefail
H="${RM_HOST:-root@10.11.99.1}"
X=/home/root/xovi
QRR=$X/exthome/qt-resource-rebuilder
ssh "$H" "cd $QRR && rm -f carnets_lies.qmd crayons.qmd menu_crayon.qmd formes.qmd quad.qmd primary.qmd eraser.qmd;
          rm -rf $X/crayons $X/formes $X/xochitl-patch $X/services/xochitl.service/xochitl-patch.conf"
echo "Retiré. Redémarrez la tablette (ou relancez xovi/start) pour revenir à l'interface d'origine."
echo "Vos palettes (/home/root/crayons.json) et liens de carnets (/home/root/carnets-lies.json) sont conservés."
