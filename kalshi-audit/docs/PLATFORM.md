# Kalshi Platform Deep Dive

Living reference on the venue itself — market types, ticker anatomy, settlement,
exact fee math, API capabilities, combo + perps mechanics, and every trap that
can surprise a bot. Built 2026-09-24 from the official OpenAPI spec (v3.31.0,
fetched 2026-09-24), live API responses, the official fee schedule (via multiple
independent captures quoting the PDF), and web research. **Verify against the
live API before trusting anything here for money** — Kalshi changes things.

> Standing rule: never build trading logic on guessed platform behavior. When
> this doc and a live API response disagree, the live response wins — then
> update this doc.

---

## 1. Market types

### 1a. Event contracts (the core product)

Every tradable is a **binary** contract (API `market_type: binary`) paying **$1.00**
if the Yes side wins, $0.00 otherwise. (`scalar` exists in the API enum but zero
open scalar markets were observed 2026-09-24 — treat as vestigial.)

Three shapes, all binary under the hood:

| Shape | What it is | Example ticker |
|---|---|---|
| **Single yes/no** | One market per event, "will X happen" | `KXNBAGAME-26OCT20BOSDET-BOS` |
| **Ladder** | Many markets, each "will price be ≥ strike K" (cumulative) | `KXBTCD-26SEP24-T95000` |
| **Bracket** | Many markets, each "will outcome land exactly in bucket B" (mutually exclusive) | `KXDOGE-26SEP24-B0.097` |

- **Ladders** (`-T<strike>` suffix): strikes are thresholds. YES on `KXBTCD-…-T95000`
  wins if BTC ≥ $95,000 at close. Ladder markets are NOT mutually exclusive —
  if BTC closes at $96k, every strike ≤ 96k settles Yes.
- **Brackets** (`-B<bucket>` suffix): buckets partition the outcome space.
  Exactly one bucket settles Yes (for well-formed exhaustive brackets).
  `KXECONSTATCORECPIYOY-26SEP-T2.5` uses `-T` with 0.1pp-wide buckets — note the
  suffix letter alone doesn't tell you ladder-vs-bracket; check the series.
- **Singles**: team suffixes (`-BOS`, `-DET`), `-0`/custom strikes, or bare
  event tickers with a hash suffix (`KXMVECROSSCATEGORY-S2026C07B2F79C53-29882799AA9`).

Hierarchy: **Series** → **Event** → **Market**. The series (`KXBTCD`) defines the
recurring contract; the event (`KXBTCD-26SEP24`) is one expiry instance; the
market (`KXBTCD-26SEP24-T95000`) is the tradable.

### 1b. Combos (listed)

Combos are **pre-packaged conjunction markets** — still binary, still $1 payout.
Each market's rules are "IF ALL of the following occur … then Yes."
Example: `KXFEDCOMBO-26OCT-0-0` = "Oct 2026: Fed funds decision = no change AND
dissents = 0". The ticker suffix after the event ticker encodes the leg
combination (`-0-0`, `-25C-0`, `-25C-T0`) with `strike_type: custom`.

28 combo series observed live (2026-09-24): `KXCPICOMBO`, `KXFEDCOMBO`,
`KXEMPLOYMENTCOMBO`, `KXBALANCEPOWERCOMBO`, `KXLEGISLATIVECOMBO`,
`KXTRUMPBEARCASECOMBO`, `KXMANCHINCOMBO`, `KXBLUETRICKLECOMBO`,
`KXBLUEWAVECOMBO`, `KXREDWAVECOMBO`, `KXMEGATSUNAMICOMBO`,
`KXBLUETSUNAMICOMBO`, `KXAKCOMBO`, state `*SENGOVCOMBO` series, etc.

There is **no multi-leg atomic order endpoint** in the public API. "Building
your own combo" = placing N separate single-leg orders and managing fill risk
yourself (see §8 traps).

### 1c. Perps — American Perpetuals (NOT in the trade API)

- CFTC-approved: **BTCPERP** (May 29, 2026), then ETH, XRP, SOL, ADA, DOGE,
  SHIB, ZEC, NEAR filed days after.
