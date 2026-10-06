Icons are plain geometric symbols on a 16px grid: 1.5px stroke, round caps and joins, no fills except the half-filled `grayscale` disc, and corner radii that echo `radius-xs` and `radius-sm`.

**Consumer provides:** an icon name from `Softclub.icons` and a colour from the surrounding text (`currentColor`).

- Render inline: `Softclub.icon('flip-h')` returns an SVG string; `<span data-icon="flip-h"></span>` plus `Softclub.mount()` fills it. Do not load these through `<img>`; they take their colour from `currentColor`.
- Default size 16px (`icon`); 24px only in empty states and documentation. Do not scale the stroke with the size.
- Inactive `ink-muted`, hover `ink`, active `accent`. Icons never change shape between themes.
- To add one: draw it in the 16px box with the same stroke, keep two or three strokes at most, and add it to `icons` in `components/bundle.js`.
