# Design Review 1 — Paper Preview Dissection (Muse)

Date: 2026-09-24. Preview: https://peesherman42wallabywaysydney-star.github.io/bot-lobby/preview/
All text synthetic placeholder. Reviewed against Jeremiah's design vision + my living design bible.
Labels: `verified` = observed/tested; `opinion` = judgment call; `unverified` = could not test.

## User direction (2026-09-24, APPROVED BY JEREMIAH — implement, don't debate)

1. **Voice:** fun + quirky + serious + factual, with its own voice. It should pop and be designed beautifully — never cookie-cutter.
2. **Nature photography, Bing-style:** bold full-bleed nature imagery per edition/section, captioned and credited, photography LEADS — not a background wash behind everything. (License-clean sources already researched and filed in this repo: Unsplash, Pexels, Pixabay, Wikimedia Commons, StockSnap, Kaboompics.)
3. **Orange is too much:** cut it way back. Approved: orange = controls/alerts only; decorative uses move to stone/plaster/line.
4. **The forest background feels like hunting, not a paper:** tone it down. The ground should feel like a newspaper; nature lives in the photography.

**New process (approved by Jeremiah):** no pre-approval gate on design feedback. Claude implements freely, pushes to the live preview so it's visible to Jeremiah, and I post-review the implemented version with suggestions here. This review is my first post-review — treat the ranked list below as suggestions, implement at Claude's discretion.

## A. Functional / technical (verified unless noted)

**Load.** Page 200; edition.json 200 (valid JSON); tldr.json 200; ArchivoBlack woff2 200; mist.jpg 200 (1280×853). Cold load ~8.8s, warm ~0.9s. `paper_design_v3.css` **404s** — all CSS is inline in the document; the premise that tokens live in that file is wrong for this deployment. All paper content is inlined in the HTML (~316KB); edition.json/tldr.json may never be fetched at runtime (unverified — end-of-body script not inspectable). No render-blocking resources; fonts font-display:swap; photo fades in 1.4s. Layout shift minimal (transform/opacity entrances only).

**Interactions (all tested live).** Working: nav highlight + smooth scroll + scroll-spy (hash not reflected in URL — minor); receipt cards expand/collapse both ways; TL;DR always visible (no toggle exists); magazine rack expands; "more" pile expands; A−/A+ resizes via --fs (default 15.5px). **Dead:** "Past editions" date select (single option 2026-01-01); "Design preview" pill (a span, not in a11y tree). Outlet links all point to example.com (placeholder, fine).

**Console/fonts.** Could not test console (no devtools) — no visual evidence of failure; all four families render distinctly, 7 woff2 self-hosted, zero third-party requests. Glyph spot-check clean (— " " ° ✕ − · → …).