- Contract unit: **1/10,000 of one bitcoin** (per the CFTC order). 24/7 trading.
- **Isolated margin** — collateral posted per position is the max at risk.
- Leverage: conservative; **BTC capped ~5.7x at launch**, altcoins lower,
  adjusts with conditions.
- **Funding every 8 hours, capped at ±2% per window.** Longs pay shorts when
  perp > spot; shorts pay longs when perp < spot.
- **Separate margin account** (Kinetics FCM / Kalshi Klear DCO). A perp
  liquidation **can never touch** the event-contracts balance. Idle margin
  earns ~3.25% APY (US, ≥$250 avg balance, paid monthly).
- Liquidation is automatic when margin falls below minimum; **not a guaranteed
  stop** — gaps can push the account negative.
- **API status: the public Trade API spec (v3.31.0) contains ZERO perp
  endpoints.** Perps are not listed as event series in `/events` either.
  Programmatic perps access appears institutional (FIX / FCM subtrader
  sessions, margin WebSocket). **Do not plan perps automation on the REST API
  until Kalshi publishes endpoints.** The website/app is the only confirmed
  retail path.

---

## 2. Ticker anatomy

### Series ticker
Uppercase alphanumeric, usually `KX`-prefixed (legacy series like
`SENATEAK`, `HOUSECA13`, `GOVPARTYTX` lack it). Encodes the market family:
`KXBTC15M`, `KXBTCD`, `KXHIGHCHI`, `KXECONSTATCORECPIYOY`, `KXFED`,
`KXNBAGAME`, `KXCPICOMBO`.

### Event ticker
`{series}-{datecode}` most of the time: `KXBTCD-26SEP24`, `KXHIGHCHI-26SEP24`,
`KXECONSTATCORECPIYOY-26SEP`, `KXFEDCOMBO-26OCT`. Variants:
- Intraday: `KXBTC15M-26SEP24-0345`-style (HHMM ET close embedded).
- Sports: `KXNBAGAME-26OCT20BOSDET` (date + team codes).
- Opaque: `KXMVECROSSCATEGORY-S2026C07B2F79C53` (hash suffixes).

### Market ticker
`{event_ticker}-{market_suffix}`. Suffixes observed:
- `-T<strike>` — ladder threshold or bracket bucket value
  (`-T95000`, `-T2.5`, `-T69`). Decimal points allowed.
- `-B<bucket>` — bracket bucket (`-B0.097`).
- `-<TEAM>` — sports singles (`-BOS`, `-DET`).
- `-0`, `-25C`, `-T0` combos — custom conjunction encodings.
- `-<hex>` — opaque suffixes on odd series.

**Parsing rule:** never assume suffix semantics from the letter alone.
`-T` can be a ladder strike OR a narrow bracket bucket. Resolve shape from
the series, not the suffix.

### Useful series fields (GET /series/{ticker})
`fee_type`, `fee_multiplier`, `category`/`categories`, `settlement_sources[]`
(name + url), `contract_terms_url`, `additional_prohibitions[]`,
`exchange_index` (shard; orders auto-route, `-1` forces auto-routing).

---

## 3. Settlement

- Each market has `close_time`; settlement follows once the source confirms.
  `result` → `yes`/`no`; winners credited **$1.00 per contract**.
- Numeric markets expose **`expiration_value`** — the actual measured value
  (e.g. `64.00` for `KXHIGHCHI-26SEP22-T69`). This is the ground truth for
  verifying settlement-source alignment.
