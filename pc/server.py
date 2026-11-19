#!/usr/bin/env python3
"""remarkable-studio — serveur local (PC).

Pages :
  /         bibliothèque : la sauvegarde de la tablette (dossier xochitl, synchronisée automatiquement),
            pages rendues avec leurs annotations, export PDF
  /studio   le document ouvert sur la tablette, en direct : écran réel fusionné avec les pages enregistrées,
            crayon, formes parfaites, formules LaTeX, surlignage du texte, dessin, export PDF

Usage :  python server.py [--port 8765] [--data xochitl] [--open]
Tablette : USB (10.11.99.1), ou Wi-Fi si tablette.conf contient « wifi=<adresse> » (USB prioritaire, choix
automatique à chaque connexion) ; ou variable d'environnement RM_HOST pour forcer une adresse.
Le serveur n'écoute que sur 127.0.0.1 ; les requêtes POST exigent l'en-tête X-RM-Viewer (protection CSRF).
"""
import argparse
import base64
import hashlib
import html
import io
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from rmscene import read_tree
from rmscene import scene_items as si
from rmscene.text import TextDocument
from rmc.exporters import svg as rsvg
from rmc.exporters.writing_tools import Pen

import live
import tablet
import draw
import formules
import screen
import autosync
import export_pdf
import annots
import autohl

HERE = Path(__file__).resolve().parent
SCALE = rsvg.SCALE                      # écran (226 dpi) -> points
SCREEN_W, SCREEN_H = 1404, 1872
UUID_RE = re.compile(r"^[0-9a-f-]{36}$")

# ---------------------------------------------------------------- index

class Library:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.items = {}
        self.mtime = None
        self.reload()

    def _sig(self):
        return max((p.stat().st_mtime for p in self.root.glob("*.metadata")), default=0)

    def maybe_reload(self):
        if self._sig() != self.mtime:
            self.reload()

    def reload(self):
        items = {}
        for meta_path in self.root.glob("*.metadata"):
            it = self._load_item(meta_path.stem)
            if it:
                items[it["id"]] = it
        with self.lock:
            self.items = items
            self.mtime = self._sig()

    def reload_one(self, uid):
        it = self._load_item(uid)
        with self.lock:
            items = dict(self.items)
            if it:
                items[uid] = it
            else:
                items.pop(uid, None)
            self.items = items
            self.mtime = self._sig()

    def _load_item(self, uid):
        meta_path = self.root / f"{uid}.metadata"
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            return None
        if meta.get("deleted"):
            return None
        content = {}
        cpath = self.root / f"{uid}.content"
        if cpath.exists():
            try:
                content = json.loads(cpath.read_text())
            except Exception:
                pass
        is_folder = meta.get("type") == "CollectionType"
        ftype = "folder" if is_folder else (content.get("fileType") or "notebook")
        pages = [] if is_folder else self._pages(uid, content, ftype)
        return {
            "id": uid,
            "name": meta.get("visibleName") or "(sans nom)",
            "parent": meta.get("parent") or "",
            "type": ftype,
            "modified": int(meta.get("lastModified") or 0),
            "opened": int(meta.get("lastOpened") or 0),
            "pinned": bool(meta.get("pinned")),
            "lastPage": meta.get("lastOpenedPage") or 0,
            "pages": pages,
            "pageCount": len(pages),
            "tags": [t.get("name") for t in content.get("tags", []) if isinstance(t, dict)],
            "hasFile": (self.root / f"{uid}.{ftype}").exists() if ftype in ("pdf", "epub") else False,
        }

    def _pages(self, uid, content, ftype):
        pages = []
        if "cPages" in content:
            raw = [p for p in content["cPages"].get("pages", []) if not p.get("deleted")]
            raw.sort(key=lambda p: (p.get("idx") or {}).get("value", ""))
            for p in raw:
                redir = (p.get("redir") or {}).get("value")
                pages.append({"id": p["id"], "redir": redir,
                              "template": (p.get("template") or {}).get("value")})
        elif content.get("pages"):
            rmap = content.get("redirectionPageMap") or []
            for i, pid in enumerate(content["pages"]):
                redir = rmap[i] if i < len(rmap) else (i if ftype in ("pdf", "epub") else None)
                pages.append({"id": pid, "redir": redir, "template": None})
        elif ftype in ("pdf", "epub"):
            n = pdf_page_count(self.root / f"{uid}.pdf")
            pages = [{"id": None, "redir": i, "template": None} for i in range(n)]
        if ftype in ("pdf", "epub"):
            for p in pages:
                if isinstance(p["redir"], int) and p["redir"] < 0:
                    p["redir"] = None
        return pages

    def snapshot(self):
        with self.lock:
            return self.items


def pdf_page_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=30).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0

# ---------------------------------------------------------------- rendu

def esc(s):
    return html.escape(str(s), quote=True)


