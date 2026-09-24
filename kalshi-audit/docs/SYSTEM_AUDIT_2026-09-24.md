# SYSTEM AUDIT — Kalshi auto-trader — 2026-09-24

Auditor posture: hostile review of everything EXCEPT the settlement-accounting
plumbing and the hourly index model post-mortem (two other agents own those).
Read-only + dry-run analysis. No orders placed.

**Verdict up front: the system is NOT safe to trade with any model right now.**
The risk gates have holes the whole bankroll fits through: unsettled exposure
bypasses the stop-loss entirely, phantom fills corrupt the ledger, there is no
in-play cap, no sports gate, and overlapping cron runs can double-trade. Fix
the five criticals before a single live order.

---

## CRITICAL

### C1. Phantom fills are manufactured by the placement logger — this is the T7669 -64c
- `auto_trade.py:1985`: `filled = int(order.get('fill_count') or n)`
  - `fill_count=0` is falsy in Python, so `0 or n` → `n`. An order the exchange
    accepted but never filled is logged as **fully filled**.
  - The T7669 NO 4@16c placed entry (trade_id `d6a41ab171f6`) shows
    `"fill_count": 4` — but the API never showed a fill; the order_id exists,
    the GTC limit simply never got hit before expiry.
- `settle_check()` (`auto_trade.py:193-249`) books P&L from `e['contracts']`
  (the *requested* count) and `e['price_cents']` (the *limit* price). It never
  consults official fill history. So the phantom 4 contracts became a phantom
  -64c settle entry.
- Fix: `filled = int(order.get('fill_count') or 0)` (0 must stay 0); confirm
  actual fills via the API before writing the `placed` log; make `settle_check`
  reconcile against official fills, and book P&L on filled quantity only.

### C2. The stop-loss only counts settled P&L — unsettled exposure is unbounded
- `main()` (`auto_trade.py:2192-2196`): `realized = load_pnl().get(day, ...)`
  reads the *settled-only* bucket. There is no position/risk accounting for
  open positions or resting orders anywhere in the gate path.
- Today: 13 correlated hourly trades were placed while realized was $0; the
  gate saw nothing; all 13 settled -14.10 at once at 09:00 CDT. The -$3 gate
  is structurally incapable of stopping a correlated batch.
- Compounding: there is **no per-event, per-expiry, or committed-notional
  limit** anywhere (grep for `MAX_IN_PLAY`, `max_in_play`, `per_event`,
  `per_expiry` → zero hits). One expiry hour = one coin flip = 13 bets.
- Fix: track open risk (positions + resting-order notional, marked) and gate
  on `realized + open_risk <= -$3`; add per-event and per-expiry exposure caps
  (e.g. max $2 committed per expiry hour).