- **No settlement fee. No membership fee.**
- Markets close at `close_time`; some settle early if the outcome is certain.
- **Settlement sources are per-series** (`settlement_sources` on the series
  object). Verified/known mappings:
  - Weather (KXHIGH*/KXLOW*): **The Weather Company**. Measured 64/64
    station-days: TWC `expiration_value` == IEM ASOS obs at mapped stations.
    Day = local standard-time midnight–midnight. Station map: CHI=MDW,
    DAL=DFW, NYC=Central Park, HOU=HOU. (Supersedes older "NWS Daily Climate
    Report" notes.)
  - CPI/jobs (KXECONSTAT*, KXCPICORE): **BLS**.
  - NBA (KXNBAGAME): the governing league (nba.com) + ESPN.
  - Always read `settlement_sources` + `rules_primary` for series you model —
    sources differ and Kalshi changes them.

---

## 4. Fees — exact math

From the official fee schedule (effective Feb 5, 2026; corroborated by the
July 7, 2026 revision and multiple independent captures):

```
taker_fee = ceil_to_cent(0.07   × C × P × (1 − P))
maker_fee = ceil_to_cent(0.0175 × C × P × (1 − P))   # ONLY on designated series
```

- `C` = contracts filled, `P` = fill price in dollars (0.50 = 50¢).
- `ceil_to_cent` rounds **up** to the next whole cent **per order**
  (not per contract — a 100-contract order at 50¢ pays $1.75 total, not
  100 × $0.02). One gotcha report notes per-fill micro-ceiling to $0.0001;
  treat the per-order cent-ceil as the binding rule and the micro-ceil as
  possible additional rounding.
- **Taker** = your order matched immediately against resting orders.
  **Maker** = your resting order got filled later. You never pay both on one
  fill. Cancelling is free.
- **Reduced rate on index markets:** `INX*` (S&P 500) and `NASDAQ100*` use
  **0.035 taker / 0.00875 maker** — half rate. (Observed in every fee capture
  since 2022.)
- **Maker fees apply ONLY where `fee_type` says so.** Per-series `fee_type`
  enum: `quadratic` (taker only), `quadratic_with_maker_fees`,
  `quadratic_with_combo_maker_fees`, `flat`. Check
  `GET /series/{ticker}` → `fee_type` (+ `fee_multiplier`, usually 1) and
  scheduled changes at `GET /series/fee_changes`, `GET /events/fee_changes`
  (event-level overrides; null = cleared).
- **Sports charge maker fees**: `KXNBAGAME` → `quadratic_with_maker_fees`.
  Resting limit orders on sports are NOT free.
- The fee curve peaks at 50¢ and vanishes toward 0¢/100¢. Round-trip at the
  same price P costs `2 × 0.07 × P × (1−P)` per contract — at 50¢ that's
  3.5¢/contract before spread; at 90¢ it's 1.26¢.
- Minimum tick: **$0.01**.
- The order response returns `average_fee_paid` — the API tells you the real
  fee per fill. **Log it and reconcile; don't trust the formula blindly.**

### Worked examples (taker, quadratic, multiplier 1)

| Order | Raw | Fee charged |
|---|---|---|
| 4 contracts @ 50¢ | 0.07×4×0.25 = $0.07 | **$0.07** |
| 4 contracts @ 80¢ | 0.07×4×0.16 = $0.0448 | **$0.05** |
| 4 contracts @ 10¢ | 0.07×4×0.09 = $0.0252 | **$0.03** |
| 100 contracts @ 50¢ | 0.07×100×0.25 = $1.75 | **$1.75** |
| 100 contracts @ 50¢, INX* | 0.035×100×0.25 = $0.875 | **$0.88** |
| 4 contracts @ 50¢ resting fill, NBA | 0.0175×4×0.25 = $0.0175 | **$0.02** |

**What this means for the 15¢ edge bar:** a taker entry at 50¢ costs ~1.75¢/contract;
a round trip (enter + exit) ~3.5¢. The 15¢ bar clears that comfortably for
takers. For **maker** entries on `quadratic_with_maker_fees` series the fee is
smaller (~0.44¢/100 at 50¢) but nonzero — the old "resting orders are free"
assumption is **wrong on sports**.

---

## 5. API capabilities

Base URLs: `https://api.elections.kalshi.com/trade-api/v2` (what we use;
also `https://external-api.kalshi.com/trade-api/v2`). Demo:
`demo-api.kalshi.co` / `external-api.demo.kalshi.co`. Demo creds ≠ prod creds.

Auth: RSA-PSS (MGF1-SHA256, salt len = digest len) over
`{timestamp_ms}{METHOD}{/trade-api/v2/path, NO query string}`.
Headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`,
`KALSHI-ACCESS-SIGNATURE`.

### Order entry — POST /portfolio/events/orders (v2, single-book)

- Legacy `POST /portfolio/orders` is **deprecated (HTTP 410)**. v1 cancel is gone.
- **Single-book, YES-perspective:** `side` is `bid` (buy YES) or `ask`
  (sell YES). Buying NO at price p = `ask` at YES-price (1−p).
  Selling NO at p = `bid` at (1−p).
- Prices are **fixed-point dollar strings** (`"0.5600"`), counts are
  **fixed-point strings** (`"10.00"`). Never floats on the wire.
- **Required:** `ticker`, `side`, `count`, `price`, `time_in_force`,
  `self_trade_prevention_type`. (The 400 we hit was the missing STP field.)
- **Time-in-force:** `fill_or_kill`, `good_till_canceled`,
  `immediate_or_cancel`. **No native GTT value** — GTC + `expiration_time`
  (unix seconds) = good-till-time. IOC can't combine with `expiration_time`.
- **Self-trade prevention:** `taker_at_cross` (cancels the *taker* order on a
  self-cross; partial fills already matched still execute) or `maker`
  (cancels the *resting* order, keeps matching).
- Useful flags: `post_only` (maker-only; rejects if it would take),
  `reduce_only` (caps fill at current position size — the safe exit flag),
  `cancel_order_on_pause` (auto-cancel if the exchange pauses),
  `client_order_id` (idempotency key — **server rejects duplicates**, use
  UUIDs; resubmitting the same id is safe), `buy_max_cost` (cents; forces
  FoK behavior), `order_group_id`, `subaccount`, `exchange_index`.
- Response: `order_id`, `fill_count`, `remaining_count`,
  `average_fill_price`, `average_fee_paid`, `ts_ms`. **Partial fills are
  normal** — `fill_count`/`remaining_count` tell you what happened.
- **Batch:** `POST /portfolio/events/orders/batched` — 10 tokens per order
  in the batch (billed per item). Response nests `{"orders": [{"order": …}]}`.
- **Amend** (`POST …/orders/{id}/amend`): price and/or count. **Queue
  position is preserved ONLY when the amendment decreases size** — any price
  change or size increase sends you to the back of the queue.
- **Decrease** (`POST …/orders/{id}/decrease`): `reduce_by` or `reduce_to`
  (exactly one).
- **Cancel one:** `DELETE /portfolio/events/orders/{order_id}` (2 tokens).
  **Cancel all resting:** `DELETE /portfolio/events/orders` (2 tokens).
- **Queue position:** `GET /portfolio/orders/queue_positions` and
  `/portfolio/orders/{order_id}/queue_position`.

### Reading state

- `GET /portfolio/balance` (cents), `/portfolio/positions`,
  `/portfolio/fills`, `/portfolio/settlements`, `/portfolio/orders`
  (filter `status`: resting/canceled/executed), `/portfolio/orders/{id}`,
  `/portfolio/summary/total_resting_order_value`.
- Public (no auth): `/markets`, `/markets/{ticker}`,
  `/markets/{ticker}/orderbook` (yes/no bid+ask `[price, qty]` arrays;
  `orderbook_fp` fixed-point variant), `/markets/candlesticks`,
  `/markets/trades`, `/events`, `/events/{ticker}?with_nested_markets=true`,
  `/series`, `/series/{ticker}`, `/exchange/status`,
  `/account/endpoint_costs`.
- **WebSocket:** `wss://api.elections.kalshi.com/trade-api/ws/v2`
  (recommended: `wss://external-api-ws.kalshi.com/trade-api/ws/v2`).
  **Auth required even for public data** (signed handshake). 13 channels;
  `{"id","cmd","params"}` envelope; `subscribe`/`unsubscribe`. We don't use
  it yet — REST polling only.

### Exchange shards — balance is PER-SHARD, not portfolio-wide

Kalshi shards its exchange (observed live since ~2026-08-14; balance reads
scoped by `exchange_index` since 2026-08-13). **Every market clears on exactly
one shard** — the market payload field `exchange_index` (int). An order's
collateral (cost + fee) is checked **only against that shard's balance**.
The aggregate `balance` field is NOT spendable cross-shard: sizing or
balance-checking against it alone produces `400 insufficient_balance` on
every order whose market sits on an unfunded shard.

Observed shard map (2026-09, may migrate — always read the market field):
shard 0 = default/econ (CPI, Fed), 1 = combos/MVE, 2 = crypto, 3 = sports
(tennis/baseball seen; our weather settlement also landed here).

`GET /portfolio/balance` returns `balance_breakdown: [{exchange_index,
balance}, ...]`. **UNIT TRAP:** inside the breakdown, `balance` is a
fixed-point DOLLAR string (`'5.6700'`); the top-level `balance` is integer
CENTS. Same field name, different units. Floor dollar strings to cents —
never round up (an overstated shard = a guaranteed rejection).

Moving collateral between shards (same account, no deposit/withdrawal):
`POST /portfolio/intra_exchange_instance_transfer`
```json
{"source": "event_contract", "destination": "event_contract",
 "amount": 20000,
 "source_exchange_shard": 3, "destination_exchange_shard": 0}
```
`amount` is in CENTICENTS (1/100¢): $2.00 = 20,000. The endpoint is NOT
idempotent — single-shot, never auto-retry (a retried ambiguous failure
moves the money twice). Settlement is async: acceptance ≠ arrival; re-read
per-shard balances to confirm before ordering.

### Rate limits (token bucket)

- Tiers: Basic 20 read / 10 write per sec (auto on signup) → Advanced 30/30
  → Premier 100/100 → Prime 400/400. Most requests cost 10 tokens; cancels
  2; batch 10 per order.
- **A 429 is a hard stop** — back off, don't retry-loop.
- Order groups (`/portfolio/order_groups/*`) are **rolling 15-second
  contract-count limiters**, not OCO/conditional orders. Don't confuse them
  with combo machinery.

---

## 6. Combos — how to trade them

1. **Listed combos** are ordinary binary markets (conjunction rules). Price
   them against the legs: fair(combo YES) ≈ Π fair(leg_i YES) for independent
   legs, with a **correlation haircut** when legs aren't independent
   (same-event combos like Fed decision × dissents are correlated — never
   use the raw product).
2. **Synthetic combos** (build your own): N separate orders. No atomicity —
   design for partial fills: place legs near-simultaneously, monitor
   `fill_count`, and cancel/reduce unfilled legs if any leg fails. Fees hit
   per leg. Only build where each leg has real resting depth.
3. Fee note: `quadratic_with_combo_maker_fees` exists as a fee type — check
   the series before assuming maker treatment on combos.

---

## 7. Perps API — current state

**There is no public perps API.** The v3.31.0 spec has no perp endpoints;
perps don't appear in `/events`. Institutional paths (FIX, FCM subtrader
sessions, margin WS) exist but are not retail-accessible. Track
`docs.kalshi.com` for a perps API launch; until then, perps = manual only,
and perps margin is fully segregated from the predictions balance anyway.

