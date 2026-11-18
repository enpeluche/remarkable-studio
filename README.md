# remarkable-studio

Des outils pour la **reMarkable 2** : voir et piloter sa tablette depuis le PC, et enrichir son interface.

- **Studio** (navigateur du PC) : le document ouvert sur la tablette, **en direct**. L'écran réel de la tablette
  est posé sur le rendu des pages enregistrées (le reste du document reste visible), sans l'interface de la tablette.
  On y règle le crayon, on y place des **formes parfaites** et des **formules LaTeX**, on y dessine, et on
  **surligne / souligne / barre le texte du PDF** à la souris (comme dans Zotero) : de vrais traits apparaissent
  sur la tablette, même hors de l'écran.
- **Sur la tablette** (mods xovi) :
  - menu du crayon enrichi : **épaisseur continue**, **couleurs libres** (R/V/B, hexadécimal, palette), **formes** ;
  - **formes parfaites instantanées** : règle, rectangle, cercle, ellipse (inclinable), grille, polygone, repère —
    à étirer au stylet, annulables d'un seul geste ;
  - **bouton « 4 cases »** : 3 crayons enregistrés + la gomme, dans un seul bouton de la barre d'outils ;
  - **carnets liés** : un bouton pour passer d'un document à son carnet de notes associé.
- **Bibliothèque** (navigateur du PC) : la sauvegarde de la tablette, **synchronisée automatiquement**, pages
  rendues avec leurs annotations, **export PDF** (annotations en vectoriel, texte du PDF conservé).
- **USB ou Wi-Fi**, choisi automatiquement (USB prioritaire).

> ⚠️ **Projet non officiel, à vos risques.** Il modifie le comportement du logiciel de la tablette (via
> [xovi](https://github.com/asivery/xovi)), sur une version précise (3.30.0.111, bêta). Tout est **non persistant** :
> un redémarrage de la tablette revient à l'interface d'origine. Lire [docs/SECURITE.md](docs/SECURITE.md).
> Projet ni affilié à reMarkable AS, ni soutenu par elle.

## Démarrage rapide

```bash
# PC (Linux) : Python 3.10+, poppler-utils (pdftoppm) ; TeX Live (latex, dvipng) pour les formules
cd pc && python3 -m venv .venv && .venv/bin/pip install -r ../requirements.txt && .venv/bin/pip install --no-deps rmc==0.3.0
./sync.sh                 # sauvegarde de la tablette (USB) dans pc/xochitl/
./lancer.sh               # serveur + navigateur : http://127.0.0.1:8765/

# Tablette (xovi déjà installé, voir docs/INSTALLATION.md)
../outils/installer.sh    # copie les mods
ssh root@10.11.99.1 /home/root/xovi/start      # active les mods (l'interface redémarre, PIN demandé)
```

## Documentation

| | |
|---|---|
| [Installation](docs/INSTALLATION.md) | PC, tablette, xovi, mise à jour du système |
| [Utilisation](docs/UTILISATION.md) | Studio, menu du crayon, formes, bouton 4 cases, carnets liés |
| [Découvertes](docs/DECOUVERTES.md) | tout ce qu'on a appris sur xochitl 3.30 (format, écran, formes, couleurs…) |
| [Architecture](docs/ARCHITECTURE.md) | comment les morceaux communiquent |
| [Sécurité](docs/SECURITE.md) | risques, ce qui est modifié, comment tout retirer |
| [Feuille de route](docs/FEUILLE-DE-ROUTE.md) | Wi-Fi, idées |

## Remerciements

[xovi](https://github.com/asivery/xovi), [qmldiff](https://github.com/asivery/qmldiff) et les extensions
d'[asivery](https://github.com/asivery/rm-xovi-extensions) ; [rmscene](https://github.com/ricklupton/rmscene) et
[rmc](https://github.com/ricklupton/rmc) pour le format `.rm` ; la police [Inter](https://rsms.me/inter/).

---

**English summary.** Tools for the reMarkable 2 (firmware 3.30): a PC "Studio" showing the tablet's live screen
fused with the saved document pages (UI masked), with pen settings, perfect shapes, LaTeX formulas and drawing;
xovi mods adding free RGB colours and continuous thickness to the pen menu, instant perfect shapes (built by
cloning and transforming a template stroke through the scene controller), a compact 3-pens + eraser toolbar
button, and linked notebooks. Non-persistent; use at your own risk. Technical findings: `docs/DECOUVERTES.md`.