### C3. The $10 max-in-play rule exists only in prose
- `desk.md` (and the user's standing rules): "at most $10 in play" of a $20
  bankroll. No constant, no check, no comment references it in `auto_trade.py`.
  The rule was never canceled; it was never implemented either.
- Fix: enforce `open_notional + resting_notional + new_cost <= $10` before
  every placement.

### C4. No non-sports gate in the trading path
- `desk.md`: "Non-sports markets only. No exceptions." The user authorized
  sports only for the 2026-09-22 evening window.
- `market_kind()` (`auto_trade.py:566`) has no sports branch — sports tickers
  fall through to `'index'`. Nothing in verify/place checks the series
  category. The universal sweep (`edge_scan.py:1211-1345`) emits `EDGE:` lines
  for **every** series (only `_COVERED_PREFIX` series are excluded) with
  `asset='SWEEP'`; `reverify()` routes `asset=='SWEEP'` to `reverify_sweep()`,
  which can pass a 15c+ result-set dislocation on a sports market straight
  into `place_single_candidate()`.
- The only sports check in the codebase is in `cancel_stale_orders`
  (`auto_trade.py:1509`) — the wrong end of the pipeline.
- Fix: fail-closed category check in verify (and belt-and-braces in place):
  `_series_category(t) == 'Sports'` → skip, always.

### C5. No run-level lock — overlapping live runs can double-trade
- The `kalshi-edge-hunt` cron fires every 2 minutes (`timeout_secs: 600`).
  `run_scan()` (`auto_trade.py:302`) takes ~105s clean, up to 270s on timeout —
  **longer than the cron interval**. Overlapping live runs are probable, not
  theoretical.
- No lock file / flock anywhere (grep `lock|flock|pidfile` → nothing).
  `client_order_id` is a fresh uuid per run, so the exchange cannot dedupe.
  `held_tickers()` mitigates via positions/resting orders, but there is a
  read-after-write race between run A's placement and run B's `held` fetch,
  and `held_tickers()` fails open (see H4).
- Concurrent runs also race on `daily_pnl.json` read-modify-write
  (`load_pnl`/`save_pnl`, `auto_trade.py:128-136`) — last write wins, losing
  a run's settlements — and on `auto_xfer_daily.json`.
- Fix: `flock` a lock file at `main()` entry; if locked, exit quietly (log
  `action='skipped', reason='previous run still active'`).

---

## HIGH

### H1. Transient API failure permanently drops a settlement from the books
- `settle_check()` (`auto_trade.py:199-200`) builds `settled_ids` from **every**
  `action='settle'` entry with a trade_id — including the `status='fetch_failed'`
  entries it writes itself (`auto_trade.py:219-222`) when `get_market()` throws.
- One timeout → the trade_id is blacklisted forever → its loss is never booked
  → the stop-loss undercounts. The failure mode corrupts the exact number the
  stop-loss depends on.
- Fix: never write `action='settle'` for fetch failures (use
  `action='settle_fetch_failed'`); only confirmed settlements join
  `settled_ids`.

### H2. Stop-loss day boundary is UTC, not America/Chicago
- `today_str()` (`auto_trade.py:113`) uses `datetime.now()` on a UTC box
  (verified: `date` → UTC). `daily_pnl.json` keys and the stop-loss gate both
  use it. The -$3 gate therefore **resets at 19:00 CDT**, handing the same
  Chicago evening a fresh stop-loss.
- `_chicago_today()` (`auto_trade.py:1275`) exists but is only used for the
  transfer caps. Inconsistent day definitions in the same file.
- Fix: one canonical `_chicago_today()` for every daily bucket and gate.

### H3. Realized P&L is booked gross of fees — the stop-loss is late by design
- `settle_check()` (`auto_trade.py:231`): `pnl_c = ((100 if won else 0) -
  e['price_cents']) * e['contracts']`. No fee term. The 12 real index trades
  paid roughly 50–80c in half-rate taker fees that never hit the ledger, so
  true net today is worse than the booked -1474c and the -$3 gate fired later
  than it should have. (RISK.md admits the tripwire is "lenient" gross; the
  stop-loss has no such excuse.)
- Fix: subtract `exact_fee_cents(filled, price, fee_meta)` at settle time.
  Recompute today's true net before any restart.

### H4. `held_tickers()` fails open
- `auto_trade.py:1401-1413`: both API calls are wrapped in bare
  `except: pass`. If `get_positions()` fails, `held` is empty and the bot can
  re-buy a ticker it already holds (or that has a resting order).
- Fix: fail closed — if the book can't be read, skip trading this run.

### H5. Singles have no executable-depth gate (combos do)
- `reverify_combo()` (`auto_trade.py:787-794`) caps size at top-of-book depth.
  `place_single_candidate()` has **no depth check at all**: a $2 order at 3c
  (66 contracts) into a 5-deep book partially fills or rests as a stale GTC.
  Partial fills + C1 = phantom P&L on the unfilled remainder.
- Fix: same touch-depth gate for singles, or FOK for small sizes.

### H6. Settlements are booked to the *placement* date, not the settlement date
- `settle_check()` (`auto_trade.py:233`): `day = e.get('date', today_str())`
  takes the date from the *placed* entry. A trade placed Sep 24 that settles
  Oct 14 books its P&L against Sep 24's daily stop-loss bucket.
- Fix: book to the settlement run's Chicago date.

---

## MEDIUM

- **M1. Re-verification is not independent.** `reverify()` uses "scanner vol
  assumptions" (`auto_trade.py` header docstring; same `_N`/vol math as
  `edge_scan.py`). A second opinion that shares the first opinion's model bug
  is not a second opinion — this is how the benched tail model passed its own
  re-checks.
- **M2. Learner trains on polluted data.** `learn_from_settlements.py` consumes
  settle entries including phantoms (C1) and gross-of-fee P&L (H3). Blast
  radius is bounded (±3c cap, shrinkage), but the calibration file should be
  wiped and rebuilt after the ledger is fixed.
- **M3. RISK.md is stale and overpromises.** Claims "there is no deposit,
  withdraw, or transfer function anywhere in its code" — false since the
  2026-09-24 shard auto-funding. Omits the $10 in-play and non-sports rules.
  Says the stop-loss means "it can't dig a deep hole" — C2 proves otherwise.
