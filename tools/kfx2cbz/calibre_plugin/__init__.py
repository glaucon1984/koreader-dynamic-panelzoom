#!/usr/bin/env python3
"""
calibre "CBZ Output" plugin.

Adds CBZ as a conversion *output* format to calibre. Image based comics
(Kindle KFX books via jhowell's "KFX Input" plugin, fixed-layout EPUBs, ...)
become a plain CBZ with the page images plus:

  * panels.json   - the publisher's panel rectangles and reading order
                    ("Kindle Panel View"), for readers that support it
                    (KOReader + Dynamic Panel Zoom plugin)
  * ComicInfo.xml - standard comic metadata (ComicRack format)

Because it is a regular output format, it works everywhere calibre converts:
Convert books (single/bulk), the ebook-convert command line, and automatic
conversion when sending to a device whose preferred format is CBZ.

The heavy lifting is done by kfx2cbz.py (shared with the command line tool).
"""

from calibre.customize.conversion import OptionRecommendation, OutputFormatPlugin

__license__ = "MIT"
__copyright__ = "2026, koreader-dynamic-panelzoom contributors"

PLUGIN_VERSION = (0, 2, 0)


class CBZOutput(OutputFormatPlugin):
    name = "CBZ Output"
    author = "koreader-dynamic-panelzoom contributors"
    version = PLUGIN_VERSION
    minimum_calibre_version = (6, 0, 0)
    supported_platforms = ["windows", "osx", "linux"]
    file_type = "cbz"
    commit_name = "cbz_output"
    description = ("Convert image based comics (e.g. Kindle KFX via the KFX Input plugin) to CBZ, "
                   "keeping the publisher's panel view data in panels.json and metadata in ComicInfo.xml")

    options = {
        OptionRecommendation(
            name="cbz_no_panels_json", recommended_value=False, level=OptionRecommendation.LOW,
            help="Do not write panels.json (the panel rectangles and reading order) into the CBZ."),
        OptionRecommendation(
            name="cbz_no_comicinfo", recommended_value=False, level=OptionRecommendation.LOW,
            help="Do not write ComicInfo.xml (title, author, publisher, ... in ComicRack format) into the CBZ."),
    }

    # Comics are pictures: keep the pipeline from doing text-oriented work.
    recommendations = {
        ("remove_first_image", False, OptionRecommendation.HIGH),
        ("insert_metadata", False, OptionRecommendation.HIGH),
        ("linearize_tables", False, OptionRecommendation.HIGH),
    }

    def gui_configuration_widget(self, parent, get_option_by_name, get_option_help, db, book_id=None):
        from calibre_plugins.cbz_panels_output.cbz_output import PluginWidget
        return PluginWidget(parent, get_option_by_name, get_option_help, db, book_id)

    def convert(self, oeb_book, output, input_plugin, opts, log):
        from calibre_plugins.cbz_panels_output.kfx2cbz import __version__, collect_pages, write_cbz
        from calibre_plugins.cbz_panels_output.oeb_source import OebSource

        self.oeb = oeb_book
        log.info("CBZ Output plugin %s (kfx2cbz %s)" % (".".join(map(str, PLUGIN_VERSION)), __version__))

        def plog(msg):
            log.info("CBZ Output: " + msg)

        source = OebSource(oeb_book)
        md = source.metadata
        log.info("CBZ Output: title=%r authors=%r direction=%s input=%s" % (
            md.get("title"), md.get("authors"), md.get("reading_direction"),
            getattr(input_plugin, "name", "?")))

        self.report_progress(0.05, "Collecting pages and panel data")
        pages = collect_pages(source, log=plog)
        if not pages:
            raise ValueError("CBZ Output: no image pages found. CBZ output needs an image based "
                             "(fixed layout) comic, e.g. a Kindle KFX comic converted with the KFX Input plugin.")

        with_panels = sum(1 for p in pages if p.panels)
        if with_panels == 0:
            log.warn("CBZ Output: no panel data found in this book; writing a plain CBZ")

        self.report_progress(0.6, "Writing CBZ")
        source_type = "kfx" if "kfx" in getattr(input_plugin, "name", "").lower() else "epub"
        write_cbz(pages, source, output, source_type=source_type, source_name=None,
                  include_panels=not opts.cbz_no_panels_json,
                  include_comicinfo=not opts.cbz_no_comicinfo, log=plog)
        self.report_progress(1.0, "Done")
