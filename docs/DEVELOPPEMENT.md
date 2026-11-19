# Développement — reprendre le projet

Ce document sert à retrouver rapidement ses repères : où est quoi, comment les morceaux communiquent, comment
tester, et les règles à respecter. Pour le *pourquoi* technique (format, adresses, pièges), voir
[DECOUVERTES.md](DECOUVERTES.md) ; pour le schéma d'ensemble, [ARCHITECTURE.md](ARCHITECTURE.md).

## Carte du code

### PC (`pc/`, Python 3.10+, bibliothèque standard + rmscene, rmc, Pillow, pypdf, CairoSVG)

| Fichier | Rôle |
|---|---|
| `server.py` | serveur HTTP (127.0.0.1), routes, rendu des pages en SVG (`Renderer`), bibliothèque (`Library`), texte du PDF (`page_text`, `text_lines`) |
| `live.py` | liaison avec la tablette (`RM_HOST`, alias SSH USB/Wi-Fi), flux du stylet (`PenStream`), page affichée (`CurrentPage`, lit `vue.json`) |
| `screen.py` | image réelle de l'écran (mémoire de xochitl), pilotée par les événements ; chaque image porte la vue de son instant |
| `tablet.py` | état de la tablette, ouverture de page, liens, palette, commandes pour `Formes.qml` (`formes_cmd`) |
| `annots.py` | recherche dans le texte, annotations d'une page (surlignages + texte, traits), recherche globale, commentaires (`notes.json`) |
| `autohl.py` | surligneur à la taille du texte (survol du stylet → épaisseur) |
| `envoi.py` | file d'envoi vers la tablette (marques, imports, liens, palette) : persistante, confirmée, rejouée |
| `cadrage.py` | cadrage automatique des PDF (mesure des marges, `zoomFit` envoyé à `Formes.qml`, confirmation par la sauvegarde) |
| `autosync.py` | synchro de la sauvegarde toutes les 10 s (fichiers modifiés seulement) |
| `export_pdf.py` | export PDF : pages d'origine + encre vectorielle + vrais surlignages PDF |
| `draw.py`, `formules.py` | dessin injecté, formules LaTeX → image |
| `library.html` | bibliothèque (une page, sans dépendance) |
| `studio.html` | Studio (une page, sans dépendance) |
| `static/` | thème commun (`theme.css`, `theme.js`), couche de texte des PDF et barre de sélection (`textlayer.js`, Studio et bibliothèque), police Inter, logo |

### Tablette (`tablette/`)

