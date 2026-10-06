Fields are recessed wells (`surface-sunken`) outlined with `control-border`, so they read as inputs on `surface` and `surface-raised` in all six themes.

**Consumer provides:** a lowercase label (`ink-muted`, in a 96px label column), placeholder text in lowercase, and a value in `ink`.

- Text field: 28px high, `radius-sm`, 10px side padding. Focus draws the 2px `focus-ring` outline; do not change the border colour instead.
- Slider: 4px pill track in `control-border`, `accent` fill, 14px `accent` thumb. Show the numeric value in `caption` to the right when precision matters.
- Switch: 28x16 pill. On = `accent` with an `on-accent` knob; off = `surface-sunken` with an `ink-muted` knob. Pair every switch with a label; never rely on colour alone.
- Checkbox: 14px, `radius-xs`; checked = `accent` fill with a 12px `check` icon in `on-accent`.
- Segmented control: use for 2 to 4 mutually exclusive modes. The active item is `surface-raised` with `ink` text.
