/* Extension xovi « studio-natif » — étape 1 : extension vide (validation de la chaîne de compilation).

   Ne fait RIEN d'autre que vérifier qu'elle est dans le bon programme et l'écrire dans le journal :
     - refuse de se charger hors de xochitl (programme sans interface Qt) ;
     - refuse de se charger si les octets du programme aux adresses utilisées ne sont pas exactement ceux de
       xochitl 3.30.0.111 (début de SceneController::addDrawingLine, table de chaînes de SceneController) :
       toute autre version est ignorée, sans risque.
   Adresses : voir docs/EXTENSION-NATIVE.md (outils/analyse_moc.py). Compilation : tablette/natif/build.sh.
*/
#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdio.h>
#include <string.h>

#define ADD_DRAWING_LINE 0x648000u   /* SceneController::addDrawingLine(const Line&), xochitl 3.30.0.111 */
#define SCENECTRL_STRS   0x11f33ccu  /* table de chaînes moc de SceneController */

static const unsigned char SIG_ADD[16] = {0xf0, 0x4f, 0x2d, 0xe9, 0x00, 0x40, 0xa0, 0xe1,
                                          0x00, 0x53, 0x9f, 0xe5, 0x7c, 0xd0, 0x4d, 0xe2};
static unsigned long base_addr = 0;

static int find_main(struct dl_phdr_info *info, size_t size, void *data) {
    (void) size; (void) data;
    if (info->dlpi_name == NULL || info->dlpi_name[0] == 0) {   /* le programme principal */
        base_addr = (unsigned long) info->dlpi_addr;
        return 1;
    }
    return 0;
}

static int bon_programme(void) {
    dl_iterate_phdr(find_main, NULL);
    if (!base_addr) return 0;
    if (memcmp((const void *) (base_addr + ADD_DRAWING_LINE), SIG_ADD, sizeof SIG_ADD) != 0) return 0;
    /* la table de chaînes contient « SceneController » à son décalage 2912 */
    return memcmp((const void *) (base_addr + SCENECTRL_STRS + 2912), "SceneController", 16) == 0;
}

char _xovi_shouldLoad(void) {
    if (dlsym(RTLD_DEFAULT, "_Z21qRegisterResourceDataiPKhS0_S0_") == NULL) return 0;   /* pas une appli Qt */
    if (!bon_programme()) {
        fprintf(stderr, "[studio-natif] version de xochitl non reconnue : extension NON chargée\n");
        return 0;
    }
    return 1;
}

void _xovi_construct(void) {
    fprintf(stderr, "[studio-natif] chargée (base 0x%lx), addDrawingLine reconnue — étape 1, aucune action\n",
            base_addr);
}

__attribute__((section(".xovi_info"))) const int EXTENSIONVERSION = 0x00000100;
__attribute__((section(".xovi"))) const char *LINKTABLENAMES = "Ephony\0\0";
__attribute__((section(".xovi"))) const void *LINKTABLEVALUES[] = { (void *) 1, (void *) 0 };
