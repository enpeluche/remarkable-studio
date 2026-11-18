#!/bin/busybox sh
# Trace sur la tablette les traits décrits dans $1 (voir trace.awk), puis supprime le fichier.
# Un seul tracé à la fois (verrou). busybox sh : le printf de bash découpe les écritures (refusées par le noyau).
F="$1"
L=/tmp/formes-trace.lock
[ -f "$F" ] || exit 1
if ! mkdir "$L" 2>/dev/null; then exit 2; fi
trap 'rmdir "$L"' EXIT
awk -f /home/root/xovi/formes/trace.awk "$F" | {
    exec 3>/dev/input/event1
    while IFS= read -r l; do
        case "$l" in
            S*) usleep "${l#S}" ;;
            *) printf "$l" >&3 ;;
        esac
    done
}
rm -f "$F"
