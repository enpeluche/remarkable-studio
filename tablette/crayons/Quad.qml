// Bouton « 4 cases » : remplace le contenu du bouton du crayon secondaire (quad.qmd).
//   3 cases = crayons enregistrés (appui : charger dans le crayon secondaire et l'activer ; appui sur la
//             case déjà active : menu complet du crayon ; appui long : y ranger le crayon actif) ; 1 case = gomme.
// Crayons enregistrés : /home/root/xovi/crayons/quad.json. Rechargé à chaud (quad.version).
import QtQuick
import com.remarkable
import xofm.libs.toolbar
import xofm.libs.peninput
import ark.controls as ArkControls

Item {
    id: q
    property var tool: null                   // le bouton (WritingTool) du crayon secondaire
    anchors.fill: parent

    readonly property string file: "file:///home/root/xovi/crayons/quad.json"
    property var slots: [
        { tool: 17, color: 0, colorCode: 4278190080, thickness: 2 },     // fineliner noir
        { tool: 15, color: 6, colorCode: 4283327945, thickness: 2 },     // stylo bille bleu
        { tool: 18, color: 3, colorCode: 4294440729, thickness: 2 }      // surligneur jaune
    ]
    property int flash: -1                    // case qui vient d'être enregistrée (retour visuel)

    PenToolModel { id: penIcons }
    EraserToolModel { id: eraserIcons }

    function load() {
        const x = new XMLHttpRequest();
        x.open("GET", file, false);
        try { x.send(); const d = JSON.parse(x.responseText); if (d.pens && d.pens.length === 3) slots = d.pens;
                if (typeof d.current === "number") current = d.current; } catch (e) {}
    }
    function save() {
        const x = new XMLHttpRequest();
        x.open("PUT", file);                  // asynchrone (en synchrone, Qt écrit un fichier vide)
        x.send(JSON.stringify({ pens: slots, current: current }, null, 1));
    }
    // Le bouton entier passe en fond noir quand l'outil est actif (mise en évidence officielle) : on la
    // neutralise pour ce bouton, le petit carré noir indique déjà la case active.
    function noHighlight() {
        if (!tool) return;
        try { if (tool.highlighted) tool.highlighted = false; } catch (e) {}
        try { if (tool.selected) tool.selected = false; } catch (e) { console.log("QUAD selected non modifiable : " + e); }
    }
    onToolChanged: noHighlight()
    Connections {
        target: q.tool
        ignoreUnknownSignals: true
        function onHighlightedChanged() { q.noHighlight(); }
        function onSelectedChanged() { q.noHighlight(); }
    }
    Component.onCompleted: load()


    // ---- case active et enregistrement automatique
    // La case active est la dernière choisie (même si le crayon a été modifié depuis) ; les réglages faits
    // ensuite (menu du crayon, PC) sont enregistrés dans cette case. Avant : la case n'était « active » que si
    // le crayon était identique à celui enregistré, et la toucher pour fermer le menu rechargeait l'ancien crayon.
    property int current: -1
    Connections {
        target: q.tool ? q.tool.pen : null
        ignoreUnknownSignals: true
        function onPropertyChanged() { if (q.current >= 0 && q.active === q.tool) saveTimer.restart(); }
    }
    Timer {
        id: saveTimer
        interval: 800
        onTriggered: {
            const p = q.tool ? q.tool.pen : null;
            if (!p || q.current < 0 || q.active !== q.tool) return;
            // outils temporaires (Formes passe le crayon actif en Sélection le temps d'une opération)
            if (p.tool === Line.SelectionTool || p.tool === Line.Eraser || p.tool === Line.EraseSection || p.tool === Line.ZoomTool) return;
            const s = { tool: p.tool, color: p.color, colorCode: p.colorCode >>> 0, thickness: p.thickness };
            const o = q.slots[q.current];
            if (o && o.tool === s.tool && o.color === s.color && (o.colorCode >>> 0) === s.colorCode && o.thickness === s.thickness) return;
            const list = q.slots.slice();
            list[q.current] = s;
            q.slots = list;
            q.save();
        }
    }

    readonly property var pens: Toolbar.pens
    readonly property var active: pens ? pens.activePen : null
    readonly property bool eraserActive: active !== null && active !== undefined && active.penToolType === "eraser"

    function sameAs(s) {
        const p = pens.secondaryPen;
        return active === tool && p.tool === s.tool && p.color === s.color
               && (s.color !== Line.ArgbCode || (p.colorCode >>> 0) === (s.colorCode >>> 0))
               && Math.abs(p.thickness - s.thickness) < 0.01;
    }
    function usePen(i) {
        const s = slots[i], p = pens.secondaryPen;
        current = i;
        save();
        p.tool = s.tool;
        p.color = s.color;
        p.colorCode = s.colorCode;
        p.thickness = s.thickness;
        pens.requestPenSelect(tool, Toolbar.SelectMode.DontActivate);
    }
    function storePen(i) {
        const a = active && active.pen ? active.pen : null;
        if (!a || active.penToolType === "eraser") return;
        const list = slots.slice();
        list[i] = { tool: a.tool, color: a.color, colorCode: a.colorCode >>> 0, thickness: a.thickness };
        slots = list;
        if (active === tool) current = i;
        save();
        flash = i; flashTimer.restart();
    }
    Timer { id: flashTimer; interval: 900; onTriggered: q.flash = -1 }

    function findByName(it, name, depth) {
        if (!it || depth > 40) return null;
        if (it.objectName === name) return it;
        const ch = it.children || [];
        for (let i = 0; i < ch.length; i++) { const r = findByName(ch[i], name, depth + 1); if (r) return r; }
        return null;
    }
    function eraserMenu() {                   // fenêtre « gomme » (types, épaisseur, tout effacer)
        menuOpen = !menuOpen;
    }
    property bool menuOpen: false
    function topItem() { let t = q; while (t.parent) t = t.parent; return t; }
    function findPenInput(it, depth) {       // gestionnaire d'entrée du stylet (pour bloquer l'encre sous la fenêtre)
        if (!it || depth > 40) return null;
        try { if (it.visible && it.penInput && it.penInput.surfaceManager) return it.penInput.surfaceManager; } catch (e) {}
        const ch = it.children || [];
        for (let i = 0; i < ch.length; i++) { const r = findPenInput(ch[i], depth + 1); if (r) return r; }
        return null;
    }
    function useEraser() {
        let top = q;
        while (top.parent) top = top.parent;
        const e = findByName(top, "eraserMenu", 0);
        if (e) {
            pens.requestPenSelect(e, Toolbar.SelectMode.DontActivate);
            Toolbar.eraser.eraserToolSelected(e.pen.tool);
        } else {                              // pas de bouton gomme dans la barre : le crayon secondaire devient gomme
            pens.secondaryPen.tool = Line.Eraser;
            pens.requestPenSelect(tool, Toolbar.SelectMode.DontActivate);
        }
    }

    // ---- fenêtre gomme
    Item {
        id: overlay
        // calque des bulles d'aide de la barre d'outils : il pivote avec l'interface (portrait / paysage)
        parent: q.menuOpen ? (Toolbar.geometry.tooltipOverlay || q.topItem()) : q
        visible: q.menuOpen
        anchors.fill: parent
        z: 10000
        PenInputBlocker { anchors.fill: parent; manager: q.menuOpen ? q.findPenInput(q.topItem(), 0) : null }
        MouseArea { anchors.fill: parent; onClicked: q.menuOpen = false }     // toucher ailleurs : fermer

        Rectangle {
            id: panel
            // à côté de la barre d'outils, repérée par le bouton 4 cases lui-même (le « conteneur » officiel
            // couvre tout l'écran) : le bord d'écran le plus proche du bouton = côté de la barre
            readonly property rect btn: {
                if (!q.menuOpen || !overlay.parent) return Qt.rect(0, 0, 0, 0);   // recalculé à chaque ouverture
                const p0 = q.mapToItem(overlay, 0, 0), p1 = q.mapToItem(overlay, q.width, q.height);
                return Qt.rect(Math.min(p0.x, p1.x), Math.min(p0.y, p1.y), Math.abs(p1.x - p0.x), Math.abs(p1.y - p0.y));
            }
            readonly property string side: {
                const d = { left: btn.x, right: overlay.width - btn.x - btn.width, top: btn.y, bottom: overlay.height - btn.y - btn.height };
                let best = "left";
                for (const k in d) if (d[k] < d[best]) best = k;
                return best;
            }
            readonly property real gap: 18
            x: side === "left" ? btn.x + btn.width + gap
               : side === "right" ? btn.x - width - gap
               : Math.max(8, Math.min(btn.x + btn.width / 2 - width / 2, overlay.width - width - 8))
            y: side === "top" ? btn.y + btn.height + gap
               : side === "bottom" ? btn.y - height - gap
               : Math.max(8, Math.min(btn.y - 20, overlay.height - height - 8))
            width: 360
            height: col.implicitHeight + 24
            color: "white"
            border.color: "black"; border.width: 2
            MouseArea { anchors.fill: parent }                                 // ne pas fermer en touchant la fenêtre
            Column {
                id: col
                x: 12; y: 12
                width: parent.width - 24
                spacing: 10
                Text { text: "Gomme"; font.pixelSize: 24; font.bold: true; color: "black" }
                Row {
                    spacing: 8
                    Repeater {
                        model: eraserIcons
                        Rectangle {
                            required property string iconPath
                            required property string displayName
                            required property int tool
                            readonly property bool on: Toolbar.eraser.pen.tool === tool
                            width: 104; height: 104
                            color: "white"; border.color: "black"; border.width: on ? 3 : 1
                            ArkControls.Icon { anchors.centerIn: parent; anchors.verticalCenterOffset: -12; size: 44; source: iconPath; color: "black" }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                                   width: parent.width - 8; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                                   text: qsTranslate("xofm::libs::toolbar::ToolModel", displayName); font.pixelSize: 16; color: "black" }
                            MouseArea { anchors.fill: parent; onClicked: { Toolbar.eraser.eraserToolSelected(tool); q.useEraser(); } }
                        }
                    }
                }
                Row {
                    visible: Toolbar.eraser.pen.tool === Line.Eraser
                    spacing: 8
                    Repeater {
                        model: PenThicknessModel {}
                        Rectangle {
                            required property string iconPath
                            required property int thickness
                            readonly property bool on: Toolbar.eraser.pen.thickness === thickness
                            width: 104; height: 72
                            color: "white"; border.color: "black"; border.width: on ? 3 : 1
                            ArkControls.Icon { anchors.centerIn: parent; size: 40; source: iconPath; color: "black" }
                            MouseArea { anchors.fill: parent; onClicked: Toolbar.eraser.eraserThicknessSelected(thickness) }
                        }
                    }
                }
                Rectangle {
                    width: parent.width; height: 64
                    color: "white"; border.color: "black"; border.width: 1
                    Row {
                        anchors.centerIn: parent; spacing: 12
                        ArkControls.Icon { size: 36; source: "qrc:/ark/icons/erase_all"; color: "black"; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: "Tout effacer"; font.pixelSize: 22; color: "black"; anchors.verticalCenter: parent.verticalCenter }
                    }
                    MouseArea { anchors.fill: parent; onClicked: { Toolbar.eraser.eraseAllSelected(); q.menuOpen = false; } }
                }
            }
        }
    }

    // ---- 2 x 2 cases
    Grid {
        anchors.fill: parent
        anchors.margins: 4
        columns: 2
        spacing: 2
        Repeater {
            model: 4
            Rectangle {
                id: cell
                required property int index
                readonly property bool isEraser: index === 3
                readonly property var s: isEraser ? null : q.slots[index]
                readonly property bool on: isEraser ? q.eraserActive
                                           : (q.current >= 0 ? (q.active === q.tool && q.current === index) : (s !== null && q.sameAs(s)))
                width: (parent.width - 2) / 2
                height: (parent.height - 2) / 2
                color: q.flash === index ? "#cccccc" : "transparent"

                ArkControls.Icon {
                    anchors.centerIn: parent
                    size: Math.round(Math.min(parent.width, parent.height) * 0.72)
                    source: cell.isEraser ? eraserIcons.iconForTool(Line.Eraser) : penIcons.iconForTool(cell.s.tool)
                    color: "black"
                }
                // case active : petit carré noir dans le coin
                Rectangle {
                    visible: cell.on
                    width: 9; height: 9
                    anchors.left: parent.left; anchors.top: parent.top
                    anchors.margins: 2
                    color: "black"
                }
                // pastille de couleur du crayon
                Rectangle {
                    visible: !cell.isEraser
                    width: 11; height: 11; radius: 6
                    anchors.right: parent.right; anchors.bottom: parent.bottom
                    anchors.margins: 3
                    color: cell.s ? "#" + ((cell.s.colorCode >>> 0) & 0xffffff).toString(16).padStart(6, "0") : "black"
                    border.color: "black"; border.width: 1
                }
                MouseArea {
                    anchors.fill: parent
                    // case déjà active : ouvrir le menu complet du crayon (comme un bouton de crayon normal)
                    onClicked: cell.isEraser ? (cell.on ? q.eraserMenu() : q.useEraser())
                               : (cell.on ? q.pens.requestPenSelect(q.tool, Toolbar.SelectMode.Activate) : q.usePen(cell.index))
                    onPressAndHold: if (!cell.isEraser) q.storePen(cell.index)
                }
            }
        }
    }
}
