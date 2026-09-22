"""Options page for the CBZ Output plugin in calibre's conversion dialog.

The module name (cbz_output) and class name (PluginWidget) are what calibre
expects; see CBZOutput.gui_configuration_widget in __init__.py.
"""

from qt.core import QCheckBox, QFormLayout, QLabel, QSizePolicy, QSpacerItem

from calibre.gui2.convert import Widget


class PluginWidget(Widget):
    TITLE = "CBZ Output"
    HELP = "Options specific to CBZ output"
    COMMIT_NAME = "cbz_output"  # where option values are saved
    ICON = "mimetypes/zip.png"

    def __init__(self, parent, get_option, get_help, db=None, book_id=None):
        self.db = db
        self.book_id = book_id
        Widget.__init__(self, parent, ["cbz_no_panels_json", "cbz_no_comicinfo"])
        self.initialize_options(get_option, get_help, db, book_id)

    def setupUi(self, Form):
        Form.setObjectName("Form")
        Form.setWindowTitle("Form")
        Form.resize(588, 481)

        self.formLayout = QFormLayout(Form)
        self.formLayout.setObjectName("formLayout")

        self.opt_cbz_no_panels_json = QCheckBox(Form)
        self.opt_cbz_no_panels_json.setObjectName("opt_cbz_no_panels_json")
        self.opt_cbz_no_panels_json.setText("Do not write panels.json (panel view data for KOReader Dynamic Panel Zoom)")
        self.formLayout.addRow(self.opt_cbz_no_panels_json)

        self.opt_cbz_no_comicinfo = QCheckBox(Form)
        self.opt_cbz_no_comicinfo.setObjectName("opt_cbz_no_comicinfo")
        self.opt_cbz_no_comicinfo.setText("Do not write ComicInfo.xml (title, author, publisher, ...)")
        self.formLayout.addRow(self.opt_cbz_no_comicinfo)

        self.formLayout.addItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.help_label = QLabel(Form)
        self.help_label.setWordWrap(True)
        self.help_label.setOpenExternalLinks(True)
        self.help_label.setObjectName("help_label")
        self.help_label.setText(
            "<p>Writes the page images unchanged into a CBZ. When the source is a Kindle comic "
            "(KFX, converted by the <b>KFX Input</b> plugin) the publisher's panel rectangles and "
            "reading order are stored in <tt>panels.json</tt> inside the CBZ; other readers ignore that file.</p>"
            '<p>Documentation: <a href="https://github.com/tarcisiotm/koreader-dynamic-panelzoom">'
            "koreader-dynamic-panelzoom</a> (tools/kfx2cbz).</p>")
        self.formLayout.addRow(self.help_label)
