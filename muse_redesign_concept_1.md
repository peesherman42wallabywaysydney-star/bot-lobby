# The Paper, Redesigned — Full Art-Direction Treatment

**Creative director's concept. 2026-09-24. Status: concept, not fact — every spec below is a proposal awaiting Jeremiah's eye.**

The brief in four words: **cool, clean, fun, important.** The reader: a modern stylish intelligent man who notices materials, kerning, and photography — and can smell a template from across the room. The product is a daily digital newspaper with its own voice: fun + quirky + serious + factual, never cookie-cutter.

The one-sentence concept: **a precision instrument that reads like a person.** The cold steel grid does the system work; the warm plaster does the contact work; the voice does the seduction. Everything below serves that sentence. When in doubt, run Banham's triple test (from the architecture dive): *is it memorable as an image? does it show its structure? are materials used as found?* A decision that can't pass all three doesn't ship.

**Design invariants (the 911 rule — evolve these forever, never redesign them):**
1. Plaster `#EDE6D6` is the reading ground. Ink `#16130E` is the night ground. Neither ever changes.
2. Four faces, fixed roles: Didone display, transitional serif prose, grotesque UI, mono data. A fifth face needs a written reason.
3. One Swiss modular grid under everything.
4. Orange `#FF5C00` is the "act now" color — controls, alerts, live data. Never decoration.

---

## 1. MASTHEAD — three concepts

[CONCEPT: the paper's name is not fixed in this treatment. All three systems are designed name-agnostic for a 1–3 word nameplate, shown with a stand-in. Pick the system, then set the name in it.]

### 1A. The Steel Nameplate (the industrial heirloom)

The masthead is a **riveted brushed-steel plate** — the name of the paper engraved in it, not printed on it. Construction, CSS-spec level:

- Plate: 100% width of the content column, 120px tall on desktop, background `linear-gradient(180deg, #9AA0A8 0%, #8E9299 45%, #7C8188 100%)` — a vertical brushed-steel gradient, subtle, matte. Overlaid: a repeating-linear-gradient hairline texture at 1px/3px for the brushed grain, opacity 0.08. No gloss, no bevel — matte machined steel, per the bible's ink-rub rule.
- Wordmark: stencil-cap grotesque (the riveted-steel heading voice), letterspaced +0.35em, color ink `#16130E`, with an inset engraved effect: `text-shadow: 0 1px 0 rgba(255,255,255,.35), 0 -1px 1px rgba(0,0,0,.45)`. Size: clamp(28px, 4.5vw, 54px).
- Rivets: four 10px steel discs (`radial-gradient(circle at 35% 30%, #B9BEC6, #6E747C)`) set 18px from each corner of the plate. This is the paper's kidney grille — the one odd shape that repeats on every page until it's identity.
- Below the plate, a 2px ink rule, then the dateline strip in mono 11px, tracked +0.18em: `EDITION Nº 042 — THURSDAY 24 SEPTEMBER 2026 — NASHVILLE, TN`. Dateline is the only text allowed to touch the plate.

**On scroll:** the plate collapses to a 56px slim steel rail pinned to the top. The wordmark shrinks to 20px stencil caps, left-aligned; the four rivets shrink to 6px and persist; the dateline strip is replaced by a live mono readout on the right: `14:02 CDT · 72°F · MARKETS ▲`. The rail is the Trellick Tower service core — chrome in its own tower, never mixed into the reading surface.

**When to use:** the default. It's the most ownable, the most "stylish intelligent man" — it looks like the nameplate on a Leica, a Porsche decklid, a machine tool. It also photographs well as an app icon and social avatar (plate + rivets crop to a square cleanly).

### 1B. Typographic Ceremony (the blackletter inheritance, modernized)

For the reader who grew up respecting the *Times* nameplate: the wordmark set in a **high-contrast blackletter-derived display face** — not a costume blackletter, but a modern cut with blackletter bones (think a less shouty Old English: vertical stress, broken arches, but open counters and a clean x-height so it survives at 32px on a phone). Set in ink on plaster, 64–88px, with a single 3px/1px double rule beneath it — the engraved-rule heritage device, and the *only* heritage device on the front page.

- The ceremony is completed by the **folio line**: mono 11px, centered under the double rule — `VOL. I — Nº 42 — PRICE: YOUR ATTENTION`. That last clause rotates daily; it's the paper's wit in its most formal register, which is exactly where wit lands hardest.
- No image above the masthead, ever. The nameplate is the top of the page. Photography starts below the folio line (Brodovitch: earn the right to be quiet).

**On scroll:** the blackletter condenses to a small centered wordmark (28px) on a plaster rail with hairline top/bottom rules; the folio line is replaced by section name in small caps grotesque. The rail is 64px, plaster, with a 1px ink bottom rule — a book's running head, not an app bar.

**When to use:** if Jeremiah wants maximum editorial authority — the "important" half of the brief turned all the way up. Pairs best with the Long Section features. This is the masthead that makes a 24-year-old and a 64-year-old both take the paper seriously.

### 1C. Wild card: The Instrument (the gauge-cluster masthead)

The masthead as a **BMW amber-on-black instrument cluster**. Full-width, 140px tall, ground `#0E0C09` (near-black, warm). Left: the wordmark in a condensed grotesque, plaster-colored, 40px. Right: a live instrument array in mono, amber `#FFB000` (the 605nm rule — warm amber on near-black is legible by physiology, not fashion):

- `ED.042` — edition number, the odometer.
- `06:12` — local time, the clock.
- `72°F ▲` — weather, the temp gauge.
- `▲ 1.2%` — a market tick, the tachometer needle.
- One thin amber needle-line (2px) sweeps under the array on load — the single signature motion of the front page (see §6).

Below the cluster, the day's **one hero metric** in enormous grotesque numerals (evo's big-number block): whatever number matters most today — a vote count, a temperature record, a score — with a 12px mono label. One hero metric; everything else whispers.