class Bounds:
    def __init__(self):
        self.x0, self.x1, self.y0, self.y1 = -SCREEN_W / 2, SCREEN_W / 2, 0, SCREEN_H

    def add(self, x, y):
        self.x0, self.x1 = min(self.x0, x), max(self.x1, x)
        self.y0, self.y1 = min(self.y0, y), max(self.y1, y)


def stroke_svg(line, out, dx=0.0, dy=0.0, bounds=None):
    """Dessine un trait (objet rmscene Line ou équivalent v5) via les stylos de rmc."""
    try:
        pen = Pen.create(line.tool.value, line.color.value, line.thickness_scale)
    except Exception:
        try:   # couleur inconnue de rmc (ex. 9 = couleur libre) : stylo noir, la vraie couleur est appliquée plus bas
            pen = Pen.create(line.tool.value, 0, line.thickness_scale)
        except Exception:
            return
    if line.tool.value == si.Pen.ERASER_AREA.value:
        return
    rgba = getattr(line, "color_rgba", None)   # couleur libre (ARGB) des firmwares 3.x récents
    custom = f"rgb({rgba[0]},{rgba[1]},{rgba[2]})" if rgba else None
    prev = None
    seg_w = 0
    for i, p in enumerate(line.points):
        x, y = p.x + dx, p.y + dy
        if bounds:
            bounds.add(x, y)
        if i % pen.segment_length == 0:
            if prev is not None:
                out.write('"/>\n')
            try:
                color = pen.get_segment_color(p.speed, p.direction, p.width, p.pressure, seg_w)
                nw = pen.get_segment_width(p.speed, p.direction, p.width, p.pressure, seg_w)
                op = pen.get_segment_opacity(p.speed, p.direction, p.width, p.pressure, seg_w)
            except Exception:
                color, nw, op = "rgb(0,0,0)", 2, 1
            if custom:
                color = custom
                op = round(float(op) * rgba[3] / 255, 3)
            seg_w = nw
            out.write(f'<polyline fill="none" stroke="{color}" stroke-width="{nw * SCALE:.3f}" '
                      f'opacity="{op}" stroke-linecap="{pen.stroke_linecap}" stroke-linejoin="round" points="')
            if prev is not None:
                out.write(f"{prev[0] * SCALE:.2f},{prev[1] * SCALE:.2f} ")
        out.write(f"{x * SCALE:.2f},{y * SCALE:.2f} ")
        prev = (x, y)
    if prev is not None:
        out.write('"/>\n')


HL_COLORS = {3: "#fbf719", 4: "#7cf27c", 5: "#ffb6c8", 6: "#8fa6ff", 7: "#ff8f8a",
             9: "#fbf719", 10: "#a1d87d", 11: "#8bd0e5", 12: "#b782cd", 13: "#f7e851"}


def render_v6(f, out, bounds, skip_highlights=False):
    tree = read_tree(f)
    anchors = rsvg.build_anchor_pos(tree.root_text)
    if tree.root_text is not None:
        try:
            doc = TextDocument.from_scene_item(tree.root_text)
            y = rsvg.TEXT_TOP_Y
            for para in doc.contents:
                y += rsvg.LINE_HEIGHTS.get(para.style.value, 70)
                txt = str(para).strip()
                if not txt:
                    continue
                st = para.style.value
                size = 14 if st == si.ParagraphStyle.HEADING else (8 if st == si.ParagraphStyle.BOLD else 7.5)
                weight = "bold" if st in (si.ParagraphStyle.BOLD, si.ParagraphStyle.HEADING) else "normal"
                if st in (si.ParagraphStyle.BULLET, si.ParagraphStyle.BULLET2):
                    txt = "• " + txt
                elif st == si.ParagraphStyle.CHECKBOX:
                    txt = "☐ " + txt
                elif st == si.ParagraphStyle.CHECKBOX_CHECKED:
                    txt = "☑ " + txt
                tx, ty = tree.root_text.pos_x, tree.root_text.pos_y + y
                bounds.add(tx, ty)
                out.write(f'<text x="{tx * SCALE:.2f}" y="{ty * SCALE:.2f}" font-family="sans-serif" '
                          f'font-size="{size}" font-weight="{weight}">{esc(txt)}</text>\n')
        except Exception:
            pass

    def group(item, dx, dy):
        ax, ay = rsvg.get_anchor(item, anchors)
        dx, dy = dx + ax, dy + ay
        for child in item.children.values():
            if isinstance(child, si.Group):
                group(child, dx, dy)
            elif isinstance(child, si.Line):
                if skip_highlights and child.tool.value in (si.Pen.HIGHLIGHTER_1.value, si.Pen.HIGHLIGHTER_2.value):
                    continue                  # export PDF : devenu une vraie annotation de surlignage
                stroke_svg(child, out, dx, dy, bounds)
            elif isinstance(child, si.GlyphRange):
                if skip_highlights:
                    continue
                rgba = getattr(child, "color_rgba", None)
                col = (f"rgb({rgba[0]},{rgba[1]},{rgba[2]})" if rgba
                       else HL_COLORS.get(getattr(child.color, "value", 3), "#fbf719"))
                for r in child.rectangles or []:
                    out.write(f'<rect x="{(r.x + dx) * SCALE:.2f}" y="{(r.y + dy) * SCALE:.2f}" '
                              f'width="{r.w * SCALE:.2f}" height="{r.h * SCALE:.2f}" fill="{col}" '
                              f'opacity="0.45" style="mix-blend-mode:multiply"/>\n')
    group(tree.root, 0, 0)


