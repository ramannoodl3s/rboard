Softclub is the interface theme for the moodboard app. It is matte, rounded and lowercase, and it exists to step back: the user's images are the only loud thing on screen.

## Content fundamentals

Write UI copy in lowercase, except filenames, proper nouns and key names: "add images", "export board", "fit to window". Lead with the verb. No exclamation marks, no emoji, no "please", no marketing voice.

- Empty board: "drop images here". Confirm: "delete 3 images?" with the body "this can't be undone."
- Errors state the cause, then the fix: "couldn't read photo.heic. convert it to jpg or png."
- Counts and values are plain: "24 images", "100%", "640 px". Use middle dots to join status facts: "5 images · 1 selected".
- Section headers use `label` (10px, tracked, UPPERCASE, `ink-muted`) and nothing else is uppercase.

## Visual foundations

**Images first.** Board images are never framed, rounded, shadowed, tinted or overlaid (`radius-image` is 0). Chrome sits around them in neutral tones; if anything competes with an image, make the chrome quieter.

**Colour.** Neutrals carry the interface: `canvas` behind images, `surface` for docked panels, `surface-raised` for floating things (toolbar, menus, dialogs, zoom pill), `surface-sunken` for fields. Text is `ink`; secondary text, placeholders and inactive icons are `ink-muted`. The single `accent` marks the active tool, the primary button, links, the slider fill, the selected row (as `accent-soft`), the selection outline (`selection`) and the keyboard focus ring (`focus-ring`). Use `danger` only for destructive text and the delete button, always with a word. The `palette-*` swatches belong to colour tags only. No gradients, glass, glow or tinted overlays in the chrome. See the Themes section for the six palettes.

**Type.** Helvetica Neue through the `sans` stack (`--font-sans`: Helvetica Neue, Helvetica, Nimbus Sans, Arial). Light 300 is for `display` and `heading` only; 400 for `body` and `caption`; 500 for `title`, `body-strong`, `label` and buttons. No italics and no bold 700. Default UI size is `body` 12px on 16px.

**Shape.** Everything chrome is rounded: `radius-xs` thumbnails, handles and checkboxes; `radius-sm` buttons, fields and menu items; `radius-md` docked panels and menus; `radius-lg` the floating toolbar and dialogs; `radius-pill` the zoom pill, tags, switches and slider tracks. Board images stay square.

**Borders and shadow.** Separate with a 1px `divider` hairline; outline controls with `control-border`. The only shadows are `shadow-float` (toolbar, dialogs) and `shadow-popover` (menus). Docked panels and images have none.

**Spacing and density.** Controls and rows are 28px (`control-md`); panel padding is `space-4`; gaps inside bars are `space-1`; panels float `space-2` in from the window edge and are `panel-w` (240px) wide.

**States.** Hover fills with `hover`. Pressed and hovered primary buttons use `accent-strong`. Focus is a 2px `focus-ring` outline offset 1px on every focusable control. Disabled is 45% opacity with no pointer events. Active tools and selected rows use `accent-soft`, never a bare `accent` fill, except the primary button.

**Motion.** 120ms ease-out on background and colour only. No bounce, no slide, no scale; nothing moves the images except the user.

## Iconography

Icons are simple geometric symbols on a 16px grid: 1.5px stroke, round caps and joins, `currentColor`, no fills except the half-filled `grayscale` disc. They live in `Softclub.icons` (components/bundle.js) and render inline with `Softclub.icon(name)`; do not use `<img>`. Inactive icons are `ink-muted`, hover `ink`, active `accent`. Pair every icon-only button with an `aria-label` and a tooltip showing its shortcut. Never use emoji or glyph characters as icons.

## Accessibility

In every theme `ink` holds 7:1 and `ink-muted` 4.5:1 on `canvas`, `surface`, `surface-raised`, `surface-sunken`, `hover` and `accent-soft`; `accent` holds 4.5:1 on all panel surfaces and 3:1 on `canvas`; `control-border` holds 3:1 on every surface; `on-accent` holds 4.5:1 on `accent` and `accent-strong`. Status and meaning always carry a word or icon in addition to colour.
