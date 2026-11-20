#!/bin/sh
# Compile l'extension pour la tablette (ARM 32 bits, Qt 6.10.3).
# Prérequis : sudo apt install g++-arm-linux-gnueabihf ; QT = Qt 6.10.3 pour PC (en-têtes et moc, ex. aqtinstall :
# aqt install-qt linux desktop 6.10.3 linux_gcc_64) ; QTLIBS = dossier avec libQt6Core.so et libQt6Qml.so copiés
# depuis la tablette (/usr/lib), pour l'édition de liens seulement.
set -e
cd "$(dirname "$0")"
: "${QT:?QT = dossier gcc_64 de Qt 6.10.3}"
: "${QTLIBS:?QTLIBS = dossier des bibliothèques Qt de la tablette}"
"$QT/libexec/moc" studio-natif.cpp -o studio-natif.moc
arm-linux-gnueabihf-g++ -std=c++17 -O2 -Wall -Wextra -shared -fPIC \
    -I"$QT/include" -I"$QT/include/QtCore" -I"$QT/include/QtQml" \
    -o studio-natif.so studio-natif.cpp -L"$QTLIBS" -lQt6Qml -lQt6Core
echo "studio-natif.so prêt"
