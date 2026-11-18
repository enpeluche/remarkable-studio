# Architecture

```
 PC                                                     Tablette (SSH)
 ┌────────────── pc/server.py ──────────────┐          ┌──────────────────────────────────────────┐
 │ /         library.html  (sauvegarde)      │          │ xochitl + xovi (non persistant)           │
 │ /studio   studio.html                     │          │  ├ menu_crayon.qmd → PenMenu.qml (à chaud)│
 │ screen.py  capture de l'écran ────────────┼─ ssh ───▶│  ├ formes.qmd → Formes.qml (à chaud)      │
 │ live.py    stylet (event1), page affichée ┼─ ssh ───▶│  │    vue.json  (page, orientation,        │
 │ tablet.py  crayon, palette, liens ────────┼─ ssh ───▶│  │              correspondance, masque)    │
 │ draw.py    injection de traits ───────────┼─ ssh ───▶│  │    formes-cmd.json ← commandes          │
 │ formules.py LaTeX → image ────────────────┼─ ssh ───▶│  │    formes/trace.sh (injection)          │
 └───────────────────────────────────────────┘          │  ├ quad.qmd → Quad.qml (à chaud)          │
                                                        │  └ crayons.qmd (messages xovi : penGet…)  │
                                                        └──────────────────────────────────────────┘
```

- **Écran** : `screen.py` garde une session SSH ouverte ; la tablette lit l'image dans la mémoire de xochitl et la
  renvoie compressée, à la demande (pilotée par l'activité du stylet et `vue.json`). Chaque image est envoyée
  avec la vue de son instant (en-tête `X-Vue`). Le Studio pose dessous le PDF net (`/api/pagebg`) et ne garde de
  l'image que ce qui diffère du PDF.
- **Page affichée** : `Formes.qml` (dans chaque vue de page) écrit `vue.json` : identifiant de page, orientation,
  correspondance écran → page (3 coins), masque de l'interface (seulement si un Studio regarde : `studio.watch`).
- **Commandes vers la tablette** : le PC écrit `formes-cmd.json` (`build`, `place`, `image`, `placeImage`,
  `marks` — surlignage du texte —, `pen` — réglage du crayon —, `cancel`) ; `Formes.qml` le relit toutes les 0,4 s.
  L'état du crayon arrive dans `vue.json`. xovi-message-broker ne sert plus qu'aux actions ponctuelles (ouvrir
  une page, recharger les liens) : sollicité en continu, il fait planter l'interface.
- **Synchro** : `autosync.py` (toutes les 10 s : fichiers modifiés depuis le passage précédent, puis rsync).
- **Export PDF** : `export_pdf.py` (pypdf + CairoSVG) : pages d'origine + encre en vectoriel.
- **Liaison** : `live.py` génère `.ssh_config` (alias `remarkable` : USB si joignable, sinon Wi-Fi de `tablette.conf`).
- **Formes** : gabarits (droite redressée) copiés une fois par style (`formes-etat.js`, partagé entre pages),
  puis collés/étirés/tournés par `SceneController`. Voir [DECOUVERTES.md](DECOUVERTES.md) §5.
- **Rechargement à chaud** : `Formes.qml`, `PenMenu.qml`, `Quad.qml` sont chargés par des `Loader` dont la source
  porte un numéro de version (fichiers `*.version`) : on les modifie sans redémarrer l'interface.
