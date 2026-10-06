Tags are the only place the soft-club `palette-*` colours appear inside the app: a pill outlined with `control-border` holding an 8px colour dot and the tag's name.

**Consumer provides:** the tag name (lowercase) and one of `palette-teal`, `palette-lime`, `palette-orange`, `palette-yellow`, `palette-magenta`, `palette-sky`, `palette-violet`, set through the `--dot` custom property.

- The name is always shown; the dot never carries meaning alone.
- A filter-on tag sets `aria-pressed="true"` and takes `accent-soft` with an `accent` border.
- Never use palette colours for text, selection or focus; those are `accent`.