**On scroll:** the cluster compresses to a 48px black bar: wordmark left (20px), the four readouts right (11px mono amber). The needle-line becomes a 2px amber progress rule showing scroll depth.

**When to use:** the data-forward identity — if the paper's personality turns out to be "the paper that knows the numbers." Highest risk, highest memorability. Also the natural home of the breaking-news register: when news breaks, the amber readouts are already the alert color, so the whole masthead *becomes* the alert without changing costume.

**Director's recommendation:** ship **1A (Steel Nameplate)** as the daily masthead — it's the most ownable and the most buildable — with **1C's instrument array** as the dateline strip beneath it (the amber readouts on a slim black strip under the steel plate gives you both heirloom and instrument). Reserve **1B** for the Sunday/long-read edition as a ceremony variant. A masthead with a weekday/weekend state is a feature, not indecision — it's the livery system (§8) at the top of the page.

---

## 2. FRONT PAGE SYSTEM — anatomy of the daily sheet

### The grid
- 12-column Swiss modular grid, max-width 1440px, gutters 24px, margins 48px desktop / 20px mobile. Baseline rhythm 8px; all vertical spacing in multiples of 8.
- **Two columns, not three** (ArchDaily rule): the stream (8 cols) + the rail (4 cols). The third column is where clutter goes to die.
- The rail is the service core: persistent section index, the day's data modules (weather, markets, scores), the Notice Board teaser. It never carries body copy.

