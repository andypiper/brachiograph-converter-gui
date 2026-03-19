# brachiograph-converter-gui

![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)

Desktop application for converting images to [BrachioGraph](https://www.brachiograph.art/) JSON drawing format.

tl;dr I wanted a GUI app for quickly converting images to draw with a BrachioGraph, I really liked [the one that Henry Triplette made](https://github.com/henrytriplette/python-brachiograph-gui), but then PySimpleGUI went to a paid model. After thinking about upgrading (or migrating to FreeSimpleGUI), I decided to write a new-but-similar thing using PySides / QT instead. That thing, is this thing.

## Background

Provides a graphical interface for the image-to-JSON conversion workflow used with BrachioGraph pen plotters. Supports loading images, adjusting conversion parameters, previewing results, and uploading output to a BrachioGraph device via SFTP.

Uses the `linedraw.py` module for image processing, [originally written by Lingdong Huang](https://github.com/LingDong-/linedraw) with modifications for BrachioGraph.

## Install

Requires [uv](https://docs.astral.sh/uv/).

No separate install step is needed. Run directly with:

```sh
uv run brachiograph_converter_gui.py
```

uv will handle dependency installation automatically on first run.

## Usage

```sh
uv run brachiograph_converter_gui.py
```

The application provides:

- **Image** — select an image file (JPG, PNG, TIFF, WebP)
- **Contours** — edge detection detail (0–10, default 2; lower values produce more detail)
- **Hatch** — hatching line spacing (1–100, default 16; lower values produce more detail)
- **Repeat contours** — repeat outer edges for emphasis (0–10, default 0)
- **Generate** — convert the image; output SVG and JSON are saved to the `images/` directory
- **Upload** — send a JSON file to a BrachioGraph device over SFTP
- **SFTP Settings** — configure hostname, username, password, and remote directory
- **View Files** — open the `images/` output directory

SFTP connection settings and last-used image directory are persisted in `~/.brachiograph_converter.json`.

## Maintainers

[@andypiper](https://github.com/andypiper)

## Thanks

- Henry Triplette — concept and original [python-brachiograph-gui](https://github.com/henrytriplette/python-brachiograph-gui)
- Lingdong Huang — [linedraw](https://github.com/LingDong-/linedraw) image processing routines
- Daniele Procida — [BrachioGraph](https://www.brachiograph.art/) project
- Streamline icon set

## License

[MIT](LICENSE) © 2024 Andy Piper

Streamline icon: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)