| Fichier | Rôle |
|---|---|
| `xovi/*.qmd` | patchs QMLDiff ; chaque module charge un fichier QML de `crayons/` par un `Loader` rechargeable à chaud |
| `crayons/Formes.qml` | dans chaque page : formes, surlignage (`marks`), réglage du crayon (`pen`), images, `vue.json` |
| `crayons/PenMenu.qml` | ajouts au menu du crayon (épaisseur continue, couleurs libres, formes) |
| `crayons/Quad.qml` | bouton 4 cases (3 crayons + gomme) |
| `crayons/formes-etat.js` | état partagé (gabarits) — `.pragma library` : en cache jusqu'au redémarrage de l'interface |
| `formes/trace.sh`, `trace.awk` | injection de traits dans `/dev/input/event1` (busybox sh) |
| `patch-couleurs/` | lanceur de la copie patchée de xochitl (vérifie l'empreinte) |

### Outils (`outils/`)

`installer.sh`, `desinstaller.sh`, `diagnostic.sh` (état complet en une connexion), `patch_couleurs.py`,
`extraire_qml.py` (étudier le QML d'une nouvelle version), `test_formes.py` (test complet des formes sur la tablette), `test_perf.py` (temps de réponse du serveur, coût
de l'image en direct du Studio, avec seuils).

## Synchronisation : chacun fonctionne sans l'autre

- **La tablette est la référence pour son contenu** (documents, pages, surlignages, notes manuscrites). Elle
  fonctionne seule ; le PC en garde une copie (`autosync.py`, rattrapage complet si la tablette a redémarré).
- **Tout ce que le PC demande à la tablette passe par la file d'envoi** (`envoi.py`, `envoi.json`, fichiers joints
  dans `envoi/`) : surligner / souligner / barrer, importer un PDF ou EPUB (USB), carnets liés, palette.
  Rien n'est perdu si la tablette est absente : c'est exécuté dès que possible, et retiré de la file seulement
  quand la tablette a confirmé (`resultat.json`, ou la copie synchronisée). Une marque demandée à l'instant ouvre
  la page sur la tablette ; un rattrapage attend que la page y soit affichée (jamais de changement de page
  imposé). Studio et bibliothèque montrent la file (pastille, marques en pointillés, annulation).
- **Ce qui n'existe que sur le PC** (commentaires des surlignages, `notes.json`) n'est jamais effacé par la
  tablette : un commentaire dont le surlignage a été supprimé reste visible (« surlignages supprimés ») et
  trouvable.
- **En direct seulement** (agissent sur la page affichée) : formes, dessin, formules du Studio, réglage du
  crayon ; un échec est signalé, rien n'est mis en attente.

## Échanges PC ↔ tablette (tous par SSH)

| Sens | Moyen | Contenu |
|---|---|---|
| tablette → PC | `/home/root/xovi/formes/vue.json` | page affichée, orientation, correspondance écran → page, masque d'interface, crayon |
| PC → tablette | `/home/root/xovi/crayons/formes-cmd.json` | commandes (`build`, `place`, `marks`, `pen`, `image`, `placeImage`, `zoomFit`, `open`, `linksReload`, `cancel` ; mise au point : `diag`,
`zoomInfo`, `deleteArea`, `resetTemplates`), id croissant |
| tablette → PC | `/home/root/xovi/formes/resultat.json` | compte rendu de la dernière construction (`marks`, `build`) : `{id, ok, message}` ; le PC l'attend (`tablet.formes_run`) avant de répondre |
| PC ← tablette | `/dev/input/event1` (lecture) | stylet, survol compris |
| PC ← tablette | `/proc/<pid>/mem` de xochitl | image de l'écran |
| PC → tablette | `http://10.11.99.1/upload` | envoi de fichiers (interface web USB officielle) |
| PC → tablette | `formes-cmd.json` : `open`, `linksReload` | ouvrir un document à une page, relire les carnets liés (quand un document est ouvert ; la liste est aussi relue à chaque ouverture). xovi-message-broker n'est plus utilisé : ses signaux n'arrivent plus, et sollicité souvent il faisait planter l'interface |

Rechargement à chaud : incrémenter `/home/root/xovi/crayons/formes.version` (ou `quad.version`) ;
`PenMenu.qml` est relu à chaque ouverture du menu. Un changement de `.qmd` demande `xovi/start` (PIN).

## Routes du serveur

Lecture : `/` (bibliothèque), `/studio`, `/api/library`, `/api/library/version`, `/api/page/<doc>/<n>?hd=1|2`,
`/api/pagebg/<doc>/<n>` (PDF seul), `/api/text/<doc>/<n>`, `/api/search/<doc>?q=`, `/api/annotations/<doc>`,
`/api/notes/<doc>`, `/api/highlights?q=` (tous documents), `/api/export/<doc>.pdf[?annotees=1]`, `/api/thumb/<doc>`,
`/api/file/<doc>.pdf|.epub`, `/api/live/state`, `/api/live/pen` (flux SSE), `/api/screen/next?after=<seq>`
(image + en-têtes `X-Seq`, `X-Vue`), `/api/screen/stats`, `/api/pen`, `/api/palette`, `/api/autohl`, `/api/cadrage`, `/api/envoi[?doc=]`,
`/api/tablet/status`.

Écriture (POST, en-tête `X-RM-Viewer: 1` obligatoire) : `/api/tablet/open`, `/api/tablet/start`, `/api/links`,
`/api/pen`, `/api/palette`, `/api/formes/build`, `/api/annot` (surligner/souligner/barrer), `/api/draw`,
`/api/latex/render`, `/api/latex/send`, `/api/notes`, `/api/autohl`, `/api/cadrage`, `/api/envoi/annuler`, `/api/upload` (corps brut + `X-Filename`).

## Données et caches (jamais dans le dépôt)

| Chemin | Contenu |
|---|---|
| `pc/xochitl/` | sauvegarde des documents (synchro auto) |
| `pc/.cache/` | pages rendues (SVG), PNG des PDF, texte extrait (`*-p<i>-text.json`), annotations par page (`*-annots2-<mtime>.json`), formules. Limité à 300 Mo : les rendus les moins récemment utilisés sont retirés (toutes les 30 min) |
| `pc/notes.json` | commentaires des surlignages |
| `pc/reglages.json` | réglages (surligneur auto, cadrage auto) |
| `pc/envoi.json`, `pc/envoi/` | file d'envoi et fichiers à importer |
| `pc/cadrage.json` | état du cadrage de chaque PDF (fait, aucun, envoyé, échec) |
| `pc/tablette.conf`, `pc/.ssh_config` | adresse Wi-Fi, configuration SSH générée |
| `pc/carnets-lies.json`, `pc/crayons.json` | liens entre documents, palette |

Changer le format d'un cache : changer son nom (ex. `annots2`) pour que l'ancien soit ignoré.

## Repères géométriques

- Unités de page de la tablette : 1 unité = 1 pixel de l'écran à zoom 1 (226 dpi). PDF placé à **227 dpi**,
  centré en x = 0, haut en y = 0 : point PDF × 227 / 72, x décalé de la demi-largeur.
- SVG du serveur : coordonnées = unités de page × `SCALE` (72 / 226) ; `X-Scene-Bounds` = viewBox / SCALE.
- Écran physique : 1404 × 1872 (même en paysage). Capteur : `x_écran = ABS_Y / 15725 × 1404`,
  `y_écran = (1 − ABS_X / 20966) × 1872`.
- Correspondance écran → page (`vue.json`, `map`) : coins (0,0), (1404,0), (0,1872) exprimés dans la page.

## Tester

- **Serveur** : `python server.py --port 8799 --data <sauvegarde>` à côté de celui en service, puis `curl` sur les
  routes. Sans tablette, tout doit répondre (états « non connectée »).
- **Pages web** : Chromium sans interface piloté par le protocole DevTools (`--remote-debugging-port`), évaluer
  du JavaScript dans la page, capturer l'écran. Désactiver le cache (`Network.setCacheDisabled`) : `/static`
  est servi avec `max-age=300`, et le Chromium « snap » ignore `--user-data-dir` hors de son dossier.
- **Performance** : `python outils/test_perf.py` (serveur lancé) : routes < 300 ms, page en cache < 150 ms,
  image en direct du Studio < 40 ms. À relancer après toute modification du Studio ou du serveur.
- **Formes** : `python outils/test_formes.py --effacer` avec une page de TEST ouverte, stylet éloigné : construit
  les 7 formes (gabarits compris), vérifie chacune dans la page, le regroupement et le crayon rendu. À relancer
  après toute modification de `Formes.qml`, `Quad.qml` ou `PenMenu.qml` (ils partagent le crayon actif).
- **Tablette** : `outils/diagnostic.sh` ; journal : `journalctl -u xochitl -f` (les messages de `Formes.qml`
  commencent par `FORMES`). Avant d'injecter des traits de test, vérifier le document et la page ouverts.

## Sobriété (ce qui tourne en continu)

- Studio : état de la page 1×/s, crayon toutes les 4 s, capture de l'écran pilotée par les événements ; **rien
  quand l'onglet est caché** (la capture du serveur s'arrête 15 s après la dernière demande).
- Synchro de la sauvegarde : toutes les 10 s quand une page du PC sert, sinon toutes les 60 s (~0,3 s de
  processeur de la tablette par passage).
- Tablette : `Formes.qml` relit le fichier de commandes toutes les 0,4 s et écrit `vue.json` toutes les 0,7 s
  (Studio ouvert) ou 1,5 s.

## Règles

- Ne jamais rendre xovi persistant (démarrage automatique) : un redémarrage doit toujours revenir à l'origine.
- Chaque redémarrage de l'interface (`xovi/start`, nouvel index) demande le PIN de l'utilisateur.
- Ne jamais publier de fichiers de reMarkable (programme, QML extrait, index) ni de données personnelles.
- Interface et documentation en français ; textes d'interface sobres ; thème commun dans `static/theme.css`.
- Après une mise à jour du système : `outils/diagnostic.sh`, reconstruire l'index, vérifier les fichiers QML patchés,
  retrouver la fonction du patch des couleurs (DECOUVERTES §3).
