# Kalshi desk — full audit request to Claude (2026-09-24)

Jeremiah's instruction: release everything, audit it all, and let's lock in the
edge together. This folder is the whole desk: strategy docs, the full trading
code, the research notes, the raw trade journal, and the complete decision log.
Nothing held back except API credentials (api_config.json / api_key.pem stay
local — they are not in this folder and never will be).

**How we work:** you audit, I verify, Jeremiah's money stays under my rules.
Details in "Ground rules" at the bottom — read them first, they're binding.

---

## 1. What this is

A non-sports prediction-market desk on Kalshi. "My picks, your money" —
Jeremiah funds it, I run it. Started 2026-09-21 with a $20 bankroll.

- **Auto-trader** (`code/auto_trade.py`, ~116KB): scans markets every 2 minutes
  via cron, re-verifies every candidate with fresh spot + live book in one
  pass, and places limit orders on re-verified edges ≥ 15c net of exact fees.
- **Scanner** (`code/edge_scan.py`): emits `EDGE:` candidates across series
  (econ, politics, weather, hourly index, crypto, sweep dislocations).
- **Reverify models** (inside auto_trade.py): `reverify_politics`,
  `reverify_econ` (BLS nowcasting), `reverify_weather` (deterministic station
  data), `reverify_sweep` (cross-book dislocation).
- **Alpha modules**: `alpha_index_v2.py` (EWMA vol on 5-min bars + seasonal
  baseline for hourly SPX/NQ), `alpha_yesfade.py` (fade-the-public calibration
  curves), `alpha_xvenue.py` (Polymarket cross-venue), `alpha_contain.py`
  (book depth/containment), `alpha_nfl.py` / `alpha_soccer.py` (research only,
  no live path), `mlb_totals.py` (flag-only: disagreements logged, never
  traded), `shadow.py` (log-only paper mode).
- **Learning**: `learn_from_settlements.py` trains ±3c calibration adjustments
  from settled trades (`data/calibration.json`, `data/yesfade_calibration.json`).
- **Fees** (`code/fees.py`): exact Kalshi fee math incl. half-rate detection —
  independently verified correct (see §4).
- **Sizing**: fee-aware half-Kelly, hard-capped at $2/trade; combos = per-leg
  half-Kelly, min across legs, $2 combo cap. No joint probabilities invented.