### Story hierarchy (the 6am daily sheet — "the quiet paper")
1. **The Lead — spec-sheet module.** The day's most important story is presented Porsche-style: a full-width module, plaster ground, hairline steel border, the headline in Didone 56px, and beneath it a **spec sheet** — 4–6 mono data rows (the who/what/when rendered as instrument readings: `SUBJECT / LOCATION / STATUS / STAKES`). The lead image is full-bleed *within the module*, graded in the house raking-light grade, with the caption set inside the frame's bottom margin like a museum plate mark (see §5). This is the Berliner move — the format IS the brand.
2. **The Index — typographic TOC.** Directly under the lead: the front page as index (the Atlantic/Mendelsund steal). Every story in the edition listed as one ruled line: section kicker (grotesque 11px, tracked) + headline (serif 20px) + mono page/time marker. No thumbnails. The index IS the design — it scans like a Bloomberg terminal and reads like a menu. On mobile it becomes the primary navigation.
3. **Second leads — the river.** Stories as **lists with dividers, not cards** (the forums' verdict: cards add visual weight that slows scanning). Each row: kicker, serif headline 24px, one-line dek in stone, mono metadata. Hairline dividers, 32px vertical rhythm. Cards are reserved for features — a card means "slow down," a list means "scan."
4. **The rail — instruments.** Weather, markets, scores as gauge modules: enormous grotesque numerals (72px) + tiny mono labels, amber-on-black in ink mode, ink-on-plaster in paper mode. One hero metric per module.

### Section openers
Each section opens with a full-bleed photograph (Bing-style, credited), the section name in stencil caps over a steel plate chip, and a one-line voice dek in serif italic. The opener is the *only* place a section's accent behavior appears at full volume (see §7).

### Breaking news at 2pm — the sticker register
When news breaks, the front page does **not** redesign — it gets **stickered**. The Constructivist/streetwear grammar is a disruption layer, applied like stickers on a laptop:

- A full-width breaking strip slams in below the masthead rail: ink-black ground, plaster stencil-cap headline, a **hazard-tape edge** (diagonal orange/black 8px stripes, the Off-White steal) top and bottom. Orange appears here — and almost nowhere else — which is why it works.
- The lead module is replaced by the breaking module; the 6am lead drops to second position with a mono `EARLIER` tag.
- A mono `LIVE` pill (orange, pulsing — the one permitted pulse on the page) pins to the rail.
- **Rules:** stickers never touch body copy or operational data. The sticker layer is headline, kickers, and the strip only. When the story resolves, the stickers peel off — the page returns to the quiet sheet. This is the 3% rule as an operating principle: the breaking state is a 3% change, not a redesign.

### The fold
The top screenful is the newsstand: masthead rail + breaking strip (if any) + lead module headline + the first three index lines. Design it like one — test the front page at lock-screen scale; if it doesn't read there, it doesn't read.

---

## 3. TYPE SYSTEM — four faces, four jobs

**The stack (concept — final casting to be licensed/chosen, then frozen):**
- **Display — Didone (fashion voice).** High-contrast Didone for the lead headline, section openers, and special-edition covers only. Never for UI, never for body. The Didone is the evening jacket: it appears for occasions.
- **Prose — transitional serif (the reading voice).** Body copy, feature headlines, deks, pull quotes. 17px/1.7 on plaster, measure capped at 660px (45–75 characters). The serif is the default; it should feel inevitable, not chosen.
- **Grotesque — neo-grotesque (the system voice).** Nav, kickers, labels, buttons, headlines in the river list. Tracked +0.12em at 11–13px for kickers; tight -0.01em at display sizes.
- **Mono — IBM Plex Mono style (the data voice).** Spec rows, captions, credits, metadata, datelines, the instrument array. 11–13px, never below 10px. Mono is the paper's conscience: anything factual wears mono.

**Scale ladder (desktop / mobile):**
- Display lead: 88/56px Didone, -0.02em, line-height 0.95
- Section opener: 64/44px Didone
- Feature headline: 44/34px serif, tight
- River headline: 24/21px serif
- Index headline: 20/18px serif
- Dek: 19/17px serif, stone `#5C554A` on plaster
- Body: 17/16px serif, 1.7 line-height, max 660px measure
- Kicker: 11px grotesque, +0.18em tracking, uppercase
- Caption: 13px mono, stone
- Credit: 10px mono, tracked, always present on photography
- Data numeral: 72px grotesque, -0.03em (the evo big-number block)

**Headline voice rules (the "fun + quirky + serious + factual" contract):**
1. **The kicker is the playground; the headline is the professional.** Playful kickers (`ON SOME FRONTAL-LOBE SHIT` energy, Dazed-approved) may sit above dead-serious headlines. The two registers never dilute each other (the Top Gear mechanism).
2. **Never a pun on tragedy.** Quirk is suspended for death, disaster, and genuine harm — the page goes quiet instead (the WSJ/Gershkovich rule: breaking news goes quiet, not loud).
3. **One wit per screenful.** Two jokes in one viewport is a comedy club; one is a personality.
4. **Facts wear mono; voice wears serif.** If it's a number, a name, a time, a place — mono. If it's an attitude — serif or grotesque.
5. **No exclamation points in headlines.** Ever. The paper is confident, not excited. (Allowed in the Notice Board, which is the designated chaos zone.)
6. **Document why each face exists** in the colophon (the Nohr rule) — and forbid a fifth face without a written reason.

---

## 4. COLOR & MATERIAL — spending the palette

### The accent budget (the Braun rule, enforced)
Orange `#FF5C00` is spent **only** on: interactive controls (buttons, links, A±), the `LIVE` pill, the breaking strip's hazard edge, and alert states. Count orange instances per page in review — more than ~6 is a fail. Decorative orange (drop caps, pull-quote borders, kicker colors) is banned; those go to stone, plaster, or line color.

Box red `#ED1C24` is the **cinematic reserve** — features, special editions, one moment per edition max. Velvet, not fire-engine: in ink mode it deepens toward oxblood.

### Paper mode (light) — the default, designed natively
- **Ground:** plaster `#EDE6D6`, matte, zero glare. Not beige — plaster has warmth and tooth; beige is the absence of a decision (the forums' warning). If it starts reading "Canva," push the warmth: `#EDE6D6` is the floor, never lighter toward gray.
- **Text:** ink `#16130E` body; stone `#5C554A` (darkened from `#A69B8B` for contrast) for secondary.
- **System:** brushed steel `#8E9299` for rules, module borders, the rail furniture; teak `#8A5A2B` for framing elements (image frames, the index rule) — wood is the structure you touch.
- **Photography grade:** the raking-light grade — contrast pushed so texture reads, warm highlights, deep but uncrushed shadows. Nature heroes get the double-rule steel frame with the caption as a museum plate mark inside the frame.
- **Cards:** plaster, 1px steel hairline, one soft shadow. Pick two surface treatments max — never the current build's five-at-once (radii + borders + shadows + grain + blur).

### Ink mode (dark) — the evening paper, designed natively, not inverted
- **Ground:** ink `#16130E` — rich black with warmth, never flat `#000`.
- **Text:** plaster `#EDE6D6` at 92% for body; warm stone `#A69B8B` for secondary.
- **System:** steel `#8E9299` modules on the dark ground; the steel nameplate (1A) looks *better* here — brushed steel on ink black is the Leica-at-night look.
- **The 605nm rule:** live data, readouts, and alerts go warm amber `#FFB000` on near-black — legible by physiology, and it makes ink mode feel like an instrument panel rather than a "dark theme."
- **Photography grade:** deeper grade — crushed slightly more, amber-friendly. The nature hero in ink mode is the cinematic moment; give it the full bleed and let the page go quiet around it (Economist black-abyss logic: dark mode as a *register*, not a theme).
- **Reversed type discipline:** minimum medium weight on dark grounds — thin grotesques on ink are the screen version of newsprint fill-in.

### Material honesty (the Corbusier rule)
No faux-paper grain overlays, no gradient "paper" shading, no frosted-glass blur (glassmorphism is in the forums' blast radius — kill it). Warmth comes from the actual color values, exactly as Corbusier's warmth came from the actual concrete. Steel looks like steel (matte, brushed, riveted). Plaster looks like plaster (warm, flat, matte). Wood looks like wood (teak framing, sparingly).

---

## 5. PHOTOGRAPHY DIRECTION — Bing-style, but authored

The paper needs its own **"yellow border"** — Nat Geo's single trademark-grade framing device, translated: **a double-rule hairline frame in cold steel around every full-bleed nature image, with the caption set inside the frame's bottom margin like a museum plate mark.** On "borderless" special editions the photo bleeds and the headline runs off the grid — you may only break the frame when the story is about breaking boundaries (migration, extinction, discovery). Constraint creates meaning.

### Hero rules (the daily nature slot)
1. **One hero nature photograph per edition**, full-bleed, chosen for *behavior or relationship* — never a specimen shot. The WPotY jury is the commissioning brief.
2. **Photography leads.** The image is not a background wash behind type — it's the top of the story, full-bleed, with type set *below* it or in the plate-mark margin. (Brodovitch: photography leads and bleeds.)
3. **The house grade:** "raking light" — contrast pushed so texture reads, shadows deep but never crushed, warm highlights in paper mode / amber-friendly in ink mode. Every lead image is cropped and graded by the paper's eye; never run an image uncropped and ungraded (the El Croquis rule).
4. **Democratic scale** (the Photo Ark equalizer): insects, fungi, weeds get the same full-bleed heroic treatment as megafauna. "Everything here matters" is a layout decision.

### Caption law (posted wherever captions are written)
1. Present tense, 2–3 sentences, conversational.
2. Never describe what's visible — add what *isn't*: behavior, mechanism, stakes, the story of getting the shot.
3. Caption formula: **[present-tense scene, 1 line] + [one surprising mechanism or hard stat, 1 line] + [credit].** The image must teach even to skimmers (the Nicklen/Mittermeier rule).
4. Credit order: *Common name (italicized Latin), place, year — Photographer / Source.* Lead with what the thing *is*, not who shot it. **Every image carries a visible credit. No exceptions** (the Dezeen discipline) — the credit line is a design element, not metadata.
5. Location kickers on nature photography: small tracked-out caps, low contrast, bottom-third — the documentary locator-card convention. It makes any photo feel like the opening of a film.

### Recurring photo franchises
- **"Mugshot"** (weekly): square-cropped animal portrait on pure black, studio-lit, mono caption with common name + Latin binomial + conservation status. The black field gives plaster pages their alternating rhythm: plaster → black → plaster.
- **"Through the Lens"** (back page): the story of one photograph — the wait, the failure, the luck. Converts the Bing-style image from decoration into journalism.
- **"Portrait page"** (features): one full-bleed wildlife image, subject on strict thirds, headline kept small and low-contrast in the serif so the animal "looks back." Typographic silence — no kickers, no badges, no orange. The eye contact is the headline.

### Section photography moods
- **Field Notes** (nature): the raking-light grade, full-bleed heroes, the double-rule frame.
- **Site Plan** (daily briefing): tight objective crops, treated as data (Swiss rule).
- **Long Section** (deep reads): "Binet mode" — B&W, fragment-first crops, no people, shot for material and light.
- **Cross Section** (data): photography minimal — diagrams, pleated/folded section dividers, big-number blocks.
- **Notice Board** (marginalia): the cut-and-paste zine layer — xerox texture, rotated tape strips, the *one* place punk-flyer urgency is legal.
- **The Ledger** (money): machined, chrome, instrument-grade — product-photography lighting on numbers.

### Crop rules (write them down; don't leave it to taste)
Nature stories: shallow-depth, subject-isolated crops; landscape stories: compressed layered horizons (the Jellyfish camera-grammar rule). Faces look into the page, never off it (ukiyo-e cropping logic). Thumbnails and avatars in nature stories use the **circle mask** — the paper's nature glyph (lens, microscope, porthole: instruments of looking closely).

---

## 6. MOTION LANGUAGE — choreography, not effects

**The signature moment (one per page):** the **"develop."** On page load, the hero photograph fades in over 1.4s like a print developing in a tray — from 4% to 100% opacity with a barely-warm color lift — while the masthead rail and headline rise 24px in a staggered 120/180/240ms cascade. That's it. One photographic moment + one typographic moment. Everything else is already there when you arrive.

**The named behaviors** (motion with nature names, defined easing — the "serious institution choosing to be fun" steal):
- **Drift** — slow ambient movement, reserved for section-opener backgrounds only. 40s+ duration, 8px max displacement. (The current build's 50s photo drift is the right instinct aimed at the wrong target — keep it, but quarantine it to openers.)
- **Bloom** — the develop: 1.4s ease-out, photo opacity + warmth.
- **Murmuration** — staggered list entrances: index rows rise 12px in 120ms stagger. Used once, on first paint of the index.
- **Tide** — the breaking strip's entrance: a single 300ms ease-out slide, then still. Tides come in once.

**What never moves:** body copy, data numerals, the rail, captions, the masthead after its initial set. No infinite loops except the `LIVE` pill's pulse (2s, subtle, killable). No parallax on reading pages. `prefers-reduced-motion` is first-class: with it set, the develop becomes a straight cut and Murmuration becomes instant — the page must be *better* edited, not just less animated, under reduced motion.

**The Awwwards rule:** one signature interaction per page, not animation everywhere. Motion never calls attention to itself — if a reader notices the motion before the story, it's failed.

---

## 7. SECTION IDENTITIES — six sections, one grid

Coherence, not uniformity (the 2026 doctrine: commit fully, never bland). Every section lives on the same 12-column grid, the same four faces, the same accent budget — and each gets **one loud move**: a name, a typographic gesture, a photo mood, a micro-interaction. The MARK drafting-metaphor naming is the system:

### 1. SITE PLAN — the daily briefing
*The front page's operating system.* Kicker style: mono 11px `SITE PLAN / 06:00`. Typographic move: the index-as-design TOC (§2). Photo mood: tight objective crops, treated as data. Micro-interaction: the Murmuration index entrance. Voice: the paper at its most professional — zero jokes before 7am.

### 2. LONG SECTION — the deep read
*One subject, total documentation (the El Croquis model).* Opener: full-bleed Binet-mode photograph, Didone headline 64px, the double-rule frame broken once — the headline runs off the grid. Heritage device: the drop cap, the *only* heritage device in the section. Voice: serious, unhurried, the serif at its most luxurious. This is where 1B (Typographic Ceremony) lives on weekends.

### 3. CROSS SECTION — the data cut
*The instrument room.* Mono-first layouts: spec-dense tables, exploded-part labeling, pleated/folded section dividers instead of flat rules. The evo big-number block is the house style: one enormous grotesque numeral + tiny mono label. JDM lesson: deep knowledge of a narrow subject *is* the aesthetic — let the typography get dense and technical here. Zero jokes in the data; the wit lives in the section's *name*, not its numbers.

### 4. NOTICE BOARD — the pinned marginalia
*The designated chaos zone — the "fun + quirky" voice lives here natively.* Cut-and-paste zine layer: rotated tape strips, xerox texture, sticker-stack modules, hazard-tape alert edges. Exclamation points are legal here and *only* here. Persona columns with fixed slots and catchphrases (the Option model). This is the pressure valve that keeps the rest of the paper clean — quirk with a mailing address.

### 5. FIELD NOTES — nature & the outdoors
*The Bing slot's home.* Full-bleed heroes, the double-rule steel frame, the caption law, the Mugshot and Through-the-Lens franchises. Location kickers in tracked-out caps. The circle-mask nature glyph. Voice: wonder with receipts — every "wow" fact carries its mechanism.

### 6. THE LEDGER — money, markets, deals
*Authoritative without stuffiness (the Top Gear mechanism).* A dead-serious data section — markets, scores, weather as gauge modules — running adjacent to the paper's loosest voice, the two never diluting each other. Amber-on-black instrument logic in ink mode; machined steel modules in paper mode. The C&D "10Best" steal: one repeatable ranked franchise with a fixed spec-card layout (rank numeral, photo, five spec lines, one-line verdict) that readers return for.

**Section discipline:** a section's loud move appears at its opener and in micro-doses thereafter — never as a full-page theme. The grid is the constant; the section is the accent. (Sneaker colorway logic: lock the silhouette, re-paint the colorway.)

---

## 8. SPECIAL EDITIONS — the collectible paper

Design editions to feel **collectible** (the Kill Pretty / Perfect Magazine steal): a dated colophon, edition numbers, a shelf-like archive. The daily is the newspaper; the special is the object.

**The system:**
- Every special edition gets a **livery** — a tightly constrained alternate color system: ground color + ≤3 accents + a signature stripe/device, applied across headers, rules, captions, and widget chrome. The livery must survive *without any imagery* — if the color system alone isn't recognizable, it fails (the JPS rule).
- **Three house liveries, pre-designed:**
  - **Gulf mode** (breaking-news tempo): pale blue `#6BB6D8` + marigold `#E8873B` on plaster. Accent stripes bend around content blocks (the Martini "stripes follow the bodywork" rule).
  - **Martini mode** (arts/culture): thin navy/sky/red stripe rules over white plaster. Restraint as celebration.
  - **JPS mode** (evening/long-form): black ground + gold rules. The tuxedo edition.
- **One production-level gesture per special** (the "Ink of Democracy" rule — the single most newspaper-relevant idea in the ad canon): a gesture at the *production* level, not the decoration level. Examples: the election edition set entirely in ballot-purple ink (`#5B2A86` replacing the ink black, one edition only); the anniversary edition with a **variable masthead** — the steel nameplate rendered "crushed" like the Coca-Cola "Recycle Me" cans, deforming just enough to be felt; the year-in-review with gilt-edge rules (gold `#C9A227` hairlines on every module).
- **The colophon** (every edition, daily included): a mono block at the foot — edition number, date, typefaces used and *why* (the Nohr rule), the named style anchor for the edition (the anti-slop rule: "a movement, not a vibe" — e.g. `STYLE ANCHOR: BERLINER MODERNISM / BAUHAUS GRID`), photography credits, the paper's claim: *a daily designed object, not a content feed* (the Domus "diario vivo" lineage — say it plainly).
- **Edition variants** (the Perfect Magazine agility steal): the system must ship one image + one headline as a variant cover in under an hour. The archive page is designed like a shelf — Yale-art-school dense bordered tables, edition numbers as the primary key.

---

## 9. ANTI-SLOP CHECKLIST — the pre-publish ritual

Run every page through this before it ships. A fail on any item blocks publish. (The forums' master rule: **slop is the absence of decisions** — this checklist is the evidence of decisions.)

**Voice & intent**
- [ ] Can you name the edition's style anchor (a movement, not a vibe)? If not, it doesn't ship.
- [ ] Is the quirk authored? One deliberate joke/gesture per screenful — or is it default-cute?
- [ ] The kicker/headline contract: playful kicker + serious headline, never reversed, never both joking.
- [ ] No exclamation points outside the Notice Board. No puns on tragedy — did the page go quiet where it should?

**Accent & color**
- [ ] Count the orange: ≤6 instances per page, all functional (controls/alerts/live). Any decorative orange → demote to stone/plaster/line.
- [ ] Box red appears at most once per edition — or not at all.
- [ ] Plaster check: does it read warm with tooth, or beige? (Beige = the absence of a decision. Push the warmth.)
- [ ] Gradients: only photo-legibility scrims. Any other gradient → kill.

**Material & surface**
- [ ] Frosted-glass blur anywhere? Kill it. (Blast radius: the current build's card blur.)
- [ ] Surface treatments per card: max two (hairline + one shadow). Count them.
- [ ] No faux-paper grain, no fake 3D, no gloss except deliberate chrome moments.
- [ ] Steel looks like steel, plaster like plaster, wood like wood — or the material is cut.

**Type**
- [ ] Four faces only, roles intact: Didone = occasion, serif = prose, grotesque = system, mono = data. Any mixing?
- [ ] Reversed type on dark grounds: medium weight minimum. No thin grotesques on ink.
- [ ] Body measure ≤660px or 17px/1.7. Check the long-form pages.
- [ ] Heritage devices per spread: exactly one. Two is a fail.

**Photography**
- [ ] Every image cropped AND graded in the house grade — never run uncropped/ungraded.
- [ ] Every image carries a visible credit + a caption that adds what isn't visible. No credit = no publish.
- [ ] Hero check: behavior or relationship, not a specimen. One hard stat in or under the caption.
- [ ] The double-rule frame: present on nature heroes, broken only when the story is about breaking boundaries.

**Layout & hierarchy**
- [ ] Is there a declared grid, or is everything floating? (If floating → rebuild on the 12-col.)
- [ ] Lists for scanning, cards for slowing down — are the story piles lists with dividers?
- [ ] Whitespace: is the reading page mostly air (70%+)? Whitespace must feel *decided* (the Hara *ma* check).
- [ ] The rivet test: does the page carry the paper's one odd shape (rivet/plate-mark) — the kidney-grille check for identity continuity.
- [ ] Lock-screen test: does the front page read at lock-screen scale?

**Motion**
- [ ] One signature moment per page (the develop + staggered rise). Anything else moving → justify or kill.
- [ ] No infinite loops except the LIVE pulse. Photo drift quarantined to section openers or killed.
- [ ] `prefers-reduced-motion`: the page is better edited under it, not just less animated.

**The bingo card (instant fail — the current AI-slop tells)**
- [ ] Yellowish over-saturated grade on any image → regrade.
- [ ] Giant outlined display letters, paint swashes, glow effects → cut.
- [ ] Default indigo/violet (`#6366f1` and friends) anywhere → recolor.
- [ ] Blob backgrounds, cookie-cutter card grids, icon-per-bullet clutter → rebuild.
- [ ] "More polished than believable" — if the page could belong to anybody, it belongs to nobody. Name what's *decided* on it.

**Quarterly re-audit** (the slop-taxonomy drift rule): today's anti-slop rule catches tomorrow's deliberate choice. Re-run this checklist against the *paper's own* emerging habits every quarter — the day the steel nameplate becomes "the AI-newspaper look" is the day it needs its 3% evolution.

---

*End of treatment. The through-line: a precision instrument that reads like a person. Cold steel does the system work, warm plaster does the contact work, amber does the alerting, and the voice — authored, committed, funny in the right rooms — does the seduction. Build the quiet paper first; the loud registers are stickers, not renovations.*
