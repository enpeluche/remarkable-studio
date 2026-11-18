# Sécurité, risques, retour en arrière

**Ce que fait le projet :**
- xovi injecte des modifications dans l'interface de la tablette **à son lancement** ; rien n'est écrit sur la
  partition système. **Un redémarrage de la tablette revient à l'origine.**
- Le patch des couleurs (facultatif) lance une **copie modifiée** du programme, gardée dans `/home/root/xovi/` ;
  `/usr/bin/xochitl` n'est jamais modifié, et la copie n'est lancée que si le programme d'origine est exactement
  la version prévue.
- L'extension `qt-command-executor` permet au QML de **lancer des commandes en root** : seuls nos fichiers
  l'utilisent (injection des gabarits), mais c'est une capacité puissante.
- Le serveur du PC n'écoute que sur `127.0.0.1` ; les requêtes qui agissent exigent un en-tête spécial (protection
  contre les sites tiers). Il dispose d'un accès SSH root à la tablette.

**Risques :** logiciel non officiel sur une version bêta ; une mise à jour peut casser les mods (ils ne s'appliquent
alors plus, ou l'interface peut refuser de démarrer avec eux → redémarrer). La garantie de la tablette peut être en
jeu selon l'usage. Gardez une sauvegarde (`pc/sync.sh`).

**Tout retirer :** `outils/desinstaller.sh`, `outils/patch_couleurs.py --retirer`, puis redémarrer la tablette.
Pour désinstaller xovi lui-même, voir sa documentation.

**Ne jamais publier** vos documents (`pc/xochitl/`), vos liens (`pc/carnets-lies.json`), votre palette, ni les
fichiers de reMarkable (programme, QML extrait, index) : le `.gitignore` les exclut.
