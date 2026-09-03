# GigaPay Brand Asset Requirements

## Status: WAITING ON SOURCE FILES — DO NOT mark logo integration as done until resolved

The client approved a brand collage (shared 2026-09-03) as the visual reference for
the new "GigaPay" identity. Claude has no file-level access to that collage (shown
inline in chat only) and no image-editing tool in this environment, so it cannot crop
or export clean assets from it. Per the rebrand brief, a degraded manual crop or a
newly generated logo is explicitly disallowed — so no logo files have been created,
and no code has been wired up to reference logo image files that don't exist yet
(that would break the build).

**Confirmed incoming files (client, 2026-09-03):**
- `gigapay-mark.png` — symbol only
- `gigapay-logo-horizontal.png` — mark + "GigaPay" wordmark

Drop them at `gigveyro-frontend/public/brand/gigapay-mark.png` and
`gigveyro-frontend/public/brand/gigapay-logo-horizontal.png` respectively (the
`public/brand/` directory already exists, currently empty) and then do the wiring
listed under "Integration points" below.

## Approved visual direction (from the reference collage)

- Wordmark: "Giga" in white/near-white, "Pay" in vivid red, tight kerning, bold
  geometric sans.
- Mark: an angular shield/arrow "G" monogram — white and red split diagonally —
  reads at both large and small sizes.
- Palette: near-black / dark navy background (#07090d-ish), white, vivid red
  (#ff2a2a-ish accent, red-to-dark-red gradient seen on the mark).
- Tagline (optional, not part of the core lockup): "PAYMENTS • EXCHANGE • GLOBAL".

## Assets still needed beyond the two confirmed files

| # | Asset | Spec | Target path |
|---|---|---|---|
| 3 | App/favicon icon | Square, mark only, no fine text (must read at 16-32px). Can likely be generated from `gigapay-mark.png` once received, but a dedicated export is cleaner. Replaces the current placeholder `src/app/icon.svg` / `src/app/favicon.ico`. | `gigveyro-frontend/src/app/icon.svg`, `gigveyro-frontend/src/app/favicon.ico` |
| 4 | Telegram avatar | Square, mark only, centered, high contrast, no world map / phone mockup / business card / tagline. Must read clearly when Telegram crops it into a circle. | `docs/branding/telegram-avatar.png` (min 512x512) |

## Integration points (wire these up once the PNG files exist — not done yet)

- `gigveyro-frontend/src/app/login/page.tsx` — 3 spots currently render
  `<div className={styles.logo}>G</div>` next to `<strong>GigaPay</strong>` (a plain
  text placeholder, no image). Swap to `next/image` pointing at
  `/brand/gigapay-mark.png` (compact contexts) or
  `/brand/gigapay-logo-horizontal.png` (full lockup), matching each screen's layout.
- `gigveyro-frontend/src/components/layout/dashboard-shell.tsx` line ~58 — same
  `<span className={styles.logo}>G</span>` text placeholder in the sidebar brand
  link. Swap to `/brand/gigapay-mark.png`.
- `gigveyro-frontend/src/app/icon.svg` — currently a generic placeholder "G" glyph
  (not the approved GigaPay mark). Replace once asset #3 is exported.
- Check contrast/legibility in both the light and dark theme (`data-theme="light"` /
  `"dark"` on `<html>`, see `layout.tsx` theme bootstrap) before calling this done.

## Explicitly out of scope as production assets (per brief)

Do not export/use these collage sections as logo files:
- the world-map hero panel
- the phone mockup panel
- the business-card mockup panel
- any panel containing the "FAST / SECURE / GLOBAL" marketing copy blocks

These are marketing-presentation sections of the collage, not clean logo exports.
