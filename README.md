# KOReader Dynamic Panel Zoom (fork with publisher panel data + calibre CBZ Output)

> **About this fork.** This repository is a fork of
> [tarcisiotm/koreader-dynamic-panelzoom](https://github.com/tarcisiotm/koreader-dynamic-panelzoom),
> which in turn forked [JorgeTheFox/koreader-dynamic-panelzoom](https://github.com/JorgeTheFox/koreader-dynamic-panelzoom)
> (inspired by Kaito0's [panelreader.koplugin](https://github.com/Kaito0/panelreader.koplugin)).
> All credit for the on-the-fly panel detection, the panel viewer and the
> reading features below goes to those authors. The code is MIT licensed
> (see [LICENSE](LICENSE)); this fork keeps that license.
>
> **What this fork adds**
> * The plugin can use *publisher supplied* panel data instead of detecting
>   panels: a `panels.json` inside the CBZ (or next to it) with the exact
>   panel rectangles and reading order. See
>   [Publisher panel data](#publisher-panel-data-kindle-comics-panelsjson).
> * `tools/kfx2cbz`: a calibre **CBZ Output** plugin and a command line tool
>   that convert DRM-free Kindle (KFX) comics to CBZ while preserving the
>   Kindle "Panel View" data as `panels.json`, plus `ComicInfo.xml` metadata.
> * Small fix: toggling "full page before/after" now refreshes cached page layouts.
>
> Nothing in this repository contains or downloads any comic. The tools only
> work on files you already own, and they do not remove DRM.

This fork modifies the original plugin to add more features such as:

- Optional display of the full page before the first panel and after the last panel
- Persistent settings
- Two-finger gesture to rotate the current panel (resets after turning the page)
- Two-finger spread gesture to focus on the frame defined by where the fingers initially landed
- Configurable full page refresh options (based on the excellent work by [darkpf](https://github.com/darkpf/koreader-dynamic-panel-plus/) in their fork)

A KOReader plugin that automatically detects and displays comic and manga panels one by one for a seamless reading experience on E-Ink devices. 

No pre-processing required—it analyzes the page on the fly. Optionally it uses publisher panel data when a comic carries it (see [Publisher panel data](#publisher-panel-data-kindle-comics-panelsjson)).

<p align="center">
  <img src="https://github.com/user-attachments/assets/839285a6-00c0-4308-82cb-ba637a2e0284" width="300" alt="Demo GIF showing Dynamic Panel Zoom in action" style="border: 5px solid #ccc; border-radius: 4px;">
</p>

## Features
- **🤖 Real-time Detection:** Analyzes pages instantly using KOReader's native engine.
- **📖 Focused View:** Centers each panel and masks adjacent content to reduce distractions.
- **⚡ Smart Pre-loading:** Renders the next panel in the background for zero-lag transitions.
- **🔄 Reading Direction:** Supports Left-to-Right (Western) and Right-to-Left (Manga).
- **🔍 Hold-to-Zoom Mode:** Long-press on any panel to instantly enter a free-zoom state with smart text padding to read cut-off speech bubbles or admire wide landscape art.

## Installation
1. Download the latest `dynamic_panelzoom.koplugin.zip` from the Releases page of this repository (the calibre `CBZ Output` plugin zip is published there too).
2. Unzip and copy the `dynamic_panelzoom.koplugin` folder to your KOReader's `plugins/` directory.
3. Restart KOReader.

## Usage
1. Open a comic (`.cbz`, `.pdf`, etc.) in "full page mode": fit = full and view mode = page (see the gif above).
2. Go to the top menu, tap on the document tab and check **Allow panel zoom**.
3. Select **Reading direction**:
   - **Left-to-Right (LTR)** for Western comics
   - **Right-to-Left (RTL)** for Manga/Eastern comics
4. **Standard panel settings** (Optional):
   - **Show adjacent page content:** Toggle whether parts of the page outside the current panel are masked or visible.
   - **Padding around panel:** Adds a margin (`0%` to `10%`) around the detected panel for the standard panel view.
5. **Hold-to-Zoom settings** (Optional):
   - **Hold-to-Zoom padding:** Adds a safe margin (`2%` to `20%`) around the detected panel to capture overlapping speech bubbles when long-pressing.
   - **Initial zoom level:** Choose how the zoom mode starts (`1.0x Fit` to `2.0x Heavy Zoom`).
6. **Navigation:**
   - Long-press on a panel to enable panel view.
   - Tap the **edges** of the screen to move between panels or pages.
   - **Hold (Long-press)** anywhere while viewing a panel to trigger the **Free Zoom Mode**.
   - Tap the **center** to exit panel view.

## Publisher panel data (Kindle comics, `panels.json`)

Detection on the fly works well for most pages, but some comics already carry
the *publisher's* panel rectangles and reading order — Kindle comics bought
from Amazon do ("Kindle Panel View"). This plugin can use that data instead of
guessing:

1. **Convert the comic to CBZ with calibre** (recommended workflow):
   1. In calibre install jhowell's **KFX Input** plugin (Preferences → Plugins
      → *Get new plugins* → "KFX Input") if you do not have it yet.
   2. Download `CBZ_Output.calibre-plugin.zip` from the
      [Releases](../../releases) page of this repository and install it with
      Preferences → Plugins → **Load plugin from file**, then restart calibre.
   3. Add the DRM-free KFX file to your library, select it and click
      **Convert books**. Choose **CBZ** as the *Output format* (top right)
      and press OK. calibre adds a CBZ format to the book.
   4. Send the CBZ to your device as usual (**Send to device**, or copy the
      file). Tip: with CBZ set as the preferred output format
      (Preferences → Behavior) calibre converts KFX comics automatically
      when you send them.

   The result is a normal CBZ (page images + `ComicInfo.xml`) that
   additionally contains a small `panels.json` with the panel rectangles and
   their order. Any comic reader opens that CBZ as usual.

   *Alternative:* the same converter exists as a command line script,
   `kfx2cbz-cli.zip` on the Releases page (`python kfx2cbz.py book.kfx`).
   Details for both in [`tools/kfx2cbz`](tools/kfx2cbz/README.md).
2. Open the CBZ in KOReader. The plugin looks for panel data in this order:
   * `<book>.cbz.panels.json` or `<book>.panels.json` next to the file (sidecar),
   * `panels.json` inside the archive (CBZ/CBT/...).

   When found, the top menu shows **Panel data file: found** in the Panel zoom
   menu, and panel-by-panel navigation uses the exact publisher panels in the
   publisher's reading order. Pages listed without panels (cover, credits)
   are shown whole. Pages missing from the file fall back to dynamic detection.
3. Options (Panel zoom menu → *Panel data file*):
   * **Use panel data file when available** — turn the feature off to force
     dynamic detection.
   * **Reload panel data file** / **Panel data file information** — re-read
     the file and show a summary (pages, panels, source, reading direction).
   * *Reading direction* gains an **Auto from panel data** entry that follows
     the direction declared in the file (falls back to LTR).

The file format is documented in the `kfx2cbz` README; it is plain JSON with
page-relative fractions, so it can also be written by hand or by other tools.

## Known Issues
- **Full page mode Only:** If you use the plugin without full page view, you may see some repeated panels.

- *Tested primarily on Linux (Native/AppImage) and Kindle Colorsoft (2025).*

## Credits & License
Inspired by Kaito0's [panelreader.koplugin](https://github.com/Kaito0/panelreader.koplugin), but built from scratch to use on-the-fly detection via Leptonica instead of pre-generated JSON files.

Licensed under the MIT License.
