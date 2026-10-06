Buttons are quiet by default: an outlined `sc-btn` with `ink` text, and a single `sc-btn--primary` filled with `accent` for the one main action in a view.

**Consumer provides:** a short lowercase label (verb first: "add images", "export board"); an optional leading icon from `Softclub.icons`.

- Use one primary button per panel or dialog. Everything else is outlined or `sc-btn--ghost`.
- Use `sc-btn--danger` only inside a confirm dialog, and always with a word ("delete board"), never icon-only.
- Height is `control-md` (28px); dialog actions use `sc-btn--lg` (`control-lg`).
- Hover fills with `hover` (primary: `accent-strong`). Focus is a 2px `focus-ring` outline with 1px offset. Disabled is 45% opacity with no pointer events.
- Radius is `radius-sm`. Do not use pill buttons; pills are for zoom, tags and switches.