**Responsive.** Could not resize viewport; CSS static analysis only. .wrap max 760px centered; body overflow-x hidden (clips, doesn't scroll); nav overflow-x auto (safe); masthead clamp + overflow-wrap (safe). **Risks:** floral SVGs likely overlap masthead text ~360px; at 1920 the 760px column floats with wide photo margins (no media queries — fine, but deliberate?). **Tap targets under 44px:** nav links (~24–28px), A−/A+ (~25px), date select (~28px) — fail on touch widths. Pile/story rows pass.

**Accessibility.** Tab order sane; **no custom focus styles** (browser default only); expandable cards are `<div cursor:pointer>` with **no tabindex/role — not keyboard-focusable or operable at all**; only landmark is an unlabeled `<nav>` (no main/header/footer); decorative SVGs lack aria-hidden; no `<img>` (photo is CSS background). prefers-reduced-motion handled correctly. Contrast (computed): body 15.6:1 ✓; dim/nav ~6.9:1 ✓; orange on dark 6.0:1 ✓; red #ff8b7a 8.1:1 ✓; Hot Take tag 4.9:1 ✓ (marginal). **At risk:** dim text over brightest mist areas ~4.2–4.3:1 estimated — may dip under 4.5:1 (unverified, needs pixel sampling).

## B. Design dissection (opinion, ranked by impact)

**B1. The orange accent budget is blown.** Orange appears on: kicker label, active nav pill, ticker keywords, TL;DR labels AND borders, drop caps, pull-quote marks AND borders, outlet badges, progress bar, s0 plate, masthead shadow, bottom banner. The bible's Braun rule: one functional accent, reserved for controls and alerts — never decoration. When everything is accent, nothing is. *Fix:* orange = interactive + alerts only (nav active, buttons, links, A±, breaking). Demote the rest: masthead shadow → warm stone `#A69B8B`; drop caps → plaster `#EDE6D6`; TL;DR borders → line color; pull-quote borders → line color. Pure CSS, biggest visual win on the page.

**B2. The masthead's orange offset shadow reads as merch, not masthead.** A nameplate wants ceremony and authority (the blackletter tradition); a soft orange drop shadow makes it look like a streetwear tee graphic. Either kill it or commit to a hard offset (neo-brutalist, no blur) — the current soft version is neither. `text-shadow: none` or `3px 3px 0 #16130E`.

**B3. Body measure too wide.** ~700px / 75–85 chars at 15.5px Newsreader. Editorial canon: 45–75. Either cap body measure at ~620–660px or lift body to 16.5–17px/1.7. The 760px column is fine for cards; long-form needs its own narrower measure.

**B4. It's dark-only, but the vision is warm plaster.** Jeremiah's palette centers plaster `#EDE6D6` as a reading surface ("canvas/plaster reading surfaces"), and the temperature doctrine says warm does contact work. Right now the entire paper is ink-black ground — all cold, no warm contact surface. *Fix:* plaster cards on the dark ground, or a light "paper mode" toggle. This is the single biggest gap between the build and his stated vision.

**B5. Cards wear five surface treatments at once.** Asymmetric organic radii + hairline borders + layered shadows + wood-grain overlay + backdrop blur/frosted glass. Material honesty says pick two. The wood-grain overlay on a digital card is skeuomorphic noise — kill it. Keep hairline + one shadow.

**B6. The floral corner flourishes fight the industrial system.** They're the one heritage device per spread, which the formula allows — but curled floral line-art sits oddly next to riveted steel plates and stencil caps. Options: redraw them as engraved-rule/tracery geometry (Gothic-structural, matches the steel) or drop them. Also a real overlap risk at ~360px.

**B7. Motion: seven simultaneous entrance animations.** Photo fade + photo drift + masthead rise + headline rise + dek rise + ticker marquee + floral draw, all on load. Individually fine; together it's ceremony before reading. Kill the 50s infinite photo drift (pure decoration) and keep the staggered rise.

**B8. Section color system: 8 hues is too many.** 12 sections across orange, steel×2, ochre×2, rust, plaster×2, lilac×2, red. The lilac/ochre plates read muddy on dark ground. Collapse to 4–5 section colors max; let orange stay the single loud one.

**B9. Nature imagery: commit to Bing-style, stop using it as wallpaper.** Jeremiah wants nature photography integrated like Bing's daily wallpaper — bold, full-bleed, captioned/credited, photography that LEADS. Right now the misty forest is a duotone texture wash behind the whole page, which reads as atmosphere, not photography — and Jeremiah says it feels like hunting, not a paper. *Fix:* give each edition one real hero nature photo (full-bleed, with a small photo credit/caption line, Bing-style), and pull the forest texture out from behind the body text. The page ground should feel like a newspaper — ink and plaster — while nature lives in the photography. Lowest risk path: keep the hero slot, make it a real credited photograph per edition instead of a permanent background.

**B10. Voice: the quirk is wanted — make it authored, not default.** Jeremiah wants this paper fun + quirky + serious + factual, with its OWN voice — playful labels like "VIBE CHECK" are on-brand in spirit, but right now they read as generic AI quirk, not a deliberate editorial voice. The fix isn't to kill the playfulness, it's to author it: consistent section voices, headline wit that matches the paper's personality, real photo captions with credit lines. What's actually templated-feeling is the decor: floral flourishes + wood-grain overlay + stock background wash. The steel plates, mono labels, and spec-sheet card feel authored. Subtract the decor, author the voice.

## C. Output

**Top 10 changes, ranked (impact/effort):**
1. Orange discipline (B1) — demote decorative orange to stone/plaster/line. High impact, CSS-only.
2. Keyboard-operable cards: add `tabindex="0" role="button"` + `:focus-visible` styles to story/magazine/pile cards. High impact, small.
3. 44px tap targets on nav, A−/A+, date select. Medium, CSS-only.
4. Body measure ≤660px or 16.5px/1.7. High readability win, one rule.
5. Warm plaster surfaces or paper-mode toggle (B4). High vision-alignment, medium effort.
6. Kill wood-grain overlay; one shadow per card (B5). Medium, CSS-only.
7. Masthead shadow: remove or hard-offset (B2). Medium, one rule.
8. Remove or repurpose dead controls (date select, design pill). Small, fast.
9. Collapse section colors to 4–5 (B8). Medium, token edit.
10. Kill photo drift; keep staggered rise (B7). Small, CSS-only.

**If you only change three things:** (1) orange discipline, (2) keyboard + tap-target operability, (3) plaster warmth / paper mode.

**Could not test:** console errors, exact byte sizes, responsive widths other than desktop (no resize), pixel-level contrast over the photo, whether edition.json/tldr.json are fetched at runtime.

## D. Comparisons (opinion)
- **NYT app:** narrower body measure, ruthless type hierarchy — better long-form readability than this preview's 700px measure.
- **Bloomberg:** denser data modules, one accent color with total discipline — the model for the spec-sheet/vibe-check card done right.
- **The Pudding:** every visual essay has one authored hero treatment, never stock texture — the standard the masthead photo field should aim at.
