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
- **Right-click** an image for the image menu. **tags** is one list of
  everything about the image, each with a count: main tags first (colour,
  tone, kind, mood, style), then your own tags (add or remove them right
  there), then everything else found (subjects, shape, source, folder,
  text, visually similar). Clicking a tag opens its **sub board**.
  **view palette** shows the image's 8 main colours by prominence with
  hex codes (click one to copy it); it's worked out the first time you
  look and kept with the image. Right-click on empty canvas for a short
  menu.
- **Links**: drag from the round handle beside an image onto another to
  link them with an arrow, or press L (with several images selected, L
  chains them in reading order). Links belong to the images, like notes.
  Right-click an arrow to reverse or remove it; "open link tree" in the
  image menu opens everything connected as a flowchart sub board.
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
  every colour), home bar timing, interface size (200% by default, on top
  of what Windows already scales), interface font (any installed font or
  a font file you add), board, tools, content, imports, keyboard & mouse.

## Board files

R Board saves `.brd` files: the same SQLite layout as BeeRef's `.bee`
(images, positions, and R Board's per-image data such as tags, notes,
links, palettes and what the content model read) plus a table of
board-level data (where you were looking, your tag list). `.bee` boards
open too; saving one writes a `.brd` next to it and leaves the `.bee` as
it was. Save as can still write a plain `.bee` for BeeRef.

## Content understanding

A small image model (OpenAI's CLIP, MIT licence) runs on your computer
through ONNX Runtime. It's downloaded once on first use from
huggingface.co/Xenova/clip-vit-base-patch32: the image model (89 MB) when
you first group by content, the text model (67 MB) only for searching by
meaning or matching custom tags by name. Nothing is uploaded. Once the
image model is installed, new images are read in the background (about
20 ms each) and the results are saved in the board.

- **Tags** for every image, in the image menu:
  - *kind*: album cover, poster, magazine page, product shot, interface,
    illustration and 25 more.
  - *mood* and *style* (calm, eerie, joyful… minimalist, Swiss graphic
    design, Frutiger Aero, rave…): judged against the rest of the board,
    so on a board that's all one era you still see what sets each image
    apart. Boards under 12 images use the plain best match.
  - *subjects*: up to three of 140 things (interior, car, flowers,
    headphones, neon sign…).
- **Group by content** (arrange menu, Ctrl+Shift+G): clusters images by
  what they show, names each group (poster, interior, album cover…),
  sorts each group by colour and labels it. Fewer/more groups slider.
- **Search by meaning**: Ctrl+F also finds images that look like what you
  type ("people on a sofa").
- **Custom tags** use the same matching as built-in labels: a tag's sub
  board shows your tagged images plus *suggested* ones, found from the
  tag's name and from the images you've tagged. Right-click a suggestion
  to add the tag; each confirmed example improves the next suggestions.
- Settings → content shows what's installed and can remove the models.

## Features

| Where | Feature | Shortcut |
|---|---|---|
| Arrange | By Dominant Color — rainbow order, using each image's strongest color | Shift+K |
| Arrange | By Average Color / By Lightness | |
| Arrange | Justified Rows (equal height, flush right edge) | Shift+J |
| Arrange | Masonry Columns / Equal-Size Grid | |
| Images | View Palette — the selection's (or board's) colours by prominence, with hex codes | Shift+P |
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
| Links | Link the selected image to another (or chain several) | L |
| Insert | Sync Are.na Channels — adds blocks added since import | |
| File | Import PureRef Board (2.x .pur) | |

You can also drop a `.pur` file or an Are.na link onto the window.

Layouts work on the current reading order, so "By Dominant Color" followed
by "Justified Rows" gives justified rows in color order. All arranging,
palettes and text reading can be undone.

Color statistics, palettes, recognised text and image content are cached
inside the board file, so they're computed once per image.

## Tests

```
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests
```

R Board's own tests are in `tests/rboard/`. Nine upstream tests fail
headless on Windows (window-manager and permission tests); they fail the
same way on unmodified BeeRef.

## License

R Board is free software under the GNU General Public License v3 (see
`LICENSE`), as is BeeRef, which it is based on: Copyright © 2021-2024
Rebecca Breu. If you share R Board, share its source code too.
