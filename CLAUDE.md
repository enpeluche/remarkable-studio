# remarkable-studio — notes pour l'assistant

- Lire d'abord `docs/DEVELOPPEMENT.md` (carte du code, échanges PC ↔ tablette, routes, caches, tests, règles),
  puis `docs/DECOUVERTES.md` pour le détail technique de xochitl 3.30.
- Répondre et documenter en français.
- Tablette : `ssh root@10.11.99.1` (USB) ; `outils/diagnostic.sh` donne l'état complet sans rien modifier.
- Ne jamais rendre xovi persistant ; prévenir avant tout redémarrage de l'interface (PIN demandé).
- Vérifier le document et la page ouverts avant d'injecter des traits de test sur la tablette.
- Ne jamais committer de données personnelles (sauvegarde, notes.json, tablette.conf…) ni de fichiers de reMarkable.
- Après toute modification du QML de la tablette : `outils/test_formes.py --effacer` sur une page de test.
  Le crayon actif est `toolSettings.activePen` (le bouton 4 cases active le crayon secondaire, pas `primaryPen`).
