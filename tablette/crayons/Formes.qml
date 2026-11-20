// Formes — chargé dans chaque DeviceSceneView par formes.qmd ; rechargé à chaud (formes.version).
// Le menu du crayon (PenMenu.qml) choisit une forme et écrit /home/root/xovi/crayons/formes-cmd.json :
//   {"id": n, "action": "place", "shape": "grid|rect|ellipse|line|polygon|axes", "spacing": px, "sides": n}
// On étire alors la forme avec le stylet (aperçu en pointillés) ; au lever, une fois le stylet éloigné,
// /home/root/xovi/formes/trace.sh la trace avec le crayon actif (les formes « maintenues » sont redressées
// par le geste natif de la tablette).
import QtQuick
import com.remarkable
import xofm.libs.library
import common
import xofm.libs.peninput
import net.asivery.CommandExecutor 1.0
import "file:///home/root/xovi/crayons/formes-etat.js" as Etat

Item {
    id: f
    property var view: null
    property var lastId: -1
    width: view ? view.width : 0
    height: view ? view.height : 0

    property var spec: null          // forme en cours de placement
    property point a: Qt.point(0, 0)
    property point b: Qt.point(0, 0)
    property bool dragging: false
    property int ellipseStep: 0      // ellipse : 0 = tracer le grand axe depuis le centre, 1 = régler le petit rayon
    property string pendingFile: ""  // tracé prêt, en attente que le stylet s'éloigne
    property string status: ""

    function log(s) { console.log("FORMES " + s); }

    CommandExecutor { id: exe }

    // ------------------------------------------------------------ commandes du menu
    function readCmd() {
        const x = new XMLHttpRequest();
        x.open("GET", "file:///home/root/xovi/crayons/formes-cmd.json", false);
        try { x.send(); return JSON.parse(x.responseText); } catch (e) { return null; }
    }
    Timer {
        interval: 400
        repeat: true
        running: f.view !== null && f.view.visible
        onTriggered: {
            const c = f.readCmd();
            if (!c || c.id === undefined) return;
            if (f.lastId === -1) { f.lastId = c.id; return; }   // commande déjà présente au chargement
            if (c.id === f.lastId) return;
            f.lastId = c.id;
            if (Date.now() - c.id > 15000) return;               // trop ancienne
            try { f.run(c); } catch (e) { f.log("erreur " + e); f.result(false, "erreur " + e); }
        }
    }
    // Compte rendu de la commande en cours (marks, build) dans resultat.json : le PC l'attend pour répondre vrai.
    property double cmdId: 0
    function result(ok, msg) {
        if (!cmdId) return;
        const x = new XMLHttpRequest();
        x.open("PUT", "file:///home/root/xovi/formes/resultat.json");
        x.send(JSON.stringify({ id: cmdId, ok: ok, message: msg }));
        log("résultat " + (ok ? "ok" : "échec") + " : " + msg);
        cmdId = 0;
    }
    function fail(msg) {                            // échec d'une construction : style du crayon rendu, compte rendu
        if (job) { restoreStyle(job); job = null; }
        tplSkip = 0;
        result(false, msg);
    }
    function run(c) {
        if (c.action === "marks" || c.action === "build" || c.action === "snapmarks" || c.action === "natifTrait" || c.action === "dessin" || c.action === "traitsRel") cmdId = c.id;
        if (c.action === "place") {
            spec = c; dragging = false; status = ""; ellipseStep = 0;
            log("placement " + c.shape);
        } else if (c.action === "build") {
            // coordonnées reçues = écran physique (image de l'écran) -> repère de la page (tourné en paysage)
            spec = c; a = layer.mapFromItem(null, c.ax, c.ay); b = layer.mapFromItem(null, c.bx, c.by);   // (minor : longueur, inchangée)
            commit();
        } else if (c.action === "diag") {
            // diagnostic en lecture seule
            // c.scene : zone déjà dans le repère de la page ; c.rect : zone dans le repère de la vue
            const r = c.scene ? Qt.rect(c.scene[0], c.scene[1], c.scene[2], c.scene[3])
                    : view.tileManager.viewToScene(c.rect ? Qt.rect(c.rect[0], c.rect[1], c.rect[2], c.rect[3]) : Qt.rect(0, 1600, 1404, 272));
            log("diag vue status=" + view.status + " visible=" + view.visible + " page=" + (view.tileManager ? view.tileManager.pageId : "?") + " opacité=" + view.opacity);
            log("diag bas de page : " + rectsIn(r) + " | outil " + view.toolSettings.activePen.tool
                + " | gabarits " + Object.keys(Etat.gabarits).join(", ") + " | zone " + tplArea + " attendu " + tplExpect);
        } else if (c.action === "open") {
            // ouvrir un document à une page (Studio, bibliothèque du PC) : fonction onOpened de la vue principale,
            // comme le faisait carnets_lies.qmd sur signal (le signal n'arrive pas)
            const mv = findItem(it => typeof it.onOpened === "function" && "documentViewActive" in it);
            if (mv) { mv.onOpened({ documentId: c.doc, page: c.page !== undefined ? c.page : -1 }); log("ouverture " + c.doc + " page " + c.page); }
            else log("ouverture impossible : vue principale introuvable");
        } else if (c.action === "linksReload") {
            log("liens relus : " + reloadLinks() + " bouton(s)");
        } else if (c.action === "zoomInfo") {
            // lecture seule : état du zoom de la vue
            const tm = view.tileManager, pr = view.controller.primaryContentRect;
            log("zoomInfo mode=" + view.zoomMode + " scale=" + tm.scale + " center=" + tm.center + " defaultScale=" + view.defaultScale
                + " pdf=" + pr + " doc=" + (view.document ? view.document.id : "?") + " vue=" + view.width + "x" + view.height);
        } else if (c.action === "zoomFit") {
            // cadrage enregistré pour TOUT le document (comme « Ajuster la vue > personnalisé »), appliqué à sa
            // prochaine ouverture ; c.list : plusieurs documents ; c.mode seul : mode de vue (0 = page entière)
            let n = 0;
            for (const z of (c.list || [c])) {
                if (z.mode !== undefined) LibraryController.setZoomMode(z.doc, z.mode);
                else LibraryController.setCustomZoomFit(z.doc, z.scale, Qt.point(z.cx, z.cy), Qt.size(z.w, z.h));
                n++;
            }
            log("zoomFit : " + n + " document(s)");
        } else if (c.action === "pen") {
            // pendant une forme, le stylet simulé survole la page : le surligneur automatique du PC le prend pour
            // le vrai et demanderait une autre épaisseur (constaté) ; changer le crayon fausserait aussi le gabarit
            if (busy()) { log("réglage du crayon ignoré : forme en cours"); return; }
            setPen(c);
        } else if (c.action === "marks") {
            marks(c);
        } else if (c.action === "snapmarks") {
            snapMarks(c);
        } else if (c.action === "natifTrait") {
            natifTrait(c);
        } else if (c.action === "dessin") {
            dessin(c);
        } else if (c.action === "traitsRel") {
            traitsRel(c);
        } else if (c.action === "image") {
            // insère une image (ex. formule LaTeX rendue sur le PC) dans la page
            const ctl = view.controller, L = ctl.currentLayer;
            const url = "file://" + c.file;
            const q = layer.mapFromItem(null, c.x !== undefined ? c.x : 702, c.y !== undefined ? c.y : 600);   // écran physique -> page
            const pos = toScene([q.x, q.y]);
            ctl.insertImageFileAsSceneItem(url, Qt.point(pos.x, pos.y));   // (url, point de la page)
            log("image insérée : " + c.file);
        } else if (c.action === "placeImage") {
            // formule (image) envoyée par le PC : on touche l'endroit où la poser
            spec = { shape: "image", file: c.file, w: c.w, h: c.h }; dragging = false; status = "";
            log("placement image " + c.file);
        } else if (c.action === "deleteArea") {
            const A = layer.mapFromItem(null, c.x0, c.y0), B2 = layer.mapFromItem(null, c.x1, c.y1);
            delArea = view.tileManager.viewToScene(Qt.rect(Math.min(A.x, B2.x), Math.min(A.y, B2.y), Math.abs(B2.x - A.x), Math.abs(B2.y - A.y)));
            delExpect = c.expect; delStep = 0; delTimer.start();
        } else if (c.action === "resetTemplates") {
            for (const k of Object.keys(Etat.gabarits)) delete Etat.gabarits[k];
            log("gabarits oubliés");
        } else if (c.action === "cancel") {
            spec = null;
        }
    }

    // ------------------------------------------------------------ géométrie (coordonnées du calque)
    function densify(pts) {
        const out = [pts[0]];
        for (let i = 1; i < pts.length; i++) {
            const p = pts[i - 1], q = pts[i];
            const n = Math.max(1, Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / 4));
            for (let k = 1; k <= n; k++) out.push([p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n]);
        }
        return out;
    }
    // liste de traits {hold, pts}
    function shapeStrokes(s, A, B) {
        const x0 = Math.min(A.x, B.x), x1 = Math.max(A.x, B.x), y0 = Math.min(A.y, B.y), y1 = Math.max(A.y, B.y);
        const w = x1 - x0, h = y1 - y0, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
        const out = [];
        const seg = (p, q, hold) => out.push({ hold: hold, pts: [p, q] });
        const sp = Math.max(10, s.spacing || 60);
        switch (s.shape) {
        case "line":
            seg([A.x, A.y], [B.x, B.y], 1000); break;
        case "rect":
            seg([x0, y0], [x1, y0], 1000); seg([x1, y0], [x1, y1], 1000);
            seg([x1, y1], [x0, y1], 1000); seg([x0, y1], [x0, y0], 1000); break;
        case "circle":
        case "ellipse": {
            // A = centre, B = bout du grand axe (rayon + inclinaison) ; petit rayon : s.minor (ellipse)
            const ra = Math.hypot(B.x - A.x, B.y - A.y), ang = Math.atan2(B.y - A.y, B.x - A.x);
            const rb = s.shape === "circle" ? ra : (s.minor !== undefined ? s.minor : ra * 0.6);
            const per = Math.PI * (3 * (ra + rb) - Math.sqrt((3 * ra + rb) * (ra + 3 * rb)));
            // un segment tous les ~14 px : écart au vrai cercle < 0,2 px, et 2 fois moins d'éléments à redessiner
            const n = Math.max(36, Math.min(160, Math.round(per / 14))), pts = [];
            const ux = Math.cos(ang), uy = Math.sin(ang);
            for (let i = 0; i <= n; i++) {
                const t = 2 * Math.PI * i / n, c = Math.cos(t) * ra, d = Math.sin(t) * rb;
                pts.push([A.x + c * ux - d * uy, A.y + c * uy + d * ux]);
            }
            out.push({ hold: 0, pts: pts }); break;
        }
        case "grid": {
            const nx = Math.max(1, Math.round(w / sp)), ny = Math.max(1, Math.round(h / sp));
            for (let i = 0; i <= nx; i++) { const x = x0 + w * i / nx; seg([x, y0], [x, y1], 0); }
            for (let j = 0; j <= ny; j++) { const y = y0 + h * j / ny; seg([x0, y], [x1, y], 0); }
            break;
        }
        case "polygon": {
            const n = Math.max(3, Math.min(24, s.sides || 6)), r = Math.min(w, h) / 2, v = [];
            for (let i = 0; i < n; i++) {
                const t = -Math.PI / 2 + 2 * Math.PI * i / n;
                v.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]);
            }
            for (let i = 0; i < n; i++) seg(v[i], v[(i + 1) % n], 0);
            break;
        }
        case "axes": {
            seg([x0, cy], [x1, cy], 0); seg([cx, y1], [cx, y0], 0);
            const L = 16;
            out.push({ hold: 0, pts: [[x1 - L, cy - L * 0.6], [x1, cy], [x1 - L, cy + L * 0.6]] });
            out.push({ hold: 0, pts: [[cx - L * 0.6, y0 + L], [cx, y0], [cx + L * 0.6, y0 + L]] });
            for (let x = cx + sp; x < x1 - L; x += sp) seg([x, cy - 7], [x, cy + 7], 0);
            for (let x = cx - sp; x > x0; x -= sp) seg([x, cy - 7], [x, cy + 7], 0);
            for (let y = cy - sp; y > y0 + L; y -= sp) seg([cx - 7, y], [cx + 7, y], 0);
            for (let y = cy + sp; y < y1; y += sp) seg([cx - 7, y], [cx + 7, y], 0);
            break;
        }
        }
        return out;
    }

    // ------------------------------------------------------------ création
    // Les formes sont construites en copiant des gabarits (droite, cercle) collés, étirés et tournés par
    // le contrôleur de la page : instantané. Un gabarit est fabriqué une fois par style de crayon (injection
    // + redressement natif), puis gardé en mémoire pour toutes les pages (formes-etat.js).
    // Si la zone était vide, la forme est ensuite regroupée pour qu'« Annuler » la retire d'un coup.
    // Outil Sélection : à poser sur le crayon ACTIF (le bouton 4 cases active le crayon secondaire, pas le
    // principal) ; addSelectionRect ne sélectionne rien si le crayon actif n'est pas l'outil Sélection.
    // Repasser du Sélection au crayon arrondit son épaisseur (0,9 -> 1 au surligneur, constaté) : tout le réglage
    // est mémorisé puis remis.
    property var selPen: null
    property var selSaved: null
    function selectionTool() {
        const p = view.toolSettings.activePen, t = p.tool;
        selPen = p;
        selSaved = { tool: t, color: p.color, colorCode: p.colorCode >>> 0, thickness: p.thickness };
        p.tool = Line.SelectionTool;
        return t;
    }
    function restoreTool(t) {
        const p = selPen || view.toolSettings.activePen, r = selSaved;
        p.tool = t;
        if (r && r.tool === t) {
            if (p.color !== r.color) p.color = r.color;
            if ((p.colorCode >>> 0) !== r.colorCode) p.colorCode = r.colorCode;
            if (p.thickness !== r.thickness) p.thickness = r.thickness;
        }
        selPen = null; selSaved = null;
    }
    function isWriting() {
        const t = view.toolSettings.activePen.tool;
        return t !== Line.SelectionTool && t !== Line.Eraser && t !== Line.EraseSection && t !== Line.ZoomTool;
    }
    function commit() {
        const s = spec;
        spec = null;
        if (!isWriting()) { status = "Choisissez d'abord un crayon"; clearMsg.restart(); result(false, "le crayon actif n'écrit pas (gomme, sélection)"); return; }
        const strokes = shapeStrokes(s, a, b);
        if (natifOk()) { buildNatif(strokes); return; }
        const job = { segs: [], ellipses: [], area: null, group: false };
        for (const st of strokes) {
            if (st.ellipse) { job.ellipses.push(st.ellipse); continue; }
            for (let i = 1; i < st.pts.length; i++) job.segs.push([toScene(st.pts[i - 1]), toScene(st.pts[i])]);
        }
        // zone de la forme = enveloppe de tous ses points (un cercle tracé depuis son centre déborde du geste)
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (const st of strokes) for (const p of st.pts) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
        job.area = view.tileManager.viewToScene(Qt.rect(x0 - 14, y0 - 14, x1 - x0 + 28, y1 - y0 + 28));
        const before = rectsIn(job.area);
        job.group = before === "";
        if (!job.group) log("zone déjà occupée, pas de regroupement : " + before.substring(0, 120));
        run2(job);
    }
    // Construction directe (extension native) : traits consécutifs bout à bout = une seule polyligne (rectangle,
    // polygone, cercle : un trait, une étape d'annulation) ; plusieurs traits (grille, axes) : regroupés comme
    // avant pour qu'« Annuler » retire la forme d'un coup (zone vide au départ).
    function buildNatif(strokes) {
        const t0 = Date.now(), lignes = [];
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (const st of strokes) {
            for (const q of st.pts) { x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]); }
            const pts = st.pts.map(q => { const r = toScene(q); return [r.x, r.y]; });
            const last = lignes.length ? lignes[lignes.length - 1] : null;
            if (last && Math.hypot(last[last.length - 1][0] - pts[0][0], last[last.length - 1][1] - pts[0][1]) < 0.01)
                for (let i = 1; i < pts.length; i++) last.push(pts[i]);
            else lignes.push(pts);
        }
        const area = view.tileManager.viewToScene(Qt.rect(x0 - 14, y0 - 14, x1 - x0 + 28, y1 - y0 + 28));
        const p = view.toolSettings.activePen;
        placerLignes(lignes, { tool: p.tool, color: p.color, argb: p.colorCode, thickness: p.thickness }, area, t0);
    }
    // Ajoute des traits (unités de page) avec un style, puis les regroupe pour qu'« Annuler » les retire d'un coup
    // (si la zone était vide au départ et qu'il y a plusieurs traits). area : zone de la forme (unités de page).
    function placerLignes(lignes, st, area, t0) {
        const group = lignes.length > 1 && rectsIn(area) === "";
        const err = natifLignes(lignes, st.tool, st.color, st.argb, st.thickness);
        if (err) { status = "Forme : " + err; clearMsg.restart(); result(false, err); return; }
        log("natif : " + lignes.length + " trait(s) en " + (Date.now() - (t0 || Date.now())) + " ms");
        if (group) {
            grouping.job = { area: area, restore: null, natif: { lignes: lignes, tool: st.tool, color: st.color,
                                                                 argb: st.argb, thickness: st.thickness } };
            grouping.saved = selectionTool();
            grouping.steps = lignes.length; grouping.phase = 0;
            grouping.start();
        } else {
            status = "";
            result(true, lignes.length + " élément(s)");
        }
    }
    // Traits relatifs à un point de l'écran (formule LaTeX en traits) : c.ancre = [x, y] pixels de l'écran physique,
    // c.traits = [[[dx, dy], ...], ...] en unités de page autour de ce point (repère de la page : la formule suit
    // la page, pas l'écran) ; couleur du crayon actif (noir si ce n'est pas un crayon), feutre fin.
    function traitsRel(c) {
        if (c.page && String(view.tileManager.pageId) !== String(c.page)) { result(false, "autre page affichée"); return; }
        if (!natifOk()) { result(false, "extension native absente"); return; }
        const l = layer.mapFromItem(null, c.ancre[0], c.ancre[1]), o = toScene([l.x, l.y]);
        const lignes = (c.traits || []).filter(t => t.length >= 2).map(t => t.map(q => [o.x + q[0], o.y + q[1]]));
        if (!lignes.length) { result(false, "rien à tracer"); return; }
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (const t of lignes) for (const q of t) { x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]); }
        const p = view.toolSettings.activePen, ecrit = isWriting();
        placerLignes(lignes, { tool: 17, color: ecrit ? p.color : 0, argb: ecrit ? p.colorCode : 0xFF000000,
                               thickness: c.epaisseur || 1.0 }, Qt.rect(x0 - 10, y0 - 10, x1 - x0 + 20, y1 - y0 + 20), Date.now());
    }
    // Annotations de texte (Studio) : segments donnés en unités de PAGE [x0, y0, x1, y1, largeur],
    // largeur > 0 = bande (surligneur) obtenue par l'étirement perpendiculaire du gabarit.
    // Style imposé le temps de l'opération (c.pen), puis crayon de l'utilisateur restauré.
    function marks(c) {
        if (c.page && String(view.tileManager.pageId) !== String(c.page)) { log("marks : autre page affichée"); result(false, "autre page affichée"); return; }
        if (natifOk() && c.segs && c.segs.length) {
            const pen = c.pen || {}, band = c.segs.filter(g => (g[4] || 0) > 0), lines = c.segs.filter(g => !((g[4] || 0) > 0));
            let err = "";
            for (const g of band)                      // bande de surligneur : largeur de bande = 30 x épaisseur
                err = err || natifLignes([[[g[0], g[1]], [g[2], g[3]]]], 18, 9, pen.argb || 0xFFFBF06A, g[4] / 30);
            if (lines.length)
                err = err || natifLignes(lines.map(g => [[g[0], g[1]], [g[2], g[3]]]), pen.tool || 17, 9,
                                         pen.argb || 0xFF000000, pen.thickness || 2);
            log("marks natif : " + c.segs.length + " segment(s)" + (err ? " — " + err : ""));
            result(!err, err || c.segs.length + " élément(s)");
            return;
        }
        if (!isWriting()) { status = "Choisissez d'abord un crayon"; clearMsg.restart(); result(false, "le crayon actif n'écrit pas (gomme, sélection)"); return; }
        const p = view.toolSettings.activePen;
        const restore = { tool: p.tool, color: p.color, colorCode: p.colorCode >>> 0, thickness: p.thickness,
                          snap: p.snapHighlighterToText };
        if (c.pen) {
            if (c.pen.tool !== undefined) p.tool = c.pen.tool;
            if (c.pen.argb !== undefined) { p.color = Line.ArgbCode; p.colorCode = c.pen.argb; }
            if (c.pen.thickness !== undefined) p.thickness = c.pen.thickness;
            try { p.snapHighlighterToText = false; } catch (e) {}   // le gabarit ne doit pas s'accrocher au texte
        }
        const job = { segs: [], ellipses: [], area: null, group: false, restore: restore };
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (const g of c.segs || []) {
            const w = g[4] || 0, seg = [Qt.point(g[0], g[1]), Qt.point(g[2], g[3])];
            if (w > 0) seg.push(w);
            job.segs.push(seg);
            x0 = Math.min(x0, g[0], g[2]); x1 = Math.max(x1, g[0], g[2]);
            y0 = Math.min(y0, g[1] - w / 2, g[3] - w / 2); y1 = Math.max(y1, g[1] + w / 2, g[3] + w / 2);
        }
        if (!job.segs.length) { restoreStyle(job); result(false, "rien à tracer"); return; }
        job.area = Qt.rect(x0 - 10, y0 - 10, x1 - x0 + 20, y1 - y0 + 20);
        job.group = rectsIn(job.area) === "";
        log("marks : " + job.segs.length + " segments, outil " + p.tool);
        run2(job);
    }
    // Surlignage accroché au texte, tracé directement sur les lignes : le stylet simulé passe sur chaque ligne avec
    // le surligneur et « accrocher au texte » ; la tablette en fait un vrai surlignage de texte (calé sur les
    // lettres, texte enregistré). Pas de gabarit. Seulement si chaque ligne est entièrement à l'écran et hors de
    // toute interface (menu de la barre d'outils fermé d'abord) ; sinon échec « zone » : le PC passe par marks.
    // Extension native (tablette/natif) : traits créés sans stylet. Absente : null (rien ne change).
    property var natifRef: undefined
    function natif() {
        if (natifRef === undefined) {
            try {
                natifRef = Qt.createQmlObject('import QtQuick; import net.studio.Natif 1.0; QtObject { function n() { return StudioNatif; } }', f).n();
            } catch (e) { natifRef = null; }
        }
        return natifRef;
    }
    // Extension utilisable ? (vérifiée une fois : disponible() vide)
    property var natifOkCache: undefined
    function natifOk() {
        if (natifOkCache === undefined) { const n = natif(); natifOkCache = !!n && !n.disponible(); }
        return natifOkCache;
    }
    // largeur des points et pression d'un trait, par outil : médianes mesurées sur 27 000 traits du stylet
    // (largeur = rapport x épaisseur) ; feutre par défaut
    readonly property var natifStyle: ({ 17: [8, 206], 15: [6, 174], 14: [12, 244], 13: [8, 206], 16: [14.5, 255],
                                         21: [5, 156], 18: [120, 254], 5: [120, 254], 12: [30, 239] })
    // traits ajoutés directement (polylignes en unités de page) avec un style donné -> "" ou la raison
    function natifLignes(lignes, tool, color, argb, thickness, accroche) {
        const n = natif(), st = natifStyle[tool] || [8, 206];
        const w = Math.max(1, Math.round(st[0] * thickness)), all = [];
        for (const pts of lignes) {
            const pp = pts.map(q => [q[0], q[1], w, st[1]]);
            const err = n.ajouterTrait(view.controller, view.tileManager, tool, color, argb >>> 0, thickness, pp,
                                       accroche === undefined ? -1 : accroche);
            if (err) return err;
            for (const q of pts) all.push(q);
        }
        if (all.length) natifRepaint(all);
        return "";
    }
    // Dessin et gomme depuis le Studio : c.traits = [[[x, y], ...], ...] en pixels de l'écran physique (comme l'image
    // en direct) ; convertis ici dans le repère de la page (zoom, défilement, orientation de l'instant).
    // c.mode : "trait" (crayon actif ; si c'est une gomme : gomme) ou "gomme" ; c.taille : largeur de gomme (px écran)
    function dessin(c) {
        if (c.page && String(view.tileManager.pageId) !== String(c.page)) { result(false, "autre page affichée"); return; }
        if (!natifOk()) { result(false, "extension native absente"); return; }
        const p = view.toolSettings.activePen;
        const gomme = c.mode === "gomme" || p.tool === 6 || p.tool === 8;
        const traits = (c.traits || []).map(t => t.map(q => { const l = layer.mapFromItem(null, q[0], q[1]); const r = toScene([l.x, l.y]); return [r.x, r.y]; }))
                                       .filter(t => t.length >= 2);
        if (!traits.length) { result(false, "rien à tracer"); return; }
        let err = "";
        if (gomme) {
            // largeur de gomme : c.taille pixels d'écran -> unités de page (zoom de l'instant) ; la largeur des points
            // vaut 4 x la largeur effacée (mesuré : comme pour le surligneur) ; l'épaisseur du trait n'y change rien
            const s0 = toScene([0, 0]), s1 = toScene([c.taille || 30, 0]);
            const w = Math.max(8, Math.round(4 * Math.hypot(s1.x - s0.x, s1.y - s0.y)));
            for (const t of traits) {
                err = err || natif().effacer(view.controller, p.tool === 8 ? 8 : 6, 2, t.map(q => [q[0], q[1], w, 255]),
                                             SceneController.ImageErasingDisabled);
                natifRepaint(t);
            }
        } else {
            err = natifLignes(traits, p.tool, p.color, p.colorCode, p.thickness);
        }
        log("dessin natif : " + traits.length + " trait(s), " + (gomme ? "gomme" : "crayon " + p.tool) + (err ? " — " + err : ""));
        result(!err, err || traits.length + (gomme ? " trait(s) gommé(s)" : " trait(s) tracé(s)"));
    }
    // c : {page, tool, color, argb, thickness, points: [[x, y, largeur, pression]...] (unités de page),
    //      accroche: absent = trait ordinaire, "texte" = surlignage accroché au texte, "libre" = surlignage libre}
    function natifTrait(c) {
        if (c.page && String(view.tileManager.pageId) !== String(c.page)) { result(false, "autre page affichée"); return; }
        const n = natif();
        if (!n) { result(false, "extension native absente"); return; }
        const d = n.disponible();
        if (d) { result(false, "extension native : " + d); return; }
        let mode = -1;
        if (c.accroche === "texte") mode = SceneController.SnapEnabled;
        else if (c.accroche === "libre") mode = SceneController.SnapDisabled;
        const err = n.ajouterTrait(view.controller, view.tileManager, c.tool, c.color === undefined ? 9 : c.color,
                                   c.argb === undefined ? 4278190080 : c.argb, c.thickness || 2, c.points, mode);
        if (!err) natifRepaint(c.points);
        result(err === "", err || "trait ajouté (natif)");
    }
    // le trait ajouté n'est pas redessiné tout seul (constaté) : zone marquée « à redessiner » puis rafraîchie
    function natifRepaint(points) {
        let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
        for (const q of points) { x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]); }
        const r = view.tileManager.sceneToView(Qt.rect(x0 - 40, y0 - 40, x1 - x0 + 80, y1 - y0 + 80));
        const vp = findItem(it => typeof it.requestRepaintDirty === "function" && typeof it.markDirty === "function");
        if (vp) { vp.markDirty(r); vp.requestRepaintDirty(); log("natif : zone redessinée " + r); }
        else log("natif : pas de zone d'affichage trouvée");
    }
    property var snapJob: null
    function snapMarks(c) {
        if (c.page && String(view.tileManager.pageId) !== String(c.page)) { result(false, "autre page affichée"); return; }
        if (natifOk()) {
            const lignes = (c.rects || []).map(r => [[r[0] + Math.min(4, r[2] * 0.1), r[1] + r[3] / 2],
                                                      [r[0] + r[2] - Math.min(4, r[2] * 0.1), r[1] + r[3] / 2]]);
            const err = lignes.length ? natifLignes(lignes, c.tool || 18, 9, c.argb || 0xFFFBF06A, 1, SceneController.SnapEnabled)
                                      : "rien à tracer";
            log("surlignage natif : " + lignes.length + " ligne(s)" + (err ? " — " + err : ""));
            result(!err, err || lignes.length + " ligne(s) surlignée(s), accrochées au texte");
            return;
        }
        if (snapJob || job || pendingFile !== "") { result(false, "occupé"); return; }
        const tb = findItem(it => typeof it.closeFoldout === "function" && "selectedTool" in it);
        if (tb) { try { tb.closeFoldout(); } catch (e) {} }
        snapJob = { c: c, step: 0 };
        snapTimer.start();                         // laisser le menu se refermer avant de mesurer l'interface
    }
    function snapPrepare(c) {
        const free = uiFreeChecker(12);
        const strokes = [];
        for (const r of c.rects || []) {
            const x0 = r[0] + Math.min(4, r[2] * 0.1), x1 = r[0] + r[2] - Math.min(4, r[2] * 0.1), y = r[1] + r[3] / 2;
            const A = view.tileManager.sceneToView(Qt.point(x0, y)), B = view.tileManager.sceneToView(Qt.point(x1, y));
            const sA = layer.mapToItem(null, A.x, A.y), sB = layer.mapToItem(null, B.x, B.y);
            const T = view.tileManager.sceneToView(Qt.point(r[0], r[1])), Bt = view.tileManager.sceneToView(Qt.point(r[0] + r[2], r[1] + r[3]));
            const s0 = layer.mapToItem(null, T.x, T.y), s1 = layer.mapToItem(null, Bt.x, Bt.y);
            const bx = Math.min(s0.x, s1.x), by = Math.min(s0.y, s1.y);
            if (!free(bx, by, Math.abs(s1.x - s0.x), Math.abs(s1.y - s0.y)))
                return { error: "ligne hors de l'écran ou sous l'interface" };
            strokes.push({ hold: 0, pts: [[A.x, A.y], [B.x, B.y]] });
        }
        return strokes.length ? { strokes: strokes } : { error: "rien à tracer" };
    }
    Timer {
        id: snapTimer
        interval: 350
        repeat: true
        onTriggered: {
            const sj = f.snapJob;
            if (!sj) { stop(); return; }
            const p = f.view.toolSettings.activePen;
            if (sj.step === 0) {
                const prep = f.snapPrepare(sj.c);
                if (prep.error) { stop(); f.snapJob = null; f.result(false, "zone : " + prep.error); return; }
                sj.restore = { tool: p.tool, color: p.color, colorCode: p.colorCode >>> 0, thickness: p.thickness,
                               snap: p.snapHighlighterToText };
                p.tool = sj.c.tool || 18;
                if (sj.c.argb) { p.color = Line.ArgbCode; p.colorCode = sj.c.argb; }
                try { p.snapHighlighterToText = true; } catch (e) {}
                sj.n = prep.strokes.length;
                sj.step = 1;
                f.inject(prep.strokes, false);
                f.log("surlignage accroché : " + sj.n + " ligne(s)");
            } else if (sj.step === 1) {
                // tracé lancé par launcher quand le stylet est loin ; fini après la durée estimée
                if (f.pendingFile !== "" || Date.now() - f.launchedAt < f.estimate + 1200) return;
                stop();
                const r = sj.restore;
                p.tool = r.tool; p.color = r.color; p.colorCode = r.colorCode; p.thickness = r.thickness;
                try { p.snapHighlighterToText = r.snap; } catch (e) {}
                f.snapJob = null;
                f.status = "";
                f.result(true, sj.n + " ligne(s) surlignée(s), accrochées au texte");
            }
        }
    }

    // Réglage du crayon depuis le PC (remplace penSet de xovi-message-broker, source de plantages)
    function setPen(c) {
        const p = view.toolSettings.activePen;
        // changer d'outil est toujours permis (crayon <-> gomme depuis le Studio) ; couleur et épaisseur : crayon seulement
        const allowed = [12, 13, 14, 15, 16, 17, 18, 21, 6, 8];
        if (c.tool !== undefined && c.tool !== null && allowed.indexOf(c.tool) >= 0) p.tool = c.tool;
        if (!isWriting()) { vueTimer.restart(); return; }
        if (c.argb !== undefined && c.argb !== null) { p.color = Line.ArgbCode; p.colorCode = c.argb; }
        if (c.thickness !== undefined && c.thickness !== null) p.thickness = c.thickness;
        vueTimer.restart();
    }
    function restoreStyle(j) {
        if (!j || !j.restore) return;
        const p = view.toolSettings.activePen, r = j.restore;
        j.restore = null;
        p.tool = r.tool; p.color = r.color; p.colorCode = r.colorCode; p.thickness = r.thickness;
        try { p.snapHighlighterToText = r.snap; } catch (e) {}
    }
    function commitImage(p) {
        const s = spec;
        spec = null;
        const pos = toScene([p.x, p.y]);
        view.controller.insertImageFileAsSceneItem("file://" + s.file, Qt.point(pos.x, pos.y));
        log("image insérée en " + Math.round(p.x) + "," + Math.round(p.y));
    }
    function toScene(p) { return view.tileManager.viewToScene(Qt.point(p[0], p[1])); }
    function rectsIn(r) { return String(view.controller.getLineBoundingRectsToBeSelected(Qt.rect(r.x, r.y, r.width, r.height))); }
    function styleKey() {
        const p = view.toolSettings.activePen;
        return [p.tool, p.color, p.colorCode, p.thickness, view.defaultScale].join("/");
    }
    function tplFor(kind) { return Etat.gabarits[kind + "2|" + styleKey()] || null; }

    property var job: null
    function run2(j) {
        // fabriquer d'abord les gabarits manquants
        if (j.segs.length && !tplFor("line")) { job = j; makeTemplate("line"); return; }
        if (j.ellipses.length && !tplFor("circle")) { job = j; makeTemplate("circle"); return; }
        build(j);
    }

    // ---- gabarits
    property string tplKind: ""
    property rect tplArea
    property real tplExpect: 0
    property int tplStep: 0
    property int savedTool: -1
    property int tplSkip: 0                        // emplacements déjà essayés sans succès
    function makeTemplate(kind) {
        status = "Préparation du gabarit…";
        tplKind = kind;
        // emplacement libre (écran physique) pour le gabarit : droite de 400 px ou cercle de rayon 60.
        // Il doit être vide de traits ET de toute interface (barre d'outils, menus… : en paysage la barre
        // d'outils occupe un bord de l'écran physique), sinon le trait injecté actionnerait l'interface.
        const uiFree = uiFreeChecker();
        const spots = [];
        // milieu de l'écran d'abord : aux bords apparaissent bandeau de titre (à l'ouverture d'un document) et menus,
        // que le tracé simulé toucherait (constaté : gabarit jamais tracé)
        for (const y of [1100, 900, 1350, 650, 1600, 400, 1800])
            for (const x of kind === "line" ? [150, 850, 500] : [1250, 150, 700, 1000, 400])
                spots.push([x, y]);
        // le gabarit est tracé dans le repère de la PAGE (droite horizontale dans la page) : en paysage il est
        // donc vertical sur l'écran physique. Zones vérifiées dans les deux repères.
        // taille fixe SUR L'ÉCRAN (400 px / rayon 60 px) quel que soit le zoom : k = pixels écran par unité
        // du calque ; sinon, document zoomé, le gabarit déborde de sa zone et n'est pas retrouvé
        const k0 = layer.mapToItem(null, 0, 0), k1 = layer.mapToItem(null, 100, 0);
        const k = Math.max(0.05, Math.hypot(k1.x - k0.x, k1.y - k0.y) / 100);
        const lineLen = 400 / k, radius = 60 / k;
        let box = null, L0 = null, skip = tplSkip;
        for (const sp of spots) {
            const Ls = layer.mapFromItem(null, sp[0], sp[1]);               // point de départ, repère de la page affichée
            let sx0, sy0, sx1, sy1;
            if (kind === "line") {
                const Se = layer.mapToItem(null, Ls.x + lineLen, Ls.y);          // autre extrémité, écran physique
                sx0 = Math.min(sp[0], Se.x) - 30; sy0 = Math.min(sp[1], Se.y) - 30;
                sx1 = Math.max(sp[0], Se.x) + 30; sy1 = Math.max(sp[1], Se.y) + 30;
            } else { sx0 = sp[0] - 90; sy0 = sp[1] - 90; sx1 = sp[0] + 90; sy1 = sp[1] + 90; }
            if (!uiFree(sx0, sy0, sx1 - sx0, sy1 - sy0)) continue;
            const A = layer.mapFromItem(null, sx0, sy0), B2 = layer.mapFromItem(null, sx1, sy1);
            const area = view.tileManager.viewToScene(Qt.rect(Math.min(A.x, B2.x), Math.min(A.y, B2.y), Math.abs(B2.x - A.x), Math.abs(B2.y - A.y)));
            if (rectsIn(area) === "") {
                if (skip-- > 0) continue;                  // nouvel essai : emplacement suivant
                box = area; L0 = Ls; break;
            }
        }
        if (!box) { status = "Pas de place libre pour le gabarit"; clearMsg.restart(); fail("pas de place libre pour le gabarit"); return; }
        tplArea = box;
        const pts = [];      // repère de la page affichée (inject() convertit vers l'écran physique)
        if (kind === "line") {
            // redressement natif indispensable : le gabarit doit être PARFAITEMENT droit (2 points), car il est
            // écrasé/étiré jusqu'à ×60 pour garder l'épaisseur ; le moindre écart d'injection serait amplifié
            for (let i = 0; i <= 100; i++) pts.push([L0.x + lineLen * i / 100, L0.y]);
        } else {
            const n = 96;
            for (let i = 0; i <= Math.round(n * 1.04); i++) {
                const t = 2 * Math.PI * i / n;
                pts.push([L0.x + radius * Math.cos(t), L0.y + radius * Math.sin(t)]);
            }
        }
        const s0 = toScene([0, 0]), s1 = toScene([lineLen, 0]);
        tplExpect = Math.hypot(s1.x - s0.x, s1.y - s0.y) * (kind === "line" ? 1 : 0.3);   // 400 px ou 120 px à l'écran
        tplStep = 0;
        inject([{ hold: 1000, pts: pts }], true);
    }
    Timer {
        id: tplTimer
        interval: 120
        repeat: true
        property int tries: 0
        onTriggered: {
            const ctl = f.view.controller, ts = f.view.toolSettings, L = ctl.currentLayer;
            if (f.tplStep === 0) {
                // tracé pas fini : la tablette remplace le trait par sa version redressée à la fin du maintien ;
                // sélectionner l'ancien trait avant ce remplacement fait échouer la sélection
                if (Date.now() - f.launchedAt < f.estimate + 900) return;
                const r = f.rectsIn(f.tplArea);
                const re = /QRect\(([-\d]+), ([-\d]+), (\d+), (\d+)\)/g;
                let m, found = null;
                while ((m = re.exec(r)) !== null) {
                    const w = +m[3], h = +m[4];
                    if (f.tplKind === "line" ? (w > f.tplExpect * 0.8 && h < Math.max(20, w * 0.25))
                                             : (w > f.tplExpect * 0.8 && Math.abs(w - h) < 12)) { found = m; break; }
                }
                m = found;
                const ok = m !== null;
                if (!ok) {
                    if (++tries > 100) {
                        stop(); f.log("gabarit introuvable " + r);
                        if (f.tplSkip < 2 && f.job) { f.tplSkip++; f.log("nouvel essai, autre emplacement"); f.makeTemplate(f.tplKind); }
                        else { f.status = "Gabarit introuvable"; f.fail("gabarit introuvable"); }
                    }
                    return;
                }
                f.tplMeasure = +m[3];
                f.tplThick = f.tplKind === "line" ? +m[4] : f.lineThick();
                f.savedTool = f.selectionTool();
                f.tplStep = 1;
            } else if (f.tplStep === 1) {
                ctl.clearSelectedItems();
                ctl.addSelectionRect(f.tplArea, 1);
                f.tplStep = 2; tries = 0;
            } else if (f.tplStep === 2) {
                if (ctl.selectionItemCount !== 1) {
                    if (tries % 8 === 7) { ctl.clearSelectedItems(); ctl.addSelectionRect(f.tplArea, 1); }   // nouvel essai
                    if (++tries > 60) { stop(); f.status = "Sélection du gabarit impossible";
                                        f.log("sélection du gabarit : " + ctl.selectionItemCount + " élément(s) " + f.rectsIn(f.tplArea));
                                        ctl.clearSelectedItems(); f.restoreTool(f.savedTool);
                                        f.fail("sélection du gabarit impossible"); }
                    return;
                }
                const items = ctl.cloneSelectedItems(L, f.view.defaultScale);
                ctl.deleteSelectedItems(L);
                ctl.clearSelectedItems();
                f.restoreTool(f.savedTool);
                stop();
                // taille utile : longueur exacte de la droite / diamètre du cercle (axe du trait)
                // taille réelle mesurée sur le trait posé (largeur de l'enveloppe moins l'épaisseur du trait) :
                // la correspondance capteur -> écran n'est pas exactement celle supposée (~1,6 %)
                const size = Math.max(1, f.tplMeasure - f.tplThick);
                Etat.gabarits[f.tplKind + "2|" + f.styleKey()] = { items: items, size: size, thick: f.tplThick };
                f.log("gabarit " + f.tplKind + " prêt, taille " + size.toFixed(1));
                f.tplSkip = 0;
                if (f.job) { const j = f.job; f.job = null; f.run2(j); }
            }
        }
    }
    property real tplMeasure: 0
    property real tplThick: 0
    function lineThick() {   // épaisseur (unités de page) mesurée sur le gabarit droite, si connu
        const l = tplFor("line");
        return l && l.thick ? l.thick : 4;
    }

    // ---- construction
    function build(j) {
        const ctl = view.controller, ts = view.toolSettings, L = ctl.currentLayer, sc = view.defaultScale;
        const t0 = Date.now();
        const line = tplFor("line"), circle = tplFor("circle");   // avant de changer d'outil (le style en dépend)
        const saved = selectionTool();
        let steps = 0, grouped = false;
        try {
        ctl.clearSelectedItems();
        for (const sg of j.segs) {
            const p = sg[0], q = sg[1], band = sg[2] || 0;
            const len = Math.hypot(q.x - p.x, q.y - p.y);
            if (len < 1) continue;
            const mid = Qt.point((p.x + q.x) / 2, (p.y + q.y) / 2);
            ctl.cloneAddAndSelectItems(L, line.items, 1 / sc, mid);
            const k = len / line.size;
            // l'épaisseur suit sqrt(sx*sy) : (k, 1/k) la garde ; pour une bande de largeur « band »,
            // sy = (band / épaisseur)² / k (une droite n'a pas de hauteur : sy ne change que l'épaisseur)
            const t = Math.max(1, line.thick || 4);
            ctl.scaleSelectedItems(L, mid, k, band > 0 ? (band / t) * (band / t) / k : 1 / k);
            const ang = Math.atan2(q.y - p.y, q.x - p.x) * 180 / Math.PI;
            if (Math.abs(ang) > 0.01) ctl.rotateSelectedItems(L, mid, ang);
            ctl.applyPendingEdit(L);
            ctl.clearSelectedItems();
            steps++;
        }
        for (const e of j.ellipses) {
            const c = toScene([e.cx, e.cy]), r = toScene([e.cx + e.rx, e.cy + e.ry]);
            const mid = Qt.point(c.x, c.y);
            ctl.cloneAddAndSelectItems(L, circle.items, 1 / sc, mid);
            ctl.scaleSelectedItems(L, mid, 2 * Math.abs(r.x - c.x) / circle.size, 2 * Math.abs(r.y - c.y) / circle.size);
            ctl.applyPendingEdit(L);
            ctl.clearSelectedItems();
            steps++;
        }
        log(steps + " éléments en " + (Date.now() - t0) + " ms");
        if (j.group && steps > 1) {
            grouping.job = j; grouping.saved = saved; grouping.steps = steps; grouping.phase = 0;
            grouping.start();
            grouped = true;
        }
        } finally {
            if (!grouped) { restoreTool(saved); status = ""; restoreStyle(j); result(steps > 0, steps + " élément(s)"); }
        }
    }

    // Regroupe la forme pour qu'« Annuler » la retire d'un coup (zone vide au départ uniquement).
    // Constaté : chaque élément construit = exactement une étape d'annulation ; après une sélection,
    // l'annulation s'applique en différé (~0,5 s) et undoAvailable aussi. Donc : copie du bloc, puis
    // annulations une par une en attendant de voir disparaître exactement un élément de la zone ;
    // au moindre écart (ou délai dépassé), on refait ce qui a été annulé, un par un, et on garde les segments.
    Timer {
        id: grouping
        interval: 100
        repeat: true
        property var job: null
        property int saved: 0
        property int steps: 0
        property int phase: 0
        property var block: null
        property int n: 0
        property int undone: 0
        property int wait: 0
        property point center
        onTriggered: {
            try { step(); } catch (e) { stop(); f.log("regroupement : erreur " + e); finish(); }
        }
        function count() { return (f.rectsIn(job.area).match(/QRect\(/g) || []).length; }
        function countAll() { return (f.rectsIn(Qt.rect(-100000, -100000, 200000, 200000)).match(/QRect\(/g) || []).length; }
        property int totalBefore: 0
        property real t0: 0
        function step() {
            const ctl = f.view.controller, L = ctl.currentLayer, sc = f.view.defaultScale;
            if (phase === 0) {                       // vérifier puis sélectionner la forme
                const rects = f.rectsIn(job.area);
                if ((rects.match(/QRect\(/g) || []).length !== steps) { abandon("éléments inattendus dans la zone"); return; }
                let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9, m;
                const re = /QRect\(([-\d]+), ([-\d]+), (\d+), (\d+)\)/g;
                while ((m = re.exec(rects)) !== null) {
                    x0 = Math.min(x0, +m[1]); y0 = Math.min(y0, +m[2]);
                    x1 = Math.max(x1, +m[1] + +m[3]); y1 = Math.max(y1, +m[2] + +m[4]);
                }
                center = Qt.point((x0 + x1) / 2, (y0 + y1) / 2);
                ctl.clearSelectedItems();
                ctl.addSelectionRect(job.area, 1);
                phase = 1; wait = 0; t0 = Date.now();
            } else if (phase === 1) {                // copier le bloc (la sélection peut prendre un moment)
                if (ctl.selectionItemCount !== steps) {
                    // juste après la construction, la tablette est occupée à afficher les éléments et la
                    // demande de sélection peut se perdre (constaté au-delà de ~10 éléments) : la renouveler
                    ++wait;
                    if (wait % 6 === 0) { ctl.clearSelectedItems(); ctl.addSelectionRect(job.area, 1); }
                    if (wait <= 50) return;
                    ctl.clearSelectedItems(); abandon("sélection " + ctl.selectionItemCount + "/" + steps); return;
                }
                block = ctl.cloneSelectedItems(L, sc);
                ctl.clearSelectedItems();
                const nb = block && block.length !== undefined ? block.length : -1;
                f.log("regroupement : sélection en " + (Date.now() - t0) + " ms, bloc " + nb); t0 = Date.now();
                if (nb === 0) { abandon("copie vide"); return; }
                n = steps; undone = 0; wait = 0;
                phase = 2;
            } else if (phase === 2) {                // annuler toute la construction d'un coup…
                if (wait === 0) {
                    totalBefore = countAll();
                    for (let k = 0; k < steps; k++) ctl.undo();
                    undone = steps; wait = 1;
                    return;
                }
                // …puis vérifier globalement : zone vide ET reste de la page amputé d'exactement `steps` éléments
                const inArea = count(), all = countAll();
                if (inArea === 0 && all === totalBefore - steps) { f.log("regroupement : annulations en " + (Date.now() - t0) + " ms"); phase = 3; return; }
                if (++wait > 40) {                   // 4 s sans le résultat attendu : tout refaire
                    phase = 4; wait = 0;
                    f.log("regroupement : résultat inattendu (" + inArea + " dans la zone, " + all + " / " + (totalBefore - steps) + ")");
                }
            } else if (phase === 3) {                // recoller le bloc : une seule étape
                if (count() !== 0) { phase = 4; wait = 0; return; }
                ctl.cloneAddAndSelectItems(L, block, 1 / sc, center);
                ctl.applyPendingEdit(L);
                ctl.clearSelectedItems();
                phase = 5; wait = 0;
            } else if (phase === 5) {                // vérifier que le bloc recollé est bien là
                if (count() === steps) {
                    stop();
                    f.log("forme regroupée : " + steps + " éléments en une étape");
                    finish();
                    return;
                }
                if (++wait <= 30) return;
                // recollage raté (constaté une fois : forme disparue) : la reconstruire élément par élément
                stop();
                f.log("regroupement : recollage raté (" + count() + "/" + steps + "), forme reconstruite sans regroupement");
                f.restoreTool(saved);
                const j = job;
                if (j.natif) {                       // forme native : retracée directement
                    const nn = j.natif, err = f.natifLignes(nn.lignes, nn.tool, nn.color, nn.argb, nn.thickness);
                    f.result(!err, err || nn.lignes.length + " élément(s), non regroupés");
                    return;
                }
                j.group = false;
                f.build(j);
            } else if (phase === 4) {                // abandon : refaire ce qui a été annulé
                if (undone === 0) { stop(); f.log("regroupement abandonné, forme intacte"); finish(); return; }
                if (wait === 0) { for (let k = 0; k < undone; k++) ctl.redo(); wait = 1; return; }
                if (countAll() === totalBefore || ++wait > 40) { undone = 0; wait = 0; }
            }
        }
        function abandon(why) { stop(); f.log("regroupement abandonné : " + why); finish(); }
        function finish() { f.restoreTool(saved); f.status = ""; f.restoreStyle(job); f.result(true, steps + " élément(s)"); }
    }

    // ---- injection (gabarits)
    function inject(strokes, forTemplate) {
        let txt = "", ms = 0;
        for (const st of strokes) {
            const pts = st.raw ? st.pts : densify(st.pts);
            txt += "B " + st.hold + "\n";
            for (const p of pts) {
                const g = layer.mapToItem(null, p[0], p[1]);     // coordonnées écran
                txt += "P " + g.x.toFixed(1) + " " + g.y.toFixed(1) + "\n";
            }
            txt += "E\n";
            ms += pts.length * 7 + 100 + (st.hold ? st.hold + 300 : 0);
        }
        const path = "/home/root/xovi/formes/f-" + Date.now() + ".txt";
        const x = new XMLHttpRequest();
        x.onreadystatechange = function() {
            if (x.readyState === XMLHttpRequest.DONE) {
                f.pendingFile = path;
                f.pendingIsTemplate = !!forTemplate;
                f.status = "Éloignez le stylet de l'écran…";
                f.estimate = ms;
            }
        };
        x.open("PUT", "file://" + path);   // asynchrone (en synchrone, Qt écrit un fichier vide)
        x.send(txt);
    }
    property bool pendingIsTemplate: false
    property rect delArea
    property int delExpect: 0
    property int delStep: 0
    property int delSaved: 17
    Timer {
        id: delTimer
        interval: 150
        repeat: true
        property int tries: 0
        onTriggered: {
            const ctl = f.view.controller, ts = f.view.toolSettings, L = ctl.currentLayer;
            if (f.delStep === 0) {
                f.delSaved = f.selectionTool();
                ctl.clearSelectedItems(); ctl.addSelectionRect(f.delArea, 1); f.delStep = 1; tries = 0; return;
            }
            const n = ctl.selectionItemCount;
            if (n !== f.delExpect && ++tries < 20) return;
            stop();
            if (n === f.delExpect) { ctl.deleteSelectedItems(L); f.log("zone effacée : " + n + " éléments"); }
            else f.log("zone NON effacée : " + n + " éléments sélectionnés au lieu de " + f.delExpect);
            ctl.clearSelectedItems(); f.restoreTool(f.delSaved);
        }
    }
    Timer { id: clearMsg; interval: 2500; onTriggered: f.status = "" }
    property int estimate: 0
    function busy() {
        return pendingFile !== "" || job !== null || snapJob !== null || tplTimer.running || grouping.running || delTimer.running
               || Date.now() < launchedAt + estimate + 3000;
    }
    property double launchedAt: 0

    // attendre que le vrai stylet soit éloigné, sinon ses événements se mêleraient au tracé
    Timer {
        id: launcher
        interval: 300
        repeat: true
        running: f.pendingFile !== ""
        property int calm: 0
        onTriggered: {
            if (f.view && f.view.penClose) { calm = 0; return; }
            if (++calm < 2) return;
            calm = 0;
            const p = f.pendingFile;
            f.pendingFile = "";
            exe.executeCommand("/bin/sh", ["-c", "/home/root/xovi/formes/trace.sh '" + p + "' >/dev/null 2>&1 &"]);
            f.launchedAt = Date.now();
            if (!f.pendingIsTemplate) { f.status = "Surlignage…"; return; }    // surlignage direct (snapTimer)
            f.status = "Préparation du gabarit…";
            tplTimer.tries = 0;
            tplTimer.start();
        }
    }

    // ------------------------------------------------------------ calque de placement
    Item {
        id: layer
        anchors.fill: parent
        visible: f.spec !== null

        PenInputBlocker {
            anchors.fill: parent
            manager: f.view && f.view.penInput ? f.view.penInput.surfaceManager : null
        }

        Canvas {
            id: preview
            anchors.fill: parent
            onPaint: {
                const ctx = getContext("2d");
                ctx.clearRect(0, 0, width, height);
                if (!f.spec || (!f.dragging && f.ellipseStep === 0)) return;
                ctx.strokeStyle = "black"; ctx.lineWidth = 2; ctx.setLineDash([8, 6]);
                for (const st of f.shapeStrokes(f.spec, f.a, f.b)) {
                    ctx.beginPath(); ctx.moveTo(st.pts[0][0], st.pts[0][1]);
                    for (let i = 1; i < st.pts.length; i++) ctx.lineTo(st.pts[i][0], st.pts[i][1]);
                    ctx.stroke();
                }
            }
        }

        Image {
            visible: f.spec !== null && f.spec.shape === "image" && f.dragging
            source: f.spec && f.spec.shape === "image" ? "file://" + f.spec.file : ""
            width: f.spec && f.spec.w ? f.spec.w : implicitWidth
            height: f.spec && f.spec.h ? f.spec.h : implicitHeight
            x: f.b.x - width / 2
            y: f.b.y - height / 2
            opacity: 0.6
        }

        MouseArea {
            anchors.fill: parent
            preventStealing: true
            function minorOf(x, y) {   // distance de la pointe à l'axe de l'ellipse
                const ang = Math.atan2(f.b.y - f.a.y, f.b.x - f.a.x);
                return Math.abs(-(x - f.a.x) * Math.sin(ang) + (y - f.a.y) * Math.cos(ang));
            }
            onPressed: (e) => {
                if (f.ellipseStep === 1) { f.spec.minor = minorOf(e.x, e.y); f.dragging = true; preview.requestPaint(); return; }
                f.a = Qt.point(e.x, e.y); f.b = f.a; f.dragging = true; preview.requestPaint();
            }
            onPositionChanged: (e) => {
                if (!f.dragging) return;
                if (f.ellipseStep === 1) f.spec.minor = minorOf(e.x, e.y); else f.b = Qt.point(e.x, e.y);
                preview.requestPaint();
            }
            onReleased: (e) => {
                if (f.ellipseStep === 1) {               // second geste : petit rayon -> on trace
                    f.spec.minor = minorOf(e.x, e.y); f.dragging = false; f.ellipseStep = 0;
                    preview.requestPaint(); f.commit(); return;
                }
                f.b = Qt.point(e.x, e.y);
                const big = Math.abs(f.b.x - f.a.x) > 12 || Math.abs(f.b.y - f.a.y) > 12;
                if (f.spec && f.spec.shape === "image") { f.dragging = false; preview.requestPaint(); f.commitImage(f.b); return; }
                if (big && f.spec && f.spec.shape === "ellipse") {   // premier geste : grand axe -> attendre le petit rayon
                    f.ellipseStep = 1; f.spec.minor = Math.hypot(f.b.x - f.a.x, f.b.y - f.a.y) * 0.6;
                    preview.requestPaint(); return;
                }
                f.dragging = false;
                preview.requestPaint();
                if (big) f.commit();
            }
        }

        // bandeau d'aide, sobre
        Rectangle {
            anchors.top: parent.top
            anchors.topMargin: 110
            anchors.horizontalCenter: parent.horizontalCenter
            width: bandeau.implicitWidth + 160
            height: 64
            color: "white"
            border.color: "black"; border.width: 2
            Row {
                id: bandeau
                anchors.centerIn: parent
                spacing: 28
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    font.pixelSize: 26; color: "black"
                    text: !f.spec ? "" : f.spec.shape === "image" ? "Touchez l'endroit où placer la formule"
                        : f.spec.shape === "circle" ? "Posez le stylet au centre, tirez jusqu'au rayon"
                        : f.spec.shape === "ellipse" ? (f.ellipseStep === 0 ? "Du centre, tracez le grand rayon" : "Tirez pour régler le petit rayon")
                        : "Étirez la forme avec le stylet"
                }
                Rectangle {
                    width: annuler.implicitWidth + 32; height: 44
                    anchors.verticalCenter: parent.verticalCenter
                    color: "white"; border.color: "black"; border.width: 2
                    Text { id: annuler; anchors.centerIn: parent; text: "Annuler"; font.pixelSize: 24; color: "black" }
                    MouseArea { anchors.fill: parent; onClicked: { f.spec = null; f.dragging = false; f.ellipseStep = 0; preview.requestPaint(); } }
                }
            }
        }
    }

    // message pendant l'attente / le tracé
    Rectangle {
        visible: f.status !== ""
        anchors.top: parent.top
        anchors.topMargin: 110
        anchors.horizontalCenter: parent.horizontalCenter
        width: msg.implicitWidth + 64; height: 60
        color: "white"; border.color: "black"; border.width: 2
        Text { id: msg; anchors.centerIn: parent; text: f.status; font.pixelSize: 26; color: "black" }
    }

    // ---- masque de l'interface (barre d'outils, menus, indicateurs…) : cases de 24 px de l'écran physique
    //      couvertes par un élément dessiné qui n'appartient pas au contenu de la page
    readonly property int maskCell: 24
    // (x0, y0, w, h) en pixels de l'écran physique -> vrai si la zone est à l'écran et loin de toute interface
    function uiFreeChecker(margin) {
        const m = margin === undefined ? 30 : margin;
        const mk = uiMask(), cols = Math.ceil(1404 / maskCell);
        const bits = [];
        for (const ch of mk.hex) { const n = parseInt(ch, 16); bits.push(n >> 3 & 1, n >> 2 & 1, n >> 1 & 1, n & 1); }
        return (x0, y0, w, h) => {
            if (x0 < 20 || y0 < 20 || x0 + w > 1384 || y0 + h > 1852) return false;
            for (let y = Math.floor((y0 - m) / maskCell); y <= Math.floor((y0 + h + m) / maskCell); y++)
                for (let x = Math.floor((x0 - m) / maskCell); x <= Math.floor((x0 + w + m) / maskCell); x++)
                    if (x >= 0 && y >= 0 && x < cols && bits[y * cols + x]) return false;
            return true;
        };
    }
    function uiMask() {
        const cols = Math.ceil(1404 / maskCell), rows = Math.ceil(1872 / maskCell);
        const bits = new Array(cols * rows).fill(0);
        let root = view;
        while (root.parent) root = root.parent;
        let n = 0;
        const mark = (it) => {
            const p = it.mapToItem(null, 0, 0), q = it.mapToItem(null, it.width, it.height);
            const x0 = Math.max(0, Math.floor(Math.min(p.x, q.x) / maskCell)), x1 = Math.min(cols - 1, Math.floor((Math.max(p.x, q.x) - 1) / maskCell));
            const y0 = Math.max(0, Math.floor(Math.min(p.y, q.y) / maskCell)), y1 = Math.min(rows - 1, Math.floor((Math.max(p.y, q.y) - 1) / maskCell));
            for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) bits[y * cols + x] = 1;
        };
        const walk = (it, depth) => {
            if (!it || it === view || depth > 80 || !it.visible || it.opacity <= 0.02) return;
            n++;
            if (it.width > 0 && it.height > 0 && it.width * it.height < 1404 * 1872 * 0.5) {
                let painted = false;
                if (it.text !== undefined && it.font !== undefined) painted = String(it.text) !== "";
                else if (it.source !== undefined && it.status !== undefined) painted = String(it.source) !== "";
                else if (it.color !== undefined && it.border !== undefined) painted = it.color.a > 0.05 || (it.border.width > 0 && it.border.color.a > 0.05);
                if (painted) mark(it);
            }
            const ch = it.children;
            if (ch) for (let i = 0; i < ch.length; i++) walk(ch[i], depth + 1);
        };
        walk(root, 0);
        let hex = "";
        for (let i = 0; i < bits.length; i += 4) hex += (bits[i] * 8 + (bits[i + 1] || 0) * 4 + (bits[i + 2] || 0) * 2 + (bits[i + 3] || 0)).toString(16);
        return { hex: hex, items: n };
    }

    // ---- page affichée et orientation, pour le PC (mode Document, rotation automatique du Studio)
    property string vueLast: ""
    property bool watching: false
    function studioWatching() {
        const x = new XMLHttpRequest();
        x.open("GET", "file:///home/root/xovi/formes/studio.watch", false);
        let ok = false;
        try { x.send(); const t = parseInt(x.responseText); ok = t > 0 && Date.now() / 1000 - t < 30; } catch (e) {}
        watching = ok;
        return ok;
    }
    property alias layer: layer
    Timer {
        id: vueTimer
        interval: f.watching ? 700 : 1500      // plus espacé quand aucun Studio ne regarde
        repeat: true
        running: f.view !== null && f.view.visible
        triggeredOnStart: true
        onTriggered: {
            const tm = f.view.tileManager;
            if (!tm) return;
            // angle de l'interface par rapport à l'écran physique (paysage = 90 ou 270)
            const p0 = f.view.mapToItem(null, 0, 0), p1 = f.view.mapToItem(null, 100, 0);
            const ang = Math.round(Math.atan2(p1.y - p0.y, p1.x - p0.x) * 180 / Math.PI);
            // correspondance écran physique -> page : 3 coins de l'écran projetés dans la page (zoom, défilement, rotation)
            const sc = (x, y) => { const q = f.layer.mapFromItem(null, x, y); const r = tm.viewToScene(Qt.point(q.x, q.y)); return [Math.round(r.x * 10) / 10, Math.round(r.y * 10) / 10]; };
            const o = { pageId: String(tm.pageId), w: Math.round(f.view.width), h: Math.round(f.view.height),
                        angle: (ang + 360) % 360, portrait: !!Values.isPortraitOrientation,
                        map: [].concat(sc(0, 0), sc(1404, 0), sc(0, 1872)) };
            const ap = f.view.toolSettings.activePen;           // état du crayon pour le Studio (remplace penGet)
            o.pen = { doc: true, writing: f.isWriting(), tool: ap.tool, color: ap.color, argb: ap.colorCode >>> 0, thickness: ap.thickness };
            const pr = f.view.controller ? f.view.controller.primaryContentRect : null;   // rectangle du PDF dans la page
            if (pr && pr.width > 0) o.pdf = [Math.round(pr.x * 10) / 10, Math.round(pr.y * 10) / 10, Math.round(pr.width * 10) / 10, Math.round(pr.height * 10) / 10];
            // masque d'interface : seulement si un Studio regarde (studio.watch mis à jour par la capture du PC)
            if (f.studioWatching()) {
                const mk = f.uiMask();
                o.mask = mk.hex; o.cell = f.maskCell;
            }
            const sv = JSON.stringify(o);
            if (sv === f.vueLast) return;
            f.vueLast = sv;
            const x = new XMLHttpRequest();
            x.open("PUT", "file:///home/root/xovi/formes/vue.json");   // asynchrone
            x.send(sv);
        }
    }

    // Bouton des carnets liés (carnets_lies.qmd) : relire /home/root/carnets-lies.json. Remplace le signal
    // carnetsReload de xovi-message-broker, qui n'arrive pas (constaté) ; bouton trouvé par ses propriétés.
    // Aussi à chaque ouverture de document : la liste a pu changer pendant qu'aucun document n'était ouvert.
    function findItem(test) {                  // premier élément de l'interface qui satisfait test (parcours)
        let top = f; while (top.parent) top = top.parent;
        const walk = (it, d) => {
            if (!it || d > 60) return null;
            try { if (test(it)) return it; } catch (e) {}
            const ch = it.children || [];
            for (let i = 0; i < ch.length; i++) { const r = walk(ch[i], d + 1); if (r) return r; }
            return null;
        };
        return walk(top, 0);
    }
    function reloadLinks() {
        const b = findItem(it => typeof it.reload === "function" && it.links !== undefined && "currentDoc" in it);
        if (b) b.reload();
        return b ? 1 : 0;
    }
    Timer { id: linksTimer; interval: 1500; onTriggered: f.reloadLinks() }
    Component.onCompleted: { log("formes prêtes"); linksTimer.start(); }
}
