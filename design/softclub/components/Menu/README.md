The context menu is a `surface-raised` list with `radius-md` corners, a 1px `divider` border and `shadow-popover`; it opens at the pointer on right-click.

**Consumer provides:** lowercase item labels, optional shortcuts (shown in `sc-kbd`, right-aligned in `ink-muted`), and separators between groups of 2 to 4 items.

- Items are 28px high with `radius-sm`; hover uses `hover`; the keyboard-current item uses `accent-soft`.
- A 16px slot at the left holds a `check` icon in `accent` for toggled-on commands; keep the slot even when empty so labels align.
- Destructive commands go last, in `danger` text with the word "delete" or similar.
- Disabled items stay in the list at 45% opacity. A submenu shows `chevron-right`.
