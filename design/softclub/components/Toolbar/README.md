The toolbar is a floating `surface-raised` bar of icon buttons, rounded with `radius-lg` and lifted by `shadow-float`; it is the only chrome that floats over the board besides menus.

**Consumer provides:** an ordered list of icon buttons, grouped by `sc-sep` dividers (tools | transforms | window).

- Icon buttons are 28px (`control-md`), 16px icons, 4px (`space-1`) gaps. Inactive icons are `ink-muted`; hover goes to `ink` on `hover`.
- The active tool sets `aria-pressed="true"`: `accent-soft` fill with an `accent` icon. Only one tool is active at a time.
- Every button needs an `aria-label` and a tooltip (`sc-tooltip`, `ink` on `surface` inverted) that shows the shortcut in `sc-kbd`.
- Do not label toolbar buttons with text, and do not add a second row.
