# R Board

A moodboard app for Windows: a fork of the reference image viewer
[BeeRef](https://github.com/rbreu/beeref) by Rebecca Breu, with colour
sorting, palettes, text reading, PureRef import, sub boards, links,
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

## Portable build

```
.venv\Scripts\pip install -r requirements\build.txt
.venv\Scripts\pyinstaller RBoard.spec --noconfirm
```

This makes `dist\R Board\` with `R Board.exe`; zip that folder to share
it. Nothing needs installing on the other computer. The content model is
downloaded on first use, as when running from source.

## Interface (Softclub)

The interface follows the Softclub design (made in Claude Design): six
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
  Colour tags go by area: an image is "yellow" when yellow covers a good
  part of it (15%), and a small strong colour shows as *accent · blue*.
  **colour study** switches the image to 8 flat regions: *value* (each
  region in the grey of its true lightness, CIELAB L\*), *colour* (each
  in its average colour) or *off*; while it's on, the menu lists the 8
  hex codes with how much of the image each covers. With several images
  selected, the menu can export them as one image, laid out as on the
  board. Right-click on empty canvas for a short menu.
- **Links**: drag from the round handle beside an image onto another to
  link them with an arrow, or press L (with several images selected, L
  chains them in reading order). Links belong to the images, like notes.
  Right-click an arrow to reverse or remove it; "open link tree" in the
  image menu opens everything connected as a flowchart sub board.
- **Sub boards** open in an area of the main window (see Areas) with
  linked copies of the images: arranging, sorting and removing stay local, while notes, tags and
  pen marks are shared with the main board (and undo there). Make one from
  a tag (right-click), a link tree, or **new sub board…** (layers menu,
  Ctrl+Alt+B): tags to include (all or any of them) and tags to leave
  out, e.g. *yellow, nighttime* without *blue*. Words that aren't tags on
  the board are matched by what the images show (needs the content
  model's text part).
- The **layers** menu lists every sub board and tree from this session,
  nested under the board they came from, with where it is (area, window,
  closed) and whether it's kept. Hover one to show it, pop it out to a
  window or dock it back, keep it in the board file, or remove it. Kept sub boards and all link trees are
  saved in the `.brd` with their layouts and come back next time; the
  rest are discarded when the app closes.
- **Notes** (Alt+C): a note per image, shown as a callout on hover or
  selection (or always: Alt+Shift+C).
- **Tags** (T): your own tags, from the image menu or the notes menu.
- **Pen** (Ctrl+Shift+D): freehand, circle, arrow and eraser in 8 colours and 3
  widths. Marks on an image move with it; Esc stops drawing.
- **Settings**: theme picker, custom theme editor (four base colours, or
  every colour), home bar timing, interface size (200% by default, on top
  of what Windows already scales), interface font (any installed font or
  a font file you add), board, tools, content, keyboard & mouse.

## Areas

The main window is divided into areas the way Blender divides its window
([Blender manual: Areas](https://docs.blender.org/manual/en/latest/interface/window_system/areas.html)).
Each area shows one board, chosen from the menu at the left of its
header (like Blender's editor type menu).

- **Resizing**: drag a border. Ctrl snaps to halves, thirds and quarters;
  Shift moves aligned borders together.
- **Splitting**: drag from an area corner left/right to split it
  vertically, up/down to split it horizontally.
- **Joining**: drag from a corner into the neighbouring area (they must
  share a whole edge); the area being absorbed is darkened. Dragging into
  the middle of another area replaces that area.
- **Swapping contents**: Ctrl-drag from a corner to another area.
- **New window**: Shift-drag from a corner (sub boards).
- Esc or right-click before releasing cancels.
- **Area options** (right-click a border): Vertical Split, Horizontal Split
  (Tab switches), Join Left/Right/Up/Down, Swap Areas.
- **View ‣ Area**: Toggle Maximize Area (Ctrl+Space, *back to previous*
  in the header), Focus Mode (Ctrl+Alt+Space), Duplicate Area into New
  Window, Close Area.

The layout is saved in the `.brd` with the kept sub boards.

## Board files

R Board saves `.brd` files: the same SQLite layout as BeeRef's `.bee`
(images, positions, and R Board's per-image data such as tags, notes,
links, palettes and what the content model read) plus a table of
board-level data (where you were looking, your tag list, kept sub
boards and link trees, and the area layout). `.bee` boards
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
- **Group by content** (arrange menu, Ctrl+Alt+G): clusters images by
  what they show, names each group (poster, interior, album cover…),
  sorts each group by colour and labels it. Fewer/more groups slider.
- **Search by meaning**: find text (Ctrl+Shift+F) also finds images that look like what you
  type ("people on a sofa").
- **Custom tags** use the same matching as built-in labels: a tag's sub
  board shows your tagged images plus *suggested* ones, found from the
  tag's name and from the images you've tagged. Right-click a suggestion
  to add the tag; each confirmed example improves the next suggestions.
- Settings → content shows what's installed and can remove the models.

## Features

| Where | Feature | Shortcut |
|---|---|---|
| File | New board / open / save / save as | Ctrl+K / Ctrl+L / Ctrl+S / Ctrl+Shift+S |
| File | Export board / selection as one image / selected images | Ctrl+E / Ctrl+Shift+E / Ctrl+Shift+I |
| File | Import PureRef Board (2.x .pur) | |
| Add | Images / text on the canvas | Ctrl+I / Ctrl+N |
| Arrange | Arrange optimally | Ctrl+P |
| Arrange | Same height / width / size | Ctrl+Alt+← / → / ↑ |
| Arrange | Justified Rows (equal height, flush right edge) | Shift+J |
| Arrange | Masonry Columns / Equal-Size Grid | |
| Arrange | Sort by Colour — overall colour (by area), accent colour, lightness, colourfulness, warm to cool or closeness to a colour, with a slider to choose which images take part; on the board or as a sub board | Shift+K |
| Arrange | Group by Content | Ctrl+Alt+G |
| Images | Colour Study — cycle value / colour / off | Shift+S |
| Images | Grayscale / crop / reset crop / reset transforms | Alt+G / Ctrl+Alt+Shift+C / Ctrl+Shift+C / Ctrl+Shift+T |
| Images | Copy Text from Image (Windows OCR, no download) | Ctrl+Alt+T |
| Images | Read Text in All Images — makes image text searchable | |
| Images | Open Source Link (e.g. the Are.na block page) | Ctrl+Shift+O |
| Edit | Find Text — searches image text, notes, tags, file names, links | Ctrl+Shift+F |
| Edit | Find by Color — selects images containing a color | Ctrl+Alt+F |
| Edit | Select Duplicates — keeps the largest copy of each | |
| Pen | Draw on images and the canvas | Ctrl+Shift+D |
| Notes | Note on the selected image / always show notes | Alt+C / Alt+Shift+C |
| Tags | Tag the selected images | T |
| Links | Link the selected image to another (or chain several) | L |
| Layers | New Sub Board — tags to include and leave out | Ctrl+Alt+B |
| View | Maximize area / focus mode | Ctrl+Space / Ctrl+Alt+Space |
| View | Always on top / fullscreen / settings | Ctrl+Shift+A / Ctrl+F / Ctrl+U |

You can also drop a `.pur` file onto the window, or a folder of images.
If the folder has a `links.txt` (file name, a tab, its link; one per
line), the images get those source links. The separate Are.na Grabber
writes one, so Are.na images still link back to their blocks.

Shortcuts follow PureRef's where R Board has the same function (all can
be changed in Settings → keyboard & mouse). Esc clears the selection.

Big imports load everything first, with a progress bar, and put the
images on the board in one go. All arranging, sorting and text reading
can be undone.

Colour statistics (including each image's 8-colour breakdown),
recognised text and image content are cached
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
