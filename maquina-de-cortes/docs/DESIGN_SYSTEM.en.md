# Design system — Máquina de Cortes

[Português](DESIGN_SYSTEM.md) · **English**

Minimal, black and white, with a single red. The reference is the Swiss school and industrial design
(Braun, Nothing, Teenage Engineering, Vercel): few pieces, each with a job, and one color that only appears
when it matters. The interface stays quiet so the video is the star.

Tokens live in [`frontend/src/index.css`](../frontend/src/index.css). No component should use loose hex values
or Tailwind palette colors (`zinc-*`, `amber-*`…): always use the tokens below.

## Color

There are three, and there is no fourth.

| Token | Hex       | Role |
|-------|-----------|------|
| Black | `#000000` | Background for everything: page, sidebar, cards, dialogs. |
| White | `#ffffff` | Text, icons, lines and neutral states. |
| Cut   | `#df2531` | Emphasis: primary action, active item, selection, focus, error. |

**In-between tones are white with transparency over black**, never a new gray:

| Use | Value | Class |
|-----|-------|-------|
| Secondary text | white 60% | `text-muted-foreground` |
| Hairline (borders, dividers) | white 12% | `border` (default) |
| Field border | white 18% | `border-input` |
| Light fill (hover, chip) | white 7–8% | `bg-accent`, `bg-secondary`, `bg-muted` |

### Rules for red

- **One primary action per screen.** Only the button that does the main thing (`Criar cortes`, `Exportar`) is red.
  Everything else is `outline`, `secondary` or `ghost`.
- **Red marks what is selected or active**: current menu item, selected range on the timeline,
  chosen caption preset, keyboard focus.
- **Red is also error.** Since emphasis and error share the color, errors always come with an icon and text explaining
  what happened. Never rely on color alone.
- Clips with a high score (≥ 80) get a solid red badge: they are the highlight of the project.
- Progress bars are **white**: progress is information, not a call to action.

### Colorless states

Success and warning have no color of their own. The icon and the text carry the meaning:

| State | Treatment |
|-------|-----------|
| Success / done | white, check icon, completed step as a filled white circle |
| Warning / optional | white 75%, alert icon, badge with a dashed border |
| Error / destructive | red, X or alert icon |

In the editor, framing regions differ by stroke: webcam with a solid white line,
game with a dashed white line, active region in red.

## Typography

**Poppins** everywhere, loaded locally via `@fontsource/poppins` (the app works offline). Weights in use:

| Weight | Use |
|--------|-----|
| 400 | Body text |
| 500 | Buttons, labels, list items |
| 600 | Headings (`font-display`, with `letter-spacing: -0.03em`) |
| 700 | Reserved; avoid |

Scale (rem over 16 px): `xs 12` · `sm 14` · `base 16` · `lg 18` · `xl 20` · `2xl 25` · `3xl 31` · `4xl 39` · `5xl 49`.
From `xl` up the scale follows a major third (×1.25). Text lines at most ~70 characters (`max-w-prose`, `max-w-md`).

**Caption** fonts for the clips (Montserrat, Inter, Bebas Neue) are video content, not interface,
and sit outside this system.

## Shape

- **No shadows.** Depth comes from hairlines and space.
- **Surfaces are black.** Cards and dialogs separate from the background only by a 1 px border.
- **Radii with hierarchy:** 4 px (thumbnails, tags), 6 px (buttons, fields), 10 px (cards), 14 px (dialogs and hero media),
  fully round only for indicators (counters, status dots, badges).
- **Buttons:** 36 px tall (44 px for `lg`), weight 500, no uppercase.
- **Focus:** 2 px red ring with a 2 px offset, always visible on keyboard.

## Imagery and motion

- Brand illustrations and media are shown in **grayscale** (`grayscale`) so they don't compete with the red.
  User thumbnails and videos stay in color: they are the content.
- Motion only answers an action (open, confirm, drag). The one exception is the **Home hero entrance**,
  once on load (`enter`, staggered by `--enter-delay`). No per-section or scroll-triggered entrances.
- Micro-interactions (utilities in `index.css`, `transform`/`opacity` only):

  | Utility | Where | What it does |
  |---------|-------|--------------|
  | button (`Button`) | every button | fill changes on hover, presses to 97% on click |
  | `lift` | linked card | rises 2 px on hover |
  | `zoom-in-frame` | photo inside a `.group` card | zooms 2% inside its frame |
  | `link-draw` | text link | underline draws left to right |

- Decorative loops longer than 5 s (the hero video) have a pause button.
- `prefers-reduced-motion` zeroes every duration.

## Interaction and accessibility

We follow Vercel's [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines). The essentials:

- "Skip to content" link as the first Tab stop; focus always visible.
- The primary button stays enabled until the request starts; validation explains what is missing.
- Placeholders end with "…"; fields have the right `type`, `name`, `autocomplete` and `spellCheck`.
- Curly quotes (“ ”) and ellipses (…) in copy; `text-wrap: balance` on headings.
- Images have `width`/`height`; below the fold, `loading="lazy"`.
- Errors say what happened **and what to do** (`LoadError` component).
- Below 768 px the sidebar collapses to icons.

## Copy

Short sentences, imperative verbs, sentence case. A button says what happens (`Criar cortes`, not `Enviar`).
No UPPERCASE labels above headings and no decorative numbering: numbers only where there is a real sequence
(the three steps of "Como funciona").
