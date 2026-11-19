#!/bin/bash
# Auto-diagnostic remarkable-studio : état de la tablette, de xovi et des mods, en une seule connexion SSH.
# À lancer après une mise à jour du système, un redémarrage, ou quand quelque chose ne marche plus.
# Ne modifie rien. Adresse : RM_HOST (défaut : USB), ou alias Wi-Fi si pc/.ssh_config existe.
cd "$(dirname "$0")/.."
if [ -n "$RM_HOST" ]; then H="$RM_HOST"; SSH=(ssh)
elif [ -f pc/.ssh_config ]; then H=root@remarkable; SSH=(ssh -F pc/.ssh_config)
else H=root@10.11.99.1; SSH=(ssh); fi

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; [ -n "$2" ] && printf '      → %s\n' "$2"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; [ -n "$2" ] && printf '      → %s\n' "$2"; PROBLEMES=$((PROBLEMES + 1)); }
PROBLEMES=0

# Empreintes connues du programme d'origine (/usr/bin/xochitl) pour le patch des couleurs
KNOWN_MD5="a491e48d1b35cc32c2ae40e468ebf8b7"   # 3.30.0.111

echo "remarkable-studio — diagnostic ($H)"
echo
echo "Connexion"
OUT=$("${SSH[@]}" -o BatchMode=yes -o ConnectTimeout=5 "$H" 'sh -s' 2>&1 <<'REMOTE'
X=/home/root/xovi
QRR=$X/exthome/qt-resource-rebuilder
echo "lien=$(echo $SSH_CONNECTION | cut -d" " -f3)"
echo "version=$(grep REMARKABLE_RELEASE_VERSION /usr/share/remarkable/update.conf 2>/dev/null | cut -d= -f2)"
echo "md5=$(md5sum /usr/bin/xochitl | cut -d" " -f1)"
echo "xovi=$([ -f $X/xovi.so ] && echo oui || echo non)"
for e in qt-resource-rebuilder xovi-message-broker qt-command-executor; do
  echo "ext_$e=$([ -f $X/extensions.d/$e.so ] && echo oui || echo non)"
done
echo "actif=$(systemctl show xochitl -p DropInPaths 2>/dev/null | grep -q 00-xovi.conf && echo oui || echo non)"
echo "hashtab=$([ -f $QRR/hashtab ] && echo oui || echo non)"
echo "hashtab_recent=$([ -f $QRR/hashtab ] && [ $QRR/hashtab -nt /usr/bin/xochitl ] && echo oui || echo non)"
echo "qmd=$(cd $QRR 2>/dev/null && ls *.qmd 2>/dev/null | sed 's/\.qmd$//' | tr '\n' ' ')"
for f in PenMenu.qml Formes.qml Quad.qml formes-etat.js; do echo "fichier_$f=$([ -f $X/crayons/$f ] && echo oui || echo non)"; done
echo "trace=$([ -x $X/formes/trace.sh ] && echo oui || echo non)"
P=$(pidof xochitl xochitl-libre xochitl-3.30-libre 2>/dev/null | cut -d" " -f1)
echo "pid=$P"
echo "exe=$([ -n "$P" ] && readlink /proc/$P/exe)"
echo "patch_installe=$([ -f $X/services/xochitl.service/xochitl-patch.conf ] && echo oui || echo non)"
echo "formes_pretes=$(journalctl -u xochitl -n 4000 --no-pager 2>/dev/null | grep -c 'FORMES formes prêtes')"
echo "erreurs_qml=$(journalctl -u xochitl -n 4000 --no-pager 2>/dev/null | grep -E 'file:///home/root/xovi' | grep -cE 'Error|error:|is not a type|not installed|Cannot assign')"
echo "plantages_24h=$(journalctl -u xochitl --since -24h --no-pager 2>/dev/null | grep -c 'status=6/ABRT')"
echo "dernier_plantage=$(journalctl -u xochitl --since -24h --no-pager 2>/dev/null | grep 'status=6/ABRT' | tail -n 1 | cut -c1-15)"
echo "web_usb=$(wget -q -T 2 -O /dev/null http://10.11.99.1/ 2>/dev/null && echo oui || echo non)"
echo "ssh_wifi=$(systemctl is-active dropbear-wlan.socket 2>/dev/null)"
echo "wifi_ip=$(ip -4 addr show wlan0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2)"
echo "disque=$(df /home | tail -n 1 | awk '{print $5}')"
REMOTE
)
if ! printf '%s\n' "$OUT" | grep -q '^version='; then
  bad "tablette injoignable" "brancher en USB (ou vérifier le Wi-Fi), puis : ssh $H  (clé SSH installée ? empreinte changée après une mise à jour : ssh-keygen -R 10.11.99.1)"
  printf '%s\n' "$OUT" | tail -n 2 | sed 's/^/      /'
  exit 1
fi
get() { printf '%s\n' "$OUT" | grep "^$1=" | head -n 1 | cut -d= -f2-; }
case "$(get lien)" in
  *10.11.99.1) ok "joignable en USB" ;;
  *) ok "joignable en Wi-Fi ($(get lien))" ;;
