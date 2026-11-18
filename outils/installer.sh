#!/bin/bash
# Installe les mods remarkable-studio sur la tablette (depuis le PC, par SSH).
# Prérequis : xovi installé sur la tablette, avec qt-resource-rebuilder et xovi-message-broker
# (voir docs/INSTALLATION.md). Variable RM_HOST : adresse de la tablette (défaut : USB).
# Rien n'est activé tout de suite : lancez ensuite les mods (xovi/start, PIN demandé).
set -euo pipefail
cd "$(dirname "$0")/.."
H="${RM_HOST:-root@10.11.99.1}"
X=/home/root/xovi
QRR=$X/exthome/qt-resource-rebuilder
# modules (fichiers .qmd) à installer ; par défaut tous
MODULES="${MODULES:-carnets_lies crayons menu_crayon formes quad primary eraser}"

echo "Tablette : $H"
ssh -o ConnectTimeout=5 "$H" "test -f $X/xovi.so && test -f $X/extensions.d/qt-resource-rebuilder.so && test -f $X/extensions.d/xovi-message-broker.so" \
  || { echo "xovi (avec qt-resource-rebuilder et xovi-message-broker) introuvable sur la tablette : voir docs/INSTALLATION.md"; exit 1; }

# qt-command-executor : nécessaire aux formes (lance l'injecteur de traits depuis le QML)
if ! ssh "$H" "test -f $X/extensions.d/qt-command-executor.so"; then
  if ssh "$H" "test -f $X/inactive-extensions/qt-command-executor.so"; then
    ssh "$H" "cp $X/inactive-extensions/qt-command-executor.so $X/extensions.d/" && echo "qt-command-executor activé"
  else
    echo "Attention : qt-command-executor absent (les formes ne pourront pas créer leur gabarit). Voir docs/INSTALLATION.md"
  fi
fi

ssh "$H" "mkdir -p $X/crayons $X/formes $QRR"
scp -q tablette/crayons/{PenMenu,Formes,Quad,Crayons}.qml tablette/crayons/formes-etat.js "$H:$X/crayons/"
ssh "$H" "test -f /home/root/crayons.json" || scp -q tablette/crayons/crayons.json "$H:/home/root/crayons.json"
scp -q tablette/formes/trace.sh tablette/formes/trace.awk "$H:$X/formes/"
ssh "$H" "chmod +x $X/formes/trace.sh; echo 1 > $X/crayons/formes.version; echo 1 > $X/crayons/quad.version; echo '{\"id\":0}' > $X/crayons/formes-cmd.json"
for m in $MODULES; do scp -q "tablette/xovi/$m.qmd" "$H:$QRR/"; echo "module $m"; done

ssh "$H" "test -f $QRR/hashtab" || echo "Pas d'index (hashtab) : lancez d'abord  ssh $H 'echo | $X/rebuild_hashtable'  (PIN demandé)."
echo
echo "Installé. Pour activer :  ssh $H $X/start   (l'interface redémarre, PIN demandé)."
echo "Pour revenir à l'origine : redémarrez simplement la tablette."
