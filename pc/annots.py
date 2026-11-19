"""Recherche dans le texte d'un document et liste de ses annotations (surlignages, notes manuscrites).

Recherche : insensible à la casse et aux accents, sur le texte du PDF extrait une fois pour tout le document.
Annotations, par page :
  - surlignages natifs de la tablette (surligneur « accroché au texte ») : leur texte est enregistré tel quel ;
  - traits de surligneur (dont ceux posés depuis le Studio) : texte retrouvé en croisant le trait avec les mots ;
  - notes manuscrites : nombre de traits de la page.
Toutes les positions sont en unités de page de la tablette (comme le Studio).
"""
import io
import json
import math
import unicodedata

from rmscene import read_tree
from rmscene import scene_items as si
from rmc.exporters import svg as rsvg

HL_COLORS = {3: "#fbf719", 4: "#7cf27c", 5: "#ffb6c8", 6: "#8fa6ff", 7: "#ff8f8a",
             9: "#fbf719", 10: "#a1d87d", 11: "#8bd0e5", 12: "#b782cd", 13: "#f7e851"}
HL_TOOLS = {si.Pen.HIGHLIGHTER_1.value, si.Pen.HIGHLIGHTER_2.value}
NOT_INK = HL_TOOLS | {si.Pen.ERASER.value, si.Pen.ERASER_AREA.value}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def search(lib, renderer, uid, query, limit=500):
    item = lib.snapshot().get(uid)
    q = " ".join(norm(query).split())
    if not item or len(q) < 2:
        return []
    results = []
    for n, page in enumerate(item["pages"]):
        if page["redir"] is None:
            continue
        lines = renderer.text_lines(uid, page["redir"])
        if not lines:
            continue
        # texte de la page : mots séparés par une espace, avec la position de chaque mot
        text, spans = [], []
        pos = 0
        for li, line in enumerate(lines):
            for wi, w in enumerate(line):
                t = norm(w[4])
                spans.append((pos, pos + len(t), li, wi))
                text.append(t)
                pos += len(t) + 1
        full = " ".join(text)
        start = full.find(q)
        while start >= 0 and len(results) < limit:
            end = start + len(q)
            hit = [(li, wi) for a, b, li, wi in spans if a < end and b > start]
            rects = {}
            for li, wi in hit:
                x, y, w, h = lines[li][wi][:4]
                r = rects.get(li)
                rects[li] = [x, y, x + w, y + h] if not r else [min(r[0], x), min(r[1], y), max(r[2], x + w), max(r[3], y + h)]
            li0, wi0 = hit[0]
            flat = [(li, wi) for li, line in enumerate(lines) for wi in range(len(line))]
            k = flat.index((li0, wi0))
            ctx = " ".join(lines[a][b][4] for a, b in flat[max(0, k - 6):k + len(hit) + 6])
            results.append({"page": n, "rects": [[r[0], r[1], r[2] - r[0], r[3] - r[1]] for r in rects.values()],
                            "snippet": ctx})
            start = full.find(q, start + 1)
        if len(results) >= limit:
            break
    return results