esac

echo
echo "Système"
V=$(get version)
if [ "$(get md5)" = "$KNOWN_MD5" ]; then ok "logiciel $V (version connue)"
else warn "logiciel $V : version inconnue de remarkable-studio" "les patchs QML peuvent ne plus s'appliquer ; le patch des couleurs ne sera pas lancé (voir docs/DECOUVERTES.md §3)"; fi
D=$(get disque); ok "espace utilisé sur /home : $D"

echo
echo "xovi"
[ "$(get xovi)" = oui ] && ok "xovi installé" || bad "xovi absent" "voir docs/INSTALLATION.md"
for e in qt-resource-rebuilder xovi-message-broker qt-command-executor; do
  [ "$(get ext_$e)" = oui ] && ok "extension $e" || bad "extension $e absente" "voir docs/INSTALLATION.md (outils/installer.sh active qt-command-executor s'il est présent)"
done
if [ "$(get hashtab)" != oui ]; then bad "index (hashtab) absent" "ssh $H 'echo | /home/root/xovi/rebuild_hashtable'  (PIN demandé)"
elif [ "$(get hashtab_recent)" != oui ]; then bad "index plus ancien que le programme (mise à jour du système ?)" "ssh $H 'echo | /home/root/xovi/rebuild_hashtable'  (PIN demandé)"
else ok "index (hashtab) à jour"; fi
if [ "$(get actif)" = oui ]; then ok "mods actifs (xovi lancé)"
else warn "mods inactifs (tablette redémarrée ?)" "ssh $H /home/root/xovi/start  (l'interface redémarre, PIN demandé) — ou bouton « Activer les modifs » de la bibliothèque"; fi

echo
echo "Mods remarkable-studio"
Q=" $(get qmd) "
for m in crayons menu_crayon formes quad primary eraser carnets_lies; do
  case "$Q" in *" $m "*) ok "module $m" ;; *) warn "module $m non installé" "outils/installer.sh (ou MODULES=\"$m\" outils/installer.sh)" ;; esac
done
for f in PenMenu.qml Formes.qml Quad.qml formes-etat.js; do
  [ "$(get fichier_$f)" = oui ] || bad "fichier $f absent" "outils/installer.sh"
done
[ "$(get trace)" = oui ] || bad "injecteur de traits (formes/trace.sh) absent" "outils/installer.sh"
if [ "$(get actif)" = oui ]; then
  [ "$(get formes_pretes)" -gt 0 ] 2>/dev/null && ok "moteur de formes chargé" \
    || warn "moteur de formes jamais chargé depuis le démarrage" "ouvrir un document ; sinon le patch formes.qmd ne s'applique plus (journalctl -u xochitl | grep qmldiff)"
  E=$(get erreurs_qml)
  [ "${E:-0}" -eq 0 ] 2>/dev/null && ok "aucune erreur dans les fichiers QML des mods" \
    || warn "$E erreur(s) QML dans les mods" "ssh $H \"journalctl -u xochitl | grep file:///home/root/xovi | grep -i error | tail\""
fi

echo
echo "Couleurs libres (patch facultatif)"
EXE=$(get exe)
if [ "$(get patch_installe)" != oui ]; then ok "patch non installé (couleurs et épaisseurs officielles seulement)"
elif [[ "$EXE" == *libre* ]]; then ok "patch actif ($EXE)"
elif [ "$(get md5)" != "$KNOWN_MD5" ]; then warn "patch installé mais pas lancé : programme d'origine différent (mise à jour)" "le patch est à refaire pour cette version (outils/patch_couleurs.py, docs/DECOUVERTES.md §3)"
else warn "patch installé mais pas lancé" "relancer les mods : ssh $H /home/root/xovi/start"; fi

echo
echo "Stabilité"
C=$(get plantages_24h)
[ "${C:-0}" -eq 0 ] 2>/dev/null && ok "aucun plantage de l'interface depuis 24 h" \
  || warn "$C plantage(s) de l'interface depuis 24 h (dernier : $(get dernier_plantage))" "ssh $H \"journalctl -u xochitl --since -24h | grep -B30 ABRT | tail -n 40\""

echo
echo "Connexions"
[ "$(get web_usb)" = oui ] && ok "interface web USB active (envoi de fichiers depuis la bibliothèque)" \
  || warn "interface web USB inactive : envoi de fichiers indisponible" "tablette : Paramètres > Stockage > Interface web USB"
if [ "$(get ssh_wifi)" = active ]; then
  W=$(get wifi_ip)
  [ -n "$W" ] && ok "SSH en Wi-Fi actif ($W)" || warn "SSH en Wi-Fi actif, mais la tablette n'est connectée à aucun Wi-Fi"
else ok "SSH en Wi-Fi désactivé (USB seulement ; activer : ssh $H rm-ssh-over-wlan on)"; fi

echo
[ $PROBLEMES -eq 0 ] && echo "Bilan : rien de bloquant." || echo "Bilan : $PROBLEMES problème(s) bloquant(s), voir les ✗ ci-dessus."
