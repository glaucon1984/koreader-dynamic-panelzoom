#!/usr/bin/env python3
"""Build the calibre 'CBZ Output' plugin zip from calibre_plugin/ + kfx2cbz.py.

    python build_calibre_plugin.py            -> dist/CBZ Output.zip
    python build_calibre_plugin.py -o my.zip
Install it in calibre with Preferences -> Plugins -> Load plugin from file
(or `calibre-customize -a "dist/CBZ Output.zip"`).
"""
import argparse
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(HERE, "calibre_plugin")
FILES = [
    (os.path.join(PLUGIN_DIR, "__init__.py"), "__init__.py"),
    (os.path.join(PLUGIN_DIR, "cbz_output.py"), "cbz_output.py"),
    (os.path.join(PLUGIN_DIR, "oeb_source.py"), "oeb_source.py"),
    (os.path.join(PLUGIN_DIR, "plugin-import-name-cbz_panels_output.txt"), "plugin-import-name-cbz_panels_output.txt"),
    (os.path.join(HERE, "kfx2cbz.py"), "kfx2cbz.py"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-o", "--output", default=os.path.join(HERE, "dist", "CBZ Output.zip"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src, name in FILES:
            zf.write(src, name)
    print("Wrote", args.output)


if __name__ == "__main__":
    main()
