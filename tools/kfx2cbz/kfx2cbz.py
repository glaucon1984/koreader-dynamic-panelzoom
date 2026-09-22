#!/usr/bin/env python3
"""
kfx2cbz - convert a (DRM-free) Kindle KFX comic into a CBZ that keeps Kindle's
panel-by-panel ("Region Magnification" / "Virtual Panels") data.

Pipeline
--------
1. KFX -> EPUB using the calibre "KFX Input" plugin (jhowell).  The plugin
   translates the KFX panel data into the KF8 "app-amzn-magnify" markup:
   every page gets absolutely positioned <div id="magnify_source_N"> tap
   rectangles (with an `ordinal` = reading order) and <div id="magnify_target_N">
   zoomed views.
2. Parse that markup, normalise every rectangle to 0..1 fractions of the page
   image, and write:
     * 0001.jpg, 0002.jpg, ...   the page images, spine order
     * panels.json               the panel data (see SCHEMA below)
     * ComicInfo.xml             standard comic metadata (ComicRack format)
   into a CBZ.  Readers that do not understand panels.json simply ignore it.

This module is used in two ways:
  * as a command line tool (see `main`), working on an EPUB/KFX file, and
  * by the calibre "CBZ Output" plugin (calibre_plugin/), working on calibre's
    in-memory OEB book.  Both feed a `ComicSource` adapter to `collect_pages`
    and `write_cbz`.

Usage
-----
    python kfx2cbz.py book.kfx                    # -> book.cbz next to the input
    python kfx2cbz.py book.epub -o out.cbz        # EPUB already made by KFX Input
    python kfx2cbz.py book.kfx --sidecar          # also write out.panels.json
    python kfx2cbz.py book.kfx --preview previews # draw panel overlays to check

The EPUB may be the direct output of `calibre-debug -r "KFX Input" -- in.kfx out.epub`
(inline styles) or a calibre-converted EPUB (class based CSS); both are handled.

SCHEMA (panels.json)
--------------------
{
  "format": "comic-panels", "version": 1, "generator": "kfx2cbz x.y",
  "reading_direction": "ltr" | "rtl",
  "source": {"type": "kfx", "asin": "...", "title": "..."},
  "pages": [
    {"index": 1, "file": "0001.jpg", "width": 1344, "height": 1920,
     "spread": "left" | "right" | "center" | null,
     "panels": [
        {"order": 1, "x": 0.0678, "y": 0.0491, "w": 0.4783, "h": 0.3105,
         "view": {"x": ..., "y": ..., "w": ..., "h": ...}}   # optional zoomed region
     ]}
  ]
}
All coordinates are fractions of the page image (x,y = top-left corner, w,h = size).
`index` is the 1-based page number in the CBZ (images sorted by file name).
`view` is the region Kindle actually shows when the panel is magnified; it is
usually the panel plus a little context, fitted to the device aspect ratio.
"""

import argparse
import io
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from lxml import etree

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None

__version__ = "0.2.0"

NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xh": "http://www.w3.org/1999/xhtml",
    "svg": "http://www.w3.org/2000/svg",
    "xlink": "http://www.w3.org/1999/xlink",
    "cn": "urn:oasis:names:tc:opendocument:xmlns:container",
}
XH = "{%s}" % NS["xh"]
SVG = "{%s}" % NS["svg"]
XLINK = "{%s}" % NS["xlink"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".jxr"}
MEDIA_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
             "image/bmp": ".bmp", "image/tiff": ".tif"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- KFX -> EPUB

CALIBRE_DEBUG_CANDIDATES = [
    r"C:\Program Files\Calibre2\calibre-debug.exe",
    r"C:\Program Files (x86)\Calibre2\calibre-debug.exe",
    "/Applications/calibre.app/Contents/MacOS/calibre-debug",
    "/usr/bin/calibre-debug",
    "/opt/calibre/calibre-debug",
]


