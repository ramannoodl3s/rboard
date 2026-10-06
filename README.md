# R Board

A moodboard app for Windows: a fork of the reference image viewer
[BeeRef](https://github.com/rbreu/beeref) by Rebecca Breu, with colour
sorting, palettes, text reading, Are.na and PureRef import, sub boards,
notes, tags and a pen. Everything BeeRef does still works.
New code lives in `beeref/rboard/`; changes to BeeRef's own files are small
hooks (menus, item metadata, palette loading).

## Run from source

Needs Python 3.11 on Windows 10 or 11.

```
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\rboard.exe
```

## Interface (Softclub)

The interface follows the Softclub design in `design/softclub/`: six
themes (Carbon, Teal Room, Handset, Albumen, Pictogram, Blood Orange) plus
custom themes, lowercase labels, Helvetica Neue.

- **Home bar** (bottom right): undo, redo | file, add | arrange, image,
  find | pen, notes and tags | layers, view, settings. Hover an icon for
  its menu. It fades out after a moment (Settings → appearance) and comes
  back when the pointer nears the corner. Arrange commands work on the whole
  board when nothing is selected.
- **Right-click** an image for the image menu: its colour family, tone,
  shape, likely-album-cover guess, source, text, note and tags, each with a
  count. Clicking one opens a **sub board**. Right-click on empty canvas
  for a short menu.
- **Sub boards** open in their own window with linked copies of the
  images: arranging, sorting and removing stay local, while notes, tags and
  pen marks are shared with the main board (and undo there). They live in
  memory only: closing a window caches it, and they're discarded when the
  main board changes or the app closes. The **layers** menu lists them
  (open / cached, nested under the board they came from).
- **Notes** (N): a note per image, shown as a callout on hover or
  selection (or always: Shift+N).
- **Tags** (T): your own tags, from the image menu or the notes menu.
- **Pen** (P): freehand, circle, arrow and eraser in 8 colours and 3
  widths. Marks on an image move with it; Esc stops drawing.
- **Settings**: theme picker, custom theme editor (four base colours, or
  every colour), home bar timing, board, tools, imports, keyboard & mouse.

## Features

| Where | Feature | Shortcut |
|---|---|---|
| Arrange | By Dominant Color — rainbow order, using each image's strongest color | Shift+K |
| Arrange | By Average Color / By Lightness | |
| Arrange | Justified Rows (equal height, flush right edge) | Shift+J |
| Arrange | Masonry Columns / Equal-Size Grid | |
| Images | Generate Palette — swatches + hex codes for the selection or board; Ctrl+C on it copies the codes | Shift+P |
| Images | Copy Text from Image (Windows OCR, no download) | Ctrl+Shift+T |
| Images | Read Text in All Images — makes image text searchable | |
| Images | Open Source Link (Are.na block page) | Ctrl+L |
| Edit | Find Text — searches image text, notes, file names, links | Ctrl+F |
| Edit | Find by Color — selects images containing a color | Ctrl+Shift+F |
| Edit | Select Duplicates — keeps the largest copy of each | |
| View | Value Study — images as 2–8 gray tones | Shift+G |
| Insert | From Are.na — paste a channel or block link | Ctrl+Shift+I |
| Pen | Draw on images and the canvas | P |
| Notes | Note on the selected image / always show notes | N / Shift+N |
| Tags | Tag the selected images | T |
| Insert | Sync Are.na Channels — adds blocks added since import | |
| File | Import PureRef Board (2.x .pur) | |

You can also drop a `.pur` file or an Are.na link onto the window.

Layouts work on the current reading order, so "By Dominant Color" followed
by "Justified Rows" gives justified rows in color order. All arranging,
palettes and text reading can be undone.

Color statistics and recognised text are cached inside the `.bee` file, so
they're computed once per image.

## Tests

```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests
```

R Board's own tests are in `tests/rboard/`. Ten upstream tests fail
headless on Windows (window-manager and permission tests); they fail the
same way on unmodified BeeRef.

## License

R Board is free software under the GNU General Public License v3 (see
`LICENSE`), as is BeeRef, which it is based on: Copyright © 2021-2024
Rebecca Breu. If you share R Board, share its source code too.
