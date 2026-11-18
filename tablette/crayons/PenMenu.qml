// Ajouts au menu officiel du crayon (WritingTool) — chargé par menu_crayon.qmd.
// Rechargé à chaque ouverture du menu : on peut modifier ce fichier sans redémarrer la tablette.
//   section "thickness" : curseur d'épaisseur continu, sous les 3 épaisseurs officielles
//   section "color"     : couleurs libres (palette partagée avec le PC) + réglage R/V/B + hexadécimal
import QtQuick
import QtQuick.Layouts
import com.remarkable
import ark.controls as ArkControls
import xofm.libs.toolbar

ColumnLayout {
    id: m
    spacing: 0
    // largeur : la colonne de droite (couleurs) est plus large pour accueillir plus de pastilles
    readonly property int colorColumns: 5
    implicitWidth: section === "color" ? colorColumns * 112 + 16 : 336

    property var menu: null            // le PenTool officiel (root de WritingTool.qml)
    property string section: ""
    readonly property var pen: menu ? menu.pen : null

    // ---------------------------------------------------------------- outils
    readonly property string paletteFile: "file:///home/root/crayons.json"
    readonly property real minThickness: 0.3
    readonly property real maxThickness: 15

    function hex2(v) { return ("0" + Math.round(v).toString(16)).slice(-2).toUpperCase(); }
    function hexOf(a) { a = a >>> 0; return "#" + hex2((a >>> 16) & 255) + hex2((a >>> 8) & 255) + hex2(a & 255); }
    function argbOf(r, g, b) { return ((255 << 24) | (Math.round(r) << 16) | (Math.round(g) << 8) | Math.round(b)) >>> 0; }

    // nom approximatif d'une couleur, en français, à la façon des noms officiels
    function colorName(a) {
        a = a >>> 0;
        const r = ((a >>> 16) & 255) / 255, g = ((a >>> 8) & 255) / 255, b = (a & 255) / 255;
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
        if (d < 0.08) {
            if (l < 0.12) return "Noir";
            if (l > 0.92) return "Blanc";
            return l < 0.4 ? "Gris foncé" : (l > 0.7 ? "Gris clair" : "Gris");
        }
        let h;
        if (mx === r) h = ((g - b) / d + 6) % 6; else if (mx === g) h = (b - r) / d + 2; else h = (r - g) / d + 4;
        h *= 60;
        const names = [[15, "Rouge"], [40, "Orange"], [65, "Jaune"], [90, "Vert anis"], [150, "Vert"],
                       [175, "Turquoise"], [195, "Cyan"], [220, "Azur"], [255, "Bleu"], [285, "Violet"],
                       [320, "Magenta"], [345, "Rose"], [360, "Rouge"]];
        let n = "Rouge";
        for (const [lim, name] of names) { if (h < lim) { n = name; break; } }
        if (n === "Orange" && l < 0.35) n = "Brun";
        if (l < 0.3) n += " foncé"; else if (l > 0.75) n += " clair";
        return n;
    }

    // ---------------------------------------------------------------- état
    property real thickness: pen ? pen.thickness : 2
    property real r: 0
    property real g: 0
    property real b: 0
    readonly property int argb: argbOf(r, g, b)
    property var palette: []
    property bool removing: false     // appui long : mode « retirer »

    // couleurs officielles : leur teinte réelle vient du modèle de couleurs de la tablette
    PenColorModel {
        id: colorModelM
        tool: m.pen ? m.pen.tool : 17
        colorProfile: (Toolbar.composition && Toolbar.composition.provider) ? Toolbar.composition.provider.colorProfile : colorProfile
    }
    function syncFromPen() {
        if (!pen) return;
        if (pen.color === Line.ArgbCode) {
            const a = pen.colorCode >>> 0;
            r = (a >>> 16) & 255; g = (a >>> 8) & 255; b = a & 255;
        } else {
            const c = colorModelM.displayColor(pen.color, pen.colorCode);
            r = Math.round(c.r * 255); g = Math.round(c.g * 255); b = Math.round(c.b * 255);
        }
        thickness = pen.thickness;
    }
    onPenChanged: syncFromPen()
    // choisir une couleur (pastille officielle ou libre) met l'éditeur R/V/B à jour
    Connections {
        target: m.pen
        function onPropertyChanged() { m.syncFromPen(); }
    }

    function applyColor(a) {
        if (!pen) return;
        // écriture directe dans le crayon, comme depuis le PC (le bouton 4 cases l'enregistre dans sa case active)
        pen.color = Line.ArgbCode;
        pen.colorCode = a >>> 0;
    }
    function applyThickness(t) {
        if (!pen) return;
        pen.thickness = Math.max(minThickness, Math.min(maxThickness, Math.round(t * 100) / 100));
    }

    function loadPalette() {
        const x = new XMLHttpRequest();
        x.open("GET", paletteFile, false);
        try { x.send(); palette = JSON.parse(x.responseText).palette || []; } catch (e) { palette = []; }
    }
    function savePalette(list) {
        palette = list;
        const x = new XMLHttpRequest();
        x.open("PUT", paletteFile);          // asynchrone : en synchrone Qt écrit un fichier vide
        x.send(JSON.stringify({ palette: list }, null, 1));
    }
    function addCurrent() {
        const list = palette.slice();
        if (list.some(p => (p.argb >>> 0) === argb)) return;
        list.push({ name: colorName(argb), argb: argb });
        savePalette(list);
    }
    function removeAt(i) {
        const list = palette.slice(); list.splice(i, 1); savePalette(list);
        removing = false;
    }

    // ---------------------------------------------------------------- formes (voir Formes.qml)
    property int shapeSpacing: 60
    property int sides: 6
    readonly property string shapePrefsFile: "file:///home/root/xovi/crayons/formes-prefs.json"
    function loadShapePrefs() {
        const x = new XMLHttpRequest();
        x.open("GET", shapePrefsFile, false);
        try { x.send(); const p = JSON.parse(x.responseText); shapeSpacing = p.spacing || 60; sides = p.sides || 6; } catch (e) {}
    }
    function saveShapePrefs() {
        const x = new XMLHttpRequest();
        x.open("PUT", shapePrefsFile);
        x.send(JSON.stringify({ spacing: shapeSpacing, sides: sides }));
    }
    function closeMenu() {
        try {
            if (menu && menu.toolbar && typeof menu.toolbar.closeFoldout === "function") { menu.toolbar.closeFoldout(); return; }
            if (typeof Toolbar !== "undefined" && Toolbar.closeFoldout) { Toolbar.closeFoldout(); return; }
            if (menu && menu.foldout) {
                if (typeof menu.foldout.close === "function") { menu.foldout.close(); return; }
                menu.foldout.visible = false;
            }
        } catch (e) { console.log("FORMES fermeture du menu : " + e); }
    }
    function placeShape(shape) {
        const x = new XMLHttpRequest();
        x.open("PUT", "file:///home/root/xovi/crayons/formes-cmd.json");
        x.send(JSON.stringify({ id: Date.now(), action: "place", shape: shape, spacing: shapeSpacing, sides: sides }));
        closeMenu();
    }

    Component.onCompleted: { loadPalette(); syncFromPen(); loadShapePrefs(); }

    // ================================================================ ÉPAISSEUR
    ColumnLayout {
        visible: m.section === "thickness"
        spacing: 0
        Layout.fillWidth: true
        Layout.leftMargin: 24
        Layout.rightMargin: 24
        Layout.bottomMargin: 16

        Curseur {
            Layout.fillWidth: true
            label: ""
            // échelle logarithmique : plus de précision sur les traits fins
            value: Math.log(m.thickness / m.minThickness) / Math.log(m.maxThickness / m.minThickness)
            valueText: m.thickness.toFixed(2)
            onMoved: (v) => m.thickness = m.minThickness * Math.pow(m.maxThickness / m.minThickness, v)
            onReleased: m.applyThickness(m.thickness)
        }
    }

    // ================================================================ COULEURS
    ColumnLayout {
        visible: m.section === "color"
        spacing: 0
        Layout.fillWidth: true

        ArkControls.FoldoutSectionHeader {
            label: m.removing ? "Touchez une couleur pour la retirer" : "Couleurs libres"
            Layout.fillWidth: true
        }

        // palette : même présentation que les pastilles officielles (pastille + nom dessous)
        GridLayout {
            columns: m.colorColumns
            rowSpacing: 0
            columnSpacing: 0
            Layout.alignment: Qt.AlignHCenter
            Repeater {
                model: m.palette
                Case {
                    required property var modelData
                    required property int index
                    swatch: (modelData.argb >>> 0)
                    text: modelData.name || m.colorName(modelData.argb)
                    selected: !m.removing && m.pen && m.pen.color === Line.ArgbCode && (m.pen.colorCode >>> 0) === (modelData.argb >>> 0)
                    crossed: m.removing
                    onTapped: m.removing ? m.removeAt(index) : m.applyColor(modelData.argb)
                    onHeld: m.removing = !m.removing
                }
            }
            Case {
                plus: true
                text: m.removing ? "Terminé" : "Ajouter"
                onTapped: m.removing ? (m.removing = false) : m.addCurrent()
            }
        }

        ArkControls.FoldoutDivider { Layout.fillWidth: true; Layout.topMargin: 8 }

        // couleur en cours : pastille, hexadécimal, nom
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.topMargin: 20
            spacing: 20
            Rectangle {
                width: 56; height: 56; radius: 28
                color: m.hexOf(m.argb)
                border.color: "black"; border.width: 2
            }
            ColumnLayout {
                spacing: 2
                Text { text: m.hexOf(m.argb); font.pixelSize: 30; font.bold: true; color: "black" }
                Text { text: m.colorName(m.argb); font.pixelSize: 22; color: "black" }
            }
            Item { Layout.fillWidth: true }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            Layout.topMargin: 8
            spacing: 0
            Curseur {
                Layout.fillWidth: true
                label: "R"; value: m.r / 255; valueText: Math.round(m.r)
                onMoved: (v) => m.r = Math.round(v * 255)
                onReleased: m.applyColor(m.argb)
            }
            Curseur {
                Layout.fillWidth: true
                label: "V"; value: m.g / 255; valueText: Math.round(m.g)
                onMoved: (v) => m.g = Math.round(v * 255)
                onReleased: m.applyColor(m.argb)
            }
            Curseur {
                Layout.fillWidth: true
                label: "B"; value: m.b / 255; valueText: Math.round(m.b)
                onMoved: (v) => m.b = Math.round(v * 255)
                onReleased: m.applyColor(m.argb)
            }
        }

        // ---------------------------------------------------------- formes
        ArkControls.FoldoutDivider { Layout.fillWidth: true; Layout.topMargin: 8 }
        ArkControls.FoldoutSectionHeader { label: "Formes"; Layout.fillWidth: true }
        GridLayout {
            columns: m.colorColumns
            rowSpacing: 0
            columnSpacing: 0
            Layout.alignment: Qt.AlignHCenter
            Repeater {
                model: [["line", "Règle"], ["rect", "Rectangle"], ["circle", "Cercle"], ["ellipse", "Ellipse"],
                        ["grid", "Grille"], ["polygon", "Polygone"], ["axes", "Repère"]]
                Case {
                    required property var modelData
                    icon: modelData[0]
                    text: modelData[1]
                    onTapped: m.placeShape(modelData[0])
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 24
            Layout.rightMargin: 24
            spacing: 0
            Curseur {
                Layout.fillWidth: true
                label: ""; value: (m.shapeSpacing - 20) / 180; valueText: Math.round(m.shapeSpacing) + " px"
                onMoved: (v) => m.shapeSpacing = Math.round(20 + v * 180)
                onReleased: m.saveShapePrefs()
            }
            Curseur {
                Layout.fillWidth: true
                label: ""; value: (m.sides - 3) / 9; valueText: m.sides + " côtés"
                onMoved: (v) => m.sides = Math.round(3 + v * 9)
                onReleased: m.saveShapePrefs()
            }
        }

        // ma petite marque
        RowLayout {
            Layout.alignment: Qt.AlignRight
            Layout.rightMargin: 20
            Layout.topMargin: 10
            Layout.bottomMargin: 14
            spacing: 8
            Etincelle { size: 18 }
            Text { text: "a little extra by Claude"; font.pixelSize: 17; font.italic: true; color: "black" }
        }
    }

    // ================================================================ composants

    // curseur sobre et anguleux : trait noir, poignée carrée
    component Curseur: Item {
        id: c
        property string label
        property real value: 0
        property string valueText
        signal moved(real v)
        signal released()
        implicitHeight: 60
        Text {
            id: lab
            visible: c.label !== ""
            width: visible ? 30 : 0
            anchors.verticalCenter: parent.verticalCenter
            text: c.label; font.pixelSize: 24; font.bold: true; color: "black"
        }
        Text {
            id: val
            width: 110
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            horizontalAlignment: Text.AlignRight
            text: c.valueText; font.pixelSize: 22; color: "black"
        }
        Item {
            id: track
            anchors.left: lab.right
            anchors.leftMargin: lab.visible ? 8 : 0
            anchors.right: val.left
            anchors.rightMargin: 18
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width; height: 2; color: "black"
            }
            Rectangle {   // portion « remplie »
                anchors.verticalCenter: parent.verticalCenter
                width: knob.x + knob.width / 2; height: 6; color: "black"
            }
            Rectangle {
                id: knob
                width: 26; height: 26
                anchors.verticalCenter: parent.verticalCenter
                x: Math.max(0, Math.min(1, c.value)) * (track.width - width)
                color: area.pressed ? "black" : "white"
                border.color: "black"; border.width: 3
            }
            MouseArea {
                id: area
                anchors.fill: parent
                anchors.topMargin: -10; anchors.bottomMargin: -10
                preventStealing: true
                function v(mx) { return Math.max(0, Math.min(1, (mx - knob.width / 2) / (track.width - knob.width))); }
                onPressed: (e) => c.moved(v(e.x))
                onPositionChanged: (e) => c.moved(v(e.x))
                onReleased: c.released()
            }
        }
    }

    // case de palette, au format des pastilles officielles (112 x 112, pastille 39, nom dessous)
    component Case: Rectangle {
        id: cs
        property var swatch: 0
        property string text
        property bool selected: false
        property bool plus: false
        property bool crossed: false
        property string icon: ""
        signal tapped()
        signal held()
        implicitWidth: 112; implicitHeight: 112
        color: selected ? "black" : "white"
        Column {
            anchors.centerIn: parent
            spacing: 8
            Item {
                width: 39; height: 39
                anchors.horizontalCenter: parent.horizontalCenter
                Canvas {
                    anchors.fill: parent
                    visible: cs.icon !== ""
                    property string kind: cs.icon
                    onKindChanged: requestPaint()
                    onPaint: {
                        const c = getContext("2d"), w = width, h = height;
                        c.clearRect(0, 0, w, h);
                        c.strokeStyle = cs.selected ? "white" : "black"; c.lineWidth = 3;
                        c.beginPath();
                        if (kind === "line") { c.moveTo(3, h - 3); c.lineTo(w - 3, 3); }
                        else if (kind === "rect") { c.rect(4, 8, w - 8, h - 16); }
                        else if (kind === "circle") { c.moveTo(w - 3, h / 2); c.arc(w / 2, h / 2, Math.min(w, h) / 2 - 3, 0, 2 * Math.PI); c.moveTo(w / 2 + 2, h / 2); c.arc(w / 2, h / 2, 2, 0, 2 * Math.PI); }
                        else if (kind === "ellipse") { c.ellipse(3, 8, w - 6, h - 16); }
                        else if (kind === "grid") {
                            for (let i = 0; i <= 3; i++) { const x = 4 + (w - 8) * i / 3; c.moveTo(x, 4); c.lineTo(x, h - 4); }
                            for (let j = 0; j <= 3; j++) { const y = 4 + (h - 8) * j / 3; c.moveTo(4, y); c.lineTo(w - 4, y); }
                        } else if (kind === "polygon") {
                            for (let i = 0; i <= 6; i++) {
                                const t = -Math.PI / 2 + 2 * Math.PI * i / 6;
                                const x = w / 2 + (w / 2 - 3) * Math.cos(t), y = h / 2 + (h / 2 - 3) * Math.sin(t);
                                if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
                            }
                        } else if (kind === "axes") {
                            c.moveTo(3, h / 2); c.lineTo(w - 3, h / 2); c.moveTo(w / 2, h - 3); c.lineTo(w / 2, 3);
                            c.moveTo(w - 10, h / 2 - 6); c.lineTo(w - 3, h / 2); c.lineTo(w - 10, h / 2 + 6);
                            c.moveTo(w / 2 - 6, 10); c.lineTo(w / 2, 3); c.lineTo(w / 2 + 6, 10);
                        }
                        c.stroke();
                    }
                }
                Rectangle {
                    anchors.fill: parent
                    visible: !cs.plus && cs.icon === ""
                    radius: width / 2
                    color: m.hexOf(cs.swatch)
                    border.color: cs.selected ? "white" : "black"; border.width: 2
                }
                // "+" pour ajouter
                Rectangle { visible: cs.plus; anchors.centerIn: parent; width: 30; height: 4; color: "black" }
                Rectangle { visible: cs.plus; anchors.centerIn: parent; width: 4; height: 30; color: "black" }
                // croix en mode « retirer »
                Rectangle { visible: cs.crossed; anchors.centerIn: parent; width: 46; height: 4; rotation: 45; color: "black" }
                Rectangle { visible: cs.crossed; anchors.centerIn: parent; width: 46; height: 4; rotation: -45; color: "black" }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 104
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: cs.text; font.pixelSize: 18
                color: cs.selected ? "white" : "black"
            }
        }
        MouseArea {
            anchors.fill: parent
            onClicked: cs.tapped()
            onPressAndHold: cs.held()
        }
    }

    // petit astérisque à six branches, arrondi
    component Etincelle: Item {
        property int size: 18
        implicitWidth: size; implicitHeight: size
        Repeater {
            model: 3
            Rectangle {
                required property int index
                anchors.centerIn: parent
                width: parent.size; height: parent.size / 5; radius: height / 2
                rotation: index * 60
                color: "black"
            }
        }
    }
}
