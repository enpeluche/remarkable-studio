"""Ajouter des traits dans le fichier d'une page (.rm v6), sans la tablette et sans stylet.

Règle de sûreté : le fichier d'origine n'est jamais réécrit. Ses octets sont gardés tels quels (rmscene ne
réécrit pas fidèlement les blocs qu'il ne connaît pas, types 14 et 15 de la 3.30) et les nouveaux traits sont
AJOUTÉS à la fin, comme des blocs « trait » ordinaires :
  - parent : le calque où sont les traits (le premier calque par défaut) ;
  - identifiant : auteur de la tablette, compteur au-delà du plus grand identifiant du fichier ;
  - chaînage : à la suite du dernier élément du calque (left_id), fin de séquence (right_id = 0:0).
Le résultat est relu et vérifié (tous les traits d'origine + les nouveaux) avant d'être rendu.

À n'utiliser que document FERMÉ sur la tablette : xochitl relit le fichier à l'ouverture ; ouvert, il
garde la page en mémoire et réécrirait le fichier sans nos traits.
"""
import io
import struct

from rmscene import read_blocks, read_tree, write_blocks, CrdtId, LwwValue
from rmscene import scene_items as si
from rmscene.scene_stream import (SceneLineItemBlock, AuthorIdsBlock, MigrationInfoBlock, PageInfoBlock,
                                  SceneTreeBlock, TreeNodeBlock, SceneGroupItemBlock)
from rmscene.crdt_sequence import CrdtSequenceItem

HEADER = 43


def _block_spans(raw):
    """(début, type, longueur) de chaque bloc : sert à vérifier que le fichier est complet."""
    pos, out = HEADER, []
    while pos < len(raw):
        ln, _, _, _, typ = struct.unpack_from("<IBBBB", raw, pos)
        out.append((pos, typ, ln))
        pos += 8 + ln
    if pos != len(raw):
        raise ValueError("fichier .rm tronqué ou inattendu")
    return out


def _layer_and_ids(raw):
    blocks = list(read_blocks(io.BytesIO(raw)))
    ids = [b.item.item_id for b in blocks if hasattr(b, "item") and isinstance(getattr(b.item, "item_id", None), CrdtId)]
    for b in blocks:
        for name in ("tree_id", "node_id", "parent_id"):
            v = getattr(b, name, None)
            if isinstance(v, CrdtId):
                ids.append(v)
    authors = sorted({i.part1 for i in ids if i.part1 > 0}) or [1]
    tree = read_tree(io.BytesIO(raw))
    layers = [c for c in tree.root.children.values() if isinstance(c, si.Group)]
    return blocks, ids, authors, tree, layers


def author_of(raw):
    """Identifiant d'auteur (UUID) de la tablette dans un fichier de page existant."""
    for b in read_blocks(io.BytesIO(raw)):
        if isinstance(b, AuthorIdsBlock) and b.author_uuids:
            return b.author_uuids[min(b.author_uuids)]
    return None


def new_page(author_uuid):
    """Fichier de page vierge, sur le modèle de ceux de la tablette : un auteur, la racine (0:1), un calque
    « Layer 1 » (0:11) rattaché à la racine (0:13)."""
    blocks = [
        AuthorIdsBlock(author_uuids={1: author_uuid}),
        MigrationInfoBlock(migration_id=CrdtId(1, 1), is_device=True),
        PageInfoBlock(loads_count=1, merges_count=0, text_chars_count=0, text_lines_count=0),
        SceneTreeBlock(tree_id=CrdtId(0, 11), node_id=CrdtId(0, 0), is_update=True, parent_id=CrdtId(0, 1)),
        TreeNodeBlock(si.Group(node_id=CrdtId(0, 1))),
        TreeNodeBlock(si.Group(node_id=CrdtId(0, 11), label=LwwValue(timestamp=CrdtId(0, 12), value="Layer 1"))),
        SceneGroupItemBlock(parent_id=CrdtId(0, 1), item=CrdtSequenceItem(
            item_id=CrdtId(0, 13), left_id=CrdtId(0, 0), right_id=CrdtId(0, 0), deleted_length=0, value=CrdtId(0, 11))),
    ]
    buf = io.BytesIO()
    write_blocks(buf, blocks)
    return buf.getvalue()


def add_lines(raw, lines, layer_index=0):
    """raw : octets du .rm ; lines : [{"tool": si.Pen, "color": si.PenColor, "thickness": float,
    "points": [(x, y, width)], "rgba": (r, g, b, a) facultatif}] en unités de page.
    -> (nouveaux octets, identifiants ajoutés)."""
    if raw[:HEADER] != b"reMarkable .lines file, version=6          ":
        raise ValueError("format .rm v6 attendu")
    _block_spans(raw)
    blocks, ids, authors, tree, layers = _layer_and_ids(raw)
    if not layers:
        raise ValueError("aucun calque dans la page")
    layer = layers[min(layer_index, len(layers) - 1)]
    group_id = layer.node_id
    keys = list(layer.children.keys())
    left = keys[-1] if keys else CrdtId(0, 0)
    author = authors[0]
    counter = max(i.part2 for i in ids) + 1
    new_blocks, added = [], []
    for ln in lines:
        pts = [si.Point(x=float(x), y=float(y), speed=0, direction=0, width=int(round(w)), pressure=100)
               for x, y, w in ln["points"]]
        line = si.Line(color=ln["color"], tool=ln["tool"], points=pts, thickness_scale=float(ln["thickness"]),
                       starting_length=0.0)
        if ln.get("rgba"):
            line.color_rgba = tuple(ln["rgba"])
        iid = CrdtId(author, counter)
        counter += 1
        new_blocks.append(SceneLineItemBlock(parent_id=group_id, item=CrdtSequenceItem(
            item_id=iid, left_id=left, right_id=CrdtId(0, 0), deleted_length=0, value=line)))
        left = iid
        added.append(iid)
    buf = io.BytesIO()
    write_blocks(buf, new_blocks)
    tail = buf.getvalue()[HEADER:]                 # nouveaux blocs seuls (sans l'en-tête)
    out = raw + tail
    # vérification : tout se relit, les traits d'origine sont là, les nouveaux aussi, dans le bon calque
    _block_spans(out)
    check = read_tree(io.BytesIO(out))
    grp = next(c for c in check.root.children.values() if isinstance(c, si.Group) and c.node_id == group_id)
    got = list(grp.children.keys())
    if got[:len(keys)] != keys or got[len(keys):] != added:
        raise ValueError("vérification après écriture : ordre des éléments inattendu")
    return out, added
