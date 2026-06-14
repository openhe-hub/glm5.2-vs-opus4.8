# FORM 01 — Mechanical Studies

A self-contained, single-file immersive product page for a fictional high-end
design brand, **FORM**. The hero product is the **FORM 01**, a mechanical
automatic watch. Open `index.html` directly in a browser — no build step, no
network, no dependencies.

---

## 1. Art direction

The reference world is editorial watchmaking print (think a Hodinkee long-read
meets a Dieter Rams spec sheet), not a "landing page". The decisions, on purpose:

- **A point of view, not a centred headline.** The hero is a 12-column editorial
  grid: a left-aligned three-line H1 set in mixed sans + serif-italic accent
  ("A watch, / stripped to / *its physics.*"), with the watch pushed to the right
  column and a typographic "spec ticker" running under a hairline rule. Negative
  space is the layout material.
- **Information design over decoration.** The spec section is a real datasheet —
  grouped `dl` rows with hairline dividers and an annotated movement schematic —
  not three "feature cards".
- **The product is drawn, not stock-photo'd.** The watch is a **procedural SVG**
  generated in JS: 60 tick markers, swept hands, gradient case, stitched strap.
  The configurator mutates that same SVG live. Gallery "detail studies" are line
  drawings (crown, lug, bezel, dial, hand) — consistent with the brand's restraint
  and avoiding stock imagery / lorem.
- **One accent, used like ink.** A single oxblood/vermillion accent does all the
  emotional work; everything else is paper, ink, and hairlines.

What was deliberately avoided (the brief's "instant-deduct originality" list):
no Tailwind blue, no component-library look, no centred-hero + 3-cards, no emoji
icons, no lorem, no stock gradients carrying the visual.

## 2. Type system

System fonts only (no external font CDN, per the constraint).

| Role        | Stack                                                                                |
| ----------- | ------------------------------------------------------------------------------------ |
| Display/sans| `"Helvetica Neue", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans`   |
| Editorial   | `Georgia, "Times New Roman", serif` — used **only** for italic accents               |
| Data/mono   | `ui-monospace, "SF Mono", "Cascadia Code", Menlo, monospace` — labels, specs, prices |

Fluid type via `clamp()`; tabular-nums on all prices; tight negative tracking on
the H1 (`-0.03em`); wide tracking (`0.2em`, uppercase) on mono eyebrows.

## 3. Grid

- 12-column fluid grid, `max-width: 1320px`, gutters `clamp(20px, 4vw, 56px)`.
- Asymmetric column spans per section (e.g. hero copy `1/span 6` + stage
  `8/span 5`; spec diagram `1/span 5` + groups `7/span 6`).
- Breakpoints at 1024 / 880 / 560 / 360. Below 880 every multi-column block
  collapses to a single column; the watch stage re-orders above the copy on
  phones so the product leads.

## 4. Colour system

Token-driven via CSS custom properties. Two palettes (light/dark) that **follow
`prefers-color-scheme` by default**, overridable by an explicit
`data-theme="light|dark"` set from the nav toggle (persisted in `localStorage`).

```
LIGHT                  DARK
--bg     #F2EEE5 paper --bg     #100F0C ink
--ink    #181612       --ink    #EDE7D8 bone
--ink-2  #3A352D       --ink-2  #C9C2B0
--ink-soft #5E574A     --ink-soft #9C9484
--ink-faint #6E6759    --ink-faint #8A8273   (all text ≥ 4.5:1)
--rule   #CFC8B8       --rule   #2C2820
--accent #B23A1E ox    --accent #E0613F
--on-accent #F7F2E8    --on-accent #15120D
```

The two SVG previews use **unique gradient IDs** (`h*`/`c*` prefixes) so there
are no duplicate IDs in the document and `url(#…)` paints resolve per-instance.

## 5. Interaction & state

**Scroll-driven reveal/parallax (restrained).** `IntersectionObserver` fades
content up 14px with a small stagger; a single rAF-throttled scroll handler
translates the hero watch by `scrollY * 0.04` (≈4% parallax). Everything motion
is killed under `prefers-reduced-motion` (CSS media query forces transitions to
~0ms, reveals to visible, and JS skips parallax/hand-tick/swap animation).

**Configurator.** Four `<fieldset>`/`<legend>` groups (size, material, dial,
strap) using **native radio inputs** — so arrow-key navigation, Tab order and
`:focus-visible` rings come for free; labels are the styled swatches. Changing
any option instantly recomputes price and re-paints the SVG preview, with a
short cross-fade + scan-line transition. A live `aria-live="polite"` region
announces the full configuration and price to screen readers.

**All eight states are designed:**

| state | where it lives |
|-------|----------------|
| default | every swatch / button |
| hover   | swatch border lifts, nav/footer links underline-grow |
| focus   | `:focus-visible` 2px accent ring on every interactive element |
| active  | buttons translate 1px on press |
| disabled | "Ceramic — Q3 2026" material (static); "Steel Bracelet" strap auto-disables at 38 mm with an inline note and auto-reverts the selection |
| loading | "Add to bag" and "Subscribe" show a spinner + disable (~0.9s simulated); preview shows a scan-line + "Updating" status |
| empty   | bag counter reads `0`; newsletter field is blank before submit |
| error   | newsletter: invalid email → red inline message, `aria-invalid`, field ring; cleared on first keystroke |

**Add-to-bag** flips to loading, then increments the nav bag counter and fires a
`role="status"` toast ("Added — Black DLC, Oxblood dial ($3,250)").

## 6. Accessibility

- Semantic landmarks: `header[role=banner]`, `main`, `footer[role=contentinfo]`,
  four `<nav>` (primary + footer columns), one `<h1>`, sequential heading order
  (no skipped levels).
- Skip-to-content link; visible `:focus-visible` everywhere; real `<button>`,
  `<a>`, `<label>` and `<fieldset>`/`<legend>` throughout — no `div`-as-control.
- Form fields have labels; the newsletter input is a labelled email field with
  inline validation and `aria-describedby`.
- Decorative SVGs are `aria-hidden`; the spec schematic carries `<title>/<desc>`.
- Colour contrast verified for every text token (light & dark) — all pass WCAG AA
  at 4.5:1, most well above. `color-scheme` is set so native form controls match.
- Full keyboard reachability; the configurator is operable with Tab + arrows +
  Enter/Space with no mouse.
- `prefers-reduced-motion` fully respected (motion → instant, parallax off,
  reveals visible, swap animation suppressed).

## 7. Performance & compliance

- **Single self-contained file.** No UI component library, no framework, no
  external font CDN, no network requests.
- **JS budget:** gzip **5.6 KB** (limit was 30 KB). Vanilla JS, one IIFE.
- **Whole page:** 62.4 KB raw / **15.5 KB gzip**.
- No `console` output, no unhandled exceptions (verified headless). Animations
  are transform/opacity only; the only scroll handler is `requestAnimationFrame`
  throttled and `passive`. SVG gradients are reused, IDs are unique.
- Responsive **320 → 1440 px with zero horizontal overflow** at every breakpoint
  (verified headless at 320 / 360 / 414 / 560 / 768 / 1024 / 1280 / 1440).

## 8. How to view

Double-click `index.html`, or:

```bash
python3 -m http.server 8000   # then open http://localhost:8000/solution/
```

Try: resize to 320 px, toggle dark mode, tab through the configurator and use
arrow keys, pick size 38 mm to watch the bracelet disable, submit the newsletter
with garbage then a real address.
