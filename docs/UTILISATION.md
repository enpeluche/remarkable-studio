# Utilisation

## Studio (PC) — http://127.0.0.1:8765/studio

- **Le document ouvert sur la tablette**, toutes ses pages, sur toute la largeur. Sur la page ouverte, la zone que
  montre la tablette est **en direct** (contour pointillé), sans l'interface de la tablette ; le reste est le rendu
  enregistré. Ce que vous écrivez apparaît instantanément.
- **Outils** (barre du haut) : Voir (cliquer une page l'ouvre sur la tablette), Libre, Règle, Rectangle, Cercle
  (centre puis rayon), Ellipse (grand rayon depuis le centre, puis petit rayon à la souris, clic), Grille, Polygone,
  Repère, Formule. Les outils agissent sur la page ouverte.
- **Palettes** flottantes : Crayon (outil, couleur, épaisseur, palette), Formes (espacement, côtés),
  Formule (LaTeX avec aperçu ; la formule se glisse et se redimensionne sur la page, puis ✓ Placer).
- **Texte du PDF** (outil Voir) : sélectionner à la souris ; une barre propose 4 surligneurs, souligner, barrer
  (couleur du crayon) et copier. Les marques sont tracées sur la tablette (page ouverte d'abord si besoin), en
  traits parfaits, annulables d'un seul geste ; le crayon de l'utilisateur est restauré ensuite.
- **Zoom du Studio** (indépendant de la tablette) : boutons − / + de l'en-tête, Ctrl + molette, touches `+` `−` `0`.
  Le PDF est rendu à la résolution de la tablette, au double quand on zoome.
- **Zone en direct nette** : sous la zone visible sur la tablette, le PDF net ; par-dessus, seulement ce qui diffère
  du PDF dans l'image de l'écran (encre, couleurs). Un effacement sur la tablette se voit tout de suite.
- **Recherche** (Ctrl+F ou la loupe) : dans tout le texte du document, sans tenir compte des majuscules ni des
  accents ; résultats encadrés sur les pages, Entrée / Maj+Entrée pour passer de l'un à l'autre, bouton pour
  ouvrir la page du résultat sur la tablette.
- **Annotations** (en-tête) : par page, les surlignages avec leur texte (natifs, au surligneur, ou posés depuis le
  Studio) et le nombre de traits manuscrits ; un clic y emmène ; « Copier en Markdown » (citations + pages +
  commentaires).
- **Commentaires** : outil Voir, **clic sur un passage surligné** : petite fenêtre pour écrire un commentaire
  (Ctrl+Entrée). Gardés sur le PC (`pc/notes.json`), jamais sur la tablette ; pastille violette sur les passages
  commentés ; repris dans la recherche de la bibliothèque, le Markdown et l'export PDF.
- **Surligneur à la taille du texte** (palette Crayon) : pendant que le stylet survole une ligne de texte avec le
  surligneur, son épaisseur est réglée pour que la bande ait la hauteur de la ligne (serveur du PC allumé ; sur la
  tablette, désactiver « accrocher au texte »).
- **PDF** (en-tête) : exporte le document ouvert, annotations comprises (Maj+clic : pages annotées seulement).
- Raccourcis : `V` voir, `L` libre, `R` règle, `C` cercle, `E` ellipse, `G` grille, `P` polygone, `F` formule,
  `Entrée` placer la formule, `Échap` annuler.

## Bibliothèque (PC) — http://127.0.0.1:8765/

- **Synchro automatique** : toutes les 10 s, seuls les fichiers modifiés sur la tablette sont recopiés ; la page
  se met à jour sans perdre la position. Rien n'est jamais effacé de la sauvegarde. (La tablette n'enregistre une
  page qu'en changeant de page : la page en cours arrive un peu plus tard.)
- **Recherche** : tape un mot (3 lettres ou plus) ; en plus des documents, la section « Dans vos surlignages »
  liste les passages surlignés (et commentaires) qui le contiennent, dans tous les documents ; un clic ouvre la
  bonne page. (Au premier lancement, la bibliothèque est analysée en arrière-plan, quelques minutes.)
- **Envoyer des PDF / EPUB sur la tablette** : bouton « Envoyer », ou glisser-déposer les fichiers sur la page.
  Ils arrivent dans « Mes fichiers », sans redémarrage (USB, avec Paramètres > Stockage > Interface web USB activé).
- **Export PDF** : bouton « PDF » d'un document ouvert (Maj+clic : pages annotées seulement). Pages sans
  annotation recopiées telles quelles (texte, liens), encre en vectoriel par-dessus, page agrandie si l'encre
  déborde dans la marge ; pages de notes et carnets : pages blanches avec l'encre.

## Sur la tablette

- **Menu du crayon** : sous les épaisseurs, un curseur continu ; à droite, « Couleurs libres » (palette partagée
  avec le PC, appui long pour retirer), couleur en cours (hexadécimal, nom), curseurs R/V/B, et **Formes**.
- **Formes** : choisir une forme, l'étirer au stylet (aperçu en pointillés), lever. La première fois pour un style
  de crayon, éloigner le stylet ~1 s (fabrication du gabarit). Sur une zone vide, la forme s'annule d'un seul geste.
- **Bouton 4 cases** : toucher une case pour changer de crayon ; toucher la case active pour le menu complet.
  Chaque case garde ses réglages : ce qui est changé ensuite (couleur, épaisseur, outil, depuis le menu ou le PC)
  est enregistré dans la case active. **Appui long** : y copier le crayon actuel. Case gomme : 2e appui = types
  de gomme, tout effacer.
- **Carnets liés** : lier deux documents depuis la bibliothèque du PC ; un bouton en bas à droite passe de l'un à l'autre.