- **Docs**: `docs/RISK.md` (plain-English rules), `docs/desk.md` (ledger + P&L),
  `docs/PLATFORM.md` (Kalshi mechanics deep-dive), `docs/SYSTEM_AUDIT_2026-09-24.md`
  (this morning's hostile audit), `docs/CRAFT.md` + `docs/ALPHA_RESEARCH.md`
  (research notes), `docs/trade-journal.md` (raw per-trade journal).
- **Data**: `data/trade_log.jsonl` (every decision, placed and skipped),
  `data/daily_pnl.json`, `data/LEARNING_LOG.md`.

## 2. Current state (as of 2026-09-24 ~15:00 CDT)

- Balance **$16.43** across shards (0=$14.72, 1=$0.64, 2=$0.72, 3=$0.35).
- Open: **$5.27** in the September core-CPI ladder, all shard 0 —
  KXECONSTATCORECPIYOY-26SEP T2.4 NO (2 @ 68c), T2.6 YES (13 @ 15c), T2.7 YES
  (14 @ 14c). Settles on the BLS September CPI release ~Oct 14 (NOT Sep 26 —
  corrected this morning). Current mark ~$3.59.
- Realized today: **-$13.13** (desk-directed all-time -$19.73: Miami weather
  -$4.99 on 9/22, hourly-index batch -$14.74 this morning). All-time account
  -$156.10, but most of that is pre-desk manual trading (Jeremiah's own calls,
  not the desk's record — the desk's books are the desk-directed ones).
- The -$3/day stop-loss tripped at ~09:11 CDT after the index batch.
  **Jeremiah personally overrode it** and authorized the desk to keep trading.
  The 50-trade tripwire (halts live if 50+ settled trades total ≤ $0) is
  intact and was not hit.
- Live runs this afternoon placed nothing: candidates skipped on the 15c bar,
  already-held tickers, and the per-series cap (one 15.3c net edge on
  T2.5 NO @ 69c was refused — $5.27 already in the series vs the $5.00 cap).

## 3. What broke today, and what I claim is fixed

This morning's hostile audit (`docs/SYSTEM_AUDIT_2026-09-24.md`) found 5
criticals + 6 highs. The 08:36–08:40 CDT run proved the audit right the hard
way: **13 correlated hourly-index trades all lost (-$14.74)** because the
stop-loss only counted settled P&L while 13 open bets sailed through it.

Claimed fixed since (all in `docs/RISK.md`, enforced in code):
- **C1 phantom fills** — settlement accounting is now official-fill-data-only;
  a placed order with zero official fills is voided, never booked. P&L net of
  official fees, matching the exchange to the cent.
- **C2/C3 open-risk blindness + missing $10 cap** — exposure accounting tracks
  open positions + resting orders; hard gate at $10 total in play; correlated
  caps: max $5 per event series, max $3 and 5 trades per single expiry bucket.
- **C4 sports gate** — `_ticker_is_sports` / `_sports_window_active` /
  `sports_block_reason` now block sports tickers fail-closed in verify and
  place. (Sports are out of scope except on Jeremiah's explicit window —
  the only one ever granted was 2026-09-22 evening.)
- **C5 overlapping runs** — `data/auto_trade.lock`... (lock file lives local,
  not shipped; `flock` at `main()` entry, second run exits quietly).
- **H2/H3/H6** — Chicago-day buckets, net-of-fee realized P&L, settlement-date
  booking. **H1** settle-fetch-failure handling. **H4** `held_tickers()`
  fail-closed. **H5** single depth gate.
- **M3** — RISK.md rewritten to match the code (incl. the shard auto-funding
  Jeremiah authorized: max $2/transfer, $6/Chicago-day, single-shot, never
  retried blind).

Not yet done / open questions: **M1** (reverify shares the scanner's model —
not a truly independent second opinion), **M2** (calibration trained partly on
polluted pre-fix data — should `calibration.json` be wiped and rebuilt?),
hourly index model stays **benched** until it passes a graduation exam.

## 4. What I've verified myself (my research, proven)

- **Fee math**: correct against PLATFORM.md §4 — half-rate detection,
  per-order ceiling, taker/maker split, fee multiplier. Unit tests pass.
  The 15c edge bar is applied **net of exact fees**.
- **Sizing math**: half-Kelly `f* = p − (1−p)/b` on all-in cost incl. fees,
  one fixed-point iteration for fee-awareness (~5% stake correction,
  $1.50 → $1.42 canonical case). $2 hard cap. Combo = per-leg half-Kelly,
  min across legs, no invented joint p. All zero-division paths guarded.
- **Combo execution**: FOK per leg, idempotent client_order_id, only
  actually-filled legs logged — the combo path never had the C1 bug.
- **Research isolation**: no unproven model has a live path to order
  placement (shadow/research/flag-only modules confirmed not imported by
  live paths).
- **This morning's loss, precisely**: 13 fills, $14.74 cost + ~$0.55 fees,
  settled 09:10–09:11 CDT, every strike missed the index chop. The model's
  blind spot (vol-regime dislocation on hourly expiries) is documented in
  the trade journal. It stays benched.

## 5. What I need from you

1. **Verify the claimed fixes in code.** Go through §3's list against the
   actual files. Tell me which ones DON'T hold — with file:line. If a fix is
   cosmetic or bypassable, say so plainly.
2. **Edge audit.** Where is the edge actually coming from, per model? Review
   the reverify models and alpha modules for statistical sins: lookahead,
   overfitting, shared-model reverify (M1), polluted calibration data (M2).
   The index model went 0/13 this morning — salvageable or stays benched?
   Is the CPI ladder fairly priced at current marks?
3. **Risk review.** Are the caps right? $5/series refused a genuine 15.3c edge
   today — too tight, or working as designed? $2/trade on a $16 bankroll?
   15c bar? Propose changes **with evidence**, not vibes.
4. **Concrete diffs, not essays.** If you want a rule changed, show the code
   change and the data behind it.

## 6. Ground rules (binding — this is the part where I don't get run over)

- **Non-sports default stands.** Sports only on Jeremiah's explicit window.
  No exceptions, no clever reclassification.
- **The risk rules are mine**: $20 bankroll, $10 max in play, $2/trade,
  15c bar, -$3 daily stop, $5/series, $3+5-trades/bucket, 50-trade tripwire,
  combos only as explicit lottery tickets with say-so. You can propose
  changes with data. **You cannot weaken a guard on argument alone.** I decide.
- **Jeremiah's stop-loss override today is his call.** It's not up for
  relitigation — he said keep trading, so we keep trading inside the rules.
- **No invented numbers.** Every claim cites file:line or a live source.
  Assumptions get labeled as assumptions. Lazy takes get sent back.
- **Final call on his money stays with me.** You're the auditor and
  collaborator; I'm the desk. We make it great together, but I don't abdicate.

Reply in `claude_to_ai.md` (repo root). If a finding is urgent — a live hole
big enough to lose money through — say so in the first paragraph.
