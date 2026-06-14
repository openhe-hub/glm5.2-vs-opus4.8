# FORM — Halo 01

An immersive single-page product page for a fictional high-end lighting brand, **FORM**.
Hero product: **Halo 01**, a modular task lamp. One self-contained file, no build step,
no dependencies, no UI library, no external fonts.

```
solution/index.html   ← the whole page (HTML + CSS + JS inlined)
solution/README.md     ← this file
```

Open `index.html` in any modern browser. Nothing to install.

---

## Art direction

The brief was to avoid the "centered headline + three feature cards" template, so the page
is built as an **editorial spread**, not a landing page.

- **A single argument, stated typographically.** The hero is asymmetric: a serif headline set
  ragged against deliberate negative space on the left, the product floating into the right
  column and bleeding past the grid. An oversized italic index numeral (`01`) and a rotated
  vertical caption sit in the margins the way they would in a print object — they carry the
  layout instead of decorating it.
- **The product is drawn, not photographed.** The lamp is hand-built **inline SVG**, so the
  configurator recolours a *real object* in real time rather than swapping stock images. This
  also keeps the page weightless and removes any reliance on stock photography or gradient
  filler (both explicitly forbidden).
- **Restraint over spectacle.** One accent colour, hairline rules, generous rhythm, monospace
  used only for technical figures and labels (the "spec-sheet" voice). Motion is subtle —
  a few pixels of parallax and a soft reveal, never a carousel of effects.

Sections: art-directed Hero → Specification → Principles (an editorial numbered list, *not*
cards) → interactive Configurator → Up-close Details/gallery → multi-tier Footer.

## Type system

System / self-hosted only — **no third-party font CDN**. Three stacks, each with a job:

| Role | Stack | Used for |
|------|-------|----------|
| Display | `"Iowan Old Style", "Palatino Linotype", Palatino, "Hoefler Text", Georgia, serif` | headlines, lede, prices, spec values |
| UI | `ui-sans-serif, -apple-system, "Segoe UI", Roboto, …` | body, controls, navigation |
| Technical | `ui-mono, "SF Mono", Menlo, Consolas, …` | labels, figures, kickers, captions |

The serif gives the brand voice; the mono gives the engineering credibility; the sans keeps
the UI quiet. A fluid `clamp()` scale (`--fs-display` … `--fs-cap`) drives every size so the
hierarchy holds from 320 px to 1440 px without a single fixed breakpoint for type.

## Grid

A 12-column editorial mindset expressed with CSS Grid. A `.shell` wrapper (`max-width 1320px`,
fluid `clamp()` gutters) centres content. The hero is an intentionally **uneven** two-track grid
(`1.05fr / .95fr`) with overlapping layers; specs use a 1→2→3 column dl; features use a
`5rem / 1fr / 1.1fr` baseline-aligned row. Everything collapses to a single column on small
screens. `overflow-x: clip` plus `min-width: 0` on grid children guarantee **no horizontal
overflow** across the whole 320–1440 px range.

## Palette

Deliberately **not** a framework default — warm "bone" paper and ink, with a single burnt
**terracotta** accent (`#a8431d`). No signature framework blue anywhere.

- Light: bone `#efe9dc` / ink `#1b1a14` / terracotta accent / hairline `#d3ccba`.
- Dark: charcoal `#15140f` / warm off-white `#ece6d6` / brightened terracotta `#d8743f`.
  Driven entirely by `prefers-color-scheme`; `color-scheme` is declared so native controls and
  scrollbars follow.

All token pairings were checked for **WCAG contrast**: body and label colours clear 4.5:1, the
accent clears 4.5:1 against both paper surfaces and as button text, in both schemes.

**Configurator materials** are separate product colours, consistent across light/dark:
Anodised Aluminium · Matte Steel · Solid White Oak (structure) × Ochre · Sage · Bone · Oxblood
(anodised accent). Price = €340 base + material + accent premium.

---

## States (all eight, deliberately designed)

| State | Where |
|-------|-------|
| **default** | every control's resting style |
| **hover** | nav links (animated underline), buttons (lift + shadow), swatches, bag, inputs |
| **focus** | `:focus-visible` rings everywhere; on swatches the ring is reflected from the hidden native radio via `:has(input:focus-visible)`; `:focus:not(:focus-visible)` stays clean for mouse users |
| **active** | buttons/swatches depress (`:active`) on press |
| **disabled** | "Add to bag" while a request is in flight; the **Oxblood × Oak** pairing is genuinely unavailable, so that swatch becomes `disabled` (and the price turns red) when Oak is selected |
| **loading** | "Add to bag" shows a spinner + "Adding…", `aria-busy="true"`, button disabled during the simulated request |
| **empty** | the bag recap starts in an explicit empty state ("Your bag is empty — …"); **Remove** returns it there |
| **error** | the newsletter validates inline (invalid / missing email → red field + assertive message + focus return); the unavailable-combination path shows a recovery note |

The configurator also handles **graceful recovery**: choosing Oak while Oxblood is selected
auto-switches to a valid accent and explains why via a polite live region — no dead ends.

## Interaction & accessibility

- **Keyboard-complete configurator.** Swatches are real `<input type="radio">` inside
  `role="radiogroup"` fieldsets, so **Tab** moves between groups, **arrow keys** move within a
  group, and **Space/Enter** select — all native, plus visible `:focus-visible` rings. Disabled
  options are skipped automatically.
- **Screen-reader support.** Skip link; semantic landmarks (`header`/`main`/`footer`/`nav`),
  one `<h1>` and a clean heading order; `aria-label`led sections; the live SVG carries a
  descriptive `aria-label` updated on every change; price, recovery note, bag recap and form
  messages are `aria-live` regions; the bag link's label tracks its count.
- **Motion, restrained and reducible.** Scroll reveal (IntersectionObserver) and a few pixels
  of hero parallax (rAF, transform-only). All of it is gated behind
  `@media (prefers-reduced-motion: no-preference)` **and** disabled in JS when the user prefers
  reduced motion — content is fully visible without JS or with motion off (no FOUC, no
  JS-dependent content). Spinner animation and smooth scrolling are likewise gated.
- **Responsive 320 → 1440 px** with no horizontal scroll; fluid type and spacing throughout.
- **Dark mode** via `prefers-color-scheme`, including matching `theme-color` meta tags.

## Performance / constraints

- **Single self-contained file**; zero runtime dependencies, zero UI libraries.
- **Transferred JS ≈ 2.9 KB gzipped** (vanilla, no framework) — well under the 30 KB budget.
- **No external requests at all** — no font CDN, no images; the product art is inline SVG, so
  there are no network round-trips and nothing to lazy-load.
- Transform/opacity-only animation and static SVG filters keep it at 60 fps; the script guards
  every DOM lookup, so there are **no console errors**.
- Built toward **Lighthouse a11y ≥ 95 / performance ≥ 90**: semantic HTML, labelled controls,
  checked contrast, no render-blocking external resources.
