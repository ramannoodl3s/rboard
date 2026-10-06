Docked panels are `surface` columns with a 1px `divider` border and `radius-md` corners; they sit 8px (`space-2`) in from the window edge and never have a shadow.

**Consumer provides:** a lowercase panel title (`title` style), rows or controls for the body, and optional `label`-style section headers.

- Width is `panel-w` (240px). The header holds the title and at most one small icon button.
- Rows are 28px with a 20px `radius-xs` thumbnail, name in `body`, count in `caption`. Hover is `hover`; the selected row is `accent-soft` with `body-strong` text.
- Controls inside a panel sit on `surface`; fields use `surface-sunken`.
- Panels recede: no gradients, no tinted headers, no inner shadows. If a panel competes with the images, reduce it, not the board.
