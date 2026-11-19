"""Export PDF d'un document de la tablette, annotations comprises, en vectoriel.

- Page du PDF sans annotation : recopiée telle quelle (texte, liens, polices : rien ne change).
- Page annotée : la page d'origine, avec l'encre posée par-dessus en vectoriel (traits, surlignages, texte
  tapé) ; si l'encre déborde de la page (marges), la page est agrandie pour tout garder.
- Page de notes insérée, carnet : page blanche au format de la tablette, avec l'encre.
Repère : le PDF est placé à 227 dpi sur la tablette, centré en x = 0, haut en y = 0 (format v6).
"""
import io
from pathlib import Path

import cairosvg
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
                           NumberObject, TextStringObject)

import annots

import server as rv

K = 72 / 227          # unités de page de la tablette -> points PDF


def _overlay(ann, b, w_pt, h_pt):
    """Annotations (fragment SVG, coordonnées = unités de page x SCALE) -> page PDF vectorielle."""
    S = rv.SCALE
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_pt:.3f}pt" height="{h_pt:.3f}pt" '
           f'viewBox="{b.x0 * S:.3f} {b.y0 * S:.3f} {(b.x1 - b.x0) * S:.3f} {(b.y1 - b.y0) * S:.3f}">{ann}</svg>')
    return PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0]


def _hex_rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _highlight(writer, quads_pt, color, text, note=""):
    """Annotation PDF /Highlight standard (texte dans /Contents) avec son propre rendu (multiplication) :
    reconnue comme surlignage par Zotero, Acrobat, Firefox…"""
    xs = [q[0] for q in quads_pt] + [q[2] for q in quads_pt]
    ys = [q[1] for q in quads_pt] + [q[3] for q in quads_pt]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    r, g, b = _hex_rgb(color)
    qp = []
    for a, bb, c, d in quads_pt:                       # haut-gauche, haut-droite, bas-gauche, bas-droite
        qp += [a, d, c, d, a, bb, c, bb]
    ops = [f"/GS0 gs {r:.3f} {g:.3f} {b:.3f} rg"]
    ops += [f"{a - x0:.2f} {bb - y0:.2f} {c - a:.2f} {d - bb:.2f} re f" for a, bb, c, d in quads_pt]
    ap = DecodedStreamObject()
    ap.set_data("\n".join(ops).encode())
    ap.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
               NameObject("/BBox"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(x1 - x0), FloatObject(y1 - y0)]),
               NameObject("/Resources"): DictionaryObject({NameObject("/ExtGState"): DictionaryObject({
                   NameObject("/GS0"): DictionaryObject({NameObject("/BM"): NameObject("/Multiply"),
                                                         NameObject("/ca"): FloatObject(0.6)})})})})
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Highlight"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (x0, y0, x1, y1)]),
        NameObject("/QuadPoints"): ArrayObject([FloatObject(round(v, 2)) for v in qp]),
        NameObject("/C"): ArrayObject([FloatObject(round(v, 3)) for v in (r, g, b)]),
        NameObject("/CA"): FloatObject(1), NameObject("/F"): NumberObject(4),
        # /Contents = commentaire (Zotero l'importe comme commentaire ; il relit lui-même le texte surligné)
        NameObject("/Contents"): TextStringObject(note or ""),
        NameObject("/T"): TextStringObject("reMarkable"),
        NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(ap)}),
    })
    return writer._add_object(annot)


def export(lib, uid, only_annotated=False, renderer=None):
    item = lib.snapshot().get(uid)
    if not item:
        raise KeyError(uid)
    pdf_path = lib.root / f"{uid}.pdf"
    reader = PdfReader(str(pdf_path)) if item["type"] == "pdf" and pdf_path.exists() else None
    writer = PdfWriter()
    notes = annots.doc_notes(uid)
    for page in item["pages"]:
        rm = lib.root / uid / f"{page['id']}.rm" if page["id"] else None
        has_ink = bool(rm and rm.exists())
        if only_annotated and not has_ink:
            continue
        orig = None
        if reader is not None and page["redir"] is not None and page["redir"] < len(reader.pages):
            orig = reader.pages[page["redir"]]
            if rm and rm.exists() and b"version=6" not in rm.read_bytes()[:43]:
                pass                                   # ancien format (v5) : placement différent, page seule
        b = rv.Bounds(item.get("landscape", False))
        if orig is not None:
            if orig.rotation:
                orig.transfer_rotation_to_content()
            w0, h0 = float(orig.mediabox.width), float(orig.mediabox.height)
            iw, ih = w0 / K, h0 / K
            b.x0, b.x1, b.y0, b.y1 = -iw / 2, iw / 2, 0, ih
        page_box = (b.x0, b.x1, b.y0, b.y1)
        # surlignages -> vraies annotations PDF (avec leur texte), plus dessinés comme des traits
        hls = []
        if has_ink and orig is not None and renderer is not None:
            data = rm.read_bytes()
            if b"version=6" in data[:43]:
                try:
                    items, _ = annots.page_annotations(data, renderer.text_lines(uid, page["redir"]), page["id"])
                    hls = [a for a in items if a["kind"] in ("highlight", "native")]
                except Exception:
                    hls = []
        ann = rv.render_annotations(rm, b, skip_highlights=bool(hls)) if has_ink else ""
        if orig is not None and not ann.strip() and not hls:
            writer.add_page(orig)                      # page intacte
            continue
        w_pt, h_pt = (b.x1 - b.x0) * K, (b.y1 - b.y0) * K
        out = writer.add_blank_page(w_pt, h_pt)
        if orig is not None:
            # coin bas-gauche de la page d'origine dans la nouvelle page (repère PDF : origine en bas)
            tx = (page_box[0] - b.x0) * K - float(orig.mediabox.left)
            ty = h_pt - (page_box[2] - b.y0) * K - float(orig.mediabox.height) - float(orig.mediabox.bottom)
            out.merge_transformed_page(orig, Transformation().translate(tx, ty))
        if ann.strip():
            out.merge_page(_overlay(ann, b, w_pt, h_pt))
        if hls:
            to_pt = lambda x, y: ((x - b.x0) * K, h_pt - (y - b.y0) * K)
            refs = []
            for a in hls:
                quads = []
                for x, y, w, h in a["quads"]:
                    (qx0, qy1), (qx1, qy0) = to_pt(x, y), to_pt(x + w, y + h)
                    quads.append([qx0, qy0, qx1, qy1])
                refs.append(_highlight(writer, quads, a["color"], a["text"],
                                       (notes.get(a.get("key")) or {}).get("note", "")))
            out[NameObject("/Annots")] = ArrayObject(list(out.get("/Annots", [])) + refs)
    writer.add_metadata({"/Title": item["name"], "/Producer": "remarkable-studio"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


if __name__ == "__main__":     # essai : python export_pdf.py <uid> sortie.pdf
    import sys
    lib = rv.Library(Path(__file__).resolve().parent / "xochitl")
    Path(sys.argv[2]).write_bytes(export(lib, sys.argv[1], "--annotees" in sys.argv))
    print("ok", sys.argv[2])