def render_v5(data: bytes, out, bounds):
    """Ancien format .lines v5 (firmware < 3.0). Coordonnées 0..1404 -> recentrées."""
    off = 43
    (nlayers,) = struct.unpack_from("<i", data, off); off += 4
    for _ in range(nlayers):
        (nstrokes,) = struct.unpack_from("<i", data, off); off += 4
        for _ in range(nstrokes):
            pen, color, _u, width, _u2, npts = struct.unpack_from("<iiifii", data, off); off += 24
            pts = []
            for _ in range(npts):
                x, y, speed, tilt, w, pressure = struct.unpack_from("<6f", data, off); off += 24
                pts.append(types.SimpleNamespace(
                    x=x - SCREEN_W / 2, y=y, speed=speed * 4, direction=tilt * 255 / 6.283185307,
                    width=w * 4, pressure=pressure * 255))
            line = types.SimpleNamespace(tool=types.SimpleNamespace(value=pen),
                                         color=types.SimpleNamespace(value=color),
                                         thickness_scale=width, points=pts)
            stroke_svg(line, out, 0, 0, bounds)


def render_annotations(rm_path: Path, bounds, skip_highlights=False):
    out = io.StringIO()
    if rm_path and rm_path.exists():
        data = rm_path.read_bytes()
        head = data[:43].decode("ascii", "replace")
        try:
            if "version=6" in head:
                render_v6(io.BytesIO(data), out, bounds, skip_highlights)
            elif "version=5" in head or "version=3" in head:
                render_v5(data, out, bounds)
        except Exception as e:  # page illisible : on affiche ce qu'on a
            out.write(f"<!-- erreur: {esc(e)} -->")
    return out.getvalue()


