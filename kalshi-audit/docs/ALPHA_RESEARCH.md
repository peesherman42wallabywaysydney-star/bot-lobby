# Alpha Research — New Sources for the Kalshi Desk

Researched 2026-09-24. Scope: NEW fair-value/signal sources only — the desk already
covers crypto (spot+vol), indices, econ nowcasts, weather kills, and Senate
cross-venue. Sports/props/parlays/combos currently get consistency scans only.
Strict budget: free sources rank higher; anything paid is flagged and ranked down.
Nothing here was backtested — every item needs validation on live books before
sizing. No trades placed, no money moved for this research.

---

## Ranked shortlist (top 5)

### 1. Polymarket ↔ Kalshi cross-venue pricing (full board, not just Senate)

- **Data source:** Polymarket Gamma API `https://gamma-api.polymarket.com`
  (market discovery, `outcomePrices`, volume, liquidity) + CLOB public endpoints
  (`/price`, `/midpoint`, `/book`) for executable depth. **Verified live from
  this machine 2026-09-24** — no auth, no key, no signup; ~4,000 req/10s
  (Gamma), ~9,000 req/10s (CLOB). Confirmed real overlap: Polymarket "Fed
  Decision in October?" ($11.9M volume) vs Kalshi `KXFED`; "How many dissent…"
  ($19k) vs Kalshi dissent markets; full sports slate (game winners, props).
- **Update cadence:** every 5-min cycle, inline with the existing scan.
- **Why the edge should exist:** the two books never synchronize themselves —
  separate users, fee schedules, liquidity, information flow. Academic work
  documented ~$40M in arb extracted from Polymarket (Apr 2024–Apr 2025);
  practitioner research finds cross-venue spreads persist for hours because the
  pool of capital straddling both books is small. Retail-dominated books with
  no institutional market-making infrastructure misprice chronically.
- **What it takes to build:** the desk already has the pattern
  (`_pm_event`/`_pm_side` in `edge_scan.py`, Senate-only). Extend to a mapping
  table: Polymarket event slug ↔ Kalshi series for Fed, CPI, crypto, weather,
  and sports games. Keep the existing staleness gates (active, unclosed,
  future-settling, ≥$25k volume). Compare executable prices (book depth, not
  mid) on both sides.
- **Honest caveats:** we cannot hedge on Polymarket (no wallet connected), so
  treat divergences as a *signal* (fade the stale book), not a locked arb —
  unless resolution sources are verified identical. Mapping slugs↔tickers is
  the real work; fuzzy matching will produce false pairs.
- **Cost:** $0. **Effort:** medium.

### 2. YES-bias retail fade (behavioral overlay, zero data cost)

- **Data source:** none — pure logic change using the desk's own books.
- **Update cadence:** applies to every candidate evaluation, every cycle.
- **Why the edge should exist:** Bartlett & O'Hara (2026, Kalshi data):
  market makers earn **+1.91¢/contract on single-name markets not from the
  spread but from a frequency edge** — YES-biased uninformed takers
  systematically overbet YES on markets that mostly settle NO. The behavioral
  tax (~$18.2M on NO-settling markets) cross-subsidizes everyone else.
  Independent live testing on Polymarket sports confirmed the same asymmetry
  (YES fills −4.6¢, NO fills +2.3¢). Translation: the NO side is structurally
  the better side on retail-heavy books.
- **What it takes to build:** add a retail-fade overlay to candidate scoring —
  e.g. require +2¢ extra edge for YES-side entries on retail-heavy series
  (sports, parlays, politics), and/or tilt sizing toward NO. A/B it against
  the current log before making it default.
- **Honest caveats:** the paper is 2026 Kalshi data but markets evolve; the
  overlay must earn its place against the desk's own fill history, not the
  paper alone.
- **Cost:** $0. **Effort:** low.

### 3. Cross-event logical containment (parlay-vs-legs, touch-vs-terminal)

- **Data source:** Kalshi's own order books (no external data).
- **Update cadence:** every 5-min cycle.
- **Why the edge should exist:** if event P logically implies event A
  (P ⊆ A), then P(P) ≤ P(A) must hold — a quote violating that is a locked
  vertical. Kalshi's own no-arb scanner is **within-event only**, so three
  classes are unchecked: parlay-vs-legs (listed combo price vs product of leg
  prices), touch-vs-terminal ("ever touches K" must cost ≥ "closes above K"),
  and unflagged cross-series sets. The counterparty on parlay legs is retail
  parlay flow — the best-documented bias in sports betting is overpaying for
  correlated multi-leg tickets, which pushes the parlay bid *up*, exactly the
  direction that opens the lock. The desk's consistency scans are all
  within-event; this is the cross-event extension.
- **What it takes to build:** for each listed combo series, map combo market →
  leg markets (`combo.py` exists — extend it), compute Π(leg YES asks) vs
  combo YES bid each cycle; flag `combo_bid > Π legs_ask` (sell combo / buy
  legs) and the reverse. Same check for touch-vs-terminal crypto pairs.
  Note: listed combos can't be arbitraged atomically (no multi-leg endpoint),
  so treat violations as strong directional signals with leg-fill risk, not
  risk-free locks — size accordingly.