def find_calibre_debug(explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise SystemExit("calibre-debug not found at %s" % explicit)
    found = shutil.which("calibre-debug")
    if found:
        return found
    for cand in CALIBRE_DEBUG_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    raise SystemExit(
        "calibre-debug not found. Install calibre + the 'KFX Input' plugin, "
        "or pass --calibre-debug PATH, or convert to EPUB yourself and pass the EPUB.")


def kfx_to_epub(kfx_path, epub_path, calibre_debug=None):
    exe = find_calibre_debug(calibre_debug)
    cmd = [exe, "-r", "KFX Input", "--", kfx_path, epub_path]
    log("Running KFX Input: %s" % " ".join('"%s"' % c if " " in c else c for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if line.strip():
            log("  | " + line.rstrip())
    if proc.returncode != 0 or not os.path.isfile(epub_path):
        if "kfx_input" in out.lower() and ("no module" in out.lower() or "not found" in out.lower()):
            raise SystemExit("The calibre 'KFX Input' plugin does not seem to be installed.")
        raise SystemExit("KFX Input conversion failed (exit %s)" % proc.returncode)
    return epub_path


# --------------------------------------------------------------------------- CSS helpers

_CSS_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def parse_declarations(text):
    props = {}
    for decl in text.split(";"):
        if ":" in decl:
            k, v = decl.split(":", 1)
            k = k.strip().lower()
            v = v.strip()
            if k:
                props[k] = v
    return props


def parse_css_classes(css_text):
    """Return {classname: [props...]} for simple `.class {}` rules (order preserved)."""
    rules = {}
    css_text = _CSS_COMMENT_RE.sub("", css_text or "")
    for m in _CSS_RULE_RE.finditer(css_text):
        selectors, body = m.group(1), m.group(2)
        props = parse_declarations(body)
        if not props:
            continue
        for sel in selectors.split(","):
            sel = sel.strip()
            # accept ".cls", "div.cls", "a.cls" (a single simple selector with one class)
            m2 = re.fullmatch(r"[a-zA-Z0-9]*\.([\w-]+)", sel)
            if m2:
                rules.setdefault(m2.group(1), []).append(props)
    return rules


def px(value):
    """'123.4px' / '123' / '-4.02px' -> float, else None."""
    if value is None:
        return None
    v = value.strip().lower()
    if v.endswith("px"):
        v = v[:-2]
    try:
        return float(v)
    except ValueError:
        return None


# --------------------------------------------------------------------------- sources

class ComicSource:
    """Adapter interface over a book. `metadata` is a dict with the keys
    title, authors (list), publisher, language, description, date, asin,
    reading_direction ('ltr'/'rtl')."""

    metadata = {}

    def spine_items(self):
        """Yield (href, spread) for every linear spine document. spread is
        'left'/'right'/'center' or None."""
        raise NotImplementedError

    def read(self, href):
        """Raw bytes of a manifest item (KeyError when missing)."""
        raise NotImplementedError

    def xhtml_root(self, href):
        """lxml root element of an XHTML document, or None."""
        raise NotImplementedError

    def css_text(self, href):
        """Text of a stylesheet ('' when missing)."""
        raise NotImplementedError

    def resolve(self, base_href, rel):
        """Resolve a relative reference inside document base_href to a manifest href."""
        rel = unquote(rel.split("#", 1)[0])
        base_dir = posixpath.dirname(base_href)
        return posixpath.normpath(posixpath.join(base_dir, rel) if base_dir else rel)

    def media_type(self, href):
        return None

    def cover_href(self):
        """href of the cover image, if the book declares one."""
        return None

    def close(self):
        pass


class ZipEpubSource(ComicSource):
    """An EPUB file (KFX Input output or calibre-converted)."""

    def __init__(self, epub_path):
        self.epub_path = epub_path
        self.zf = zipfile.ZipFile(epub_path)
        self.opf_path = self._find_opf()
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.opf = etree.fromstring(self.zf.read(self.opf_path))
        self.manifest = {}
        for item in self.opf.findall(".//opf:manifest/opf:item", NS):
            self.manifest[item.get("id")] = {
                "href": self.resolve(self.opf_path, item.get("href")),
                "media_type": item.get("media-type"),
                "properties": (item.get("properties") or "").split(),
            }
        self.manifest_by_href = {v["href"]: v for v in self.manifest.values()}
        self.metadata = self._read_metadata()
        self._css_cache = {}

    def close(self):
        self.zf.close()

    def _find_opf(self):
        cont = etree.fromstring(self.zf.read("META-INF/container.xml"))
        rf = cont.find(".//cn:rootfile", NS)
        return rf.get("full-path")

    def _read_metadata(self):
        md = {}
        meta = self.opf.find("opf:metadata", NS)

        def text(tag):
            el = meta.find("dc:" + tag, NS)
            return (el.text or "").strip() if el is not None and el.text else None

        md["title"] = text("title")
        md["publisher"] = text("publisher")
        md["language"] = text("language")
        md["description"] = text("description")
        md["date"] = text("date")
        md["authors"] = [(c.text or "").strip() for c in meta.findall("dc:creator", NS) if c.text]
        md["asin"] = None
        for ident in meta.findall("dc:identifier", NS):
            val = (ident.text or "").strip()
            scheme = (ident.get("{%s}scheme" % NS["opf"]) or "").upper()
            md["asin"] = asin_from_identifier(val, scheme) or md["asin"]
        # reading direction
        spine = self.opf.find("opf:spine", NS)
        ppd = spine.get("page-progression-direction") if spine is not None else None
        direction = ppd if ppd in ("ltr", "rtl") else None
        for m in meta.findall("opf:meta", NS):
            name = (m.get("name") or m.get("property") or "").lower()
            content = (m.get("content") or m.text or "").strip().lower()
            if name == "primary-writing-mode" and direction is None:
                direction = "rtl" if "rl" in content else "ltr"
            elif name == "original-resolution":
                md["original_resolution"] = content
            elif name == "book-type":
                md["book_type"] = content
        md["reading_direction"] = direction or "ltr"
        return md

    def spine_items(self):
        spine = self.opf.find("opf:spine", NS)
        for itemref in spine.findall("opf:itemref", NS):
            item = self.manifest.get(itemref.get("idref"))
            if not item:
                continue
            if itemref.get("linear", "yes") == "no":
                continue
            mt = item["media_type"] or ""
            if not (mt.endswith("xml") or mt.startswith("text/html")):
                continue
            spread = None
            for p in (itemref.get("properties") or "").split():
                p = p.split(":")[-1]
                if p.startswith("page-spread-"):
                    spread = p[len("page-spread-"):]
            yield item["href"], spread

    def read(self, href):
        return self.zf.read(href)

    def xhtml_root(self, href):
        return etree.fromstring(self.read(href), parser=etree.XMLParser(recover=True, huge_tree=True))

    def css_text(self, href):
        try:
            return self.read(href).decode("utf-8", "replace")
        except KeyError:
            return ""

    def media_type(self, href):
        return self.manifest_by_href.get(href, {}).get("media_type")

    def cover_href(self):
        for item in self.manifest.values():
            if "cover-image" in item["properties"]:
                return item["href"]
        meta = self.opf.find("opf:metadata", NS)
        for m in meta.findall("opf:meta", NS):
            if (m.get("name") or "").lower() == "cover" and m.get("content") in self.manifest:
                item = self.manifest[m.get("content")]
                if (item["media_type"] or "").startswith("image/"):
                    return item["href"]
        return None


def asin_from_identifier(value, scheme=""):
    value = (value or "").strip()
    scheme = (scheme or "").upper()
    low = value.lower()
    if low.startswith("urn:asin:"):
        return value.split(":", 2)[2]
    if low.startswith("amazon:") or low.startswith("mobi-asin:"):
        return value.split(":", 1)[1]
    if "ASIN" in scheme or "AMAZON" in scheme:
        return value
    return None


# --------------------------------------------------------------------------- page parsing

class Page:
    __slots__ = ("href", "spread", "image_href", "image_bytes", "width", "height",
                 "viewport_w", "viewport_h", "panels", "label")

    def __init__(self):
        self.href = None
        self.spread = None
        self.image_href = None
        self.image_bytes = None
        self.width = self.height = None
        self.viewport_w = self.viewport_h = None
        self.panels = []
        self.label = None


def _inside_target(el):
    while el is not None:
        if (el.get("id") or "").startswith("magnify_target"):
            return True
        el = el.getparent()
    return False


def _target_alt(target):
    if target is None:
        return None
    for img in target.iter(XH + "img"):
        return img.get("alt") or None
    return None


def _parse_target(target, style_of):
    """Magnify target = hidden full-page div > [mask div, container(overflow hidden) > img].
    The visible region of the *image* = container box mapped through the img's offset/scale."""
    if target is None:
        return None
    cont = img = None
    for div in target.iter(XH + "div"):
        st = style_of(div)
        if (st.get("overflow") or "").lower() == "hidden" and div.find(XH + "img") is not None:
            cont = st
            img = style_of(div.find(XH + "img"))
            break
    if cont is None:
        for im in target.iter(XH + "img"):
            img = style_of(im)
            cont = style_of(im.getparent())
            break
    if not cont or not img:
        return None
    iw, ih = px(img.get("width")), px(img.get("height"))
    cw, ch = px(cont.get("width")), px(cont.get("height"))
    if not (iw and ih and cw and ch):
        return None
    il, it = px(img.get("left")) or 0.0, px(img.get("top")) or 0.0
    return {"x": -il / iw, "y": -it / ih, "w": cw / iw, "h": ch / ih}


def parse_page(source, href, spread=None, css_cache=None, log=log):
    """Parse one spine document into a Page (image + panels). Returns None if
    the document cannot be read."""
    page = Page()
    page.href = href
    page.spread = spread
    try:
        root = source.xhtml_root(href)
    except KeyError:
        log("  ! spine item missing: %s" % href)
        return None
    if root is None:
        return None
    if css_cache is None:
        css_cache = {}

    # collect class rules from linked stylesheets (+ inline <style>)
    class_rules = {}
    for link in root.iter(XH + "link"):
        if (link.get("rel") or "").lower() == "stylesheet" and link.get("href"):
            css_href = source.resolve(href, link.get("href"))
            if css_href not in css_cache:
                css_cache[css_href] = parse_css_classes(source.css_text(css_href))
            for cls, plist in css_cache[css_href].items():
                class_rules.setdefault(cls, []).extend(plist)
    for style in root.iter(XH + "style"):
        if style.text:
            for cls, plist in parse_css_classes(style.text).items():
                class_rules.setdefault(cls, []).extend(plist)

    def style_of(el):
        props = {}
        for cls in (el.get("class") or "").split():
            for plist in class_rules.get(cls, []):
                props.update(plist)
        props.update(parse_declarations(el.get("style") or ""))
        return props

    # viewport
    for meta in root.iter(XH + "meta"):
        if (meta.get("name") or "").lower() == "viewport":
            parts = dict(kv.strip().split("=", 1) for kv in (meta.get("content") or "").split(",") if "=" in kv)
            page.viewport_w = px(parts.get("width"))
            page.viewport_h = px(parts.get("height"))

    # base image = first <img>/<svg:image> that is not inside a magnify target
    base = None
    for el in root.iter(XH + "img", SVG + "image"):
        if not _inside_target(el):
            base = el
            break
    if base is None:
        return page  # text page or similar: no image, no panels
    src = base.get("src") or base.get(XLINK + "href") or base.get("href")
    if not src:
        return page
    page.image_href = source.resolve(href, src)
    try:
        page.image_bytes = source.read(page.image_href)
    except KeyError:
        log("  ! image missing: %s" % page.image_href)
        page.image_href = None
        return page
    page.width, page.height = image_size(page.image_bytes)

    # magnify targets by id
    targets = {}
    for div in root.iter(XH + "div"):
        did = div.get("id") or ""
        if did.startswith("magnify_target"):
            targets[did] = div

    if page.viewport_w is None or page.viewport_h is None:
        # fall back: the base image box, a magnify target box, the image size
        st = style_of(base)
        vw, vh = px(st.get("width")), px(st.get("height"))
        if not (vw and vh):
            for t in targets.values():
                ts = style_of(t)
                vw, vh = px(ts.get("width")), px(ts.get("height"))
                if vw and vh:
                    break
        page.viewport_w = vw or page.width
        page.viewport_h = vh or page.height

    for a in root.iter(XH + "a"):
        if "app-amzn-magnify" not in (a.get("class") or ""):
            continue
        try:
            data = json.loads(a.get("data-app-amzn-magnify") or "{}")
        except ValueError:
            continue
        ordinal = data.get("ordinal")
        # the tap rectangle is the nearest sized ancestor (normally the parent div)
        holder = a.getparent()
        rect = None
        while holder is not None:
            st = style_of(holder)
            if px(st.get("width")) and px(st.get("height")):
                rect = st
                break
            holder = holder.getparent()
        if rect is None:
            continue
        left, top = px(rect.get("left")) or 0.0, px(rect.get("top")) or 0.0
        w, h = px(rect.get("width")), px(rect.get("height"))
        panel = {
            "order": int(ordinal) if ordinal is not None else len(page.panels) + 1,
            "x": left / page.viewport_w, "y": top / page.viewport_h,
            "w": w / page.viewport_w, "h": h / page.viewport_h,
        }
        target = targets.get(data.get("targetId"))
        view = _parse_target(target, style_of)
        if view:
            panel["view"] = view
        page.panels.append(panel)
        if page.label is None:
            page.label = _target_alt(target)

    page.panels.sort(key=lambda p: p["order"])
    for p in page.panels:
        clamp_rect(p)
        if "view" in p:
            clamp_rect(p["view"])
    page.panels = [p for p in page.panels if p["w"] > 0.001 and p["h"] > 0.001]
    for i, p in enumerate(page.panels, 1):
        p["order"] = i  # renumber densely
    return page


def collect_pages(source, log=log):
    """All image pages of the book in reading order (cover first)."""
    pages = []
    css_cache = {}
    for href, spread in source.spine_items():
        page = parse_page(source, href, spread, css_cache, log)
        if page is None or page.image_bytes is None:
            log("  - skipping %s (no page image)" % href)
            continue
        pages.append(page)

    # A cover that is only declared in the metadata/guide (calibre's pipeline
    # drops the cover page from the spine) becomes page 1.
    cover = source.cover_href()
    if cover:
        try:
            cover_bytes = source.read(cover)
        except KeyError:
            cover_bytes = None
        if cover_bytes and not (pages and (pages[0].image_href == cover or pages[0].image_bytes == cover_bytes)):
            page = Page()
            page.href = cover
            page.image_href = cover
            page.image_bytes = cover_bytes
            try:
                page.width, page.height = image_size(cover_bytes)
            except Exception:
                page.width = page.height = None
            if page.width:
                pages.insert(0, page)
                log("  + cover image added as page 1")
    return pages


def clamp_rect(r):
    x0 = min(max(r["x"], 0.0), 1.0)
    y0 = min(max(r["y"], 0.0), 1.0)
    x1 = min(max(r["x"] + r["w"], 0.0), 1.0)
    y1 = min(max(r["y"] + r["h"], 0.0), 1.0)
    r["x"], r["y"], r["w"], r["h"] = (round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5))


def image_size(data):
    if Image is not None:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    # minimal JPEG/PNG header parsing fallback
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    raise ValueError("cannot determine image size (install Pillow)")


# --------------------------------------------------------------------------- output

def image_ext(page, source):
    ext = posixpath.splitext(page.image_href or "")[1].lower()
    if ext == ".jpeg":
        ext = ".jpg"
    if ext not in IMAGE_EXTS:
        ext = MEDIA_EXT.get((source.media_type(page.image_href) or "").lower(), ".jpg")
    return ext


def build_panel_doc(pages, source, source_type="kfx", source_name=None):
    md = source.metadata
    json_pages = []
    total_panels = 0
    for idx, page in enumerate(pages, 1):
        entry = {
            "index": idx,
            "file": "%04d%s" % (idx, image_ext(page, source)),
            "width": page.width,
            "height": page.height,
            "spread": page.spread,
            "panels": page.panels,
        }
        if page.label:
            entry["label"] = page.label
        json_pages.append(entry)
        total_panels += len(page.panels)
    return {
        "format": "comic-panels",
        "version": 1,
        "generator": "kfx2cbz %s" % __version__,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reading_direction": md.get("reading_direction") or "ltr",
        "coordinates": "fractions of page image; x,y = top-left; w,h = size; order = reading order",
        "source": {"type": source_type, "file": source_name, "asin": md.get("asin"), "title": md.get("title")},
        "page_count": len(json_pages),
        "panel_count": total_panels,
        "pages": json_pages,
    }


def write_cbz(pages, source, output, source_type="kfx", source_name=None,
              include_panels=True, include_comicinfo=True, log=log):
    """Write the CBZ to `output` (path or file-like). Returns (panel_doc, panel_json)."""
    if not pages:
        raise ValueError("No image pages found - is this an image based fixed-layout comic?")
    panel_doc = build_panel_doc(pages, source, source_type, source_name)
    panel_json = json.dumps(panel_doc, indent=1, ensure_ascii=False)

    with zipfile.ZipFile(output, "w") as zout:
        for page, entry in zip(pages, panel_doc["pages"]):
            zout.writestr(zipfile.ZipInfo(entry["file"], date_time=(1980, 1, 1, 0, 0, 0)), page.image_bytes,
                          compress_type=zipfile.ZIP_STORED)
        if include_panels:
            zout.writestr("panels.json", panel_json, compress_type=zipfile.ZIP_DEFLATED)
        if include_comicinfo:
            zout.writestr("ComicInfo.xml", comic_info_xml(source.metadata, panel_doc["pages"]),
                          compress_type=zipfile.ZIP_DEFLATED)

    log("Wrote CBZ: %d pages, %d panels (%d pages with panels)%s" % (
        len(pages), panel_doc["panel_count"], sum(1 for p in pages if p.panels),
        "" if include_panels else " [panels.json omitted]"))
    return panel_doc, panel_json


def build(epub_path, cbz_path, sidecar=False, preview_dir=None, preview_pages=None, source_type="kfx",
          source_name=None):
    source = ZipEpubSource(epub_path)
    md = source.metadata
    log("Title: %s | authors: %s | direction: %s" % (md.get("title"), ", ".join(md["authors"]), md["reading_direction"]))
    try:
        pages = collect_pages(source)
        if not pages:
            raise SystemExit("No image pages found in %s - is this an image based fixed-layout comic?" % epub_path)
        panel_doc, panel_json = write_cbz(pages, source, cbz_path, source_type, source_name)
        log("Output: %s" % cbz_path)

        if sidecar:
            side = os.path.splitext(cbz_path)[0] + ".panels.json"
            with open(side, "w", encoding="utf-8") as fh:
                fh.write(panel_json)
            log("Wrote sidecar %s" % side)

        if preview_dir:
            write_previews(pages, preview_dir, preview_pages)
    finally:
        source.close()
    return panel_doc


def comic_info_xml(md, json_pages):
    def tag(name, value):
        if value is None or value == "":
            return ""
        return "  <%s>%s</%s>\n" % (name, xml_escape(str(value)), name)

    year = month = day = None
    if md.get("date"):
        m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", md["date"])
        if m:
            year, month, day = m.group(1), m.group(2), m.group(3)
    rtl = md.get("reading_direction") == "rtl"
    authors = md.get("authors") or []
    out = ['<?xml version="1.0" encoding="utf-8"?>\n',
           '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n']
    out.append(tag("Title", md.get("title")))
    out.append(tag("Summary", strip_html(md.get("description"))))
    out.append(tag("Year", int(year) if year else None))
    out.append(tag("Month", int(month) if month else None))
    out.append(tag("Day", int(day) if day else None))
    out.append(tag("Writer", ", ".join(authors) if authors else None))
    out.append(tag("Publisher", md.get("publisher")))
    if md.get("asin"):
        out.append(tag("Web", "https://www.amazon.com/dp/%s" % md["asin"]))
    out.append(tag("PageCount", len(json_pages)))
    out.append(tag("LanguageISO", (md.get("language") or "")[:2] or None))
    out.append(tag("Manga", "YesAndRightToLeft" if rtl else "No"))
    out.append(tag("Notes", "Converted from Kindle KFX%s by kfx2cbz %s. Panel/reading-order data in panels.json." % (
        " (ASIN %s)" % md["asin"] if md.get("asin") else "", __version__)))
    out.append("  <Pages>\n")
    for i, p in enumerate(json_pages):
        attrs = 'Image="%d" ImageWidth="%d" ImageHeight="%d"' % (i, p["width"] or 0, p["height"] or 0)
        if i == 0:
            attrs += ' Type="FrontCover"'
        if p.get("spread") == "center" and (p["width"] or 0) > (p["height"] or 0):
            attrs += ' DoublePage="true"'
        out.append("    <Page %s />\n" % attrs)
    out.append("  </Pages>\n</ComicInfo>\n")
    return "".join(out)


_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text):
    if not text:
        return text
    if "<" in text and ">" in text:
        text = _TAG_RE.sub("", text)
        from html import unescape
        text = unescape(text)
    return text.strip()


def parse_page_selection(spec, count):
    if not spec:
        return list(range(1, min(count, 12) + 1))
    sel = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            sel.update(range(int(a), int(b) + 1))
        elif part:
            sel.add(int(part))
    return sorted(i for i in sel if 1 <= i <= count)


def write_previews(pages, preview_dir, spec):
    if Image is None:
        log("Pillow not installed - cannot write previews")
        return
    os.makedirs(preview_dir, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except Exception:
        font = ImageFont.load_default()
    for idx in parse_page_selection(spec, len(pages)):
        page = pages[idx - 1]
        im = Image.open(io.BytesIO(page.image_bytes)).convert("RGB")
        draw = ImageDraw.Draw(im, "RGBA")
        W, H = im.size
        for p in page.panels:
            x0, y0 = p["x"] * W, p["y"] * H
            x1, y1 = x0 + p["w"] * W, y0 + p["h"] * H
            if "view" in p:
                v = p["view"]
                draw.rectangle([v["x"] * W, v["y"] * H, (v["x"] + v["w"]) * W, (v["y"] + v["h"]) * H],
                               outline=(0, 120, 255, 200), width=3)
            draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0, 255), width=6)
            draw.rectangle([x0, y0, x0 + 70, y0 + 60], fill=(255, 0, 0, 220))
            draw.text((x0 + 10, y0 + 4), str(p["order"]), fill=(255, 255, 255, 255), font=font)
        out = os.path.join(preview_dir, "page_%04d.jpg" % idx)
        im.save(out, quality=80)
    log("Previews written to %s" % preview_dir)


