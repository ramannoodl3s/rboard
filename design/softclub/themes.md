# Themes

Six themes share one set of token names. Switch by setting `data-theme="<id>"` on the app root; only token values change.

| id | name | tone | canvas | surface | accent |
| --- | --- | --- | --- | --- | --- |
| `carbon` | Carbon | dark | `#1c1c1e` | `#131315` | `#a9aed0` |
| `nova` | Teal Room | dark | `#1c2f2d` | `#142624` | `#e4adc0` |
| `handset` | Handset | dark | `#20253c` | `#181c30` | `#b9c77a` |
| `albumen` | Albumen | dark | `#2a2640` | `#201c35` | `#d9ad82` |
| `pictogram` | Pictogram | light | `#e4e0c4` | `#efecd6` | `#9c2f3a` |
| `survivor` | Blood Orange | light | `#e2d3c8` | `#eee3da` | `#7f3519` |

All six are dusty and low-chroma, the faded-print look of the sleeves rather than their ink. **Carbon** is the black theme and the default (charcoal, with a pale lavender accent). **Teal Room** is a dusty teal with a rose accent. **Handset** is a smoky navy with a sage-lime accent. **Albumen** is a plum-violet with a tan-amber accent. **Pictogram** is a butter-cream with a brick-crimson accent. **Blood Orange** is a clay-pink cream with a terracotta accent.

- Every theme keeps `canvas` low-saturation so the user's images keep their own colour; the sleeve's hue is strongest in the panels and the accent.
- Light themes use dark `ink` and a white `on-accent`; dark themes use light `ink` and a dark `on-accent`.
- `palette-*` swatches are muted too (chroma kept low) and identical in all themes.
