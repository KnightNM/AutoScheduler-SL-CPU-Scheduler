# Design

> Terminal UI source of truth. Read before changing presentation output.

## Aesthetic direction

Technical research console: restrained, evidence-first, and readable at 80 columns.

## Dials

- Design variance: 2/10
- Motion intensity: 0/10
- Visual density: 6/10

## Typography

- Use terminal monospace font selected by user.
- Keep headings short and metrics aligned.
- Do not print lines longer than 80 columns where practical.

## Color

- Cyan: headings and section boundaries.
- Green: passing gates.
- Amber: failed gates, warnings, and unavailable artifacts.
- Never use color as only status signal; always print `PASS`, `FAIL`, or text.
- Disable ANSI codes for non-TTY output and `--no-color`.

## Layout

- One numbered top-level menu.
- Flat sections; no nested dashboards.
- Show evidence before recommendation.
- Show artifact source path after each saved result.

## Interaction

- Number keys select sections.
- `0` or `q` exits.
- Enter accepts documented defaults.
- Invalid input explains fallback without terminating demo.

## Copy

- Direct technical language.
- Label unfinished work as `NOT IMPLEMENTED`.
- Never present smoke runs as research evidence.

## Accessibility

- Every colored state includes text.
- Plain-text output remains complete.
- No animation, cursor control, or terminal clearing.

## Last updated

2026-09-22: added interactive AutoScheduler experiment demo.
2026-10-20: added a print-first 16:9 IEEE architecture figure using off-white paper, black rules, orthogonal connectors, Aptos/IBM Plex typography, and no motion.