# --------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help=".kfx (needs calibre + KFX Input plugin) or an EPUB produced by KFX Input")
    ap.add_argument("-o", "--output", help="output .cbz (default: input name with .cbz)")
    ap.add_argument("--sidecar", action="store_true", help="also write <output>.panels.json next to the CBZ")
    ap.add_argument("--keep-epub", metavar="PATH", help="keep the intermediate EPUB at PATH (KFX input only)")
    ap.add_argument("--preview", metavar="DIR", help="write page images with panel overlays into DIR")
    ap.add_argument("--preview-pages", metavar="SPEC", help="which pages to preview, e.g. 1-10,25 (default: first 12)")
    ap.add_argument("--calibre-debug", metavar="PATH", help="path to calibre-debug executable")
    ap.add_argument("--version", action="version", version="kfx2cbz %s" % __version__)
    args = ap.parse_args(argv)

    src = os.path.abspath(args.input)
    if not os.path.isfile(src):
        raise SystemExit("input not found: %s" % src)
    ext = os.path.splitext(src)[1].lower()
    out = os.path.abspath(args.output) if args.output else os.path.splitext(src)[0] + ".cbz"
    if os.path.abspath(out) == src:
        raise SystemExit("output would overwrite input")

    tmpdir = None
    try:
        if ext in (".kfx", ".kpf", ".kfx-zip", ".azw8"):
            if args.keep_epub:
                epub = os.path.abspath(args.keep_epub)
            else:
                tmpdir = tempfile.mkdtemp(prefix="kfx2cbz-")
                epub = os.path.join(tmpdir, "book.epub")
            kfx_to_epub(src, epub, args.calibre_debug)
            source_type = "kfx"
        elif ext == ".epub":
            epub = src
            source_type = "epub"
        else:
            raise SystemExit("unsupported input type %s (expected .kfx or .epub)" % ext)

        build(epub, out, sidecar=args.sidecar, preview_dir=args.preview, preview_pages=args.preview_pages,
              source_type=source_type, source_name=os.path.basename(src))
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
