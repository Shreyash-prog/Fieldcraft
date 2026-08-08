# Fieldcraft — landing site

Static: `index.html` + six lens pages under `lens/` + `style.css` + `main.js` +
`assets/`. No build step, no framework, no backend. Open `index.html` directly and
it works.

```
index.html          hero → proof → who it's for → problem → product → vision → status → try
lens/*.html         one page per vision lens, each with a hand-built inline SVG diagram
lens/_generate.py   emits all six from one template; edit copy/diagrams here, not in the HTML
style.css           the only stylesheet — both the home page and the lens pages
assets/*.webp       2x product screenshots (2912px wide)
```

## Deploy to Vercel

Point Vercel at **this directory**, not the repo root:

- **Vercel dashboard** → New Project → import the repo →
  set **Root Directory** to `site` → Framework preset **Other** →
  leave Build Command and Output Directory empty → Deploy.

- **CLI**, from the repo root:
  ```bash
  cd site && vercel --prod
  ```

Images live in `site/assets/` and are referenced relatively (`assets/…`), so they
resolve both when opening the file locally and when `site/` is the deploy root.

`vercel.json` sets `cleanUrls: false` on purpose: every internal link is written
with its `.html` extension, so local `file://`/`http.server` browsing and the
deployed site resolve identically with no redirect hop.

## Assets

Captures of the running Fieldcraft app (Board, three-mode comparison, governance
gate, Try it), stored as **2× WebP at 2912px wide** so they stay sharp on Retina.
Nothing displays them above 1143 CSS px, so they are always downscaled — never
upscaled, which is what makes a screenshot look soft.

To refresh: run the app at a 1456×827 viewport, capture the region in four
728×(h/2) tiles (each tile comes back at 2× native), and stitch them into one
2912×h image. Then re-check the `width`/`height` attributes on the `<img>` tags —
they must match the new native size or the reserved space will be wrong and the
page will shift as images load.

## Lens pages

Do not hand-edit `lens/*.html`. Change `lens/_generate.py` and re-run it from the
repo root (`python3 site/lens/_generate.py`) — that is what keeps the six pages
structurally identical.

Diagrams are inline SVG on a `0 0 880 H` viewBox, styled entirely by the shared
`.d-*` classes in `style.css` (one stroke weight, one accent) so the set reads as
designed rather than assembled. On narrow screens `.dia-scroll` pans them instead
of shrinking the labels below legibility.

## Editing notes

- One accent (`--teal`, `#14e0b0`) — used for CTAs, active states, and the two or
  three numbers worth emphasising. Adding more accent colours is the fastest way
  to make this look cheap.
- The design tokens at the top of `style.css` mirror the app's own tokens on
  purpose; the consistency between site and product is the point.