---

## 8. Traps & gotchas (bot-killers)

0. **Shard-scoped balance (broke ALL our orders 2026-09-24).** Aggregate
   `$5.70` with `$0.00` on the market's shard = `400 insufficient_balance`
   on every order. Always pre-flight cost+fee against the MARKET's shard
   (see §5 "Exchange shards"). Never size purely off the aggregate.
1. **Stale `last_price`.** `last_price_dollars` can be hours old on thin
   books (observed: DOGE bracket showing last 78¢ vs live 55/66 book). **Never
   price off last — always read live bid/ask.**
2. **Dead asks.** Missing/null `yes_ask_dollars` is common on thin brackets.
   Treat a missing ask as 1.00 (unbuyable); never sum or average across NaNs.
3. **Non-exhaustive brackets.** Some "bracket" series don't partition the
   space (candidate lists, far-dated markets). Bucket-sum ≈ 1.00 only holds
   for mutually-exclusive exhaustive sets — verify `mutually_exclusive` and
   don't run the sum check on ladders.
4. **Ladder ≠ bracket.** `-T` suffix appears on both. Shape comes from the
   series, not the suffix.
5. **STP is required.** Omitting `self_trade_prevention_type` = HTTP 400.
   `taker_at_cross` cancels your taker order on self-cross (partials keep
   their fills); `maker` kills your resting order instead.
