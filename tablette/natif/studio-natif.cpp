/* Extension xovi « studio-natif » — créer des traits sans stylet (xochitl 3.30).

   Expose au QML un objet unique « StudioNatif » (module net.studio.Natif 1.0) :
     StudioNatif.disponible()                        -> "" si utilisable, sinon la raison
     StudioNatif.ajouterTrait(controleur, tuiles, outil, couleur, argb, epaisseur, points, accroche)
        points : [[x, y, largeur, pression], ...] en unités de page ; accroche : -1 = addDrawingLine (trait
        ordinaire), sinon highlightWithLine(trait, accroche) avec SceneController.SnapEnabled / SnapDisabled
        (surlignage, accroché au texte ou non)  -> "" si fait, sinon la raison
     StudioNatif.effacer(controleur, outil, epaisseur, points, imageErasing)
        gomme le long d'un trait (outil 6 : gomme, 8 : gomme de zone), comme la gomme du stylet :
        eraseWithLine(trait, SceneController.ImageErasingEnabled / Disabled)  -> "" si fait, sinon la raison

   Aucune adresse codée en dur pour les appels : les méthodes addDrawingLine(Line), highlightWithLine(Line, …) et
   renderLineToTiles(Line) sont trouvées par leur nom dans le système de méthodes de Qt (métaobjets). La seule
   dépendance est la disposition en mémoire de « Line » (72 octets, docs/EXTENSION-NATIVE.md), contrôlée au
   chargement (taille du type) et par la signature de la 3.30.0.111.
*/
#include <QObject>
#include <QList>
#include <QMetaMethod>
#include <QMetaType>
#include <QVariant>
#include <QQmlEngine>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <link.h>
#include <unistd.h>

// ---------------------------------------------------------------- disposition de Line (xochitl 3.30)
#pragma pack(push, 1)
struct RmPoint {                    // 14 octets, comme dans les fichiers .rm
    float x, y;
    quint16 speed, width;
    quint8 direction, pressure;
};
#pragma pack(pop)
static_assert(sizeof(RmPoint) == 14, "point : 14 octets");

struct alignas(8) RmLine {
    qint32 tool;                    // 0x00
    qint32 color;                   // 0x04  (9 = couleur libre)
    quint32 argb;                   // 0x08
    QList<RmPoint> points;          // 0x0c  (d, ptr, size : 12 octets en 32 bits)
    double thickness;               // 0x18
    float startingLength;           // 0x20
    quint32 pad;                    // 0x24
    double rect[4];                 // 0x28  cache du rectangle englobant : vide = recalculé
};
static_assert(sizeof(void *) == 4, "ARM 32 bits");
static_assert(offsetof(RmLine, points) == 0x0c && offsetof(RmLine, thickness) == 0x18, "disposition");
static_assert(offsetof(RmLine, startingLength) == 0x20 && offsetof(RmLine, rect) == 0x28, "disposition");
static_assert(sizeof(RmLine) == 72, "Line : 72 octets");

// ---------------------------------------------------------------- garde-fou de version
#define ADD_DRAWING_LINE 0x648000u
#define SCENECTRL_STRS 0x11f33ccu
static const unsigned char SIG_ADD[16] = {0xf0, 0x4f, 0x2d, 0xe9, 0x00, 0x40, 0xa0, 0xe1,
                                          0x00, 0x53, 0x9f, 0xe5, 0x7c, 0xd0, 0x4d, 0xe2};
static unsigned long g_base = 0, g_text_end = 0;

// programme principal : adresse de chargement et fin de son premier segment chargé (code et données en lecture)
static int find_main(struct dl_phdr_info *info, size_t, void *) {
    if (info->dlpi_name != nullptr && info->dlpi_name[0] != 0) return 0;
    g_base = info->dlpi_addr;
    for (int i = 0; i < info->dlpi_phnum; i++)
        if (info->dlpi_phdr[i].p_type == PT_LOAD && info->dlpi_phdr[i].p_vaddr == 0) g_text_end = info->dlpi_phdr[i].p_memsz;
    return 1;
}
static bool bon_programme() {
    // 1) le programme s'appelle xochitl ; 2) les adresses lues sont DANS son segment (jamais de lecture hors zone)
    char exe[256] = {0};
    const ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0 || std::strstr(exe, "xochitl") == nullptr) return false;
    dl_iterate_phdr(find_main, nullptr);
    if (!g_base || g_text_end < SCENECTRL_STRS + 2912 + 16 || g_text_end < ADD_DRAWING_LINE + sizeof SIG_ADD) return false;
    if (std::memcmp(reinterpret_cast<const void *>(g_base + ADD_DRAWING_LINE), SIG_ADD, sizeof SIG_ADD) != 0) return false;
    return std::memcmp(reinterpret_cast<const void *>(g_base + SCENECTRL_STRS + 2912), "SceneController", 16) == 0;
}

// ---------------------------------------------------------------- objet exposé au QML
class StudioNatif : public QObject {
    Q_OBJECT
    QString remplir(RmLine &line, QObject *controleur, int outil, int couleur, uint argb, double epaisseur,
                    const QVariantList &points) const;
public:
    using QObject::QObject;

