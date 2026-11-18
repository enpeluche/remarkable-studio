#!/bin/sh
# Lance la copie modifiée de xochitl (couleurs libres + épaisseur continue) SEULEMENT si le programme
# d'origine est exactement celui pour lequel le patch a été fait (empreinte MD5 ci-dessous).
# Sinon (mise à jour du système, fichier absent…), lance le xochitl d'origine.
P=/home/root/xovi/xochitl-patch/xochitl-libre
ORIG_MD5="@MD5@"
if [ -x "$P" ] && [ "$(md5sum /usr/bin/xochitl | cut -d' ' -f1)" = "$ORIG_MD5" ]; then
    exec "$P" "$@"
fi
exec /usr/bin/xochitl "$@"