- **Honest caveats:** true locked arbs will be rare (arb watchers keep
  within-ladder tight at 0.97–0.99); most value is the one-sided retail-fade
  on overpriced combos.
- **Cost:** $0. **Effort:** medium (combo→leg mapping is the work).

### 4. NFL win-probability model (nflverse + ESPN)

- **Data source:** **nflverse** via `nflreadpy` (Python) — free play-by-play
  back to 1999, EPA, win-probability and expected-points models, served as
  parquet from GitHub releases, no key. **ESPN hidden API**
  (`site.api.espn.com/apis/site/v2/sports/football/nfl/…`, no key/no signup) —
  scoreboard, injuries, transactions, depth charts; CDN game package carries
  live win probability. Both confirmed current as of 2026-09.
- **Update cadence:** weekly model refresh (nflverse data updates post-game);
  injury/news adjustments via ESPN on the 5-min cycle on game days.
- **Why the edge should exist:** Kalshi lists 376 sports series; NFL game
  markets are among the highest-volume and most retail-heavy. A real
  EPA/Elo-based win probability beats the vibes-based pricing of retail flow,
  and the desk currently prices zero sports fundamentally.
- **What it takes to build:** preseason team priors from nflverse EPA per play
  + Elo; weekly Bayesian update; injury downgrade from ESPN injury reports;
  convert to fair moneyline; compare vs Kalshi `KXNFGAME`-family markets with
  the standard 15¢ bar. Backtest the 2024–2025 seasons from nflverse history
  before going live.
- **Honest caveats:** biggest build of the five; ESPN's API is unofficial and
  can change shape without notice (build defensively); NFL is weekly so the
  5-min cycle mostly idles — value concentrates on Sundays and injury news.
- **Cost:** $0. **Effort:** high.

### 5. Soccer xG model (Understat + ClubElo)

- **Data source:** **Understat** — free shot-level xG for top-5 European
  leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1) via session JSON API, no
  key (no official API — data rides in page payloads; use the documented
  session-JSON approach, not the dead `<script>`-tag scrapers). **ClubElo**
  (`api.clubelo.com`, free, daily team ratings + fixture probabilities).
  **ESPN** soccer scoreboard for fixtures/results. All free, all current.
- **Update cadence:** daily (ClubElo updates daily; Understat lags matches
  ~24–48h — use rolling xG, not yesterday's game).
- **Why the edge should exist:** xG-derived attack/defense strengths fed
  through a Poisson (or Dixon-Coles) model produce fair match odds that beat
  raw form tables; Kalshi lists soccer markets and retail soccer flow is thin
  and sentiment-driven. Daily match cadence fits the desk's cycle better than
  NFL's weekly rhythm.
- **What it takes to build:** rolling xG for/xG against (last 5–10 matches,
  home/away split) + ClubElo as prior → Poisson scoreline distribution →
  fair 1X2; compare vs Kalshi soccer game markets at the 15¢ bar.
- **Honest caveats:** Understat covers top-5 leagues only — skip everything
  else; the 24–48h indexing lag means no same-day xG; Dixon-Coles > plain
  Poisson for low scores.
- **Cost:** $0. **Effort:** medium-high.

---

## Honorable mentions (ranked below the top 5)

- **The Odds API free tier** (500 credits/mo) — daily sharp-line snapshot
  (DraftKings/FanDuel moneylines) as an anchor vs Kalshi sports. Too thin for
  the 5-min cadence; use as a once-daily calibration input, not a live feed.
- **Polymarket CLOB book depth** — free; use alongside #1 to size the
  cross-venue signal by real executable depth on the Polymarket side.
- **Kalshi 15-min crypto binaries** — desk already covers crypto; no new work.

## Looked at, do NOT build

- **Paid odds feeds** (Sportradar, Opta/Stats Perform, API-Football paid
  tiers): enterprise pricing, out of budget. Revisit only if the desk is
  profitable enough to fund them.
- **Pre-game passive market making on sports:** tested by practitioners —
  adverse selection from informed flow wipes out spread capture at retail
  scale (negative EV). We are takers with an edge bar, not makers.
- **Pinnacle de-vig calibration as a primary signal:** converges within
  ±0.8% — no systematic mispricing found. Useful as a sanity check, not alpha.
- **News-sentiment LLM trading on politics:** no free reliable low-latency
  feed; the desk's Senate cross-venue (#1 applied to politics) dominates it.

## Suggested build order

1. #2 (YES-bias fade) — hours, zero cost, applies everywhere immediately.
2. #1 (Polymarket cross-venue) — extends a proven in-desk pattern; biggest
   coverage win.
3. #3 (cross-event containment) — structural, permanent; pairs with #2 on
   combos.
4. #5 (soccer xG) — daily cadence, contained scope, good first real model.
5. #4 (NFL model) — highest ceiling, highest cost; build once #5 validates
   the modeling pipeline.
