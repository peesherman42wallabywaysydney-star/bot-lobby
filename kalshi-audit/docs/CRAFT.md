# Kalshi Craft Manual — built 2026-09-22 for Dyk Hedd
Concrete numbers, formulas, decision rules. No theory without a number attached.

---

## 1. Combo (parlay) RFQ pricing — when the quote is beatable

### How the machine works
- You tap legs in the app → Kalshi mints a provisional market → RFQ broadcasts to institutional makers (SIG et al). Quote lands in **1–2 seconds**.
- Quotes are **private, take-it-or-leave-it**. Retail **cannot take the NO side** — selling combos is maker-only.
- Two-step lock: accept → maker confirms (**3 s window** for combos — they're High Volatility Markets) → **1 s** execution timer → fill.
- **Re-request:** an open RFQ on a ticker 409-conflicts until it expires. Quotes **decay within ~2 minutes** pre-game; **seconds in-play**.
- Fee (taker): **⌈7¢ × P × (1−P)⌉ per contract, min 1¢**, rounded up. Q=50c→2c, Q=30c→2c, Q=10c→1c. Add it to the quote before comparing to fair.

### How makers actually price (from 8.93M settled combos, 2026-04→06 study)
- Maker fill = **product of leg mids + ~1.1¢** for decorrelated (cross-game) legs, **+ ~2.5¢** for same-game legs. That premium is a **correlation tax, not a gift** — same-game seller edge is +4.1¢/contract vs +2.9¢ decorrelated.
- **94% of same-game combo asks sit ABOVE the Fréchet upper bound** (min of the leg probs — the most the joint can be under any dependence). Almost every same-game quote is mathematically impossible as a fair price. 47% of mixed, 23% of cross-game also fail it.
- Naive product itself overstates fair: YES legs resolve ~3¢ below mid (favorites priced rich). True independence fair ≈ product − ~2c.
- Overall buyer tape: **−3.3¢/contract equal-weighted, −2.1¢ volume-weighted** (~$171M taker overpay in 2 months). Edge is maker-only.

### Decision rules (q_i = bet-side leg prob, P_ind = product, Q = quote)
1. **Fréchet gate:** B = min(q_i). **Q ≥ B → reject instantly.**
2. **Cross-game:** expect maker ≈ P_ind + 1.1¢. Demand **Q ≤ P_ind − 2¢** (favorite-richness correction). Else walk.
3. **Same-game:** never use the product. Need your own correlated fair (see §2 for the joint model). Buy only if **Q + fee ≤ your fair**; assume maker ≈ P_ind + 2.5¢.
4. **Band rule:** only historically ~fair zone is **Q ≥ 35¢**. **20–35¢ = peak-tax band** (+6¢/contract maker edge) — never buy there without a real info edge. **Sub-10¢ = donation** (buyers lose ~92¢/$).
5. **Size discipline:** stakes <$1 lose 88¢/$; $100+ lose 16¢/$. Combos are a whale's game — keep retail combo stakes small or skip.
6. **No early exits:** makers buy back won combos at ~95¢ on the dollar. Hold to settlement.
7. **In-play:** quotes stale within seconds; makers re-fetch legs at the 3s confirm (~400ms pickoff lifetime). If any leg moved ≥0.5 spread-units since the quote printed, **re-pull** — the confirm re-price moves against you, never for you.
8. Require **≥5% post-fee edge** vs your fair, and reject if |Q − fair| > 15¢ (something's wrong with your model or the quote).

### Bottom line for tonight
The three combos I priced earlier used naive product-of-mids — **that method is wrong for the buyer.** True fair ≈ product − 2¢ (cross-game) and correlation is taxed, not gifted, so my "Motor City Slugfest" same-game combo was the worst of the three, not the cleverest. Corrected rule: take a combo only if the RFQ quote comes in **at or below product-of-mids minus 2¢ (cross-game)**, and treat same-game combos as guilty until proven innocent.

---

## 2. In-play MLB totals — the 60-second model

### The formula
For a team total ("need N more runs, M innings of ABs left"):

```
lam = M × 0.50 × OFF × PARK × PEN
fair = P(X ≥ N) for X ~ Poisson(lam)
```

- **M** = full innings of at-bats remaining for that team. Road team: innings left including 9th. **Home team winning after 8.5: use M − 0.45** (might not bat in the 9th). Home team tied/trailing: full M.
- **OFF** = team's runs/game this season ÷ 4.50 (league avg). Hot offense (5.2 R/G) = 1.16; cold (3.9) = 0.87.
- **PARK** = park run factor (table below; 1.00 = neutral).
- **PEN** = opposing bullpen adjustment for remaining innings: `1 + 0.16 × (opp_bullpen_ERA − 4.20)/4.20`. A 5.00-ERA pen vs 4.20 league avg → ×1.03. A 3.40-ERA pen → ×0.97. Cap at ±8%.
- **fair** = 1 − PoissonCDF(N−1; lam). Poisson slightly understates blowout tails (real scoring is overdispersed) — true fair is ~1–3c higher on big-N tickets. That's fine; it makes this model conservative.

For a **game total** ("need N total runs"): lam = lam_home + lam_away, computed separately per team.

### Precomputed table — P(need ≥ N | M innings left), average offense, neutral park
```
M\n |   1    2    3    4    5    6
----+--------------------------------
 1  |  39%   9%   1%   0%   0%   0%
 2  |  63%  26%   8%   2%   0%   0%
 3  |  78%  44%  19%   7%   2%   0%
 4  |  86%  59%  32%  14%   5%   2%
 5  |  92%  71%  46%  24%  11%   4%
 6  |  95%  80%  58%  35%  18%   8%
 7  |  97%  86%  68%  46%  27%  14%
 8  |  98%  91%  76%  57%  37%  21%
 9  |  99%  94%  83%  66%  47%  30%
```
Shift the row: hot offense (×1.16) ≈ use the row one down; cold offense (×0.87) ≈ use the row one up. (Exact: recompute lam and Poisson.)

### Park run factors (RotoWire 2023–2025, runs; 1.00 = neutral)
| Park | Factor | Park | Factor |
|---|---|---|---|
| Coors (COL) | 1.25 | Fenway (BOS) | 1.10 |
| Great American (CIN) | 1.06 | Twins Target Field (MIN) | 1.06 |
| Citizens Bank (PHI) | 1.02 | Comerica (DET) | 1.02 |
| Sutter Health (SF temp) | 1.04 | Yankee Stadium (NYY) | 1.00 |
| Wrigley (CHC) | 1.00 | Kauffman (KC) | 1.02 |
| Oracle (SF) | 0.93 | Petco (SD) | 0.94 |
| T-Mobile (SEA) | 0.95 | Globe Life (TEX) | 0.94 |
| Tropicana (TB) | 0.92 | loanDepot (MIA) | 0.95 |
| Busch (STL) | 0.96 | Dodger Stadium (LAD) | ~1.00 |

### Decision rule (in-play baseball)
1. Get score + inning. Compute N (runs still needed) and M (ABs left).
2. Compute lam with OFF/PARK/PEN; read fair off the table.
3. **Buy YES only if ask ≤ fair − 0.05** (5c margin — model error + the phone-tap delay). **Buy NO only if bid ≥ fair + 0.05.**
4. Skip if the spread is wider than 12c — the book is telling you it doesn't know either.
5. Never bet a team total in the 8th/9th on a "need 1" at worse than 80c — the table says 39%/inning baseline; closers are not average pitchers, haircut lam ×0.8 for the 9th vs an elite closer.

---

## 3. Kalshi public API — what we're underusing

Base: `https://api.elections.kalshi.com/trade-api/v2/` (no auth needed for all of these).

### Order-book depth — the single biggest upgrade
```
GET /markets/{ticker}/orderbook?depth=10
→ {"orderbook_fp": {"yes_dollars": [["0.45","136121.60"], ...], "no_dollars": [...] }}
```
- Shows **real resting size in dollars at every cent**. `yes_bid/yes_ask` on the market object is just the top of this book.
- **How to use it:** (a) Is the top quote real? If yes_ask shows 46c but only $2 resting there and $50k at 60c, your fill walks the book — true cost is higher. (b) **Staleness detector:** a top quote with tiny size that hasn't traded in minutes while the game moved = stale maker quote, don't trust it. (c) Spoof check: huge size 1c off the touch that never trades = noise.
- Always pull depth on the exact ticker before sending Jeremiah a ticket. Cost: one HTTP call.

### Exchange-wide recent trades — the sharp-money radar
```
GET /markets/trades?limit=100&min_ts={unix}
GET /markets/trades?ticker={ticker}&limit=20
→ trades with created_time, yes_price_dollars, count_fp (size), taker_side, taker_outcome_side
```
- **Without a ticker** it returns the most active contracts across the whole exchange right now — free discovery of where volume is landing (e.g., 24 of the last 100 trades on a 15-min BTC contract = something's moving).
- **Per ticker:** timestamps tell you if the quote is live (trades in the last 60s) or dead; `taker_side`/`taker_outcome_side` shows whether buyers are lifting the ask (momentum) or sellers hitting the bid; `count_fp` flags whale prints.
- **Decision rule:** don't send a ticket on a market with zero trades in the last 10 minutes unless the order book shows deep resting size — you're likely looking at a stale quote.

### Exchange status — know which engine you're on
```
GET /exchange/status → exchange_index_statuses
  0 Default | 1 Combos | 2 Crypto & Commodities | 3 Tennis, Baseball, Basketball
```
- Sports trade on index 3, combos on index 1. If `trading_active: false` on an index, quotes are frozen — don't send tickets from it.

### Market detail fields worth reading
- `liquidity_dollars` — unreliable (often 0.00 even with a live book); trust the orderbook endpoint instead.
- `volume` / `volume_24h` / `open_interest` — frequently null on sports; don't depend on them.
- `no_bid_dollars` / `no_ask_dollars` — always derive the NO side from these, never as `1 − yes` (rounding + fees make them differ by a cent).
- `close_time` / `expiration_time` — hard expiry; never send a ticket with <10 min to close (Jeremiah taps by hand).

### What does NOT exist publicly
- No candlestick/history endpoint (404s) — reconstruct price history from `/markets/trades` instead.
- No combo listing — combos are built per-user via RFQ in the app; they never appear as public markets (verified: 1,000 open markets scanned, zero combo-shaped).
- No portfolio/balance endpoints without auth (RSA-signed requests; Secure Vault can't do it — dead end, use screenshots).

---

## 4. Softest books — where a phone trader has a chance

**Core distinction: soft + volume (hunt here) vs zombie spreads (ignore).** A 94¢ spread with zero volume means no counterparty — it's a placeholder, not an edge. Always check the live rung; series-average spreads lie because far-dated/OTM ladder tails always print ~95¢.

### Tier 1 — Zombie books (30–99¢ spreads, zero volume). Look, don't touch.
- Niche soccer moneylines: medians 55–94¢ (Italy Serie C, Brazil Serie B, Argentina Nacional B, USL, Uruguay, Canadian PL). Ex: `KXSERIECGAME-26SEP27RAVGUB-RAV` 0.01/0.95.
- NHL preseason moneylines (KXNHLGAME): 34–81¢, ~0 vol. Ex: `KXNHLGAME-26SEP26TBFLA-TB` 0.11/0.90.
- Far-dated Fed ladder tails (KXFED-27APR/MAR): 0.01/0.97 placeholders.
- Long-dated person/outcome markets (KXSUNNYSIDE): 0.01/0.99.
- NCAAF team props (KXNCAAFTEAMRECTD): 0.00/0.99.

### Tier 2 — Soft AND tradeable (5–20¢ with real volume). The hunting ground.
- **MLB moneylines 3 days out:** 10–18¢ with volume. Ex: `KXMLBGAME-26SEP251905BALNYY-NYY` 0.52/0.70 (18¢); `ATLMIA-MIA` 0.44/0.56 (12¢, vol 59).
- **WNBA spread ladders near tip:** 4–11¢ with real volume. Ex: `KXWNBASPREAD-26SEP22MININD-IND12` 0.68/0.76 (8¢, 4,949 vol/24h).
- **Econ ladder tails** (KXCPI-26DEC-T0.9): 0.09/0.18 (9¢). Near-term ATM rungs are 1–2¢ — the edge is in the tails.
- **Commodities hub** (KXWTI/KXWTIMAX, 24/7): 2–6¢, thin but quoted. Ex: `KXWTI-26SEP2414-T93.99` 0.11/0.15 (4¢, vol 158).

### Tier 3 — Tight, skip: recession (1¢), crypto hourly (1–2¢), LA mayor (1¢), near-term CPI ATM (1–2¢), PGA majors (1–6¢). SIG's desk owns these.

### Time mechanics that matter
- **Overnight softness is NOT in majors** — SIG claims ~98% around-the-clock availability on indices/econ/crypto/FX. Softness lives in non-covered categories 24/7; category > clock time.
- **8:30am ET econ prints: the fastest scheduled manual edge.** Ladders converge slowly to the now-known winner — buy the determined winner while its quote lags (one trader's parked residual: +43.4¢/contract post-jobs-print, n=36). Window is minutes, not hours.
- **Commodities source freezes:** the hub trades 24/7 against underlyings that halt (grains ~2:20–8pm ET weekdays, energy/metals 5–6pm ET + weekends). A market whose settlement window falls entirely inside a freeze is mechanically decided.
- **Weather observation-window close:** late-session running METAR observations increasingly pin the outcome; books run 24/7 so late-night window-close mispricings sit unpicked. ⚠️ As of tonight, **no daily-temperature markets are listed** in the public API (KXHIGH*/KXLOW* return 0) — verify the lineup before building around this; may be restructured under the Weather Company partnership.
- **In-play:** moneylines converge to ~0.5¢ half-spread within 60–180 min of start; **spread/total ladders stay widest** far out (~5¢ half, max 20.5¢) and in the final 60 min. Kalshi in-play ladders reprice off the game feed less sophisticatedly than sportsbooks — Kalshi lags the books live.

### Settlement-source gotchas (weather)
- **CORRECTION 2026-09-24 (measured, supersedes the old NWS line):** the current daily KXHIGH*/KXLOW* series' `settlement_sources` field says **The Weather Company**, and the settlement window is local **standard-time midnight-to-midnight** (strike_date 2026-09-25T06:00Z = Sep 24 00:00 CST Chicago). The old "NWS Daily Climate Report, 1:00am–12:59am" note is stale. Measured 2026-09-24: Kalshi TWC `expiration_value` == IEM ASOS daily max/min at the mapped station on **64/64 station-days** (8 stations × 8 days, every diff exactly 0.0).
- Station traps: Chicago=KMDW (not O'Hare), Dallas=DFW (not Love), Houston=KHOU (not Bush), NYC=KNYC (Central Park). Measured, not assumed.
- TWC rounding unknown (IEM summaries are integer-rounded) — the scanner uses 1°F integer guard bands safe under any plausible rounding; boundary-near strikes are skipped, never guessed.
- Daily markets ARE listed again (verified 2026-09-24 — the old "0 markets" note is dead).

### Manual-trader rules
1. Chase soft + volume, never zombie spreads.
2. Check the live rung, never the series average.
3. Best scheduled events: 8:30am ET econ prints, weather window-close, commodities source freezes.
4. Crypto hourly reprices instantly (no lag edge); econ ladders don't (lag edge).

---

## Quick ticket checklist (run before every send)
1. Fresh quote <2 min old? (orderbook depth pulled, trades recent)
2. Spread ≤12c? (else: no readable price)
3. Edge ≥12c vs fair on crypto ladders, ≥5c vs model on baseball?
4. Expiry >10 min out?
5. Ticket in his format: BUY YES/NO [limit] / [contracts] + plain English + exact app search phrase.

---

## 5. Auto-scanner + auto-trader new sections (2026-09-24)

`edge_scan.py` now covers crypto 15m/hourly/daily, index 15m, DOGE hourly, **politics, economics, weather** (sports fully excluded). `auto_trade.py` parses, independently re-verifies at the 15¢ bar, and trades. Both files verified live 2026-09-24.

### POL — Senate cross-venue (Kalshi vs Polymarket)
- Markets: `SENATENC-26-[D/R]`, `SENATEGA-26-[D/R]`, `SENATENH-26-[D/R]` (verified 2026 Senate races only).
- Scanner: 10¢ cross-venue gap; requires two-sided executable quotes, Kalshi spread ≤6¢, Polymarket spread ≤5¢, active/unclosed, ≥$25k volume, Polymarket ref-price agrees with live book.
- Trader re-verifies with a **fresh** Polymarket quote at the 15¢ bar.
- **One-leg only:** Polymarket is a fair-value signal, not an automatically hedged second leg. Only the Kalshi leg executes.
- Failure modes: Polymarket `outcomePrices` can be JSON-string-encoded (decoded); NO price is `1 − YES bid` (a `1 − YES ask` bug was caught and fixed); no polling aggregation — no reliable free live polling feed was found.

### ECON — CPI nowcast-anchored + Fed mechanics
- **Fair-value edges (traded as single contracts):** `KXCPICORE` (core CPI m/m ladder) and `KXECONSTATCPICORE` / `KXECONSTATCORECPIYOY` (exact buckets) priced off the **Cleveland Fed inflation nowcast** — timestamped, must be ≤4 days old, ≥8 daily values, and already-released months skipped. Current BLS base hard-coded: `2026-9: 2.4463` (measured 2026-09-24) — refresh the base and the nowcast path when months roll.
- **Mechanical flags (NOT traded, logged for human review):** `KXFEDDECISION` / `KXFOMCDISSENTCOUNT` field bucket-sum ≠ 1, `KXFED` ladder inversions, `KXFED↔KXFEDDECISION` cross-market synthetics (nearest meeting only, guarded), payrolls/unemployment (`KXPAYROLLS`, `KXU3`) ladder arb.
- Deliberately excluded: single-contract Fed fair values (no independent free anchor — futures are circular, WSJ paywalled), payrolls/u-rate models (no free consensus feed), GDP (no open brackets).
- **Parser hard rule:** the side must directly precede the ticker in EDGE lines — two-leg "locks Nc" arb lines never parse as single-ticker candidates (verified by unit test).
- Live behavior 2026-09-24: `ECON coreCPI y/y NO KXECONSTATCORECPIYOY-26SEP-T2.5` scanned at 14¢ (YES bid 28¢ vs fair 14%) and correctly **rejected** under the 15¢ bar at 13.8¢ — scan and re-verify models agree.

### WX — deterministic station-extreme kills (forecast tier stays OFF)
- **Only deterministic:** a strike the running station max/min has already killed (fair 0) or locked (fair 1). No forecast model, no sigma — every print is a fact about the world, not a model opinion.
- Rules (integer guard bands, safe under any TWC rounding; boundary-near skipped): HIGH: `less` dead if running max ≥ cap, `between` dead if ≥ cap+1, `greater` locked if ≥ floor+1; LOW mirrored. NO side prints when YES bid ≥10¢ on a dead strike; YES side prints when 1−ask ≥10¢ on a locked strike.
- Obs: NWS station obs (5-min, keyless) primary, IEM ASOS fallback; obs only need to fall in today's standard-time window — age doesn't weaken a floor/ceiling bound. No quote-age filter: a stale quote against a deterministic kill is the opportunity, and the trader re-verifies live.
- Settlement source resolved: TWC, 64/64 exact ASOS matches (see above); station map measured. Kalshi's day is local standard time.
- **Why no forecast tier:** live test 2026-09-24 printed **37 phantom edges** (incl. a 50¢ "edge" that was really a 0.7°F forecast-vs-book difference); NWS vs Open-Meteo disagreed 1.5–4.5°F; overnight quotes go 19h stale. Forecast pricing returns only when per-city/lead-time bias is measured — each scan appends NWS/Open-Meteo forecast rows to `~/workspace/kalshi/wx_fc_log.csv` (idempotent) so bias can be measured against future settlements.
- Trader re-verify: re-fetches fresh obs, re-checks the datecode is today in the station tz, reads live strike fields (`strike_type`, `floor_strike`, `cap_strike`), re-applies the kill — never trusts the scan-time extreme. Fails closed on station outage or missing obs.
- Strike semantics (verified 2026-09-24): `-T` = greater (YES iff final ≥ floor+1), `-B` = between (YES iff floor ≤ final ≤ cap), bare `-T<nn>` less = YES iff final ≤ cap−1. Parser handles both `-T` and `-B` suffixes.
- Expect it silent at night (dead strikes carry no bids) — it fires during the day when MMs post stale executable bids on already-dead strikes.

### SWEEP (§8) — universal model-free coverage of every other series
- **Goal:** literally every open series gets checked every 5-minute run, including sports (Jeremiah lifted the non-sports rule 2026-09-24 — sports are swept here via model-free checks until a dedicated sports model lands). Series with dedicated models (§1–§7: crypto, DOGE/XRP, index ladders, ECON, WX, Senate cross-venue) are skipped by prefix so models and sweep never double-signal.
- **How it fits the budget (rev 3, 2026-09-24):** FULL BOARD EVERY RUN, inline in `edge_scan.py` — the rotating cursor (`hidden_files/sweep_cursor.json`) is retired, and the separate `kalshi-sweep` cron job experiment is REVERTED (two overlapping 5-min jobs contended on the API/proxy: observed PARTIAL sweeps, RemoteDisconnected proxy failures, and a >280s run killed by timeout). Inline = one process per cycle, zero overlap possible. Pipelined: a fast sequential cursor-walk (plain events, no nested books) submits each page's `with_nested_markets=true` fetch to a 14-worker ThreadPoolExecutor as it goes, all through one shared `requests.Session` (keep-alive kills per-request TLS handshakes). ~70 pages / ~14k events. Internal 120s budget; logs FULL BOARD vs PARTIAL with page/event counts to stderr.
- **Timeout safety:** dedicated models (~50s) + sweep (≤120s, measured 17–27s clean) + re-verification fit comfortably inside the 270s `auto_trade.py` scan subprocess timeout — critical because `run_scan` DISCARDS all candidates on `TimeoutExpired`. Measured 2026-09-24: full board (71 pages / 14,011 events) swept in 17s even while a live trader run overlapped; total `edge_scan.py` 95s; full `auto_trade.py` dry run 82s.
- **429 handling:** one 5s backoff per page, then skip the page. Per-page/per-event try/except — one dead page never kills the scan.
- **Checks (all model-free, all wrapped in try/except):**
  - **RESULT-SET (auto-tradable):** `result` is yes/no but market still active/quotable → payout known. `SWEEP YES <ticker>` when yes_ask < 97¢; `SWEEP NO <ticker>` when yes_bid > 3¢. Reverify (`reverify_sweep`) re-checks result on a fresh fetch, requires real resting size (`yes_ask/bid_size_fp > 0` — market-level quotes can be stale), 10+ min to close, 15¢ bar. Rare by design (0 found in first full rotation).
  - **CROSSED (human review):** yes_bid > yes_ask > 0 → FLAG line. Our single-leg limit orders can't capture it atomically.
  - **SELL-FIELD (human review):** mutually-exclusive bracket, ≥3 active markets, closes ≤7d, live YES bids sum > 1.15 → selling every YES is an arb under true exclusivity (at most one winner ⇒ pay at most $1).
  - **BUY-FIELD (human review):** live YES asks sum < 0.85 → buy-everything arb ONLY if listed candidates exhaust the outcome space (candidate markets often lack a "field/other" bucket — e.g. KXNEWPOPE ask_sum 0.30 is NOT an arb).
- **Known traps (measured, not theorized):**
  - Loose field filters fired **460 flags per 1,000 events** — nearly all phantoms: far-dated thin books with stale quotes, non-exhaustive candidate lists, and ladder markets misread as brackets. Strict filters (ME=True, ≥3 markets, ≤7d to close) cut it to ~0.
  - NO-side "arb" math: selling NO on all n candidates collects Σno_bid but pays $(n−1) if a listed candidate wins and $n if none does — it is a bet on "winner ∈ listed", NOT an arb. No NOFIELD check exists for this reason.
  - SELL-FIELD needs TRUE exclusivity, not just the API flag — nested ladders ("resolved by 2030/2035/2040") can all win together. Hence human-review routing, never auto-traded.
  - The generic ticker alternative in CAND_RE (`[A-Z][A-Z0-9]*-[A-Za-z0-9.\-]+`) only matches when an asset tag + YES/NO directly precedes it; unit-tested that two-leg arb lines and FLAG lines still don't parse.

### §9 SYNTHETIC COMBOS — multi-leg baskets built from singles (built 2026-09-24)
- **Why synthetic, not native RFQ:** Kalshi has no public combo order books — verified 2026-09-24, zero combo-shaped series among open events. Listed combos are per-user RFQ mints with private, take-it-or-leave-it maker quotes (see §1). We can't scan what isn't listed, so we BUILD: 2 single-leg limit orders, placed simultaneously as ONE trade decision.
- **The key economics correction (§1 does not apply here):** there is no combo instrument and no maker quote, so the RFQ maker tax (+1.1¢ decorrelated / +2.5¢ same-game) does NOT apply. EV is **linear** across legs: combined edge = Σ per-leg edges − Σ per-leg fees. Correlation does NOT change EV — it only concentrates risk (correlated legs win/lose together), so correlated baskets clear a **20¢** bar instead of 15¢. A basket of singles is NOT a parlay: legs settle independently and can partially win. We never claim parlay payoff.
- **Pipeline:** `edge_scan.py` §9 records structured legs (asset, side, ticker, fair, pay cents) next to every probabilistic single-ticker edge (crypto, index, politics, econ — NOT wx kills, sweep result-sets, or multi-leg flags), pairs them across different events (same-event pairs skipped), and emits the top-3 as `COMBO legs=…` EDGE lines with scan-time edge/fee/net/maxpay/contracts. `combo.py` holds the shared math (self-tests pass).
- **Trader (`auto_trade.py`):** parses COMBO lines via `COMBO_RE` + `parse_combo_candidate` (single-leg line parsing unchanged; arb/FLAG lines still rejected by unit test). Combos are handled FIRST in the main loop. `reverify_combo` re-verifies EVERY leg on a fresh book + fresh fair (reuse of the single-leg `reverify`, 5¢ bar per leg), then applies the take/pass rule: all legs ≥5¢, combo net (edges minus exact per-leg `⌈7·P·(1−P)⌉` fees) ≥ 15¢ decorrelated / 20¢ correlated.
- **Execution (the hard problem — Kalshi has no atomic multi-leg):** every leg is placed as **fill_or_kill** (FOK): fully fills immediately or dies, so there are NO partial fills within a leg. Across legs the failure mode is some-fill/others-die — safe by construction because every leg was re-verified +EV standalone (≥5¢), so the worst case is holding a subset of +EV legs, never a donation. A **depth gate** (resting size at the touch ≥ contracts on EVERY leg, from a book fetched seconds earlier) makes FOK failures rare; sizing = min(risk budget, depth) per unit across all legs.
- **Failure modes, documented honestly:**
  - **FOK dies on a leg while another fills → orphan +EV leg.** Acceptable by construction (the filled leg is still +EV); logged as `placed` with `status=partial`, missing legs listed. NO auto-unwind — unwinding at any price would be worse.
  - **FOK partially fills a leg (should be impossible).** Logs `combo_anomaly` — means exchange behavior changed, investigate before the next run.
  - **All legs die →** `skipped`, no exposure, combo aborted clean.
  - **Two combos sharing a leg:** the second is skipped via the held-ticker check after the first places.
- **Risk accounting:** the whole combo = ONE trade: logs one `action='placed', kind='combo'` entry (counts 1 against the 3/day cap), worst-case cost = Σ leg prices × contracts must fit min($2, 35% balance). Each FILLED leg gets its own `placed_leg` entry so `settle_check` books P&L leg-by-leg (the combo-level `placed` entry is skipped by settlement). Held-ticker checks reject any combo containing an already-held ticker. No GTC leftovers — FOK orders die on their own.
- **Measured 2026-09-24:** full scan emitted 117 pairs at the 10¢ scan bar (top net 39¢), all as `COMBO legs=…` lines; dry-run end-to-end verified (combo handled before singles, FOK legs shown, single traded after); `reverify_combo` unit tests pass (decorr pass, corr pass at exactly 20¢, corr rejection at 18¢, weak-leg rejection, duplicate-leg rejection, depth-gate clipping, balance-cap rejection).

### §10 EXECUTION SAFETY + EXACT FEES (built 2026-09-24, from PLATFORM.md §4/§5/§9)

**Exact fees replaced the flat 10% buffer.** `fees.py` computes the real Kalshi fee per order: `⌈0.07 × C × P × (1−P)⌉` cents taker, quarter-rate resting maker on `quadratic_with_maker_fees` series, half rate (0.035) on `INX*`/`NASDAQ100*` regardless of fee_type, zero under an unexpired fee waiver. `fee_type`/`fee_multiplier` come from `GET /series/{ticker}` and are cached on disk (`hidden_files/fee_type_cache.json`). `trade_client.get_series()` fetches them live (verified: KXNBAGAME → quadratic_with_maker_fees, KXFED → quadratic_with_maker_fees, KXINX → quadratic but half rate). All PLATFORM.md worked examples verified by unit test (`fees.py` self-tests + `test_exec_safety.py`).

- The 15¢ bar now applies to the **net edge after exact fees** (`net = edge − fee/n per contract` for singles; per-unit for combos with the 20¢ corr / 15¢ decorr rule unchanged). The balance check is `cost + fee + 1¢ slack` (no more `×1.10`); combos size on exact per-leg order fees.
- Scan-time combo legs in EDGE lines still carry the old `⌈7·P·(1−P)⌉` per-contract estimate (from `combo.py`) — the trader re-computes with exact order-level fees at decision time, so this only affects scan-time ranking, not trade decisions.

**Order placement is now execution-safe end-to-end** (`trade_client.place_order` accepts, `auto_trade.py` uses):

- **Stale-order protection:** every GTC entry carries `expiration_time = min(market close, now+24h)`. The cancel-stale pass runs **before** new entries every cycle: it re-verifies each resting order on a fresh book + fresh fair and cancels when the edge died, faded below 15¢, or the order sat past the per-kind limit (crypto15m 10min / crypto daily+index 60min / everything else 2h). `cancel_order_on_pause=True` on every order — a pause kills resting orders instead of letting them fill on a frozen book.
- **TIF discipline:** entries are taker-intent (we cross the spread) → `post_only=False` by design; crypto15m entries are `immediate_or_cancel` (a resting taker-intent order is a stale-order accident); everything else rests GTC with the expiration backstop. Combo legs stay `fill_or_kill`.
- **Idempotency:** every order carries an explicit `client_order_id` (trade_id; combo legs `{tid}L{i}`) — a retry after a network timeout can never double-place.
- **Exits:** `reduce_only=True` is mandatory plumbing for every close (no close path exists yet — the API is ready); amend-down uses `decrease_order`/`amend_order` which preserve queue position when only size shrinks.
- **Log discipline:** every placement logs `client_order_id`, TIF, expiration, exact modeled fee, and `fill_count` (balance debited by actual fills, not ordered count). `average_fee_paid` in order responses is the reconciliation hook when fills land.

**Measured 2026-09-24:** dry-run end-to-end after these changes — cancel-stale pass ran clean, net-edge-after-fees gating exercised, IOC/GTC+expiry routing logged per trade, zero syntax/wiring regressions.

**Fee-aware Kelly (settled 2026-09-24 — no longer an open question).** `kelly_stake_cents()` used to compute payout odds off the quoted price; the all-in cost is price + per-contract fee, so stakes were systematically overbet. Measured on the canonical case ($17 bankroll, 15¢ ask, 30% win prob, standard 7% taker rate): pre-fee stake $1.50 → fee-aware $1.42 (~5% shift; 10 contracts → 8 once the all-in cost is the divisor). Small next to model-error (±5–10¢ on p moves Kelly 30–50%), but the bias points one way and the fix is one fixed-point iteration in `size_contracts()` (size pre-fee → exact per-contract fee → re-size on all-in cost), so it is applied to singles and to every combo leg. Combos unified the same day: each leg gets its own half-Kelly size, combo takes the min across legs, $2 hard cap on total combo cost — no joint win probability invented (the desk has no joint-distribution model, and Kelly punishes invented p's hardest exactly when legs correlate).

### §11 SPORTS COVERAGE (built 2026-09-24 — Jeremiah lifted the non-sports rule)

**Standing rule change:** sports are IN. Every sport, every prop, every strategy gets at minimum sweep coverage; dedicated models where feasible.

**Enumeration (2026-09-24, public API, category=Sports):** 71 pages, **1,054 distinct open Sports series**. Breakdown: NFL 161, NCAAF/NCAAB 96, MLB 92, NBA/WNBA 90, soccer 74 (EPL/UCL/AFCON/MLS/etc.), tennis 24, racing/F1 22, NHL 21, combat (UFC/boxing/MMA) 18, cricket 11, golf 10, Olympics + 435 long-tail (futures, awards, smaller leagues/props — KXABAGAME, KXACBGAME, KXAFCA, city champs, etc.).

**Coverage tiers:**
1. **Universal sweep (§8)** — ALL 1,054 sports series on rotation (cursor, ~35 pages/run, full board over 2–3 runs). Model-free: known-result discrepancies, crossed books, strict mutually-exclusive field sums (two-way/three-way moneyline field sums, exact-score/bucket exclusivity, monotonic ladder checks). It does NOT fundamentally price contracts — it catches books that are internally inconsistent. Measured 2026-09-24: full board 71 pages / 4,488 events / 0 edges in 127s (efficient books, as expected).
2. **MLB totals dedicated model (§9, `mlb_totals.py` v1.1)** — the only sport with a fundamental fair-value model. Pregame KXMLBTOTAL full-game totals: mean from probable-pitcher season ERA + **real IP-weighted bullpen ERA** (daily roster hydrate via `refresh_bullpen.py` → `hidden_files/mlb_bullpen.json`; team-ERA fallback if stale) + team runs/game vs league avg, × **verified park factor** (RotoWire 2023–2025, §2 table; unlisted parks 1.00). Ladder shape (sd) calibrated from the market's own rungs; only the MEAN is ours. ±0.50-run adverse guard; pregame only (game-start check, not close_time); skips COL home (Coors 1.25 exceeds the band).
3. **Status: FLAG-ONLY (research), never EDGE.** v1 measured ~+0.8 run systematic bias (team-ERA pen proxy); v1.1 closed the fixable gaps (real pen ERA, verified parks) but the model still disagrees with the efficient (1c-spread) market by ~0.68 runs avg, bidirectional — the market prices lineup cards, weather, and September rest/call-up effects no free API provides. Disagreements log as `FLAG: MLB-TOTAL …` lines (15¢ bar, 0 fired 2026-09-24); FLAG lines can never parse as trade candidates (CAND_RE unit-tested). Promote to EDGE only after lineup/weather inputs land and the gap is measured gone.

**Genuinely impossible without reliable free data (documented, not hidden):** fundamental pricing for NFL/NBA/NHL spreads & moneylines (no free power ratings), player props (no free projections API), tennis/soccer ELOs, golf/boxing/MMA futures. These get tier-1 sweep coverage only. Multi-leg sports arbitrage stays human-review: no atomic execution exists, so cross-market arb flags are FLAG, never auto-traded.

**Refresh cadence:** `refresh_bullpen.py` should run daily (pen composition changes); the 5-min scan only READS the cache and falls back to team ERA if it's older than 30h.

### §12 SHARD BALANCE FIX (2026-09-24 — root-caused the insufficient_balance rejections)

**What happened:** 04:26 CDT, two re-verified CPI candidates (T2.4 NO 2×69c, T2.7 YES 14×14c) passed the local balance check (aggregate $5.70) but the exchange 400'd both with `insufficient_balance`. Both a YES-buy and a NO-buy failed, ruling out the NO-side ask synthesis.

**Root cause:** Kalshi shards its exchange. Every market clears on one shard (`market.exchange_index`); order collateral is checked ONLY against that shard. CPI markets are shard 0; our money was $5.67 on shard 3 / $0.00 on shard 0. The aggregate balance is not spendable cross-shard. Verified live: `KXECONSTATCORECPIYOY-26SEP-T2.4` → `exchange_index: 0`; `KXBTCD-*` → 2. Transfer path exists: `POST /portfolio/intra_exchange_instance_transfer`, amount in **centicents** ($2.00 = 20000), body `{source:'event_contract', destination:'event_contract', amount, source_exchange_shard, destination_exchange_shard}` — NOT idempotent, single-shot, async settlement. (Sourced from Kalshi's 2026-08-13 changelog + two independent bot codebases' live findings.)

**What changed:**
- `trade_client.py`: `parse_shard_balances()` (handles the dollar-string-vs-cents unit trap, floors, loud failure on garbage), `get_shard_balances()`, `market_shard()`, `transfer_collateral()` (dry-run aware, never retried). CLI: `shards`, `transfer <src> <dst> <cents>`.
- `auto_trade.py`: startup reads per-shard balances (fail-closed when unreadable); `_attach_exec` carries `exchange_index` off the fresh market object; the single-trade loop runs a **shard pre-flight** — need vs the market's shard, logging `EXCHANGE WOULD REJECT …; to fix: transfer $X shard S→D (needs operator approval)` instead of burning an order attempt; `plan_shard_transfer()` greedily plans coverage from the largest surplus; combos pre-flight per-leg grouped by shard; fills decrement the shard balance in-run.
- Sizing stays portfolio-wide (risk cap), pre-flight is per-shard — matching the exchange's actual check.
- **Standing rule: shard transfers are transfers — they need Jeremiah's explicit approval.** The trader plans and logs them, never executes. Until $ moves 3→0, shard-0 markets (CPI/Fed/econ) cannot be traded via API.

**Proof:** `test_shard_balance.py` — 21 checks pass, including an exact replay of both rejected orders (pre-flight fails 142c>0c and 209c>0c on shard 0, matching the live 400s; passes after the planned 3→0 transfer). Dry-run 2026-09-24: `shards: 0=$0.00, 1=$0.01, 2=$0.02, 3=$5.67`; both CPI candidates log the would-reject + transfer plan instead of attempting. Existing `test_exec_safety.py` still passes.

**UPDATE 2026-09-24 ~04:53 CDT — standing delegation: auto shard-transfers are LIVE.**
Jeremiah: "Move the money how you wanna boss this is your thing." The old rule (transfers need per-instance approval) is superseded for INTRA-Kalshi shard collateral moves. Deposits/withdrawals of outside money still need explicit approval — unchanged.

**New behavior (`auto_fund_shard()` in `auto_trade.py`):** when a verified candidate's shard pre-flight fails, the trader now auto-executes the planned transfer instead of just logging it:
- Single planned transfer must be ≤ **$2.00**; total auto-transferred per calendar day (America/Chicago) ≤ **$6.00** — tracked in `hidden_files/auto_xfer_daily.json`, resets on a new Chicago day.
- Funds the exact shortfall (whole cents, rounded up), logs `transfer_id` per leg.
- After POSTing: waits ~15s for async settlement, re-reads shard balances, re-runs pre-flight; proceeds to the order only if it now passes.
- Ambiguous failure (raise/timeout) → candidate SKIPPED, never retried for that candidate in that run (non-idempotent POST — a blind retry could double-move).
- Still short after settle, or re-read fails → skipped, logged.
- DRY_RUN honored end-to-end: simulates funding locally, never POSTs.
- Combos still only log transfer plans (no auto-funding of multi-leg fills).

**Proof:** `test_auto_xfer.py` — 7 checks pass (executes ≤ cap; blocked > $2 cap; blocked at $6 daily cap; ambiguous failure skips without retry; dry-run performs no transfer; portfolio-can't-cover; daily reset). `test_shard_balance.py` and `test_exec_safety.py` still pass. DRY-RUN end-to-end 2026-09-24: 12 candidates, all correctly gated (held/<10min/<15¢), no orders, no transfer POSTs.

---

## §13 POST-TRADE LEARNING LOOP (built 2026-09-24 — the desk now grades itself)

### What it is
Every settled trade feeds back into the models that priced it. The loop
joins each settlement to its entry record in `trade_log.jsonl` (model fair
YES prob at entry vs actual outcome) and updates per-model calibration in
`hidden_files/calibration.json`. Plain-English lessons go to
`hidden_files/LEARNING_LOG.md`. Nothing here trades or moves money — pure
file I/O, and a learner crash can never break a trading run.

### The math (small samples = wide humility)
Per model, over settled trades: `bias = mean(fair_yes - outcome)`.
Positive bias = the model overpredicts YES.
- **Adjustment** `= -bias × n/(n+20)` — shrinkage toward zero. With 2
  settled trades the raw bias counts for ~9%; with 20 for 50%; with 100
  for ~83%. A couple of lucky/unlucky prints can't move pricing.
- **Hard cap ±3c**, enforced at write time AND re-clamped at read time.
- **Brier score** `= mean((fair_yes - outcome)²)` tracks sharpness.
- Counterfactual honesty: for each consumed trade, the log records whether
  the new adjustment would still have cleared the 15c entry bar.
- Idempotent: consumed `trade_id`s are recorded; re-runs skip them.

### Wiring
- `learn_from_settlements.py` — standalone, `run_learning()` importable,
  `--dry-run` for no-write inspection.
- `auto_trade.py`: `settle_check()` now returns the count of newly booked
  settlements; `main()` runs the learner **only when that count > 0** —
  never on the empty 5-min scans. Wrapped in try/except.
- `reverify_econ()` (CPI model, the simplest) applies
  `calib_adjustment('econ')` to its fair value before computing edge.
  With no calibration data the adjustment is exactly 0.0 — a no-op.
- `placed`/`dry_run` log events for singles now carry `fair_cents` (exact
  model fair at entry) and `asset`, so future learning needs no
  reconstruction. Older entries reconstruct fair from price + raw edge
  (±~1c rounding noise, absorbed by shrinkage).

### Calibration file format (`hidden_files/calibration.json`)
`{meta: {last_run, runs}, seen_trade_ids: [...], models: {<model>: {n,
bias, bias_sum, brier, brier_sum, adjustment (YES-prob shift, ±0.03 max),
updated}}}`. Models: econ, crypto15m, cryptodaily, weather, politics,
index, sweep, combo.

### First run (2026-09-24)
0 settled trades consumed — the two live CPI positions settle on the
September CPI print (2026-09-26). All adjustments at +0.00c. The models get
their first report card when those resolve. Logged honestly in
`LEARNING_LOG.md` rather than pretending.

---

# PART II — ALPHA MODULES (all SHADOW MODE ONLY, built 2026-09-24)

> Every module below **logs signals and fair values only**. None places
> orders, moves money, or touches the live five-minute trader.
> Nothing here graduates to live sizing without validation + a report
> + explicit Jeremiah approval. See each section's graduation criteria.

## 6. Polymarket ↔ Kalshi cross-venue signal (alpha module #1)

### What
A cross-venue dislocation scanner. For hand-verified (Kalshi event, Polymarket
event) pairs that describe the SAME event with the SAME resolution source, it
compares the Polymarket-implied fair value against the Kalshi YES ask
(executable, never mid) and logs a `shadow_candidate` when the Kalshi YES ask
is ≥15¢ cheaper than the PM fair (after Kalshi taker fees via
`combo.fee_cents`). Extends the Senate-only pattern from `edge_scan.py`
§5 beyond Senate: Fed decision, core-CPI brackets, MLB moneylines.

### Why
The same binary outcome priced on both venues is the only defensible free-data
signal here (polling aggregation was rejected in edge_scan §5: no free live
polling API). A 15¢+ gap between executable quotes is a real edge, not a
model opinion. The direction monitored is Kalshi-YES-cheap only: the reverse
trade would require buying on Polymarket, which is out of scope (no wallet),
so it cannot be acted on and is intentionally not logged.

### Mapping table (all hand-verified live 2026-09-24)

| # | Label | Kalshi | Polymarket | Same-event proof |
|---|-------|--------|------------|------------------|
| 1 | FED-OCT-25BP | KXFEDDECISION-26OCT-H25 ("Will the Federal Reserve Hike rates by 25bps at their October 2026 meeting?") | `fed-decision-in-october-20260617190323537`, group "25 bps increase" | Both = change in the upper bound of the fed funds target range at the Oct 2026 FOMC meeting (KX: "Hike of 25bps on October 28, 2026"; PM: "amount of basis points the upper bound ... is changed by versus the level it was prior to the ... October 2026 meeting") |
| 2 | FED-OCT-HOLD | KXFEDDECISION-26OCT-H0 ("Hike 0bps") | same PM event, group "No change" | Same FOMC Oct 2026 event, hold leg |
| 3 | CPI-CORE-YOY-SEP | KXCPICOREYOY-26SEP rungs ("above X%", one-decimal BLS print) | `core-cpi-yoy-september-2026` one-decimal brackets | Both = CPI-U ex food+energy, 12mo ending Sep 2026, BLS one-decimal print. Kalshi "above X" = sum of PM brackets ≥ X+0.1. BLS release ~Oct 14 2026 |
| 4 | MLB-TB-NYY | KXMLBGAME-26SEP241905TBNYY | `mlb-tb-nyy-2026-09-24` | Rays @ Yankees, Sep 24 7:05pm ET; winner of the game both sides |
| 5 | MLB-CLE-BOS | KXMLBGAME-26SEP241845CLEBOS | `mlb-cle-bos-2026-09-24` | Guardians @ Red Sox, Sep 24 6:45pm ET; winner of the game both sides |
| 6 | MLB-STL-PIT | KXMLBGAME-26SEP241235STLPIT | `mlb-stl-pit-2026-09-24` | Cardinals @ Pirates, Sep 24 12:35pm ET; winner of the game both sides |

Leg count at run time: 2 Fed + 3 CPI rungs + 6 MLB team legs = 11 legs.

### How to run
```
python3 ~/workspace/kalshi/alpha_xvenue.py          # shadow (default)
python3 ~/workspace/kalshi/alpha_xvenue.py --shadow # same
```
- Iterates PM_MAP, prints a per-pair table (leg | Kalshi ask | PM fair | edge | net | PM quote detail), then a summary.
- Logs `shadow_candidate` (module='xvenue') per qualifying leg and one `shadow_run` summary to `hidden_files/trade_log.jsonl`.
- Exits 0 always on a completed scan; zero candidates is a valid outcome.
- Rate: ~1.1s between Gamma calls (≤1 req/s), ~0.6s between Kalshi calls.
- Sports entries are date-keyed (`kx_date`) and self-skip off their date so a stale pair can never false-match a later game.
- Never places orders, never touches money, never imports auto_trade/trade_client. New file only; no live path modified.

### Staleness gates (inherited from the Senate pattern)
- PM event: active, unclosed, endDate in future, event volume ≥ $25k.
- Sports exception (documented, deliberate): PM game events split volume across
  dozens of props, so the gate is applied at the compared market level instead:
  moneyline market volume ≥ $5k. The quote-quality gates below are unchanged.
- PM quote: two-sided book, spread ≤ 5¢, outcomePrices inside [bid−0.5¢, ask+0.5¢]
  (Gamma caches aggressively — a divergence means the quote is stale).
- Kalshi quote: 0 < bid < ask < 1, spread ≤ 6¢.
- CPI "sum" legs: EVERY bracket in the sum must pass the PM quote gates or the
  leg is skipped (no partial-fair synthesis).

### Validation numbers (2026-09-24, ~05:40 CT)
- Pairs in table: 6. Hand-verified live: 6/6.
- Rejected as false/ambiguous: 7 (see below).
- Live divergences at check time (all below the 15¢ bar):
  - FED-OCT-25BP: KX 68¢ ask vs PM 68.5¢ fair → +0.5¢ edge, −1.5¢ net. No signal.
  - FED-OCT-HOLD: KX 33¢ ask vs PM 29.5¢ fair → −3.5¢ edge. No signal.
  - CPI rungs: all 3 legs gate-skipped — PM bracket books too wide (e.g. 2.4% bracket 39/51¢ = 12¢ spread). No comparable leg.
  - MLB-TB-NYY: TB −0.5¢, NYY −0.5¢. Books agree. No signal.
  - MLB-CLE-BOS / MLB-STL-PIT: PM moneyline volume $209 / $813 < $5k gate → skipped.
- Gamma API: live, no auth; median latency ~0.5–2.8s observed this session; one response-shape quirk found (`outcomes` sometimes JSON-encoded string — handled).
- Same-event check (explicit): Kalshi "Will the Federal Reserve Hike rates by 25bps at their October 2026 meeting?" (resolves Yes on a 25bps hike on Oct 28, 2026) vs PM "25 bps increase" ("amount of basis points the upper bound of the target federal funds rate is changed by versus the level it was prior to the Federal Reserve's October 2026 meeting"). Same meeting, same quantity. ✓

### Rejected pairs (NOT in the table — do not add without re-verifying)
1. **KXBTCD/KXETHD daily ↔ PM daily crypto** — different resolution source AND
   snapshot time: Kalshi = CF Benchmarks index at 7am/5pm ET; PM = Binance
   BTC/USDT (or ETH/USDT) 1m candle close at 12:00 noon ET. A divergence here
   is real price movement between snapshots, not a stale book.
2. **KXCPIYOY (headline) ↔ PM "Core CPI YoY"** — headline CPI-U vs core CPI-U
   ex food+energy. Different underlyings. (The correct pair is KXCPICOREYOY,
   which IS in the table.)
3. **KXCPI/KXCPICORE (MoM) ↔ PM "Core CPI MoM"** — also underlying mismatch
   (headline vs core) AND PM event volume $15.9k < $25k gate.
4. **KXHIGHNY ↔ PM "Highest temperature in NYC"** — different station/source:
   Kalshi = CLINYC per The Weather Company; PM = NOAA LaGuardia (KLGA). PM
   volume $23.7k also just under the $25k gate. Near-miss; revisit if PM
   volume crosses and a same-station market appears.
5. **KXFOMCDISSENTCOUNT-26OCT ↔ PM "How many dissent at the October Fed
   meeting?"** — PM event volume $7.2k < $25k gate, and Kalshi spreads are
   5–8¢+ (too wide). Doubly out.
6. **KXU3 ↔ PM "September Unemployment Rate"** — PM volume $20.8k < $25k gate.
   Near-miss; revisit on volume.
7. **Slug-collision traps** (documented so nobody re-adds them):
   `fed-decision-in-october` = the CLOSED October 2025 event ($252M vol);
   the 2026 event is `fed-decision-in-october-20260617190323537`.
   `bitcoin-price-on-september-22` = the 2025 event; 2026 dailies use the
   `-YYYY` suffix (`bitcoin-price-on-september-24-2026`).

### Graduation criteria (shadow → live consideration)
- ≥ 2 weeks of shadow runs with ≥ 5 logged candidates AND a positive realized
  edge on settled legs (measured against actual settlement, not just the bar).
- No false-pair incidents: every logged candidate's both-sides question text
  archived in the candidate's `extra` for audit.
- Jeremiah's explicit go-ahead for the Kalshi side remains required; the
  Polymarket side can never be executed from here (no wallet) — the module
  stays one-directional (Kalshi-YES-cheap) by design.
- Sports legs stay shadow-only unless Jeremiah lifts the standing non-sports
  default for this module explicitly.

## 7. YES-bias retail fade, calibrated gate (alpha module #2)

### What
An overlay on the desk's 15¢ net-edge bar, motivated by Bartlett & O'Hara
(2026, Kalshi data): makers earn +1.91¢/contract from YES-biased uninformed
takers overbetting YES on markets that mostly settle NO. NO is structurally
the better side on retail-heavy books.

**Study-hall correction (2026-09-24, 10:50 UTC — recorded in LEARNING_LOG.md):**
a 5,000-market replay showed the FLAT version of this overlay
("YES needs +2¢ extra / tilt NO") LOSES money: blanket fading −8.1¢/contract,
fading >20pp from 50% −7.5¢/contract. Only isotonic-calibration disagreements
≥4¢ made money (+11.5¢/contract). **The flat rule must NOT ship.** This module
now implements ONLY the calibrated version:

- The fade/tilt fires **only on ≥4¢ of SHRUNK measured disagreement** between
  the market's YES quote and the isotonic P(YES|quoted) curve
  (`yesfade_calibration.json`, built by `calibration_backfill.py`).
- YES overpriced ≥4¢ (shrunk) → YES entries get bar 17¢ + half size
  (`fade_yes`); NO entries get a `confirm_no` note (bar unchanged).
- YES underpriced ≥4¢ (shrunk) → YES entries get a `confirm_yes` note.
- Disagreement <4¢ (shrunk), no curve, or no calibration → **no overlay at
  all** (tilt `None` / `no_curve` / `no_calib`). Never a flat fallback.
- Retail/sharp classification is now INFORMATIONAL ONLY (recorded in the
  note, never moves the bar). The gate is calibrated, not class-based.

### The convergence trap (verified 2026-09-24 — do not "fix")
`last_price_dollars` on a SETTLED market is the **converged price**, not a
tradeable-time prediction, for every family whose market trades into the
resolution event. Evidence (settled markets with volume>0):
- KXBTCD n=885: quotes only at 0.00–0.10 (461, all NO) or 0.90–1.00 (422, all YES)
- KXBTC15M n=5,994: same binary pattern
- KXNFLGAME n=158: 79 at 0.0–0.1 (all NO), 79 at 0.9–1.0 (all YES), nothing between
- KXHIGHNY n=408: 340 at 0.0–0.1 (all NO), 68 at 0.9–1.0 (all YES)

An isotonic curve fit on these is CIRCULAR: it would tell the gate a live
25¢ quote has ~0% empirical YES rate. The backfill therefore fits ONLY the
**ECON_MACRO** super-family — scheduled macro releases (CPI core/headline,
Fed decisions, payrolls, GDP, ECB) whose markets CLOSE BEFORE the print, so
the last trade is a genuine prediction. Crypto/sports/weather are EXCLUDED
(see `excluded_families` in the calibration doc). There is deliberately NO
global fallback: a macro-bracket curve must never score a crypto/sports/
weather quote; those tickers get tilt `no_curve` and the overlay stays OFF.

### The ECON_MACRO curve (n=134, built 2026-09-24)
Isotonic P(YES|quoted) on 134 settled macro-bracket markets (class balance:
30.6% YES). Blocks (left-edge knot → empirical P(YES), [block n]):

| quoted YES | empirical | n | read |
|---|---|---|---|
| 0.01–0.05 | 0.000 | 55 | deep longshots never hit |
| 0.05–0.12 | 0.083 | 12 | ~calibrated |
| 0.12–0.36 | 0.210 | 19 | ~calibrated, slight YES overpricing |
| 0.36–0.91 | 0.640 | 25 | wide block — coarsest region |
| 0.91–0.93 | 0.667 | 3 | thin |
| 0.93–0.98 | 0.875 | 8 | ~calibrated |
| 0.98+ | 0.917 | 12 | ~calibrated |

Shrinkage: `shrunk = raw × n_block/(n_block+20)`; blocks with n<10 never move
the gate. The 0.36–0.91 block is coarse (25 points over a 55pp range) — the
shrinkage is load-bearing there. **This curve is a prior, not a verdict.**
With n=134 it cannot support fine-grained claims; it only licenses the gate
where shrunk disagreement clears 4¢.

### How it runs
- `python3 alpha_yesfade.py` — runs `edge_scan.py` once as a subprocess
  (~70s), parses EDGE stdout lines with the CAND_RE/COMBO_RE patterns (copied
  from `auto_trade.py`, never imported), computes edge/net per candidate with
  `combo.leg_edge_cents()` / `combo.fee_cents()`, runs the pure
  `apply_fade(candidates, calib)`, and logs via `shadow.py`:
  - one `shadow_candidate` per single candidate that **passes** its bar
    (note records: shrunk disagreement, curve family, block n, tilt, bar,
    pass/fail, size_mult);
  - one `shadow_run` summary with full detail on faded-out singles and combo
    decisions in `extra`, so the counterfactual cohort stays recoverable.
  - Exit code is 0 even with zero candidates.
- `python3 alpha_yesfade.py --selftest` — 8 offline checks of the calibrated
  gate math (fade/confirm/no-overlay/no-calib/no-curve/combo). No scan, no
  logging. **8/8 pass (2026-09-24).**
- `python3 calibration_backfill.py [--max-pages-per-series N]` — rebuilds
  `hidden_files/yesfade_calibration.json` from the public settled-history API
  (macro series only, ~5s). Aborts honestly if n<50.
- **SHADOW MODE ONLY.** Nothing here places orders, moves money, or POSTs
  transfers. The live trader parses EDGE stdout, never the trade log.

### Validation numbers (2026-09-24)
1. **Selftest: 8/8 pass.** Covers fade_yes (bar 17¢, half size), confirm_no,
   confirm_yes, no-overlay (|d|<4¢), no_calib, no_curve (BTC ticker with
   calibration loaded → overlay OFF, no cross-type fallback), and combo YES-leg
   fade.
2. **Live scan (2026-09-24 ~10:52 UTC):** 8 unique candidates (all ECON CPI +
   3 CPI combos). 2 singles + 3 combos passed; 3 below the base 15¢ bar.
   **0 faded by the calibrated gate.** Tilts on the two passing singles:
   - `KXECONSTATCORECPIYOY-26SEP-T2.4 NO` @~59¢ (net 36¢): yes_equiv 0.41 →
     empirical 0.64, shrunk disagreement **−12.8¢** (block n=25). Calibration
     says YES is underpriced here — it DISAGREES with the desk's nowcast model
     (which sees ~36¢ NO edge). Tilt=None (the gate only fades YES-side
     overpricing per the study-hall direction; it does not fade NO). **This
     three-way disagreement (market 41% / model ~5% / history 64%) is the
     single most important open validation question for this module — the
     September CPI print will score all three.**
   - `KXECONSTATCORECPIYOY-26SEP-T2.7 YES` @7¢ (net 24¢): yes_equiv 0.07 →
     empirical 0.083, shrunk disagreement −0.5¢ → no tilt, PASS at 15¢. The
     gate correctly stayed quiet on thin evidence instead of blindly fading a
     cheap YES.
3. **Desk's own fills (2, both unsettled):** T2.4 NO @68c and T2.7 YES @14c.
   Scored against the curve at fill prices: T2.4 → confirm_no (+5.3¢ shrunk,
   YES overpriced); T2.7 → no tilt (−3.4¢ shrunk, under the 4¢ gate). The
   shrinkage correctly kept the marginal T2.7 case out of the tilt zone.
4. **136 skipped records (historical):** the OLD flat rule would have changed
   nothing (0 retail-heavy candidates in desk history). The calibrated gate is
   stricter still — it needs a mapped series AND ≥4¢ shrunk disagreement.
5. **Bartlett & O'Hara numbers — verified vs taken:**
   - *Verified externally (2026-09-24 web check):* the paper exists —
     "Adverse Selection in Prediction Markets: Evidence from Kalshi"
     (Bartlett & O'Hara, SSRN 6615739), ~41.6M trades; multiple independent
     sources confirm the YES/NO skew axis and the YES-biased uninformed-taker
     mechanism.
   - *Taken from ALPHA_RESEARCH.md, not verified against primary data:* the
     exact +1.91¢/contract figure and the ~$18.2M behavioral-tax number.

### What the first backfill got wrong (full disclosure)
The first `calibration_backfill.py` run (15,262 pairs across 18 series) fit a
GLOBAL curve over all families — including the converged crypto/sports/weather
prices. That curve was CIRCULAR and would have made the gate confidently wrong
(e.g. a live 25¢ BTC quote scored against a curve built on 1¢/99¢ converged
last-trades). It was caught by inspecting the per-family quote distributions
before anything consumed it, and replaced by the macro-only ECON_MACRO fit.
The invalid file was overwritten the same session; no shadow decision was ever
logged against it. Lesson encoded in the backfill's docstring: **settled
last_price is converged for in-play markets — only pre-resolution-close
families calibrate.**

### Ongoing A/B (how future fills get scored)
Every `shadow_candidate` row records: `disagreement_c` (shrunk), `calib_family`,
`tilt_dir`, `bar_c`, `faded`, `size_mult`, plus the human-readable note.
Faded-out singles and combo decisions live in the `shadow_run` `extra` payload.

Scoring recipe (for `learn_from_settlements.py` / calibration work):
1. Join live fills (`action='placed'`) to `shadow_candidate` rows on
   (ticker, side, date).
2. At settlement, attribute realized net P&L per fill.
3. Compare cohorts: fills the calibrated gate would have **faded** vs
   **passed**. Gate validated when the faded cohort trails by ≥2¢/contract
   over n≥20 mapped-series fills.
4. **Curve validation:** bucket settled fills by quoted-yes decile; compare
   realized YES rate vs the curve's empirical value. Recalibrate or widen
   shrinkage if systematic drift appears.

### Graduation criteria (before this overlay may touch the live bar)
- n ≥ 20 mapped-series (ECON_MACRO) fills with settled outcomes;
- the faded cohort trails the passed cohort by ≥ 2¢/contract realized;
- the curve's decile calibration holds (no systematic drift vs realized);
- the T2.4 three-way disagreement is resolved and understood;
- explicit Jeremiah approval, then a bar change in the live path (this module
  stays shadow-only; graduation does not modify it).

## 8. Cross-event logical containment (alpha module #3)

### What
Two logic checks on Kalshi's own books (no external data), both SHADOW ONLY:

1. **Listed-combo verification (step 1).** Re-checks the KEY FACT live on every
   run: enumerate all open series, classify every combo/parlay-named series.
2. **Touch-vs-terminal containment (step 2, the real build).** Crypto one-touch
   ladders (`KXBTCMAXMON`, `KXBTCMINMON`, `KXETHMAXMON`, … — "trimmed mean above
   $K at any point before month-end") are a SUPERSET of the hourly terminal
   ladders (`KXBTCD`, `KXETHD`, … — "price above $K at expiry") at the same
   threshold, whenever the terminal expiry falls inside the touch window.
   So fair(touch YES) ≥ fair(terminal YES). The executable violation:
   `touch_yes_ask < terminal_yes_bid` net of fees on both legs.
   Trade: buy touch YES @ ask + buy terminal NO @ (100 − term_bid).
3. **Listed combo vs legs (step 3).** The `*COMBO` econ series are listed
   single-instrument AND-question markets with live books. Map combo → leg
   markets (config table `COMBO_DEFS`), flag `combo_bid > Π(leg YES-equiv asks)`
   and the reverse as DIRECTIONAL SIGNALS (no atomic multi-leg execution;
   correlation risk; size accordingly).

### Why
Cross-event containment is model-free: it needs no vol estimate, no spot
feed, no opinion — just the logical subset relation plus executable quotes.
When it fires it is the closest thing to a free lunch on the board; when it
doesn't fire it costs nothing to keep armed. The combo-vs-legs check prices
the listed AND-questions against their replicating singles.

### Verification of market existence (the honest findings)
- **Listed combos: they exist, but NOT as combo books.** 49 combo/parlay-named
  series are open. Zero are RFQ-style multi-leg books (no public RFQ book
  endpoint exists — the KEY FACT re-verified live). The non-sports ones are
  ordinary single-instrument AND-question markets (`KXCPICOMBO`,
  `KXFEDCOMBO`, `KXEMPLOYMENTCOMBO`, `KXBALANCEPOWERCOMBO`, …); the rest are
  sports parlays (out of scope). So the original "parlay-vs-legs on listed
  combo books" scan is NOT buildable — but the AND-question-vs-legs check IS,
  and that is what step 3 implements.
- **Touch ladders exist and are quoted.** Monthly one-touch MAX/MIN series for
  BTC/ETH/SOL/DOGE/XRP/HYPE/BNB (plus weekly) with two-sided orderbooks.
  Terminal hourly ladders (`KXBTCD` etc.) are quoted. Same-threshold,
  same-window pairs are constructible.
- **Quote-source gotcha (2026-09-24):** `/events?with_nested_markets` and
  `/markets/{t}` top-of-book fields returned ALL NULLs while
  `/markets/{t}/orderbook` (`orderbook_fp`) showed deep live ladders. The
  module takes executable quotes ONLY from `orderbook_fp` (`yes_dollars` /
  `no_dollars` = resting YES/NO bids; `yes_ask = 100 − no_bid`).

### How it runs
- `python3 alpha_contain.py` — full run: series census → touch/terminal pairs
  → combo-vs-legs → prints pair tables + flags → shadow-logs. Exit 0.
- `python3 alpha_contain.py --selftest` — 15 offline math/parser checks.
- **SHADOW MODE ONLY.** No orders, no transfers, no POSTs. Logs
  `shadow_candidate` (module='contain') per flag with the full inequality in
  the note, plus one `shadow_run` summary. The live trader parses EDGE
  stdout, never the trade log.

#### The one lock direction (read before "fixing" this)
Only **touch-underpriced** locks: buy touch YES + buy terminal NO. Every
outcome then pays ≥ cost (touch ⊇ terminal: terminal-win ⇒ touch-win).
**Touch-overpriced does NOT lock** (buy terminal YES + touch NO pays 0 in the
touch-wins/terminal-loses branch) — the module deliberately does not flag
that direction. Same for combos: both combo-vs-legs directions are signals,
never locks.

#### Known cracks (attached to every flag note)
1. **Settlement aggregation differs:** touch settles on a per-minute
   trimmed-mean path (drops top/bottom 20% of each minute); terminal settles
   on the 60s simple average before expiry. A sharp spike confined to the
   final minute can win terminal while losing touch — near-lock, not pure.
2. **1c strike gap:** terminal ladders use `.99` strikes ("above $87,499.99")
   vs touch round strikes ("above $87,500.00"). Measure-zero for continuous
   prices; documented anyway.
3. Both settle on CF Benchmarks; "no data → resolves NO" contingencies match.

### Validation numbers (2026-09-24, final live run, exit 0)
- Open series scanned: **14,331**; combo/parlay-named series: **49**.
  - Sports (out of scope, non-sports desk default): 7.
  - AND/parlay-question *single markets* (ordinary one-instrument events with
    an AND in the question, e.g. KXCPICOMBO, KXFEDCOMBO, KXBALANCEPOWERCOMBO,
    KXEMPLOYMENTCOMBO): 12.
  - Other/unclassified (single-market combos like KXOHSENGOVCOMBO): 30.
  - Public **RFQ-style combo order books: 0** — no such public endpoint;
    every listed "combo" is a single market. Kalshi combos proper are private
    RFQ constructions; nothing to arb against a public book.
- Touch vs terminal containment: **141 candidate pairs** (same coin, same
  strike mod penny-gap, terminal expiry inside touch window).
  - Flags: **0**. Kills: **139** (no resting NO bids on the touch side, no
    resting bids on the terminal side, or thin top < 5 contracts). 2 rows
    clean with non-positive net edge.
- Combo vs legs: **15 combo markets** across KXCPICOMBO-26SEP,
  KXFEDCOMBO-26OCT, KXEMPLOYMENTCOMBO-26SEP, KXBALANCEPOWERCOMBO-27FEB.
  - Flags (net mispricing ≥ 10c desk scan bar): **0**. Kills: **5**
    (one-sided combo book). Unmappable skips: **19** ("Exactly X%" CPI legs
    need two markets; employment legs need two-market or missing rungs —
    skipped, never approximated).
  - Largest raw sub-bar readings (directional only, killed as noise):
    KXBALANCEPOWERCOMBO-27FEB-DD over +0.1c, -RR over +0.7c, -RD under +0.0c.
- Shadow log: **0 candidates, 1 shadow_run** (0 flags). Exit 0.

### How the first (buggy) run was killed — full disclosure
The module's first live run emitted 19 touch flags + 8 combo flags, all
invalid, all now purged from the shadow log (28 records removed; other
modules' records untouched). Two bugs, both fixed and self-tested:
1. **Touch-down direction bug:** compared touch YES ask against the terminal
   market's *YES* bid. Correct lock for "touches below K" needs the terminal
   market's *NO* bid (buy terminal-ABOVE YES replicates terminal-below NO).
   All 19 "flags" (edges up to 96c — impossibly large, the tell) were false
   positives. Fixed: per-direction quote selection; final run: 0 flags.
2. **Combo leg-side case bug:** leg specs returned `'YES'`/`'NO'` while
   `yes_equiv()` matched lowercase `'yes'`/`'no'`, so every leg read the
   *wrong side's* book (NO bids priced as YES bids). All 8 combo "flags"
   (edges up to 55.7c — again impossibly large) were false positives. Fixed:
   case-insensitive side matching; combo flag bar raised to the desk's 10c
   scan bar; final run: 0 flags.

Lesson encoded: any "locked" edge > ~10c on Kalshi is guilty until proven
innocent — treat it as a bug in the pricer's direction/side mapping first.

### False-positive analysis
Per-flag kills are coded, not hand-waved:
- **(a) rules/sources:** pair requires same coin, same threshold (penny-gap
  rule), both CF Benchmarks; the aggregation crack is disclosed on every flag
  and flags need edge > 0 net of exact `fee_cents` on BOTH legs.
- **(b) expiries:** terminal expiry must fall inside the touch window
  (issuance → month-end 23:59 ET); pairs outside it are never constructed.
  Combo-vs-legs requires same-date leg events (26SEP/26OCT/…); the
  balance-of-power pair is flagged with its settlement-date caveat (combo
  settles Feb 2027, legs Nov 2026 — same midterm outcome).
- **(c) stale/thin books:** executable quotes only (both required sides must
  have resting orders); top-of-book size < 5 contracts kills the pair;
  "Exactly X%" CPI legs and two-market legs (dissent-count aside) are skipped
  as unmappable rather than approximated.

### Graduation criteria (before anything here may touch live sizing)
- ≥ 20 shadow flags with settled outcomes, or 60 days of clean runs with the
  pair tables reviewed weekly for structural drift (new series, changed
  strike conventions, changed settlement PDFs);
- no flag cohort shows negative realized net edge net of fees;
- the `orderbook_fp`-vs-nested quote discrepancy is re-checked (if nested
  top-of-book becomes reliable, simplify);
- explicit Jeremiah approval. This module stays shadow-only regardless —
  graduation means a *new* live consumer, never flipping this file.

## 9. NFL win-probability model (alpha module #4)

### What
Elo (game results) + net EPA/play (per-play efficiency) blended into an expected
point spread, converted to a win probability via normal CDF, compared against
executable Kalshi `KXNFLGAME` yes-ask prices from the public orderbook. Edge >=
15c net of taker fee logs a shadow candidate (`module='nfl'`). Never places
orders, never moves money.

### Why
NFL game markets are the deepest sports book on Kalshi and the most likely
place a quantitative edge can survive. The model is a fair-value anchor: it
rarely disagrees with the market by 15c+, and when it does the record is kept
in the shadow log so graduation is evidence-based, not vibes.

### Formulas (exact, as coded)
- **Elo**: ELO0=1505, K=20, margin-of-victory multiplier
  `ln(|margin|+1) * 2.2 / (2.2 + 0.001*|elo_diff|)` (538 NFL formula), HFA=55
  Elo baked into the expectation. Season rollover:
  `elo = 1505 + 0.75*(prev_end_elo - 1505)`.
- **EPA**: per-team net EPA/play = offensive EPA/play minus defensive EPA/play
  allowed, on pass+run plays (kneels/spikes excluded). Bayesian-ish estimate:
  `(sum_epa + 400*prior) / (plays + 400)`, prior = `0.55 * prev-season final
  net EPA/play` (0.55 = year-to-year EPA persistence shrinkage).
- **Spread (home perspective)**:
  `spread = 0.65*(elo_diff/25) + 0.35*(net_epa_diff*60) + 2.2 + rest_adj - qb_out_adj`
  (25 Elo ~= 1 spread point; 60 plays/game; HFA 2.2 pts).
- `rest_adj = clip(rest_home - rest_away, -7, 7) * 0.35` points per rest day,
  from schedule dates.
- `qb_out_adj = 4.0` spread points when the starter is OUT/IR per ESPN.
- **Win prob**: `p = Phi(spread / 13.5)` (NFL margin SD ~= 13.5).
- **Executable price**: `yes_ask = 1 - best_no_bid` from public
  `/markets/{ticker}/orderbook` (`orderbook_fp.no_dollars`); edge = fair_c -
  ask_c; fee = `fee_cents(ask)` from combo.py (taker fee ceil(7c*p*(1-p)));
  shadow candidate iff edge - fee >= 15.

### Data
- nflverse play-by-play + schedules via `nflreadpy` (free, GitHub releases, no
  key), cached as parquet in `hidden_files/nfl_cache/` (2023-2026). Re-runs
  never re-download. Python venv at `.venv-nfl/` (system pip is PEP-668 locked).
- ESPN hidden API `site.web.api.espn.com/apis/site/v2/sports/football/nfl/`
  (scoreboard + injuries; no key). NOTE: `site.api.espn.com` 403s from this
  host — the `site.web` host with a Chrome UA works. Parsing is defensive;
  any shape change degrades to "no QB adjustment" with a printed warning.
- Kalshi series ticker **verified live** (2026-09-24): `KXNFLGAME`
  ("Professional Football Game"). Ticker anatomy:
  `KXNFLGAME-26OCT04INDWAS-WAS` = date + away + home + winning side; two
  tickers per game ("X wins"). Team codes are ESPN-style (LAR/LAC/JAC/WAS);
  ESPN renamed WAS->WSH in 2025 and nflverse uses LA/JAX — normalized in
  `canon()`. Fixture->market matching is on unordered team pair + date(+/-1
  day); 0 or >1 matches -> SKIP (never guess).

### How to run
- ` ./.venv-nfl/bin/python alpha_nfl.py --backtest` — 2024+2025 validation
- ` ./.venv-nfl/bin/python alpha_nfl.py --refresh` — re-pull nflverse cache
- ` ./.venv-nfl/bin/python alpha_nfl.py --fixtures [--week N]` — fixture table
- ` ./.venv-nfl/bin/python alpha_nfl.py --scan [--week N]` — full scan, shadow-logs

### Validation (real numbers, --backtest, run 2026-09-24)
No-lookahead walk of full 2024 and 2025 regular seasons (272 games each):
ratings start from the prior completed season's final state; games processed in
strict chronological order; each game is predicted BEFORE its result/plays are
absorbed; week-w plays feed only after all week-w predictions are recorded;
preseason priors use prior-season finals only. Ties scored 0.5 (one: 2025
GB-DAL). Baselines: 50/50, Elo-only (same Elo state, EPA weight 0), and
pregame-line-implied via `Phi(spread_line/13.5)` (nflverse `spread_line`, home
perspective, pregame).

| season | N | Brier model | Brier Elo-only | Brier 50/50 | Brier line-implied |
|---|---|---|---|---|---|
| 2024 | 272 | **0.2139** | 0.2153 | 0.2500 | 0.2031 |
| 2025 | 272 | **0.2251** | 0.2250 | 0.2500 | 0.2116 |

Calibration (model p_home): 2024 — 50-60%: 47.8%... precisely: 50-60% hit
46.8% (n=47), 60-70% hit 69.8% (n=53), 70-80% hit 70.7% (n=41), 80-90% hit
84.2% (n=19), 90%+ hit 100% (n=4). 2025: 46.0/59.5/72.5/76.0/100% (n=
50/42/40/25/6). Slightly cold at 50-60%, roughly honest elsewhere.

Proxy-line edge check (no public historical KXNFLGAME prices exist, so no
simulated Kalshi P&L is possible — stated plainly): games where
|model - line_implied| >= 15c: 2024: 33 games (12.1%), model direction correct
33.3%; 2025: 27 games (9.9%), correct 29.6%. **When the model disagrees
strongly with the line, the line is usually right.** This is the key honest
finding: the model is a competent fair-value anchor (near-line Brier), not a
proven edge over an efficient book.

Bugs caught by validation: (1) line-implied sign was flipped (Brier 0.347 >
coin flip — impossible for a real line, which exposed it); (2) ties must score
0.5; (3) greedy ticker regex mis-split 2+3-letter pairs (NEBUF -> NEB|UF).

### Intended schedule
NFL is weekly — this module is NOT a 5-min-cycle tool and is not wired into
auto_trade.py: **Tue** model refresh (`--refresh`); **Sun AM + Mon PM** injury
re-check + `--scan` before kickoffs; `--fixtures` any day. First live week-4
scan (2026-09-24): 16/16 fixtures mapped, 1 shadow candidate (WAS win fair 57c
vs KX ask 35c, edge 22c, net 20c — logged, shadow only).

### Graduation criteria (shadow -> live candidate)
1. Accumulate >= 30 shadow candidates at the 15c bar with realized hit rate
   >= fair-implied rate (calibration holds on candidates, not just all games).
2. Model Brier stays within 0.005 of line-implied Brier on a rolling season.
3. No QB-out misclassification in the log (the 4-pt adjustment is the
   highest-leverage input — audit each candidate's injury flag).
Until then: shadow only, weekly cadence, evidence over vibes.

## 10. Soccer Dixon–Coles model (alpha module #5)

### What
Dixon–Coles 1X2 (home/draw/away) pricer for Kalshi soccer game markets.
Blends a goals-based Dixon–Coles scoreline model (75%) with a ClubElo prior
(25%). Compares fair YES to Kalshi's executable yes_ask; logs a
shadow_candidate when edge clears **15¢ net of the taker fee**
(`fee_cents` from combo.py). **Shadow mode only — no orders, no money.**

### Why
Soccer 1X2 is a three-outcome market where bookmaker odds (and Kalshi books)
are set by public models; a clean Dixon–Coles with shrinkage is a legible,
calibrated baseline that can spot stale quotes, especially right after
lineups/news when Kalshi game markets are thin.

### Data sources (all free)
- **football-data.co.uk** — historical results CSVs (`/mmz4281/{2425,2526,2627}/{E0,SP1,D1,I1,F1}.csv`), incl. B365 closing odds used as a market baseline in backtest; `fixtures.csv` for upcoming matches (refreshed upstream ~weekly; same team naming, no name matching).
- **clubelo.com** — daily team Elo ratings parsed from country pages (`/ENG /ESP /GER /ITA /FRA`). ClubElo slugs are abbreviated (`Bayern`, `Gladbach`, `Koeln`) — mapping in `CLUB_SLUG_FIX`. Note: ClubElo date-addressed fixture pages list only PAST matches (upcoming fixtures are login-gated) — fixtures come from FDC instead.
- **Kalshi public trade API** — open game events per league series.

**xG status (honest): shot-level xG is NOT available.** Understat and FBref are
Cloudflare-blocked for automated fetch from this sandbox; dataMB is
JS-obfuscated. The model uses goals-based strengths — Dixon–Coles was
originally fit on goals anyway. Upgrade path: Understat session-JSON pull from
a non-blocked network.

### Kalshi soccer series (verified live 2026-09-24)
`KXEPLGAME`, `KXLALIGAGAME`, `KXBUNDESLIGAGAME`, `KXSERIEAGAME`,
`KXLIGUE1GAME`, `KXUCLGAME`. Game events only appear near matchdays (zero
open on Thu 2026-09-24; only `KXUEFANLGAME` internationals were open — national
teams are out of model coverage, skipped). Each event has 3 YES/NO markets
(home / TIE / away).

### Model
1. **Strengths**: last-10 matches, venue-split goals for/against per team.
2. **Shrinkage**: team rates regressed toward league averages with
   `PRIOR_W = 8` matches of weight (fixes small-sample overconfidence).
3. **Lambdas**: `λ_h = avg_h · atk_h · def_a`, `λ_a = avg_a · atk_a · def_h`.
4. **Dixon–Coles**: full 0–8 scoreline grid with low-score correction;
   `rho` fit by log-likelihood grid search on backtest data (**rho = -0.04**).
5. **ClubElo prior**: `p_home = 1/(1+10^(-(dElo+80)/400))`, draw from league
   base rate (0.25), renormalized; blended 25%.
6. Teams with <1 prior match (e.g. newly promoted) → no price, skipped.

### How to run
```
python3 alpha_soccer.py --refresh   # rebuild results + Elo + fixtures caches (daily)
python3 alpha_soccer.py --backtest  # walk-forward validation (2024/25 + 2025/26)
python3 alpha_soccer.py             # scan: fixture table, fair vs book, shadow log
```
Caches: `hidden_files/soccer_results.json`, `hidden_files/soccer_elo.json`,
`hidden_files/soccer_fixtures.json`. Be polite: ≤1 req/s, cached daily.

### Validation (real numbers, 2026-09-24)
- **N = 3374** matches (full 2024/25 + 2025/26, all 5 leagues), walk-forward,
  no lookahead (histories and league averages strictly pre-match).
- **Brier**: model **0.6201** vs naive base-rate **0.6508** vs B365 closing
  (vig-removed) **0.5791**. Model beats naive; trails the closing line
  (expected — the book encodes team news; the 15¢ bar is the protection).
- **Calibration** (model home prob → realized home-win rate): 0.2→0.21,
  0.3→0.32, 0.4→0.40, 0.5→0.51, 0.6→0.60, 0.7→0.66, 0.8→0.79.
  Teams priced 60–70% win ~60–66%. Well calibrated.
- **Market check 2026-09-24**: 6 series verified; 0 open big-5 game events;
  0 fixtures mapped; 0 candidates cleared 15¢. Exit 0.
- **Kalshi historical soccer prices**: not available via public API
  (no price history endpoint for settled soccer markets) — no P&L backtest
  against Kalshi itself. Stated as a gap.

### Caveats
- No same-week xG; goals-based only.
- Top-5 Euro leagues only (club teams). UCL game markets (`KXUCLGAME`) are
  in scope structurally but cross-league strengths aren't normalized yet —
  currently skipped in practice (no open events to test against).
- FDC fixtures feed is weekly; mid-week refreshes may lag new postings.
- FDC 2026/27 results CSVs are partially populated (Bundes 36 rows; EPL
  empty as of 2026-09-24) — early-season prices have thin histories.
- ClubElo blend weight (25%) is structural, not backtest-validated.

### Graduation criteria (shadow → live, needs Jeremiah's sports-window auth)
1. Model Brier stays < naive Brier on each new completed season (re-run
   `--backtest` after adding 2627).
2. Calibration stays on-diagonal (±5pp per bucket, n≥50).
3. ≥20 shadow candidates logged with `would_take_live_bar=true`, and their
   realized P&L vs Kalshi settlement is positive net of fees.
4. Sports scope: per standing rule, soccer is out of scope for live trading
   until Jeremiah authorizes a window — this module stays shadow until then.

