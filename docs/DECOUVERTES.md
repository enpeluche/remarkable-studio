# Découvertes

Ce que nous avons appris en construisant remarkable-studio, sur une **reMarkable 2, logiciel 3.30.0.111** (bêta),
avec [xovi](https://github.com/asivery/xovi) (pré-v20). Tout a été mesuré ou vérifié sur la tablette ; les adresses
dans le binaire ne valent que pour cette version.

## 1. Accès, format, documents

- **SSH par USB** : `root@10.11.99.1` (Dropbear, BusyBox). `head` exige `-n N`, `ps -o` n'existe pas, `date` ne
  connaît pas `%N`.
- **Le `printf` de bash découpe ses écritures** : pour écrire des `input_event` binaires dans `/dev/input/event1`
  (que le noyau refuse si la taille n'est pas un multiple de 16 octets), utiliser `busybox sh`.
- **Documents** : `/home/root/.local/share/remarkable/xochitl/` (`.metadata`, `.content` avec `cPages`, un `.rm`
  par page). Format `.rm` v6 lisible avec [rmscene](https://github.com/ricklupton/rmscene) **0.8** (nécessaire pour
  `color_rgba`, les couleurs libres), même si rmc 0.3.0 réclame rmscene < 0.7.
- **Les PDF sont placés à 227 dpi**, centrés en x = 0, haut en y = 0 — pas 226 : l'écart (0,44 %) est mesurable
  via `controller.primaryContentRect` et provoque un décalage vertical croissant si l'on rend à 226 dpi.
- **xochitl n'écrit le `.rm` qu'au changement de page** (et périodiquement en `.rm.tmp`).
- **Ouvrir un document à une page** : `root.onOpened({documentId, page})` dans MainView (page à partir de 0).
  Changer de page *dans le même document* par ce moyen n'est pas toujours pris en compte.

## 2. xovi et QMLDiff

- **Non persistant** : `xovi/start` monte un *drop-in* systemd en tmpfs ; un redémarrage de la tablette revient
  à l'origine. Chaque redémarrage de l'interface demande le **PIN**.
- **Après une mise à jour du système** : la clé SSH de la tablette change ; il faut reconstruire l'index
  (`echo | xovi/rebuild_hashtable`, PIN) et vérifier que les fichiers QML patchés n'ont pas changé.
- **Sélecteurs QMLDiff** (lus dans le code de qmldiff) : `Type:nom` sélectionne un objet affecté à une propriété
  (`Item:foldoutContent`), `Type#id` par identifiant ; un composant `component X: Y {}` se sélectionne comme `Y:X` ;
  `REPLACE nomDePropriété WITH { … }` remplace une affectation.
- **Recharger du QML à chaud** : un `Loader` dont la source contient un numéro de version lu dans un fichier
  (`…/Formes.qml?v=N`) permet de modifier l'interface **sans redémarrer** (et sans PIN).
- **XHR vers `file://`** : en *synchrone*, `PUT` crée le fichier **vide** ; utiliser l'asynchrone.
- Les catégories de journalisation Qt sont `rm.*` (`rm.shapedetector`, `rm.ui.scenepeninputhandler`,
  `rm.peninput`…), à activer par `QT_LOGGING_RULES`.

## 3. Crayons et couleurs

- Le crayon actif (`documentViewTools.activePen`, classe C++ `PenSetting`) expose `tool`, `color`, `colorCode`
  (ARGB), `thickness` (un `double`), `snapHighlighterToText`. Outils : 17 fineliner, 15 stylo bille, 16 marqueur,
  14 crayon, 13 porte-mine, 12 pinceau, 21 calligraphie, 18 surligneur.
- **Couleur libre** = `color = Line.ArgbCode` (9) + `colorCode` ARGB ; enregistrée dans le `.rm` (`color_rgba`).
- **3.29** : la remise à noir se faisait en QML (`WritingTool.qml`, `ensureSelection`) — patchable en QML.
- **3.30** : le contrôle est passé en **C++**. Une fonction (à `0x952aa4`) reçoit le crayon, cherche l'outil dans une
  table (couleurs autorisées, ARGB compris, et épaisseurs autorisées) et renvoie une correction : couleur
  officielle **la plus proche en RGB**, cran d'épaisseur le plus proche. Elle est appelée par les slots
  `propertyChanged` de `DocumentToolSettings`. Remplacer son début par « résultat vide » (7 instructions ARM)
  rend couleurs libres et épaisseur continue — voir `outils/patch_couleurs.py`.
  *Méthode pour la retrouver dans une autre version* : la fonction lit `pen+0x10` (couleur), la compare à 9,
  lit `pen+0x14` (ARGB) et `pen+0x18` (épaisseur, double) ; les accès aux propriétés se lisent dans le
  `qt_static_metacall` de `PenSetting`, retrouvé à partir de sa table de chaînes moc.
- Le **rendu en direct** de l'encre (couche compilée) dessine les couleurs libres en noir jusqu'au rafraîchissement
  (~10 s) : non modifiable.

## 4. Stylet : lire et injecter

- **Digitaliseur** : `/dev/input/event1` (Wacom), `ABS_X` 0..20966 (axe long), `ABS_Y` 0..15725, pression 0..4095,
  événements de 16 octets. Orientation 0 : `x_écran = ABS_Y/15725·1404`, `y_écran = (1 − ABS_X/20966)·1872`.
- **Injecter** des événements crée de vrais traits avec le crayon actif. Il faut cadencer **côté tablette** (sinon
  les paquets arrivent groupés et des points sont perdus), poser le stylet immobile quelques échantillons au début
  et à la fin, et « amorcer » par un survol (le tout premier trait injecté est parfois ignoré).
- **Le noyau ignore les valeurs `ABS` répétées à l'identique** : un stylet « immobile » injecté n'émet donc rien.
- **Déclencher le geste natif « dessiner et maintenir »** (redressement en forme parfaite) par injection : il faut
  imiter un vrai stylet pendant le maintien — **pression au maximum**, **léger tremblement** (±8 unités),
  **inclinaison** (`ABS_TILT_X/Y`), paquets toutes les 5 ms. Un vrai stylet envoie ~540 échantillons/s.
- **Détecteur natif** (`shapedetector.cpp`, `drawandholdgesture.cpp`) : d'abord « ligne droite ? »
  (`lengthRatio` = longueur / distance début-fin ≈ 1, `maxDistance` à la corde faible), sinon simplification en
  sommets : Triangle (3), Quad / Rectangle (4, rectangle si angles droits), Ellipse ; 5 sommets et plus : refusé.
  Presque carré ou presque cercle : **forcé** carré / cercle. Trait produit : droite 2 points, triangle 4,
  rectangle 5, cercle 65 ou 101 points.

## 5. Créer des traits parfaits instantanément

On ne peut pas fabriquer un trait (`Line`) ni un `QPainterPath` depuis le QML, et aucune fonction ne change le
style d'une sélection. Mais le contrôleur de la page (`SceneController`, `view.controller` dans
`DeviceSceneView.qml`) expose la sélection :

| Fonction | Usage |
|---|---|
| `addSelectionRect(rectPage, 1)` | sélectionner (seulement si le crayon **actif** — `toolSettings.activePen`, qui n'est pas toujours `primaryPen` — est `Line.SelectionTool` ; asynchrone : relire `selectionItemCount` ensuite) |
| `cloneSelectedItems(calque, defaultScale)` | copier la sélection → liste de traits (comme le presse-papiers) |
| `cloneAddAndSelectItems(calque, traits, 1/defaultScale, centre)` | coller **centré** sur un point de la page |
| `scaleSelectedItems(calque, origine, sx, sy)` | étirer |
| `rotateSelectedItems(calque, origine, degrés)` | tourner |
| `applyPendingEdit(calque)`, `clearSelectedItems()`, `deleteSelectedItems(calque)` | valider, désélectionner, supprimer |

D'où le **gabarit** : une droite injectée puis redressée par la tablette (2 points, parfaitement droite), copiée
une fois par style de crayon, puis collée/étirée/tournée pour chaque segment (grille de 14 lignes en ~30 ms).

- **L'épaisseur suit `sqrt(sx·sy)`** : étirer une droite de `(k, 1/k)` garde l'épaisseur exacte (une droite n'a pas
  de largeur géométrique).
- **Le gabarit doit être parfaitement droit** : étiré jusqu'à ×60 dans la largeur, le moindre écart d'injection
  devient un éventail de segments.
- **La longueur réelle d'un trait injecté diffère de ~1,6 %** de celle visée (calibration capteur → écran) :
  mesurer le gabarit posé (largeur de l'enveloppe − épaisseur).
- **Une épaisseur quelconque** (bande de surligneur) : la droite n'ayant pas de hauteur, `sy` ne change que
  l'épaisseur ; pour une épaisseur `e` à partir d'un gabarit d'épaisseur `t` étiré de `k` : `sy = (e / t)² / k`.
  Avec un gabarit de surligneur (snapHighlighterToText coupé pendant sa fabrication), on obtient des surlignages
  parfaits de la hauteur exacte d'une ligne de texte, n'importe où dans la page (pas seulement à l'écran).
- Cercles et ellipses : segments de ~14 px (écart au vrai cercle < 0,2 px), épaisseur exacte, inclinaison libre.
- **Annulation** : chaque élément collé + transformé + validé = **une** étape. Après une sélection, `undo()`
  s'applique **en différé** (~0,5 s), comme `undoAvailable`. Pour « annuler en un coup » : copier toute la forme,
  annuler les N étapes d'un coup, vérifier (zone vide, page amputée d'exactement N éléments), recoller le bloc.
- `getLineBoundingRectsToBeSelected(rect)` liste les traits d'une zone : pratique pour vérifier.
- Faire tourner du code depuis le QML : extension `qt-command-executor` (`executeCommand` est bloquant : lancer
  en arrière-plan avec `sh -c "… &"`).

## 6. Écran réel, page affichée, interface

- **L'image affichée** se trouve dans la mémoire de xochitl : zone anonyme **juste après** la projection de
  `/dev/fb0` (`/proc/<pid>/maps`), à +8 octets, 1404 × 1872 BGRA (même en paysage : l'interface y est dessinée
  tournée). Lecture : `dd` sur `/proc/<pid>/mem` + `gzip -1` → ~50 Ko, ~0,45 s de processeur par image.
- **Correspondance écran → page** : `layer.mapFromItem(null, x, y)` puis `tileManager.viewToScene(…)` sur trois
  coins de l'écran donne une transformation affine exacte (zoom, défilement, rotation compris).
- **Orientation** : la vue garde 1404 × 1872 en paysage ; `Values.isPortraitOrientation` et l'angle mesuré par
  `mapToItem` la donnent.
- **Masquer l'interface** dans l'image : parcourir l'arbre QML (hors `DeviceSceneView`) et marquer les éléments
  réellement dessinés (`Text` non vide, `Image` avec source, `Rectangle` coloré) — ~43 ms pour ~180 éléments.
- **Barre d'outils** : `Toolbar.pens` (`primaryPen`, `secondaryPen`, `activePen`, `requestPenSelect(bouton, mode)`),
  `Toolbar.eraser` (`pen`, `eraserToolSelected`, `eraserThicknessSelected`, `eraseAllSelected`), `shouldShow` pour
  masquer un bouton, `Toolbar.geometry.tooltipOverlay` (calque qui pivote avec l'interface ; `container` couvre tout
  l'écran). Le bouton actif est mis en évidence par `highlighted` / `selected`.
- **Insérer une image** dans la page : `controller.insertImageFileAsSceneItem(url, pointPage)` (recompressée en JPEG).

## 7. Ménager le processeur

Mesures sur la tablette (2 cœurs) : capture complète toutes les 2 s = ~22 % d'un cœur ; pendant l'écriture,
captures en continu = ~90 %. Remèdes retenus : capture pilotée par les événements (bande de lignes sous la pointe
pendant l'écriture, image complète après 1,5 s de pause ou un changement de page signalé par un petit fichier),
masque d'interface calculé seulement quand un Studio regarde. Résultat : **45 % → 8 %** de la machine avec le
Studio ouvert au repos, 0 % sans lui. Les commandes distantes de longue durée doivent s'arrêter à la fin de leur
entrée (`… & P=$!; read _; kill $P`), sinon elles s'accumulent.

## 8. Pièges rencontrés (et parades)

- **xovi-message-broker sous sollicitation → plantage de xochitl** (SIGABRT, l'interface redémarre, le PIN est
  redemandé) : interroger l'état du crayon toutes les ~4 s par ce canal finissait par le faire boucler sur
  « Failed to open pipe /run/xovi-mb for reading », puis planter (3 fois en une journée). Parade : ne plus
  l'utiliser pour les échanges fréquents ; l'état du crayon est écrit par le QML dans un fichier (`vue.json`)
  et les réglages passent par un fichier de commandes relu toutes les 0,4 s.
- **Lire un fichier pendant que le QML le réécrit** (`XMLHttpRequest` PUT) donne un fichier vide ou tronqué :
  relire, puis garder la dernière lecture valide, plutôt que de se rabattre sur une autre source.
- **`Toolbar.pens` n'existe que dans le contexte de la barre d'outils** : depuis une vue de page (`DeviceSceneView`),
  il vaut `undefined`. Un code qui doit réagir aux boutons de crayon doit vivre dans la barre d'outils.
- **Un module JavaScript `.pragma library` reste en cache** tant que l'interface tourne : le recharger à chaud ne
  relit pas le fichier ; une variable ajoutée n'existe qu'après un redémarrage (ranger l'état dans un objet déjà
  présent en attendant).
- **Le bouton du crayon secondaire** : en 3.30, les pastilles officielles passent par
  `Toolbar.pens.penColorSelected` (C++) ; écrire directement `pen.color` / `pen.colorCode` fonctionne aussi.
  Un bouton qui recharge un crayon enregistré doit savoir quelle case est active sans exiger que le crayon soit
  identique à l'enregistré (sinon toute modification est écrasée au toucher suivant).
- **Après un déplacement de la page, la tablette redessine par morceaux** : une capture d'écran trop rapide a
  des bords sombres (droite, bas). Attendre que la vue soit stable ~1,2 s, puis une seconde capture de contrôle.
- **Associer chaque capture d'écran à la correspondance écran → page de son instant** (lue juste avant), sinon
  une ancienne image est posée avec un nouveau zoom.
- **Le texte d'un PDF** se positionne exactement avec `pdftotext -bbox-layout` : point PDF × 227 / 72, x décalé
  de la demi-largeur de page.
- **Image d'écran nette** : soustraire le PDF (rendu dans le repère de l'écran par la correspondance inverse, puis
  minimum 3 × 3 pour tolérer l'anticrénelage) ne laisse que l'encre ; le PDF net se pose dessous.
- **SSH en Wi-Fi** : désactivé par défaut, commande officielle `rm-ssh-over-wlan on|off`. Une configuration SSH
  avec `Match originalhost … exec "test TCP vers 10.11.99.1:22"` choisit l'USB s'il répond, sinon le Wi-Fi.
- **Synchro légère** : `find -newer <repère>` (repère dans `/tmp` de la tablette, en mémoire) puis
  `rsync --files-from` : ~0,3 s de processeur pour 16 500 fichiers.
- **Surligneur** : un trait de surligneur non accroché au texte est une droite (`HIGHLIGHTER_2`) dont la largeur
  enregistrée dans chaque point vaut 4 × les unités de page ; la largeur de la bande vaut **30 × l'épaisseur du
  crayon** (`thickness_scale`). Le surlignage « accroché au texte » est un élément à part (`GlyphRange`) qui
  enregistre le texte lui-même.
- **Identifiant stable d'un trait** : sa clé CRDT dans la scène (`CrdtId(auteur, n)`), conservée d'un
  enregistrement à l'autre : avec l'identifiant de la page, elle suffit à rattacher des données (commentaires).
- **Une capture d'écran gardée en mémoire vieillit** : un serveur qui s'endort doit l'oublier à son réveil.
- **Annotations PDF lisibles par Zotero** : `/Highlight` avec `/QuadPoints` par ligne (haut-gauche, haut-droite,
  bas-gauche, bas-droite), un rendu `/AP` (fondu « multiplier »), et le commentaire dans `/Contents` (Zotero relit
  lui-même le texte sous les zones).
- **Les blocs inconnus 14 et 15** apparaissent dans les pages 3.30 (rmscene 0.8 les ignore sans dommage).
- **Protocole « taille puis contenu » sur un fichier vivant** : annoncer `wc -c` de `vue.json` puis le `cat`
  donne parfois moins d'octets qu'annoncé (réécrit entre les deux) ; le PC les attend indéfiniment et la capture
  d'écran se fige (constaté après des heures). Parade : copier le fichier avant de le mesurer, et un délai maximal
  (15 s) sur chaque réponse, qui coupe la connexion (groupe de processus entier) pour la refaire.
- **Le crayon actif n'est pas forcément `primaryPen`** : le bouton 4 cases active le crayon secondaire ; tout ce
  qui change d'outil (passage à l'outil Sélection) doit viser `toolSettings.activePen`. Revenir de l'outil
  Sélection arrondit l'épaisseur (0,9 → 1 au surligneur) : mémoriser et remettre tout le réglage.
- **Tracé provisoire du Studio** : la mémoire d'écran lue ne contient pas toujours déjà le dernier trait ; ne
  retirer le tracé instantané que quand l'image capturée montre l'encre à sa place.
- **Zoom d'un document** : `.content` garde `zoomMode` (`bestFit` par défaut, `fitToWidth`, `fitToHeight`,
  `customFit`) et `customZoomScale`, `customZoomCenterX/Y`, `customZoomPageWidth/Height`, `customZoomOrientation`.
  `LibraryController.setCustomZoomFit(id, échelle, centre, taille de page)` (QML, `xofm.libs.library`) l'enregistre
  pour n'importe quel document, ouvert ou non ; l'affichage change à la prochaine ouverture depuis la bibliothèque.
  Échelle = pixels de l'écran par unité de page (page entière d'un US Letter : 1404 / 1929,5 = 0,7276) ; centre =
  point de la page au milieu de l'écran. `setZoomMode(id, 0)` = `bestFit`, `1` = `fitToWidth`, `3` = `customFit`.
- **Synchro par `find -newer`** : la tablette écrit un fichier dans un temporaire puis le renomme ; le fichier
  garde l'heure d'écriture, qui peut précéder le repère posé par un passage tombé entre les deux. Poser le repère
  quelques secondes dans le passé (`touch -d "@$(( $(date +%s) - 2 ))"`).
