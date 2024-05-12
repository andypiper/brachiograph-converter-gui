# brachiograph-converter-gui 🖌️
![Version](https://img.shields.io/badge/version-0.1.0-blue.svg?cacheSeconds=2592000)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://mit-license.org/)

A desktop app for converting images to [BrachioGraph](https://www.brachiograph.art/) format.

tl;dr I wanted a GUI app for quickly converting images to draw with a BrachioGraph, I really liked [the one that Henry Triplette made](https://github.com/henrytriplette/python-brachiograph-gui), but then PySimpleGUI went to a paid model. After thinking about upgrading (or migrating to FreeSimpleGUI), I decided to write a new-but-similar thing using PySides / QT instead. That thing, is this thing.

This app uses the `linedraw.py` module for converting images to JSON for the BrachioGraph, [originally written by Lingdong Huang](https://github.com/LingDong-/linedraw).

## Install

```sh
pip3 install -r requirements.txt
```

## Usage

```sh
python brachiograph_converter_gui.py
```

## 👤 Author

**Andy Piper**

* [Website](https://andypiper.org)
* GitHub: [@andypiper](https://github.com/andypiper)
* Fediverse [@andypiper@macaw.social](https://macaw.social/andypiper)

### Additional credits

* Henry Triplette (concept / original python-brachiograph-gui)
* Lingdong Huang (linedraw routines)
* Daniele Procida (BrachioGraph project)
* Streamline icon set

## 📝 License

Copyright © 2024 [Andy Piper](https://github.com/andypiper).

This project is [MIT](https://mit-license.org/) licensed.

* Streamline icon is [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).
