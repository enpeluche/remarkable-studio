#!/bin/bash
# Lance le serveur (s'il ne tourne pas déjà) et ouvre le navigateur.
cd "$(dirname "$0")"
URL="http://127.0.0.1:8765/"
if curl -s -o /dev/null "$URL"; then
  xdg-open "$URL" >/dev/null 2>&1
  exit 0
fi
exec .venv/bin/python server.py --open "$@"
