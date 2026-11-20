#!/bin/sh
# Compile l'extension pour la tablette (ARM 32 bits). Prérequis Ubuntu : sudo apt install g++-arm-linux-gnueabihf
set -e
cd "$(dirname "$0")"
arm-linux-gnueabihf-gcc -O2 -Wall -Wextra -shared -fPIC -o studio-natif.so studio-natif.c
echo "studio-natif.so prêt"