6. **GTC is forever.** Our orders rest until canceled or the market closes.
   Stale GTC orders can fill after the edge is gone — **stale-order
   cancellation is mandatory before scaling** (cancel-all endpoint exists,
   2 tokens).
7. **No GTT value** — use GTC + `expiration_time` for time-boxed orders.
8. **Partial fills are the norm.** Always read `fill_count`/`remaining_count`;
   never assume all-or-nothing (unless FoK).
9. **Amend forfeits queue** unless strictly decreasing size.
10. **Maker fees on sports.** `quadratic_with_maker_fees` (NBA etc.) —
    resting orders pay ~¼ the taker fee. "Maker is free" is false there.
11. **Fee ceil is per order, round-up.** Small orders overpay proportionally;
    the 10% fee buffer we use is crude — per-series exact math (§4) is better.
12. **TIF on the wire vs intent.** We send GTC; for short-fuse edges
    (15-min crypto) IOC/FoK or GTC+`expiration_time` is safer.
13. **API hosts:** `api.elections.kalshi.com` works for everything despite the
    name; `external-api.kalshi.com` is the recommended host. Demo creds don't
    work on prod.
14. **Signing:** path includes `/trade-api/v2`, **query string excluded**,
    timestamp in ms. Both were live bugs we already fixed — don't regress.
