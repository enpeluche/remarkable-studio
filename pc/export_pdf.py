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

import server as rv

K = 72 / 227          # unités de page de la tablette -> points PDF


def _overlay(ann, b, w_pt, h_pt):
    """Annotations (fragment SVG, coordonnées = unités de page x SCALE) -> page PDF vectorielle."""
    S = rv.SCALE
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_pt:.3f}pt" height="{h_pt:.3f}pt" '
           f'viewBox="{b.x0 * S:.3f} {b.y0 * S:.3f} {(b.x1 - b.x0) * S:.3f} {(b.y1 - b.y0) * S:.3f}">{ann}</svg>')
    return PdfReader(io.BytesIO(cairosvg.svg2pdf(bytestring=svg.encode()))).pages[0]


def export(lib, uid, only_annotated=False):
    item = lib.snapshot().get(uid)
    if not item:
        raise KeyError(uid)
    pdf_path = lib.root / f"{uid}.pdf"
    reader = PdfReader(str(pdf_path)) if item["type"] == "pdf" and pdf_path.exists() else None
    writer = PdfWriter()
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
        b = rv.Bounds()
        if orig is not None:
            if orig.rotation:
                orig.transfer_rotation_to_content()
            w0, h0 = float(orig.mediabox.width), float(orig.mediabox.height)
            iw, ih = w0 / K, h0 / K
            b.x0, b.x1, b.y0, b.y1 = -iw / 2, iw / 2, 0, ih
        page_box = (b.x0, b.x1, b.y0, b.y1)
        ann = rv.render_annotations(rm, b) if has_ink else ""
        if orig is not None and not ann.strip():
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
    writer.add_metadata({"/Title": item["name"], "/Producer": "remarkable-studio"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


if __name__ == "__main__":     # essai : python export_pdf.py <uid> sortie.pdf
    import sys
    lib = rv.Library(Path(__file__).resolve().parent / "xochitl")
    Path(sys.argv[2]).write_bytes(export(lib, sys.argv[1], "--annotees" in sys.argv))
    print("ok", sys.argv[2])
