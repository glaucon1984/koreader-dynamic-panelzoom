# kfx2cbz — keep Kindle panel data when converting comics to CBZ

Kindle comics bought from Amazon ship as KFX files that contain, besides the
page images, the publisher's **panel-by-panel view** data: for every page a
list of panel rectangles and the order in which they should be read
("Region Magnification" / "Virtual Panels", `yj_publisher_panels`).

`kfx2cbz.py` turns a DRM-free KFX comic into a plain **CBZ** and preserves that
data as a small `panels.json` file inside the archive. Any comic reader opens
the CBZ as usual (the JSON is ignored, images are just `0001.jpg`, `0002.jpg`,
...). KOReader with the Dynamic Panel Zoom plugin from this repository reads
`panels.json` and shows the publisher's panels instead of detecting them.

```
KFX ──(calibre "KFX Input" plugin)──▶ EPUB with app-amzn-magnify markup ──(kfx2cbz)──▶ CBZ
                                                                                     ├── 0001.jpg … 0366.jpg
                                                                                     ├── panels.json   ← panel rectangles + reading order
                                                                                     └── ComicInfo.xml ← standard metadata (title, author, …)
```

There are two ways to use it:

* **calibre plugin "CBZ Output"** (recommended): adds CBZ as an output format
  to calibre, so the normal *Convert books* button does everything.
* **command line** `kfx2cbz.py` for scripting.

## calibre plugin: CBZ Output

1. Install jhowell's **KFX Input** plugin in calibre (Preferences → Plugins →
   Get new plugins → "KFX Input") if you have not already.
2. Get `CBZ Output.zip` from the [releases](https://github.com/tarcisiotm/koreader-dynamic-panelzoom/releases)
   page, or build it yourself with `python build_calibre_plugin.py` (written to `dist/`).
3. Preferences → Plugins → **Load plugin from file** → pick the zip → restart calibre.
4. Add the DRM-free KFX to your library, select it, **Convert books**, choose
   **CBZ** as the output format on the top right, OK. The CBZ format is added
   to the book; send it to your device like any other format.

The output page of the conversion dialog ("CBZ Output") has two options,
to leave out `panels.json` or `ComicInfo.xml`. Both are written by default.

Because it is a regular output format it also works for bulk conversion, on
the command line (`ebook-convert book.kfx book.cbz`), and for **automatic
conversion when sending to a device**: set CBZ as the preferred output format
(Preferences → Behavior) and make sure your device/driver accepts CBZ, then
*Send to device* converts KFX comics on the fly.

Any fixed-layout, image-per-page book can be converted (EPUB comics too); the
panel data is only present when the source carries it (Kindle comics with
"Panel View").

## Command line tool

### Requirements

* Python 3.9+ with `lxml` and `Pillow` (`pip install -r requirements.txt`)
* [calibre](https://calibre-ebook.com/) with jhowell's **KFX Input** plugin
  (Preferences → Plugins → Get new plugins → "KFX Input")
* A KFX file **without DRM** (the tool does not touch DRM in any way).

### Usage

```bash
# KFX in, CBZ out (next to the input, same name)
python kfx2cbz.py "My Comic.kfx"

# choose the output, also keep a copy of the JSON next to the CBZ
python kfx2cbz.py "My Comic.kfx" -o "My Comic.cbz" --sidecar

# check the extracted panels visually: draws numbered boxes on a few pages
python kfx2cbz.py "My Comic.kfx" --preview previews --preview-pages 1-12,40

# already converted the KFX to EPUB with KFX Input? Feed the EPUB directly
python kfx2cbz.py "My Comic.epub"
```

Options:

| option | meaning |
| --- | --- |
| `-o/--output PATH` | output CBZ (default: input name with `.cbz`) |
| `--sidecar` | also write `<output>.panels.json` next to the CBZ (useful for readers that cannot read inside archives) |
| `--keep-epub PATH` | keep the intermediate EPUB |
| `--preview DIR` | write page images with red panel boxes (+ blue Kindle zoom regions) into DIR |
| `--preview-pages SPEC` | which pages to preview, e.g. `1-10,25` (default: first 12) |
| `--calibre-debug PATH` | path to `calibre-debug` if it is not on `PATH` or in the default install location |

The KFX → EPUB step is done by calling `calibre-debug -r "KFX Input" -- in.kfx out.epub`;
an EPUB produced by calibre's normal conversion pipeline (Convert books → EPUB)
works too, the tool understands both the inline styles of KFX Input and the
flattened class-based CSS of calibre.

## panels.json format

```json
{
  "format": "comic-panels",
  "version": 1,
  "generator": "kfx2cbz 0.1.0",
  "reading_direction": "ltr",
  "source": { "type": "kfx", "asin": "B01NA69LSR", "title": "The Ghost in the Shell Vol. 1" },
  "page_count": 366,
  "panel_count": 2244,
  "pages": [
    {
      "index": 26, "file": "0026.jpg", "width": 1344, "height": 1920, "spread": "left",
      "panels": [
        { "order": 1, "x": 0.06639, "y": 0.0553, "w": 0.20103, "h": 0.29287,
          "view": { "x": 0.0665, "y": 0.0553, "w": 0.201, "h": 0.29296 } },
        { "order": 2, "x": 0.06732, "y": 0.35177, "w": 0.19589, "h": 0.26505, "view": { "...": "..." } }
      ]
    }
  ]
}
```

* `index` — 1-based page number of the CBZ (readers sort the images by file name).
* `x, y, w, h` — the panel rectangle as **fractions of the page image**
  (`x, y` top-left corner, `w, h` size). Multiply by the image size in pixels
  to get pixels. This makes the data independent of the resolution a reader
  renders the page at.
* `order` — the publisher's reading order on that page (1 = first).
* `view` — optional. The region Kindle actually shows when the panel is
  magnified: the panel plus a little context, fitted to the device aspect
  ratio. Readers may ignore it.
* `spread` — `left`, `right` or `center`, taken from the EPUB spine
  (`page-spread-*` properties); informational.
* A page listed with an empty `panels` array has no panel view on Kindle
  (cover, credits, ...) and should be shown whole.

The file is deliberately reader-agnostic; nothing in it is Kindle specific,
so it can also be produced by hand or by other tools (e.g. a Kaito0-style
panel JSON could be converted into it).

## How the data is recovered

KFX Input converts KFX "publisher panels" into the KF8 region magnification
markup: on every page `<div id="magnify_source_N">` gives the tap rectangle in
a virtual viewport (`<meta name="viewport" content="width=2000, height=2857">`)
whose aspect ratio equals the page image, and the associated `<a
data-app-amzn-magnify='{"ordinal": n, ...}'>` carries the reading order. The
matching `<div id="magnify_target_N">` contains an `overflow:hidden` box with a
scaled, offset copy of the page image; mapping the box back through that scale
and offset gives the zoomed region (`view`).

## Compatibility notes

* The page images are stored unchanged (no re-encoding).
* `ComicInfo.xml` (ComicRack format) carries title, author, publisher,
  summary, date, page count, language, `Manga` flag and a link to the Amazon
  page (ASIN). Most readers, servers (Komga, Kavita, ...) and taggers read it.
* MuPDF (the engine behind KOReader's CBZ support) only treats image files as
  pages, so `panels.json` and `ComicInfo.xml` do not show up as pages.