15. **`average_fee_paid` exists** — reconcile real fees, don't just model them.
16. **Perps are a separate universe** — separate account, separate (non-public)
    API. Nothing in the trade API touches them.
17. **Exchange pauses:** `cancel_order_on_pause` exists for a reason — news
    events can pause trading with your orders resting.
18. **`reduce_only`** is the safe exit flag — use it for closes so a close
    order can never flip you into a reverse position.
19. **Selling NO on all bracket candidates is NOT an arb** — payout is n−1 or
    n depending on whether the winner is a listed candidate. (Caught by the
    sweep team; documented so nobody re-discovers it with money.)
20. **Position limits** (`risk_limit_cents`) may apply per market — check
    before sizing up.

---

## 9. What we're doing wrong / could do better (action items)

1. **[HIGH] Stale GTC orders.** We place GTC with no `expiration_time` and no
   cancellation sweep. Fix: send `expiration_time` on every order (or use
   IOC/FoK for taker entries) + a cancel-stale pass each run.
2. **[HIGH] Fee model is a flat 10% buffer.** We now know exact per-series
   math (§4) including maker-fee series and half-rate index markets. Replace
   the buffer with `fee_type`+`fee_multiplier` looked up per series.
3. **[MED] No `reduce_only` on exits.** Close orders should set it.
4. **[MED] No `client_order_id`.** We risk double-orders on retries/network
   hiccups. Send UUIDs; the server dedupes.
5. **[MED] No `post_only` discipline.** If an entry is meant to be a maker
   order, set `post_only: true` so it can't accidentally take at a bad price.
6. **[MED] Taker entries should prefer IOC/FoK** over GTC for short-fuse
   edges — a resting taker-intent order is just a stale-order accident
   waiting to happen.
7. **[LOW] Amend instead of cancel/replace** when adjusting resting orders
   downward — preserves queue position.
8. **[LOW] REST polling only.** WebSocket exists (auth required) for live
   books/fills — worth it when volume justifies the complexity.
9. **[INFO] Perps automation is blocked** on Kalshi publishing a perps API.
   Don't build perps execution on the trade API — there is nothing to build on.
10. **[INFO] Scalar markets don't exist in practice** — don't write code paths
    for them beyond the enum.

---

*Last verified: 2026-09-24. Re-verify fee schedule + spec version quarterly;
Kalshi revises both.*
