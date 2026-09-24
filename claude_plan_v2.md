# Claude's half of the plan (builder's proposal, to merge with Muse's)

Muse owns the *what and why* (art direction, voice, photography). This is the *how it feels and how it is built*: colour, motion, materials, build order. Where we disagree, we argue in the two entry files and the user sees the merged result.

## 1. Direction in one line
A real paper with real steel and real colour: **warm paper ground, ink type, photographed steel plates, one bold colour per chapter, everything that can be touched reacts.** Nothing simulated.

## 2. Colour system (orange is out; life comes from colour we choose)
| Role | Value | Spent on |
|---|---|---|
| Paper | `#F1ECE0` | the page ground (Muse's call) |
| Ink | `#14120E` | body type, rules, button faces |
| Signal blue | `#2350FF` | **all controls**: hover fills, focus rings, links, active nav (replaces orange) |
| Chapter colours | see below | section number, big numeral, rule, hover colour of that chapter's rows |
| Coral | `#F0506E` | Rivet's lips and the Notice Board only |
| Steel | the photograph | nameplate, plates, photo frame, spec tag; never tinted |

Chapter colours (each a *rule/numeral/chip*, never a tint of the metal): Front Page `#2350FF` cobalt · Map Room `#2F7D5B` moss · Money `#E0A100` marigold · Home Turf `#8C2331` oxblood · Gear Shed `#1D6F8C` petrol · Culture `#B23A6D` plum. Six saturated, distinct, all >= 4.5:1 on paper for text use, so every section has a feeling and the page is not grayscale. Marigold is used as fill with ink text, never as text on paper.

## 3. Materials
- **Steel:** Muse's public-domain photograph, cut into three optimised WebP crops (nameplate 1600x420, plate strip 1200x160, frame 1600x1000; target ~140 KB total). Different `background-position` per plate so no two are the same crop. **No CSS gradients pretending to be metal.** Engraved type (dark cut + light lower lip) and countersunk screws (SVG) sit on top. Credit line in the colophon.
- **Paper:** flat `#F1ECE0`, no texture, no cards, no shadow; hairline ink rules only.
- **Photography:** daily credited photo, hero position, steel frame; a full-bleed colour band under each chapter title picks up that chapter's colour.

## 4. Motion (transform/opacity only; cheap on a phone)
- **Controls (every button, nav item, row header):** rest = ink face, paper text, 2 px hard shadow. Hover = lift `translateY(-2px)`, shadow to 4 px, fill fades to signal blue, 140 ms `cubic-bezier(.2,.8,.2,1)`. Press = `translateY(1px)`, shadow to 1 px, 60 ms (feels like a real key). Focus-visible = 3 px signal-blue ring, 2 px offset, one 1.2 s pulse.
- **Nav:** active chapter has a sliding underline in that chapter's colour (position/width, 260 ms).
- **Reveals:** each section plate slides `translateX(-24px)->0` + fades in 520 ms `ease-out`, its children stagger 60 ms; once only (IntersectionObserver). If JS or IO is unavailable everything is simply visible.
- **Rows:** story receipts/mags expand with `grid-template-rows: 0fr -> 1fr`, 260 ms, and a 6-degree chevron turn; a 3 px chapter-coloured bar draws down the left edge on open.
- **Ticker:** 60 s linear marquee, pauses on hover and focus.
- **Hero:** slow 28 s scale `1.04 -> 1.10` alternate; on scroll the image drifts 24 px using CSS scroll-driven animation where supported (no JS).
- **Load moment (the one signature, once per edition per device):** the photo "develops" from `grayscale(1) contrast(1.2) brightness(.6)` to full colour over 1.2 s while the nameplate settles from `translateY(-8px)`. Skipped on repeat visits.
- **Rivet:** idle bob + blink already built; pops in with a small bounce at the sign-off and on Notice-Board/Machine sections only.
- **Reduced motion:** all movement off; colour/opacity changes remain.

## 5. Where the fun and the quirk visibly live
Rivet (quirk register only) · quote-labels on every plate (`"THE MAP ROOM"`) · a spec tag on the photo · hover microcopy on rows ("open the receipts") · chapter colour bands · the springy press on every button · the screws on the nameplate turn a few degrees when you hover them. One wit per screenful, facts stay plain.

## 6. Build order
1. Tokens + paper ground + ink type; delete plaster, cards, glass, CSS metal, grain, orange (source, not just overrides).
2. Real steel crops + nameplate + plates + frame + spec tag.
3. Chapter colour bands/rules/numerals.
4. Motion layer (controls first, then reveals, rows, hero, load moment).
5. Rivet placement, colophon credits.
6. Gate (adds: >= 4.5:1 contrast for every text/background pair, no gradient-as-material, blue is the only control colour, motion respects reduced-motion) and a full-page browser check at 390 / 768 / 1440.
7. Re-render, Muse review, promote to the live paper on sign-off.

## 7. Open points to settle with Muse
- Signal blue for controls versus a deep ink hover: I prefer blue for life; Muse may argue for restraint.
- Chapter colours: six vs Muse's "few"; I hold that the user asked for colour and life, so six with strict jobs.
- The steel crops: which parts of the photograph for which plate.
