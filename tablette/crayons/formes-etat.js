.pragma library
// État partagé par toutes les vues (pages) : gabarits de traits, par type et par style de crayon.
//   gabarits["line|<style>"]   = { items, size }   size = longueur de la droite (unités de page)
//   gabarits["circle|<style>"] = { items, size }   size = diamètre du cercle (axe du trait)
var gabarits = {};
// Dernière couleur libre (ARGB) de chaque outil de crayon : remise quand la barre d'outils re-sélectionne
// l'outil (sa mémoire C++ ne connaît que les couleurs officielles et repasse au noir).
var couleursLibres = {};
