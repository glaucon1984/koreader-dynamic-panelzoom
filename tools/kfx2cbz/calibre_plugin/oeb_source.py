"""ComicSource adapter over calibre's in-memory OEB book (used by the CBZ Output plugin)."""

import posixpath
from urllib.parse import quote, unquote

from lxml import etree

from calibre_plugins.cbz_panels_output.kfx2cbz import ComicSource, asin_from_identifier


class OebSource(ComicSource):
    def __init__(self, oeb):
        self.oeb = oeb
        self.metadata = self._read_metadata()

    # -- helpers -----------------------------------------------------------

    def _meta_values(self, term):
        try:
            items = getattr(self.oeb.metadata, term)
        except Exception:
            return []
        out = []
        for it in items or []:
            try:
                s = str(it).strip()
            except Exception:
                s = ""
            if s:
                out.append((s, it))
        return out

    def _read_metadata(self):
        md = {}
        first = lambda term: (self._meta_values(term) or [(None, None)])[0][0]
        md["title"] = first("title")
        md["publisher"] = first("publisher")
        md["language"] = first("language")
        md["description"] = first("description")
        md["date"] = first("date")
        md["authors"] = [v for v, _ in self._meta_values("creator")]
        md["asin"] = None
        for value, item in self._meta_values("identifier"):
            scheme = ""
            try:
                scheme = str(item.scheme or "")
            except Exception:
                for k, v in getattr(item, "attrib", {}).items():
                    if str(k).endswith("scheme"):
                        scheme = str(v)
            md["asin"] = asin_from_identifier(value, scheme) or md["asin"]
        ppd = getattr(self.oeb.spine, "page_progression_direction", None)
        md["reading_direction"] = ppd if ppd in ("ltr", "rtl") else "ltr"
        return md

    def _item(self, href):
        hrefs = self.oeb.manifest.hrefs
        for cand in (href, unquote(href), quote(href, safe="/%:@&=+$,;~!*'()")):
            item = hrefs.get(cand)
            if item is not None:
                return item
        raise KeyError(href)

    # -- ComicSource -------------------------------------------------------

    def spine_items(self):
        for item in self.oeb.spine:
            if getattr(item, "linear", True) is False:
                continue
            yield item.href, None

    def read(self, href):
        item = self._item(href)
        data = item.data
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode("utf-8")
        return item.bytes_representation

    def xhtml_root(self, href):
        item = self._item(href)
        data = item.data
        if isinstance(data, etree._Element):
            return data
        if isinstance(data, (bytes, str)):
            return etree.fromstring(data if isinstance(data, bytes) else data.encode("utf-8"),
                                    parser=etree.XMLParser(recover=True, huge_tree=True))
        return None

    def css_text(self, href):
        try:
            item = self._item(href)
        except KeyError:
            return ""
        try:
            return item.unicode_representation
        except Exception:
            return ""

    def resolve(self, base_href, rel):
        try:
            item = self._item(base_href)
            return item.abshref(rel.split("#", 1)[0])
        except Exception:
            return ComicSource.resolve(self, base_href, rel)

    def media_type(self, href):
        try:
            return self._item(href).media_type
        except KeyError:
            return None

    def cover_href(self):
        guide = self.oeb.guide
        try:
            if "cover" in guide:
                href = guide["cover"].href.split("#", 1)[0]
                if (self.media_type(href) or "").startswith("image/"):
                    return href
        except Exception:
            pass
        try:
            for cid in self.oeb.metadata.cover:
                item = self.oeb.manifest.ids.get(str(cid))
                if item is not None and (item.media_type or "").startswith("image/"):
                    return item.href
        except Exception:
            pass
        return None
