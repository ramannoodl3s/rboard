The canvas is the product. It is a flat `canvas` field; board images sit on it untouched and every piece of chrome is quieter than the images.

**Consumer provides:** the user's images at their own pixels, a selection set, and the zoom level.

- Board images use `radius-image` (square) and get no border, shadow, tint, overlay or hover effect. Do not add a drop shadow to make images "pop".
- Selection is a 1.5px `selection` outline (`outline-selection`) with 8px square handles (`handle`) in `selection`, ringed by 1px `canvas` so they stay visible over any image. Handles use `radius-xs`.
- Drag-select (marquee) is a 1px dashed `selection` rectangle with no fill.
- Status elements (zoom, counts) are `sc-pill`s in `surface-raised`: 24px high, `radius-pill`, `caption` text in `ink-muted`. Place them in the bottom corners.
- Never draw a grid, watermark or empty-state illustration; the empty state is one line of `display` text in `ink-muted`: "drop images here".