def _color(obj, default="#fbf719"):
    rgba = getattr(obj, "color_rgba", None)
    if rgba:
        return "#%02x%02x%02x" % tuple(rgba[:3])
    return HL_COLORS.get(getattr(obj.color, "value", 3), default)


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def page_annotations(rm_bytes, lines, page_id=""):
    """Annotations d'une page (.rm v6) ; lines = mots du PDF de la page, ou fonction qui les fournit
    (appelée seulement si la page contient un trait de surligneur : l'extraction du texte coûte)."""
    tree = read_tree(io.BytesIO(rm_bytes))
    anchors = rsvg.build_anchor_pos(tree.root_text)
    out, ink = [], 0
    cache = {}

    def get_words():
        if "w" not in cache:
            ls = lines() if callable(lines) else lines
            cache["w"] = [(li, wi, w) for li, line in enumerate(ls or []) for wi, w in enumerate(line)]
        return cache["w"]

    def walk(item, dx, dy):
        nonlocal ink
        ax, ay = rsvg.get_anchor(item, anchors)
        dx, dy = dx + ax, dy + ay
        for cid in item.children.keys():
            child = item.children[cid]
            key = f"{page_id}/{cid.part1}:{cid.part2}"        # identifiant stable (CRDT) du surlignage
            if isinstance(child, si.Group):
                walk(child, dx, dy)
            elif isinstance(child, si.GlyphRange):
                rs = child.rectangles or []
                out.append({"kind": "native", "key": key, "color": _color(child), "text": (child.text or "").strip(),
                            "rects": [[r.x + dx, r.y + dy, r.w, r.h] for r in rs],
                            "quads": [[r.x + dx, r.y + dy, r.w, r.h] for r in rs],
                            "y": min((r.y + dy for r in rs), default=0)})
            elif isinstance(child, si.Line):
                tool = child.tool.value
                if tool not in HL_TOOLS:
                    if tool not in NOT_INK:
                        ink += 1
                    continue
                pts = [(p.x + dx, p.y + dy) for p in child.points]
                if not pts:
                    continue
                # demi-épaisseur réelle du trait (largeur des points = 4 x unités de page, mesuré)
                half = max(p.width for p in child.points) / 8
                step = max(1, len(pts) // 40)
                pts = pts[::step] + [pts[-1]]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                hit = []
                for li, wi, w in get_words():
                    cx, cy = w[0] + w[2] / 2, w[1] + w[3] / 2
                    if cx < min(xs) - 4 or cx > max(xs) + 4:
                        continue
                    tol = max(half, w[3] * 0.5, 10)
                    if cy < min(ys) - tol - 4 or cy > max(ys) + tol + 4:
                        continue
                    d = min(_seg_dist(cx, cy, *pts[i], *pts[i + 1]) for i in range(len(pts) - 1)) if len(pts) > 1 \
                        else math.hypot(cx - pts[0][0], cy - pts[0][1])
                    if d <= tol:
                        hit.append((li, wi, w))
                hit.sort(key=lambda h: (h[0], h[1]))
                # zones par ligne de texte (mots couverts) : surlignage PDF standard à l'export
                quads = {}
                for li, wi, w in hit:
                    q = quads.get(li)
                    quads[li] = [w[0], w[1], w[0] + w[2], w[1] + w[3]] if not q else \
                        [min(q[0], w[0]), min(q[1], w[1]), max(q[2], w[0] + w[2]), max(q[3], w[1] + w[3])]
                band = [min(xs), min(ys) - half, max(xs) - min(xs), max(ys) - min(ys) + 2 * half]
                out.append({"kind": "highlight", "key": key, "color": _color(child), "text": " ".join(h[2][4] for h in hit),
                            "rects": [band],
                            "quads": [[q[0], q[1], q[2] - q[0], q[3] - q[1]] for q in quads.values()] or [band],
                            "y": min(ys)})
    walk(tree.root, 0, 0)
    out.sort(key=lambda a: a["y"])
    return out, ink


def document_annotations(lib, renderer, uid, with_bounds=False, cached_only=False, missing=None):
    """cached_only : n'analyse aucune page (recherche instantanée) ; les pages pas encore analysées sont
    comptées dans missing (liste à un élément) et seront traitées par le préchauffage."""
    item = lib.snapshot().get(uid)
    if not item:
        return None
    res = []
    for n, page in enumerate(item["pages"]):
        rm = lib.root / uid / f"{page['id']}.rm" if page["id"] else None
        if not rm or not rm.exists():
            continue
        key = renderer.cache / f"{uid}-{page['id']}-annots2-{int(rm.stat().st_mtime)}.json"
        if key.exists():
            entry = json.loads(key.read_text())
        elif cached_only:
            if missing is not None:
                missing[0] += 1
            continue
        else:
            data = rm.read_bytes()
            entry = {"items": [], "ink": 0}
            if b"version=6" in data[:43]:          # ancien format ou fichier illisible : mis en cache comme vide
                redir = page["redir"]
                lines = (lambda: renderer.text_lines(uid, redir)) if redir is not None and item["type"] == "pdf" else None
                try:
                    items, ink = page_annotations(data, lines, page["id"])
                    entry = {"items": items, "ink": ink}
                except Exception:
                    pass
            for old in renderer.cache.glob(f"{uid}-{page['id']}-annots*.json"):
                old.unlink(missing_ok=True)
            key.write_text(json.dumps(entry, ensure_ascii=False))
        if entry["items"] or entry["ink"]:
            # dimensions d'affichage (rendu de la page : coûteux) seulement pour le Studio
            res.append({"page": n, "bounds": renderer.page_bounds(uid, n) if with_bounds else None, **entry})
    return res


def search_highlights(lib, renderer, query, limit=300):
    """Surlignages de TOUS les documents dont le texte contient la requête (sans casse ni accents)."""
    q = " ".join(norm(query).split())
    res = []
    missing = [0]
    if len(q) < 2:
        return res, 0
    for uid, it in list(lib.snapshot().items()):
        if it["type"] == "folder" or it.get("parent") == "trash":
            continue
        before = missing[0]
        try:
            pages = document_annotations(lib, renderer, uid, cached_only=True, missing=missing) or []
        except Exception:
            continue
        notes = doc_notes(uid)
        keys = set()
        for p in pages:
            for a in p["items"]:
                keys.add(a.get("key"))
                note = (notes.get(a.get("key")) or {}).get("note", "")
                if (a.get("text") and q in norm(a["text"])) or (note and q in norm(note)):
                    res.append({"doc": uid, "name": it["name"], "page": p["page"], "text": a["text"],
                                "color": a["color"], "note": note})
                    if len(res) >= limit:
                        return res, missing[0]
        # commentaires dont le surlignage a été supprimé sur la tablette : toujours trouvables (analyse complète
        # du document seulement, sinon un surlignage pas encore analysé passerait pour supprimé)
        if missing[0] == before:
            for k, n in notes.items():
                if k not in keys and (q in norm(n.get("text") or "") or q in norm(n.get("note") or "")):
                    res.append({"doc": uid, "name": it["name"], "page": n.get("page") or 0, "text": n.get("text") or "",
                                "color": "transparent", "note": n.get("note", ""), "supprime": True})
    return res, missing[0]


def warm_up(lib, renderer):
    """Analyse en arrière-plan de toutes les pages annotées (cache), pour des recherches instantanées."""
    import time as _t
    for uid in list(lib.snapshot().keys()):
        try:
            document_annotations(lib, renderer, uid)
        except Exception:
            pass
        _t.sleep(0.01)


# ---------------------------------------------------------------- notes (sur le PC seulement)
from pathlib import Path as _Path
import threading as _threading

NOTES_FILE = _Path(__file__).resolve().parent / "notes.json"
_notes_lock = _threading.Lock()


def load_notes():
    try:
        return json.loads(NOTES_FILE.read_text())
    except Exception:
        return {}


def doc_notes(uid):
    return load_notes().get(uid, {})


def set_note(uid, key, note, text="", page=None):
    """Commentaire d'un surlignage (vide : supprimé). Stocké sur le PC, jamais sur la tablette."""
    import time as _t
    with _notes_lock:
        allnotes = load_notes()
        d = allnotes.setdefault(uid, {})
        note = (note or "").strip()
        if note:
            d[key] = {"note": note, "text": text, "page": page, "updated": int(_t.time())}
        else:
            d.pop(key, None)
        if not d:
            allnotes.pop(uid, None)
        tmp = NOTES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(allnotes, ensure_ascii=False, indent=1))
        tmp.replace(NOTES_FILE)
    return d.get(key)