    Q_INVOKABLE QString disponible() const {
        QMetaType t = QMetaType::fromName("Line");
        if (!t.isValid()) return QStringLiteral("type Line inconnu");
        if (t.sizeOf() != int(sizeof(RmLine))) return QStringLiteral("type Line de %1 octets (72 attendus)").arg(t.sizeOf());
        return QString();
    }

    Q_INVOKABLE QString effacer(QObject *controleur, int outil, double epaisseur, const QVariantList &points,
                                int imageErasing) {
        if (outil != 6 && outil != 8) return QStringLiteral("outil de gomme attendu (6 ou 8)");
        RmLine line{};
        QString err = remplir(line, controleur, outil, 0, 0xFF000000u, epaisseur, points);
        if (!err.isEmpty()) return err;
        const int idx = controleur->metaObject()->indexOfMethod("eraseWithLine(Line,ImageErasing)");
        if (idx < 0) return QStringLiteral("méthode eraseWithLine introuvable");
        void *argv[] = {nullptr, &line, &imageErasing};
        QMetaObject::metacall(controleur, QMetaObject::InvokeMetaMethod, idx, argv);
        return QString();
    }

    Q_INVOKABLE QString ajouterTrait(QObject *controleur, QObject *tuiles, int outil, int couleur, uint argb,
                                     double epaisseur, const QVariantList &points, int accroche) {
        const bool surligner = accroche >= 0;
        RmLine line{};                                   // tout à zéro, liste Qt vide valide (compteur de références)
        const QString err = remplir(line, controleur, outil, couleur, argb, epaisseur, points);
        if (!err.isEmpty()) return err;
        const QMetaObject *mo = controleur->metaObject();
        const int idx = surligner ? mo->indexOfMethod("highlightWithLine(Line,SceneController::LineSnapMode)")
                                  : mo->indexOfMethod("addDrawingLine(Line)");
        if (idx < 0) return QStringLiteral("méthode introuvable");
        // appel par le système de méthodes : argv[0] = retour (void), argv[1] = &line (Line const&)
        void *argv[] = {nullptr, &line, &accroche};
        QMetaObject::metacall(controleur, QMetaObject::InvokeMetaMethod, idx, argv);
        if (tuiles && !surligner) {
            const int r = tuiles->metaObject()->indexOfMethod("renderLineToTiles(Line)");
            void *argv2[] = {nullptr, &line};
            if (r >= 0) QMetaObject::metacall(tuiles, QMetaObject::InvokeMetaMethod, r, argv2);
        }
        return QString();                                // ~RmLine : notre référence à la liste ; le document garde la sienne
    }
};

// remplissage commun d'un trait : contrôles, style, points [[x, y, largeur, pression], ...]
QString StudioNatif::remplir(RmLine &line, QObject *controleur, int outil, int couleur, uint argb, double epaisseur,
                             const QVariantList &points) const {
    const QString d = disponible();
    if (!d.isEmpty()) return d;
    if (!controleur) return QStringLiteral("contrôleur absent");
    if (qstrcmp(controleur->metaObject()->className(), "SceneController") != 0)
        return QStringLiteral("ce n'est pas un SceneController");
    if (points.size() < 2 || points.size() > 20000) return QStringLiteral("nombre de points invalide");
    line.tool = outil;
    line.color = couleur;
    line.argb = argb;
    line.thickness = epaisseur;
    line.points.reserve(points.size());
    for (const QVariant &v : points) {
        const QVariantList p = v.toList();
        if (p.size() < 2) return QStringLiteral("point invalide");
        RmPoint q{};
        q.x = float(p.value(0).toDouble());
        q.y = float(p.value(1).toDouble());
        q.width = quint16(qBound(0, p.value(2, 12).toInt(), 65535));
        q.pressure = quint8(qBound(0, p.value(3, 100).toInt(), 255));
        line.points.append(q);
    }
    return QString();
}

static StudioNatif *g_instance = nullptr;

extern "C" char _xovi_shouldLoad() {
    if (dlsym(RTLD_DEFAULT, "_Z21qRegisterResourceDataiPKhS0_S0_") == nullptr) return 0;
    if (!bon_programme()) {
        std::fprintf(stderr, "[studio-natif] version de xochitl non reconnue : extension NON chargée\n");
        return 0;
    }
    return 1;
}

extern "C" void _xovi_construct() {
    g_instance = new StudioNatif();
    qmlRegisterSingletonInstance("net.studio.Natif", 1, 0, "StudioNatif", g_instance);
    std::fprintf(stderr, "[studio-natif] chargée (base 0x%lx) : StudioNatif disponible pour le QML\n", g_base);
}

extern "C" __attribute__((section(".xovi_info"))) const int EXTENSIONVERSION = 0x00000100;
__attribute__((section(".xovi"))) const char *LINKTABLENAMES = "Ephony\0\0";
__attribute__((section(".xovi"))) const void *LINKTABLEVALUES[] = {(void *) 1, (void *) 0};

#include "studio-natif.moc"
