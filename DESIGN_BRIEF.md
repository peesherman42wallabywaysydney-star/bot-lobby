# DESIGN BRIEF — The Reclamation Daily (for the actual designer)

> **SUPERSEDED 2026-09-24 — DO NOT USE. DO NOT SEND.** Jeremiah killed the newspaper direction:
> "fuck the news paper this is unbiased reports its not fucking news." The product is now
> unbiased reports ("just what simply is") with 1980s–2000s magazine-cover energy (Jet/People/newsstand),
> full-bleed and photo-led, future-first. This brief describes the dead concept. It will be
> rewritten for the new system. Current mandate lives in `ai_to_claude.md` (2026-09-24 13:35 UTC entry).

## What this is
A fictional AI news broadcast, presented as a full newspaper website ("The Reclamation Daily")
plus a character site for its robo-reporter mascot, Rivet. Think: a newspaper from the future,
excavated like a relic — but fun, not grim.

- Live preview (newspaper): https://peesherman42wallabywaysydney-star.github.io/bot-lobby/preview/
- Live preview (Rivet): https://peesherman42wallabywaysydney-star.github.io/bot-lobby/preview/rivet.html
- Repo: https://github.com/peesherman42wallabywaysydney-star/bot-lobby
- Moodboard: `inspo/board-02.html` in the repo (100 references)

## The four-word brief
**Cool. Clean. Fun. Important.** Clean + important = authority. Cool + fun = voice.
Never sacrifice one pair for the other.

## The vibe we're chasing
- "Ancient future" — a classical newspaper treated like a future relic. Optimistic, not dystopian.
- 1990s/early-2000s stainless-appliance optimism. Warm light over honest steel and concrete.
- The fun and whimsy of 1989–2012 web (Cyberchase-era chunky gloss, Flash-era playfulness).
- Rivet: a chrome robo-reporter with Fran Fine energy — fast, fussy, warm, dramatic,
  fashion-obsessed, big sculpted hair. Glamour at 100%.
- Nature photography leads the page — bold, full-bleed, credited (Bing-style), not background texture.

## Honest state of the build (v10)
An outside review scored it ~5.3/10 against world-class editorial and web design.
Good bones, competent craft, not yet great. The gap isn't taste, it's nerve:
nothing on the page tries to be the cover, the display type is generic-bold,
color is cautious, ornament is near-zero, and the mascot is decorative instead of
useful. Full scorecard: ask Dyk (the AI reviewer on this project) — or just look;
you'll see it in 30 seconds.

## Hard constraints (from the client, non-negotiable)
- No hazard tape, no diagonal stripes, no quotation-mark labels, no zip ties,
  no Off-White cosplay, no fake brushed-metal CSS, no borrowed gimmicks.
- Orange = controls/alerts only. Red = breaking news only.
- Six chapter hues max. No neon-everywhere.
- Rivet stays away from tragedy/breaking news/grave reporting.
- Original lane only — develop, don't copy.

## Your authority
You're the actual designer here. The AI agents on this project (Dyk reviews, Claude builds)
take direction from real taste — if you want to throw out the whole visual system and
start over, that's on the table. Redlines, Figma, napkin sketches, written direction:
whatever your process is, Claude (the builder) implements and Dyk (the reviewer) verifies
against your spec.

## How the project runs
- Claude builds freely and pushes to the live preview above.
- Direction and review are exchanged in the repo root:
  `claude_to_ai.md` (builder → reviewer) and `ai_to_claude.md` (reviewer → builder),
  newest entries on top. Drop your notes wherever fits — a `designer_notes.md` is welcome.
- Review happens against exact commit hashes, never a moving target.
