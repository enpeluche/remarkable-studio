#!/bin/bash
# Resynchronise la sauvegarde depuis la reMarkable (USB, ou Wi-Fi si tablette.conf contient wifi=<adresse>).
# Les fichiers supprimés sur la tablette restent dans la sauvegarde.
set -e
cd "$(dirname "$0")"
if [ -z "$RM_HOST" ] && [ -f .ssh_config ]; then
  HOST=root@remarkable; SSH="ssh -F .ssh_config"
else
  HOST="${RM_HOST:-root@10.11.99.1}"; SSH="ssh"
fi
rsync -a -e "$SSH" --info=progress2 "$HOST:/home/root/.local/share/remarkable/xochitl/" xochitl/
echo "Synchronisation terminée."
