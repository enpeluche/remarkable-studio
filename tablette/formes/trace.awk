# Transforme une description de traits en événements de stylet (input_event 16 octets, échappés en octal)
# pour la boucle de trace.sh. Entrée (pixels écran portrait 1404 x 1872) :
#   B <maintien_ms>     début d'un trait (maintien > 0 : la tablette redresse la forme, geste natif)
#   P <x> <y>           point
#   E                   fin du trait
# Sortie : lignes d'octets échappés, et "S<µs>" = pause.
function le(v, n,   s, i) { s = ""; for (i = 0; i < n; i++) { s = s sprintf("\\%03o", v % 256); v = int(v / 256) } return s }
function ev(t, c, v) { return Z le(t, 2) le(c, 2) le(v, 4) }
function pos(sx, sy) { return ev(3, 0, int((1 - sy / 1872) * 20966 + 0.5)) ev(3, 1, int(sx / 1404 * 15725 + 0.5)) }
BEGIN {
    Z = le(0, 8); SYN = ev(0, 0, 0); P = 2457; srand(42)
    # amorçage : le stylet virtuel s'approche puis s'éloigne sans toucher (le tout premier trait
    # injecté n'est sinon pas toujours pris en compte par le geste)
    print ev(1, 320, 1) pos(700, 936) ev(3, 25, 60) SYN; print "S60000"
    print ev(3, 25, 255) ev(1, 320, 0) SYN; print "S150000"
}
$1 == "B" { hold = $2 + 0; first = 1; next }
$1 == "P" {
    lx = $2; ly = $3
    if (first) {
        print ev(1, 320, 1) pos(lx, ly) ev(3, 25, 10) ev(3, 24, 0) SYN; print "S30000"
        print ev(3, 25, 0) ev(3, 24, P) ev(1, 330, 1) SYN; print "S7000"
        for (i = 0; i < 4; i++) { print pos(lx, ly) ev(3, 24, P) SYN; print "S7000" }
        first = 0
    } else { print pos(lx, ly) ev(3, 24, P) SYN; print "S7000" }
    next
}
$1 == "E" {
    for (i = 0; i < 4; i++) { print pos(lx, ly) ev(3, 24, P) SYN; print "S7000" }
    if (hold > 0) {
        X = int((1 - ly / 1872) * 20966 + 0.5); Y = int(lx / 1404 * 15725 + 0.5)
        for (i = 0; i < hold / 5; i++) {
            s = ""
            for (k = 0; k < 3; k++) {
                pr = P + (4095 - P) * (i < 20 ? i / 20 : 1); pr = int(pr) - int(rand() * 4)
                s = s ev(3, 0, X + int(rand() * 17) - 8) ev(3, 1, Y + int(rand() * 17) - 8) ev(3, 24, pr) ev(3, 26, 300) ev(3, 27, 1400) SYN
            }
            print s; print "S5000"
        }
    }
    print ev(3, 24, 0) ev(1, 330, 0) SYN; print "S20000"
    print ev(3, 25, 255) ev(1, 320, 0) SYN; print "S" (hold > 0 ? 250000 : 40000)
    next
}