- **M4. Cron reporting is unreliable.** The `kalshi-edge-hunt` task_context
  itself notes workers previously wrote false "message sent / ticket
  delivered" claims. Today's runs also emitted contradictory ledger
  commentary (13 vs ~35 settlements). Treat worker self-reports as unverified.
- **M5. `balance_c` bookkeeping ignores fees** (`auto_trade.py:2003-2006`)
  and, via C1, decrements on phantom fills. Conservative direction, but wrong.
- **M6. Combo $2 cap excludes fees.** `reverify_combo` (`auto_trade.py:780`):
  `n = min(n, 200 // total_price_c)` caps cost ex-fees; "total combo cost ≤ $2"
  is exceeded once fees land. Also `edge_c` sums per-leg *rounded* edges
  (±0.5c/leg).
- **M7. Dead code / stale comments.** `count_placed_today()` (cap removed);
  "counts toward 3/day cap" comment in `place_combo_candidate`; sprint bonus
  references a dead sprint. Harmless but rots trust in the comments.

## LOW
- `_ceil_cents` float-boundary epsilon can overstate a fee by 1c (conservative
  direction; `FEE_SLACK_CENTS` covers it). Fine.
- `size_contracts` float floor-division — numerically fine.
- `parse_candidate` regex has documented arb-line guards. Fine.
- Sprint bonus is ranking-only, matches spec. Fine.

---

## What checked out clean

- **Fee math** (`fees.py`): correct. Half-rate detection (`is_half_rate`),
  per-order ceiling, taker/maker split, fee-multiplier, cache fallback to
  conservative taker rate — all match PLATFORM.md §4 and the unit tests pass.
  Call sites apply the 15c bar **net of exact fees** (`auto_trade.py:1879`).
- **Sizing math**: half-Kelly (`kelly_stake_cents`, `auto_trade.py:1177`) is
  correct, fee-aware iteration is sound, $2 hard cap enforced for singles and
  combos, per-leg combo sizing with min-across-legs is the right call, no
  joint probability invented. No zero-division paths (all guarded). Sizing
  against aggregate balance with per-shard collateral pre-flight in Phase B
  is defensible.
- **Combo execution**: FOK per leg, idempotent `client_order_id` per leg,
  `placed_leg` logged only for actually-filled legs with real `fill_count`
  (`execute_combo`, `auto_trade.py:808-855`) — the combo path does NOT have
  the C1 bug. Partial-fill anomaly is logged loudly.
- **Shadow/research isolation**: `shadow.py` is log-only; `alpha_*.py`,
  `mlb_model.py`, `benter_second_stage.py`, `calibration_backfill.py` are not
  imported by any live path; `mlb_totals.py` is explicitly flag-only
  (`edge_scan.py:1180-1196`: "Disagreements are logged, never traded").
  No unproven model has a live path to order placement.
- **Shard plumbing**: `parse_shard_balances` unit trap documented and handled;
  `auto_fund_shard` caps ($2/transfer, $6/Chicago-day), 15s settle wait,
  single-shot non-idempotent transfers never retried — matches the standing
  delegation.
- **TIF discipline**: crypto15m IOC, everything else GTC with
  `expiration_time = min(close, 24h)`; `cancel_stale_orders` runs every cycle
  *before* the stop-loss gate, so stale defense works even on halted days.
- **Config constants match the user's rules**: 15c bar, $2/trade, -$3 stop,
  10-min-to-close, 50-tripwire all present and correct. The drift is in the
  rules that were *never encoded* ($10 in play, non-sports) and the day
  definition (UTC vs Chicago).

---

## Fix order (before any live order)

1. C1: real fill accounting (placement log + settle_check vs official fills);
   publish audited +64c correction; recompute true net incl. fees (H3).
2. C5: run-level flock.
3. C2 + C3: open-risk accounting, per-event/per-expiry caps, $10 in-play gate.
4. C4: sports category block in verify and place.
5. H1, H2, H6: settle robustness, Chicago day, settlement-date booking.
6. H4, H5: fail-closed held_tickers, single depth gate.
7. M2, M3: wipe calibration.json, rewrite RISK.md to match the code.
8. Re-certify with a dry-run day, then re-enable — hourly index model stays
   benched until it passes its graduation exam regardless.

## Cron layer note
- `kalshi-edge-hunt` (2m): still `enabled: true`. While the desk is halted it
  burns runs and emits contradictory commentary. Pause until fixes 1–5 land.
- `kalshi-chatter-watch` (45m): research-only, no trading path. Fine as-is.
