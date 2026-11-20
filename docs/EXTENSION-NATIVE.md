# Extension native : créer un trait sans stylet — défrichage

État : **analyse terminée sur une copie du programme (aucun essai sur la tablette)**. Ce document rassemble ce
qui a été établi, la méthode pour le retrouver dans une autre version, et ce qu'il resterait à faire.

## Pourquoi une extension native

Côté QML, impossible de créer un trait (voir DECOUVERTES.md) : `SceneController.addDrawingLine(stroke)` attend un
objet `Line`, que seul le code compilé fabrique (à partir du stylet) ; `Line` n'expose en QML que `lineLength()` et
des propriétés en lecture seule. Une extension xovi (bibliothèque C++ chargée dans xochitl) peut, elle, fabriquer
l'objet en mémoire et appeler la fonction directement.

## Ce qui est établi (xochitl 3.30.0.111, ARM 32 bits, PIE, dépouillé de ses symboles)

Retrouvé par `outils/analyse_moc.py` à partir des métaobjets Qt (le programme n'exporte qu'environ 200 symboles,
aucun pour ces classes : impossible de s'accrocher par nom).

| Élément | 3.30 | 3.29 |
|---|---|---|
| Métaobjet `SceneController` | `0x17a3470` | `0x1596f48` |
| `qt_static_metacall` de `SceneController` | `0x6215bc` | `0x56a6dc` |
| `addDrawingLine` (méthode n°) | 94 → **`0x648000`** | 93 → `0x58dbd8` |
| `highlightWithLine(Line, mode)` | 95 → `0x648328` | — |
| Métaobjet `Line` | `0x179d4a8` | `0x158ce08` |
| Taille de `Line` | **72 octets**, alignement 8 | 72 octets |

Adresses relatives au début du programme (PIE : ajouter l'adresse de chargement, lue par exemple dans
`/proc/self/maps` ou `dl_iterate_phdr`). Appel : `addDrawingLine(this = contrôleur, r1 = const Line*)`
(convention ARM EABI ; le cas n° 94 de l'aiguilleur fait `ldr r1, [r4, #4]` puis `bl 0x648000`).

### Disposition de `Line` (72 octets)

| Décalage | Taille | Champ | Preuve |
|---|---|---|---|
| `0x00` | 4 | outil (`Line::Tool` : 17 fineliner, 18 surligneur…) | propriété `tool` : `ldr r2, [r0]` ; `isHighlighter` = outil 5 ou 18, `isSelectionTool` = 11, `isEraserTool` = 6 ou 8 |
| `0x04` | 4 | couleur (`Line::Color`, 9 = couleur libre) | `hasExportedColor` lit `[r0, #4]` |
| `0x08` | 4 | couleur libre ARGB | trait par défaut : `0xFF000000` |
| `0x0c` | 12 | points : `QList<Point>` Qt 6 (pointeur de données partagées, pointeur vers les points, nombre) | `pointCount` = `[r0, #0x14]` ; `boundingRect` parcourt `[r0, #0x10]` par pas de 14 |
| `0x18` | 8 | épaisseur (double) | trait par défaut : 1,0 |
| `0x20` | 4 | longueur de départ (copiée sur 4 octets) | copie d'un trait |
| `0x24` | 4 | (remplissage) | mis à zéro |
| `0x28` | 32 | cache du rectangle englobant (`QRectF`, 4 doubles) ; vide (largeur ou hauteur ≤ 0) = recalculé | `boundingRect` |

**Point (14 octets)**, comme dans les fichiers `.rm` : x (float, `+0`), y (float, `+4`), puis vitesse, largeur
(2 × 16 bits), direction, pression (2 × 8 bits). Coordonnées en unités de page (repère de la scène).

Trait par défaut (code du programme) : `memset(trait, 0, 72)`, outil 9, ARGB `0xFF000000`, épaisseur 1,0.

## Ce qu'il resterait à faire

1. **Chaîne de compilation** : compilateur ARM (`arm-linux-gnueabihf-g++`, absent du PC aujourd'hui) et en-têtes
   **Qt 6.10.3** (version de la tablette) ; le SDK d'extensions de xovi (`xovi.h`).
2. **L'extension** : enregistrer pour le QML un objet natif (`qmlRegisterSingletonInstance`, exporté par Qt)
   avec une méthode `addLine(controller, outil, couleur, argb, épaisseur, points)` ; elle construit les 72 octets
   (la liste de points avec un vrai `QList` Qt 6 compilé contre la même version, pour un pointeur de données
   valide), puis appelle `base + 0x648000`. Rafraîchir ensuite l'affichage (`viewport.requestRepaint()` côté
   QML, ou `strokeHandler.updateStrokeRendering`).
3. **Vérifications avant le premier essai** : désassembler `0x648000` pour confirmer qu'elle **copie** le trait
   (et ne garde pas notre pointeur), et qu'elle gère l'annulation et l'enregistrement ; contrôler la version du
   programme (empreinte) au chargement et refuser toute autre version.
4. **Risque** : une erreur de disposition fait planter l'interface (redémarrage, PIN). Essais uniquement sur un
   document de test, xovi non persistant (un redémarrage revient toujours à l'origine).
5. **À chaque mise à jour** : relancer `outils/analyse_moc.py <programme> SceneController addDrawingLine` et
   `… Line` ; vérifier la disposition (le trait par défaut et la copie se retrouvent en cherchant `memset` de
   `0x48` octets suivi de l'écriture de `0xFF000000` en `+8`).

## Intérêt réel

L'écriture directe des fichiers (document fermé) et le surlignage accroché au texte par le stylet simulé
(document ouvert) couvrent déjà presque tout. L'extension ne servirait qu'à **souligner / barrer / dessiner dans
un document ouvert** sans passer par le gabarit (copie d'un trait tracé par le stylet simulé).