def _parse_bbox_pages(xml):
    """Sortie de pdftotext -bbox-layout -> par page : lignes de mots [x, y, w, h, "mot"] en unités de page de la
    tablette (point PDF x 227/72, x décalé de la demi-largeur : le PDF est centré en x = 0)."""
    pages = []
    k = 227 / 72
    for pm in re.finditer(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', xml, re.S):
        x0 = -float(pm.group(1)) * k / 2
        lines = []
        for lm in re.finditer(r"<line[^>]*>(.*?)</line>", pm.group(3), re.S):
            words = []
            for wm in re.finditer(r'<word xMin="([\d.-]+)" yMin="([\d.-]+)" xMax="([\d.-]+)" yMax="([\d.-]+)">(.*?)</word>',
                                  lm.group(1), re.S):
                a, b, c, d = (float(v) for v in wm.groups()[:4])
                words.append([round(x0 + a * k, 2), round(b * k, 2), round((c - a) * k, 2), round((d - b) * k, 2),
                              html.unescape(wm.group(5))])
            if words:
                lines.append(words)
        pages.append(lines)
    return pages


class Renderer:
    def __init__(self, lib: Library, cache: Path):
        self.lib = lib
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.locks = {}
        self.glock = threading.Lock()

    def _lock(self, key):
        with self.glock:
            return self.locks.setdefault(key, threading.Lock())

    def pdf_png(self, uid, idx, dpi=110):
        pdf = self.lib.root / f"{uid}.pdf"
        dst = self.cache / f"{uid}-p{idx}-{dpi}.png"
        if not dst.exists() and pdf.exists():
            with self._lock(str(dst)):
                if not dst.exists():
                    tmp = dst.with_suffix("")
                    subprocess.run(["pdftoppm", "-f", str(idx + 1), "-l", str(idx + 1), "-r", str(dpi),
                                    "-png", "-singlefile", str(pdf), str(tmp)],
                                   capture_output=True, timeout=120)
        return dst if dst.exists() else None

    def page_svg(self, uid, n, hd=1):
        """hd = 1 : PDF rendu à la résolution de la tablette (227 dpi) ; 2 : double (Studio zoomé, écran haute densité)."""
        item = self.lib.snapshot().get(uid)
        if not item or n < 0 or n >= len(item["pages"]):
            return None
        page = item["pages"][n]
        rm = self.lib.root / uid / f"{page['id']}.rm" if page["id"] else None
        sig = hashlib.sha1(json.dumps([page, rm.stat().st_mtime if rm and rm.exists() else 0,
                                       item["modified"], 8, hd]).encode()).hexdigest()[:12]
        dst = self.cache / f"{uid}-{n}-h{hd}-{sig}.svg"
        if dst.exists():
            return dst.read_bytes()
        with self._lock(str(dst)):
            if dst.exists():
                return dst.read_bytes()
            bounds = Bounds()
            bg = ""
            if item["type"] in ("pdf", "epub") and page["redir"] is not None:
                dpi = 227 * hd                      # avant : 110 dpi agrandis x2 -> flou
                png = self.pdf_png(uid, page["redir"], dpi)
                if png:
                    w, h = struct.unpack(">II", png.read_bytes()[16:24])
                    v5 = bool(rm and rm.exists() and b"version=6" not in rm.read_bytes()[:43])
                    if v5:   # ancien format : page ajustée à l'écran
                        s = min(SCREEN_W / w, SCREEN_H / h)
                    else:    # v6 : page PDF à 227 dpi (mesuré sur la tablette : primaryContentRect), centrée en x=0, haut en y=0
                        s = 227 / dpi
                    iw, ih = w * s, h * s
                    bounds.x0, bounds.x1, bounds.y0, bounds.y1 = -iw / 2, iw / 2, 0, ih
                    b64 = base64.b64encode(png.read_bytes()).decode()
                    bg = (f'<image x="{-iw / 2 * SCALE:.2f}" y="0" width="{iw * SCALE:.2f}" '
                          f'height="{ih * SCALE:.2f}" preserveAspectRatio="none" '
                          f'href="data:image/png;base64,{b64}"/>\n')
            ann = render_annotations(rm, bounds)
            x0, y0 = bounds.x0 * SCALE, bounds.y0 * SCALE
            w, h = (bounds.x1 - bounds.x0) * SCALE, (bounds.y1 - bounds.y0) * SCALE
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.2f} {y0:.2f} {w:.2f} {h:.2f}" '
                   f'width="{w:.1f}" height="{h:.1f}">\n'
                   f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#fff"/>\n'
                   f'{bg}{ann}</svg>\n').encode()
            for old in self.cache.glob(f"{uid}-{n}-h{hd}-*.svg"):
                old.unlink(missing_ok=True)
            dst.write_bytes(svg)
            return svg

    def page_text(self, uid, n):
        """Mots de la page (couche de texte du PDF), en unités de page de la tablette :
        {"bounds": [x, y, w, h] (= X-Scene-Bounds), "lines": [[[x, y, w, h, "mot"], ...], ...]}.
        PDF à 227 dpi, centré en x = 0, haut en y = 0 (format v6). Vide pour un scan ou un carnet."""
        item = self.lib.snapshot().get(uid)
        if not item or n < 0 or n >= len(item["pages"]):
            return None
        page = item["pages"][n]
        svg = self.page_svg(uid, n) or b""
        vb = re.search(rb'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg[:400])
        bounds = [round(float(v) / SCALE, 2) for v in vb.groups()] if vb else None
        out = {"bounds": bounds, "lines": []}
        pdf = self.lib.root / f"{uid}.pdf"
        rm = self.lib.root / uid / f"{page['id']}.rm" if page["id"] else None
        if item["type"] != "pdf" or page["redir"] is None or not pdf.exists():
            return out
        if rm and rm.exists() and b"version=6" not in rm.read_bytes()[:43]:
            return out                                    # ancien format : autre placement, non géré
        dst = self.cache / f"{uid}-p{page['redir']}-text.json"
        if not dst.exists():
            idx = page["redir"] + 1
            r = subprocess.run(["pdftotext", "-f", str(idx), "-l", str(idx), "-bbox-layout", str(pdf), "-"],
                               capture_output=True, timeout=60)
            pages = _parse_bbox_pages(r.stdout.decode("utf-8", "replace"))
            dst.write_text(json.dumps(pages[0] if pages else [], ensure_ascii=False))
        out["lines"] = json.loads(dst.read_text())
        return out

    def text_lines(self, uid, redir):
        """Lignes de mots d'une page du PDF (index dans le PDF), extraites pour TOUT le document en une seule
        passe la première fois (recherche) ; None si indisponible."""
        dst = self.cache / f"{uid}-p{redir}-text.json"
        if not dst.exists():
            pdf = self.lib.root / f"{uid}.pdf"
            if not pdf.exists():
                return None
            with self._lock(f"alltext-{uid}"):
                if not dst.exists():
                    r = subprocess.run(["pdftotext", "-bbox-layout", str(pdf), "-"], capture_output=True, timeout=600)
                    for i, lines in enumerate(_parse_bbox_pages(r.stdout.decode("utf-8", "replace"))):
                        f = self.cache / f"{uid}-p{i}-text.json"
                        if not f.exists():
                            f.write_text(json.dumps(lines, ensure_ascii=False))
        return json.loads(dst.read_text()) if dst.exists() else None

    def thumb(self, uid):
        item = self.lib.snapshot().get(uid)
        if not item or not item["pages"]:
            return None
        tdir = self.lib.root / f"{uid}.thumbnails"
        first = item["pages"][0]
        if first["id"] and (tdir / f"{first['id']}.png").exists():
            return tdir / f"{first['id']}.png"
        if item["type"] in ("pdf", "epub") and first["redir"] is not None:
            return self.pdf_png(uid, first["redir"], dpi=30)
        return None

# ---------------------------------------------------------------- serveur HTTP

class Handler(BaseHTTPRequestHandler):
    lib: Library = None
    renderer: Renderer = None
    pen = None
    current = None
    injector = draw.Injector()

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        try:
            if not parts:
                return self.send(200, (HERE / "library.html").read_bytes(), "text/html; charset=utf-8")
            if parts == ["api", "live", "pen"]:
                return live.sse(self, self.pen)
            if parts == ["api", "live", "state"]:
                return self.send(200, json.dumps(self.current.get()).encode(), "application/json",
                                 {"Cache-Control": "no-store"})
            if len(parts) == 3 and parts[:2] == ["api", "export"] and parts[2].endswith(".pdf") and UUID_RE.match(parts[2][:-4]):
                uid = parts[2][:-4]
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                item = self.lib.snapshot().get(uid)
                if not item or item["type"] == "folder":
                    return self.send(404, b"not found", "text/plain")
                try:
                    data = export_pdf.export(self.lib, uid, only_annotated=q.get("annotees", ["0"])[0] == "1",
                                            renderer=self.renderer)
                except Exception as e:
                    return self.json({"ok": False, "error": f"export impossible : {e}"}, 500)
                name = re.sub(r'[\\/:*?"<>|]+', "_", item["name"]).strip() or "document"
                suffix = " (pages annotées)" if q.get("annotees", ["0"])[0] == "1" else ""
                fname = urllib.parse.quote(f"{name}{suffix}.pdf")
                return self.send(200, data, "application/pdf",
                                 {"Content-Disposition": f"attachment; filename=\"export.pdf\"; filename*=UTF-8''{fname}",
                                  "Cache-Control": "no-store"})
            if len(parts) == 3 and parts[:2] == ["api", "notes"] and UUID_RE.match(parts[2]):
                return self.json({"notes": annots.doc_notes(parts[2])})
            if parts == ["api", "highlights"]:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
                res, pending = annots.search_highlights(self.lib, self.renderer, q)
                return self.json({"results": res, "pending": pending})   # pending : pages pas encore analysées
            if len(parts) == 3 and parts[:2] == ["api", "search"] and UUID_RE.match(parts[2]):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
                return self.json({"results": annots.search(self.lib, self.renderer, parts[2], q)})
            if len(parts) == 3 and parts[:2] == ["api", "annotations"] and UUID_RE.match(parts[2]):
                res = annots.document_annotations(self.lib, self.renderer, parts[2], with_bounds=True)
                if res is None:
                    return self.send(404, b"", "text/plain")
                return self.json({"pages": res})
            if parts == ["api", "autohl"]:
                return self.json({"on": self.autohl.enabled, "last": self.autohl.last})
            if parts == ["api", "library", "version"]:
                return self.json({"v": self.sync.version, **self.sync.last})
            if parts == ["api", "library"]:
                self.lib.maybe_reload()
                links = tablet.load_links()
                items = []
                for it in self.lib.snapshot().values():
                    d = {k: v for k, v in it.items() if k != "pages"}
                    d["linked"] = links.get(it["id"], {}).get("to")
                    items.append(d)
                return self.send(200, json.dumps(items).encode(), "application/json")
            if parts == ["api", "tablet", "status"]:
                return self.json(tablet.status())
            if len(parts) == 2 and parts[0] == "static" and re.fullmatch(r"[A-Za-z0-9_.-]+\.(css|js|png|svg|woff2)", parts[1]):
                f = HERE / "static" / parts[1]
                if not f.is_file():
                    return self.send(404, b"not found", "text/plain")
                types = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8", "png": "image/png",
                         "svg": "image/svg+xml", "woff2": "font/woff2"}
                return self.send(200, f.read_bytes(), types[f.suffix[1:]], {"Cache-Control": "max-age=300"})
            if parts == ["studio"]:
                return self.send(200, (HERE / "studio.html").read_bytes(), "text/html; charset=utf-8")
            if parts == ["api", "screen", "stats"]:
                return self.json({**self.screen.stats, "seq": self.screen.seq, "error": self.screen.error,
                                  "touching": bool(self.pen.touching)})
            if parts == ["api", "screen", "next"]:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                seq, png, meta = self.screen.wait_frame(int(q.get("after", ["0"])[0]), timeout=20)
                if png is None:
                    return self.json({"error": self.screen.error or "pas encore d'image"}, 503)
                return self.send(200, png, "image/png", {"Cache-Control": "no-store", "X-Seq": str(seq), "X-Vue": meta,
                                                         "Access-Control-Expose-Headers": "X-Seq, X-Vue"})
            if parts == ["api", "pen"]:
                # état du crayon lu dans vue.json (plus de penGet par xovi-message-broker : plantages)
                return self.json({"pen": self.current.get().get("pen")})
            if parts == ["api", "palette"]:
                pal, live_ = tablet.get_palette()
                return self.json({"palette": pal, "fromTablet": live_})
            if len(parts) == 4 and parts[:2] == ["api", "page"] and UUID_RE.match(parts[2]):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                hd = 2 if q.get("hd", ["1"])[0] == "2" else 1
                svg = self.renderer.page_svg(parts[2], int(parts[3]), hd)
                if svg is None:
                    return self.send(404, b"not found", "text/plain")
                # limites de la page en unités de page (viewBox / SCALE), pour superposer l'écran en direct
                vb = re.search(rb'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg[:400])
                hdr = {"Cache-Control": "no-cache", "Access-Control-Expose-Headers": "X-Scene-Bounds"}
                if vb:
                    hdr["X-Scene-Bounds"] = ",".join(f"{float(v) / SCALE:.2f}" for v in vb.groups())
                return self.send(200, svg, "image/svg+xml", hdr)
            if len(parts) == 4 and parts[:2] == ["api", "text"] and UUID_RE.match(parts[2]):
                t = self.renderer.page_text(parts[2], int(parts[3]))
                if t is None:
                    return self.send(404, b"not found", "text/plain")
                return self.json(t)
            if len(parts) == 4 and parts[:2] == ["api", "pagebg"] and UUID_RE.match(parts[2]):
                # page du PDF seule (sans annotations), 227 dpi = 1 pixel par unité de page, centrée en x = 0 :
                # fond net de la zone en direct du Studio
                item = self.lib.snapshot().get(parts[2])
                n = int(parts[3])
                if not item or item["type"] not in ("pdf", "epub") or not 0 <= n < len(item["pages"]) \
                        or item["pages"][n]["redir"] is None:
                    return self.send(404, b"", "text/plain")
                png = self.renderer.pdf_png(parts[2], item["pages"][n]["redir"], 227)
                if not png:
                    return self.send(404, b"", "text/plain")
                return self.send(200, png.read_bytes(), "image/png", {"Cache-Control": "max-age=600"})
            if len(parts) == 3 and parts[:2] == ["api", "thumb"] and UUID_RE.match(parts[2]):
                p = self.renderer.thumb(parts[2])
                if not p:   # pas de miniature : on rend la première page
                    svg = self.renderer.page_svg(parts[2], 0)
                    if svg is None:
                        return self.send(404, b"", "text/plain")
                    return self.send(200, svg, "image/svg+xml", {"Cache-Control": "max-age=3600"})
                return self.send(200, p.read_bytes(), "image/png", {"Cache-Control": "max-age=3600"})
            if len(parts) == 3 and parts[:2] == ["api", "file"]:
                uid, ext = os.path.splitext(parts[2])
                item = self.lib.snapshot().get(uid)
                if item and ext in (".pdf", ".epub") and UUID_RE.match(uid):
                    f = self.lib.root / f"{uid}{ext}"
                    if f.exists():
                        name = urllib.parse.quote(item["name"] + ext)
                        ctype = "application/pdf" if ext == ".pdf" else "application/epub+zip"
                        disp = "inline" if ext == ".pdf" else "attachment"
                        return self.send(200, f.read_bytes(), ctype,
                                         {"Content-Disposition": f"{disp}; filename*=UTF-8''{name}"})
            return self.send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.send(500, str(e).encode(), "text/plain")

    do_HEAD = do_GET

    def json(self, obj, code=200):
        return self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json",
                         {"Cache-Control": "no-store"})

    def do_POST(self):
        # en-tête personnalisé obligatoire : un autre site ne peut pas l'envoyer sans pré-vérification CORS
        if self.headers.get("X-RM-Viewer") != "1":
            return self.send(403, b"forbidden", "text/plain")
        path = urllib.parse.urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body_raw = self.rfile.read(n)
            body = {} if path == "/api/upload" else json.loads(body_raw or b"{}")
            items = self.lib.snapshot()
            if path == "/api/notes":
                doc, key = body.get("doc"), str(body.get("key") or "")
                if doc not in items or not key or len(str(body.get("note") or "")) > 20000:
                    return self.json({"ok": False, "error": "requête invalide"}, 400)
                n = annots.set_note(doc, key, body.get("note"), str(body.get("text") or "")[:2000], body.get("page"))
                return self.json({"ok": True, "note": n})
            if path == "/api/autohl":
                self.autohl.set_enabled(bool(body.get("on")))
                return self.json({"on": self.autohl.enabled})
            if path == "/api/upload":
                # Envoi d'un PDF / EPUB vers la tablette par son interface web USB (Paramètres > Stockage) :
                # la tablette l'importe elle-même, sans redémarrage. USB uniquement.
                name = urllib.parse.unquote(self.headers.get("X-Filename", "")).replace("/", "_").strip()
                ext = os.path.splitext(name)[1].lower()
                if ext not in (".pdf", ".epub"):
                    return self.json({"ok": False, "error": "seuls les PDF et EPUB sont acceptés"}, 400)
                data = body_raw
                if not data or len(data) > 200 * 1024 * 1024:
                    return self.json({"ok": False, "error": "fichier vide ou trop gros"}, 400)
                ctype = "application/pdf" if ext == ".pdf" else "application/epub+zip"
                boundary = "----rmstudio" + hashlib.sha1(data[:4096] + name.encode()).hexdigest()[:16]
                payload = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                           f"filename=\"{name.replace(chr(34), '')}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() \
                    + data + f"\r\n--{boundary}--\r\n".encode()
                req = urllib.request.Request("http://10.11.99.1/upload", data=payload, method="POST",
                                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
                try:
                    with urllib.request.urlopen(req, timeout=120) as r:
                        ok = 200 <= r.status < 300
                except urllib.error.HTTPError as e:
                    return self.json({"ok": False, "error": f"la tablette a refusé le fichier ({e.code})"})
                except Exception:
                    return self.json({"ok": False, "error": "interface web USB injoignable : brancher la tablette en "
                                                            "USB et activer Paramètres > Stockage > Interface web USB"})
                return self.json({"ok": ok, "name": name})
            if path == "/api/tablet/open":
                doc = body.get("doc")
                if doc not in items:
                    return self.json({"ok": False, "error": "document inconnu"}, 404)
                ok = tablet.open_document(doc, int(body.get("page", -1)))
                return self.json({"ok": ok, "error": None if ok else "modifications inactives sur la tablette"})
            if path == "/api/annot":
                # Surligner / souligner / barrer du texte du PDF : rectangles (unités de page) -> segments parfaits,
                # tracés par Formes.qml sur la page ouverte (ouverte d'abord si besoin), avec un style imposé
                # le temps de l'opération puis le crayon de l'utilisateur restauré.
                doc, n, kind = body.get("doc"), int(body.get("page", -1)), body.get("kind")
                it = items.get(doc)
                if not it or not 0 <= n < len(it["pages"]) or kind not in ("highlight", "underline", "strike"):
                    return self.json({"ok": False, "error": "requête invalide"}, 400)
                rects = [[float(v) for v in r[:4]] for r in (body.get("rects") or [])[:200]]
                if not rects:
                    return self.json({"ok": False, "error": "rien à marquer"}, 400)
                st = self.current.get()
                if st.get("doc") != doc or st.get("page") != n:
                    tablet.open_document(doc, n)
                    t_end = time.time() + 10
                    while time.time() < t_end:
                        time.sleep(0.8)
                        self.current.t = 0                       # forcer une nouvelle lecture
                        st = self.current.get()
                        if st.get("doc") == doc and st.get("page") == n:
                            break
                    else:
                        return self.json({"ok": False, "error": "impossible d'ouvrir la page sur la tablette"})
                argb = int(body.get("argb") or 0) & 0xFFFFFFFF
                segs = []
                for x, y, w, h in rects:
                    if kind == "highlight":
                        segs.append([x, y + h / 2, x + w, y + h / 2, h * 0.95])
                    else:
                        yy = y + h * (0.86 if kind == "underline" else 0.56)
                        segs.append([x, yy, x + w, yy, 0])
                pen = ({"tool": 18, "argb": argb or 0xFFFBF06A} if kind == "highlight"
                       else {"tool": 17, "argb": argb or 0xFF000000, "thickness": 2})
                cmd = {"action": "marks", "page": it["pages"][n]["id"], "pen": pen,
                       "segs": [[round(v, 2) for v in sg] for sg in segs]}
                self.screen.boost(4)
                return self.json({"ok": tablet.formes_cmd(cmd)})
            if path == "/api/formes/build":
                shape = body.get("shape")
                if shape not in ("line", "rect", "circle", "ellipse", "grid", "polygon", "axes"):
                    return self.json({"ok": False, "error": "forme inconnue"}, 400)
                cmd = {"action": "build", "shape": shape, "spacing": int(body.get("spacing") or 60),
                       "sides": int(body.get("sides") or 6)}
                for k in ("ax", "ay", "bx", "by"):
                    cmd[k] = min(max(float(body.get(k, 0)), 0), 1872)
                if body.get("minor") is not None:              # ellipse : petit rayon (px)
                    cmd["minor"] = min(max(float(body["minor"]), 1), 2000)
                self.screen.boost(4)
                return self.json({"ok": tablet.formes_cmd(cmd)})
            if path in ("/api/latex/render", "/api/latex/send"):
                latex = str(body.get("latex") or "")
                display = bool(body.get("display", True))
                scale = float(body.get("scale") or 1.5)
                try:
                    if path == "/api/latex/render":
                        png, w, h = formules.render(latex, display, scale)
                        return self.json({"ok": True, "w": w, "h": h, "png": base64.b64encode(png).decode()})
                    if not tablet.status().get("usb"):
                        return self.json({"ok": False, "error": "tablette non connectée"})
                    pos = None
                    if body.get("x") is not None and body.get("y") is not None:
                        pos = (min(max(float(body["x"]), 0), 1404), min(max(float(body["y"]), 0), 1872))
                        self.screen.boost(4)
                    return self.json({"ok": True, **formules.send(latex, display, scale, pos)})
                except (ValueError, RuntimeError) as e:
                    return self.json({"ok": False, "error": str(e)})
            if path == "/api/draw":
                strokes = body.get("strokes")
                if not isinstance(strokes, list) or not strokes or len(strokes) > 200:
                    return self.json({"ok": False, "error": "traits invalides"}, 400)
                clean = []
                for st in strokes:
                    pts = [(min(max(float(x), 0), draw.W - 1), min(max(float(y), 0), draw.H - 1))
                           for x, y in st[:5000]]
                    if len(pts) >= 2:
                        clean.append(draw.densify(pts))
                if not tablet.status().get("usb"):
                    return self.json({"ok": False, "error": "tablette non connectée"})
                # garde-fou : n'injecter que si la tablette affiche bien la page prévue
                if body.get("doc") is not None:
                    cur = self.current.get()
                    if cur.get("doc") != body.get("doc") or (body.get("page") is not None and cur.get("page") != body.get("page")):
                        return self.json({"ok": False, "error": "la tablette n'affiche pas la page prévue",
                                          "current": {"doc": cur.get("doc"), "name": cur.get("name"), "page": cur.get("page")}}, 409)
                hold =min(max(int(body.get("hold_ms") or 0), 0), 3000)
                for pts in clean:
                    self.injector.stroke(pts, hold_ms=hold)
                return self.json({"ok": True, "count": len(clean)})
            if path == "/api/pen":
                cmd = {"action": "pen"}
                for k in ("argb", "thickness", "tool"):
                    if body.get(k) is not None:
                        cmd[k] = int(body[k]) & 0xFFFFFFFF if k == "argb" else (float(body[k]) if k == "thickness" else int(body[k]))
                ok = tablet.formes_cmd(cmd)
                pen = dict(self.current.get().get("pen") or {})
                pen.update({k: v for k, v in cmd.items() if k != "action"})
                if "argb" in cmd:
                    pen["color"] = 9
                self.current.t = 0
                return self.json({"pen": pen if ok else None})
            if path == "/api/palette":
                pal = body.get("palette")
                if not isinstance(pal, list):
                    return self.json({"ok": False, "error": "palette invalide"}, 400)
                return self.json({"ok": True, "pushed": tablet.set_palette(pal)})
            if path == "/api/tablet/start":
                return self.json({"ok": tablet.start_mods()})
            if path == "/api/links":
                a, b = body.get("doc"), body.get("to")
                if a not in items or (b is not None and (b not in items or b == a)):
                    return self.json({"ok": False, "error": "document inconnu"}, 400)
                tablet.set_link(items, a, b)
                push = tablet.push_links()
                return self.json({"ok": True, **push})
            return self.send(404, b"not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.json({"ok": False, "error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", default=str(HERE / "xochitl"))
    ap.add_argument("--open", action="store_true", help="ouvrir le navigateur")
    a = ap.parse_args()
    lib = Library(Path(a.data))
    Handler.lib = lib
    Handler.renderer = Renderer(lib, HERE / ".cache")
    Handler.pen = live.PenStream()
    Handler.screen = screen.ScreenStream(Handler.pen)
    Handler.current = live.CurrentPage(lib, Path(a.data))
    Handler.sync = autosync.AutoSync(lib, Path(a.data))
    Handler.autohl = autohl.AutoHighlighter(Handler.pen, Handler.current, Handler.renderer)
    threading.Thread(target=annots.warm_up, args=(lib, Handler.renderer), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"{len(lib.items)} éléments chargés — {url}", flush=True)
    if a.open:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
