# Installation

## 1. Le PC (Linux)

Prérequis : Python 3.10+, `rsync`, `ssh`, **poppler-utils** (`pdftoppm`) ; pour les formules : **TeX Live**
(`latex`, `dvipng`, paquets `amsmath`, `mathtools`, `standalone`).

```bash
cd pc
python3 -m venv .venv
.venv/bin/pip install -r ../requirements.txt
.venv/bin/pip install --no-deps rmc==0.3.0      # rmc veut rmscene < 0.7, mais il faut rmscene 0.8
```

Accès SSH à la tablette : **Paramètres → Aide → À propos → Copyrights et licences** donne le mot de passe root ;
installez votre clé (`ssh-copy-id root@10.11.99.1`) pour ne plus le taper.

```bash
./sync.sh        # copie les documents de la tablette dans pc/xochitl/ (rien n'est jamais effacé localement)
./lancer.sh      # démarre le serveur et ouvre http://127.0.0.1:8765/
```

### Wi-Fi

1. En USB, activer SSH en Wi-Fi (désactivé par défaut) : `ssh root@10.11.99.1 rm-ssh-over-wlan on`.
2. Copier `pc/tablette.conf.exemple` en `pc/tablette.conf` et y mettre l'adresse Wi-Fi de la tablette
   (Paramètres → Aide → À propos → Copyrights et licences).
3. C'est tout : à chaque connexion, l'USB est utilisé s'il répond, sinon le Wi-Fi (débrancher / rebrancher en
   cours de route fonctionne). La bibliothèque affiche « · USB » ou « · Wi-Fi ».

Un peu plus lent qu'en USB (image d'écran complète ~1,6 s contre ~1,0 s). SSH root étant alors ouvert sur le
réseau, à réserver à un réseau de confiance (couper : `rm-ssh-over-wlan off`). Pour forcer une adresse :
`export RM_HOST=root@<adresse>`.

## 2. La tablette

1. **xovi** : suivre [xovi](https://github.com/asivery/xovi) et installer les extensions
   **qt-resource-rebuilder**, **xovi-message-broker** et **qt-command-executor**
   ([rm-xovi-extensions](https://github.com/asivery/rm-xovi-extensions)). Construire l'index une fois :
   `ssh root@10.11.99.1 'echo | /home/root/xovi/rebuild_hashtable'` (l'interface redémarre, PIN demandé).
   **Ne configurez pas xovi pour démarrer automatiquement** : en cas de problème, un redémarrage suffit à revenir.
2. **Les mods** : `outils/installer.sh`. Pour n'installer que certains modules :
   `MODULES="menu_crayon formes quad" outils/installer.sh`.

   | Module | Rôle |
   |---|---|
   | `crayons` | accès au crayon depuis le PC (lecture, réglage) |
   | `menu_crayon` | menu du crayon : épaisseur continue, couleurs libres, formes |
   | `formes` | accroche dans la page : formes parfaites, formules, suivi de page pour le Studio |
   | `quad` | bouton « 4 cases » (3 crayons + gomme) à la place du crayon secondaire |
   | `primary`, `eraser` | masquent les boutons crayon principal et gomme (remplacés par `quad`) |
   | `carnets_lies` | bouton « carnet lié » |

3. **Activer** : `ssh root@10.11.99.1 /home/root/xovi/start` (PIN). À refaire après chaque redémarrage de la tablette
   (ou bouton « Activer les modifs » dans la bibliothèque).
4. **Couleurs libres et épaisseur continue** (3.30) : nécessitent le patch du programme, à installer en connaissance
   de cause ([SECURITE.md](SECURITE.md)) : `outils/patch_couleurs.py --j-accepte-les-risques`.

## 3. Après une mise à jour du système

- `ssh-keygen -R 10.11.99.1` (la clé de la tablette change) ; vos fichiers dans `/home/root` sont conservés.
- Reconstruire l'index : `ssh root@10.11.99.1 'echo | /home/root/xovi/rebuild_hashtable'`.
- Vérifier les fichiers QML que modifient les patchs (`outils/extraire_qml.py` aide à comparer les versions).
- Le patch des couleurs refuse de s'appliquer à une version inconnue ; sa copie installée n'est plus lancée
  (`run.sh` vérifie l'empreinte du programme). Voir [DECOUVERTES.md](DECOUVERTES.md) §3 pour retrouver la fonction.
