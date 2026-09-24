#!/usr/bin/env python3
"""Kalshi auto-trader.

Pipeline:
  edge_scan.py (subprocess, untouched) -> parse EDGE lines ->
  atomic re-verify (fresh spot + live book, scanner vol assumptions) ->
  risk gates -> place order via trade_client.py.

AUTO-TRADE RULES (plain-English version in RISK.md):
  * Fire only on re-verified edge >= 10c ("insane" edges; 12c was the manual-relay bar)
  * Risk per trade: half-Kelly stake from the model's win probability for the
    side bought (f* = p - (1-p)/b, b = payout odds on the ALL-IN cost incl.
    exact taker fees), hard-capped at $2.00;
    contracts = floor(stake / all-in ask), >= 1
  * Portfolio caps (restored/added 2026-09-24): max $10 committed in play
    across all open trades + resting orders; max $5 per event series;
    max $3 and max 5 trades per single event/expiry bucket. Correlated
    hourly-index stacks like the 2026-09-24 13-trade loss can never recur.
  * Combos: each leg sized by its own half-Kelly (legs are separate binary
    contracts, each +EV standalone); the combo takes the min across legs,
    hard-capped at $2.00 total cost. No joint probability is invented.
  * Daily stop-loss: halt if today's realized P&L <= -$3.00
  * Settlement accounting is official-data-only: settle_check() books P&L
    from the exchange's fill history (fill price, fees, quantities), never
    from local "placed" logs. A placed trade with zero official fills is
    voided, not booked. Realized P&L is NET of official fees.
  * 50-trade tripwire: 50+ settled trades with total realized P&L <= $0
    halts LIVE trading (paper mode) until models are repaired -- enforced
    in code by tripwire_check(), not just a doc note
  * No daily trade-count cap (Jeremiah lifted it 2026-09-24: "you can enter as
    much as you want"); per-trade size cap and daily stop-loss still bind
  * Only markets closing in >= 10 minutes
  * Never deposits / withdraws outside money -- buy orders only; skip if balance short
  * Standing delegation (Jeremiah 2026-09-24): INTRA-Kalshi shard collateral
    transfers auto-execute under caps (per-transfer $2.00, daily $6.00) when a
    verified candidate's shard is short; never deposits/withdraws
  * DRY_RUN on by default; --live to actually send orders

Logs:
  ~/workspace/kalshi/hidden_files/trade_log.jsonl  -- every decision
  ~/workspace/kalshi/hidden_files/daily_pnl.json   -- realized P&L by trade date
"""
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HIDDEN = os.path.join(HERE, 'hidden_files')
os.makedirs(HIDDEN, exist_ok=True)
TRADE_LOG = os.path.join(HIDDEN, 'trade_log.jsonl')
PNL_PATH = os.path.join(HIDDEN, 'daily_pnl.json')

import trade_client  # noqa: E402  (needs DRY_RUN toggle below)
import combo as combo_math  # noqa: E402  (synthetic combo construction math)
import fees as fee_math  # noqa: E402  (exact per-series fee math, PLATFORM.md §4)

# ---------------- risk config ----------------
EDGE_BAR = 0.10              # re-verified edge must clear 10c (Jeremiah authorized thinner edges 2026-09-24)
MAX_RISK_DOLLARS = 2.00      # hard cap per trade (singles and combos)
STOP_LOSS_CENTS = -300       # halt the day at -$3.00 realized
TRIPWIRE_MIN_SETTLED = 50    # 50-trade tripwire: 50+ settled trades with total
                             # realized P&L <= $0 halts LIVE trading (paper only)
                             # until the models are repaired. Enforced in code
                             # by tripwire_check(); see RISK.md.
# ---- portfolio-level risk caps (restored/added 2026-09-24 after the
# 13-trade hourly-index stack lost ~$13 in one expiry window) ----
MAX_IN_PLAY_CENTS = 1000       # original "$10 in play" rule, restored:
                               # total committed notional across all open
                               # trades + resting orders may never exceed $10.
                               # It was never canceled; the code just stopped
                               # enforcing it. Enforced again in Phase B.
MAX_COMMIT_PER_SERIES_CENTS = 500  # correlated-risk cap per event series
                               # (e.g. all KXINXU positions combined).
MAX_COMMIT_PER_EVENT_CENTS = 300   # correlated-risk cap per single event /
                               # expiry bucket (e.g. KXINXU-26SEP24H1000).
                               # One correlated bucket can never single-
                               # handedly blow the -$3 daily stop.
MAX_TRADES_PER_EVENT = 5       # max open trades sharing one event bucket.
MAX_CONSEC_REJECTS = 3         # circuit breaker: abort the run after this
                               # many consecutive exchange order rejections
                               # (2026-09-24: 18 doomed insufficient_balance
                               # attempts fired in ~9s with no backstop).
# MAX_TRADES_PER_DAY removed 2026-09-24: Jeremiah lifted the count cap
# ("you can enter as much as you want"). Per-trade size + stop-loss bind.
MIN_MINUTES_TO_CLOSE = 10
FEE_SLACK_CENTS = 1          # +1c over the exact fee in the balance check
                             # (per-fill micro-ceiling gotcha, PLATFORM.md §4)
ENTRY_MAX_REST_HOURS = 24    # GTC expiration backstop: min(close, now+24h).
                             # The cancel-stale pass (5-min cadence) is the real
                             # mechanism; expiration is the hard backstop.
STALE_LIMIT_MIN = {          # resting-order age limits by market kind
    'crypto15m': 10, 'cryptodaily': 60, 'index': 60,
}
STALE_DEFAULT_MIN = 120      # everything else: 2h

# Sprint ranking (Jeremiah 2026-09-24): same-day goal to recover the $5.27
# committed to CPI positions (settle ~Oct 14) from the ~$9.60 liquid
# bankroll by end of tonight, Thu Sep 24. This is an ORDERING preference only --
# never a filter, never a gate. Among candidates that pass every gate,
# rank by (net edge per unit + sprint bonus). The bonus is deliberately
# small so edge still dominates: a 30c edge settling in 10 days outranks
# a 16c edge settling in 2 days (30 > 19), while 16c/2-day beats
# 17c/10-day (19 > 17) -- i.e. "close in edge" means within 3c.
SPRINT_HOURS = 72             # settle within 3 days => realized P&L lands
                              # inside the sprint window
SPRINT_BONUS_CENTS = 3.0      # ranking bonus, added to net edge per unit


def sprint_bonus_cents(hours_left):
    """Sprint ranking bonus in cents: +SPRINT_BONUS_CENTS iff the position
    settles within SPRINT_HOURS. Unknown horizon => no bonus (fail-open
    toward no preference, never toward a penalty)."""
    try:
        h = float(hours_left)
    except (TypeError, ValueError):
        return 0.0
    return float(SPRINT_BONUS_CENTS) if h <= SPRINT_HOURS else 0.0

# Scanner vol assumptions, mirrored from edge_scan.py (do not drift from it)
CRYPTO_VOL = {  # coin: (15-min vol, hourly vol)
    'BTC': (0.0011, 0.0035),
    'ETH': (0.0013, 0.0040),
    'SOL': (0.0018, 0.0055),
}
INDEX_YAHOO = {
    'GOLD': 'GC=F', 'SPX': '%5EGSPC', 'NDX': '%5ENDX',
    'WTI': 'CL=F', 'SILVER': 'SI=F',
}


# ---------------- small helpers ----------------
def today_str():
    """Desk calendar day — America/Chicago (Jeremiah's day), not UTC.
    The daily stop, ledger attribution, and log dates all key to this
    (2026-09-24 auditor finding: day boundary used UTC, not Chicago)."""
    return _chicago_today()  # defined below; resolved at call time


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def log_event(**kw):
    kw['ts'] = now_iso()
    kw.setdefault('date', today_str())
    with open(TRADE_LOG, 'a') as f:
        f.write(json.dumps(kw) + '\n')


def load_pnl():
    try:
        return json.load(open(PNL_PATH))
    except Exception:
        return {}


def save_pnl(d):
    json.dump(d, open(PNL_PATH, 'w'), indent=1)


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


_rvol_cache = {}


def crypto_realized(sym):
    """Trailing-30m realized hourly vol + drift, same math as edge_scan.py."""
    if sym in _rvol_cache:
        return _rvol_cache[sym]
    v, drift = None, None
    try:
        d = _get(f'https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=60')
        closes = [c[4] for c in d if c and c[4]][:31]
        if len(closes) >= 12:
            rets = [math.log(closes[i] / closes[i + 1]) for i in range(len(closes) - 1)]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            v = math.sqrt(var) * math.sqrt(60)
            drift = math.log(closes[0] / closes[-1])
    except Exception:
        v, drift = None, None
    _rvol_cache[sym] = (v, drift)
    return v, drift


def yahoo_spot_vol(ysym):
    """(hourly vol, spot) from Yahoo 1m bars, same math + staleness guard as edge_scan.py."""
    try:
        d = _get(f'https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1m&range=2h')
        res = d['chart']['result'][0]
        closes = [c for c in res['indicators']['quote'][0]['close'] if c]
        ts = res.get('timestamp', [])
        if not ts or not closes or len(closes) < 20:
            return None, None
        last_ts = datetime.datetime.fromtimestamp(ts[-1], datetime.timezone.utc)
        if (datetime.datetime.now(datetime.timezone.utc) - last_ts).total_seconds() > 300:
            return None, None
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        return max(math.sqrt(var) * math.sqrt(60), 0.0005), closes[-1]
    except Exception:
        return None, None


# ---------------- portfolio risk accounting ----------------
def _event_bucket(ticker):
    """Correlated-risk bucket: series + event/expiry code.
    'KXINXU-26SEP24H1000-T7669.9999' -> 'KXINXU-26SEP24H1000'.
    Trades sharing a bucket settle on the same underlying at the same
    time — they are one correlated bet, not N independent ones."""
    parts = (ticker or '').split('-')
    return '-'.join(parts[:2]) if len(parts) >= 2 else (ticker or '')


def open_exposure():
    """Committed notional (cents) currently in play, from the local log.

    Counts filled cost (contracts x price_cents) of every placed/placed_leg
    trade with no settle/void outcome yet. Uses the REQUESTED contracts, not
    the self-reported fill_count: over-counting is fail-closed for a cap,
    and local fill_count proved untrustworthy on 2026-09-24 (the phantom
    T7669.9999 logged fill_count=4 on zero official fills).

    Returns dict(total_c, by_series, by_event, count_by_event)."""
    closed = set()
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                tid = e.get('trade_id')
                if not tid:
                    continue
                a = e.get('action')
                if (a == 'settle' and 'pnl_cents' in e) or a == 'settle_void':
                    closed.add(tid)
    except FileNotFoundError:
        return {'total_c': 0, 'by_series': {}, 'by_event': {},
                'count_by_event': {}}
    total, by_series, by_event, cnt = 0, {}, {}, {}
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get('action') not in ('placed', 'placed_leg'):
                    continue
                if e.get('kind') == 'combo':
                    continue  # combo-level entry is accounting only; legs count
                tid = e.get('trade_id')
                if not tid or tid in closed:
                    continue
                try:
                    cost = int(e.get('contracts') or 0) * \
                        int(e.get('price_cents') or 0)
                except (TypeError, ValueError):
                    continue
                if cost <= 0:
                    continue
                t = e.get('ticker') or ''
                s, ev = fee_math.series_of(t), _event_bucket(t)
                total += cost
                by_series[s] = by_series.get(s, 0) + cost
                by_event[ev] = by_event.get(ev, 0) + cost
                cnt[ev] = cnt.get(ev, 0) + 1
    except FileNotFoundError:
        pass
    return {'total_c': total, 'by_series': by_series, 'by_event': by_event,
            'count_by_event': cnt}


def _resting_order_cost(o):
    """Committed collateral of one resting order, in cents, from the
    official order record: remaining contracts x the OUTCOME-side price
    (no_price_dollars when we hold NO, yes_price_dollars when YES)."""
    try:
        rem = float(o.get('remaining_count_fp') or 0)
    except (TypeError, ValueError):
        return 0
    if rem <= 0:
        return 0
    px_key = ('no_price_dollars' if o.get('outcome_side') == 'no'
              else 'yes_price_dollars')
    try:
        px = float(o.get(px_key) or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(rem * px * 100))


def add_resting_exposure(xp):
    """Fold currently-resting official orders into the exposure tracker.
    One read-only API call; fail-open (a fetch failure just skips this)."""
    try:
        orders = trade_client.list_orders('resting').get('orders', [])
    except Exception:
        return xp
    for o in orders:
        cost = _resting_order_cost(o)
        if cost <= 0:
            continue
        t = o.get('ticker') or ''
        s, ev = fee_math.series_of(t), _event_bucket(t)
        xp['total_c'] += cost
        xp['by_series'][s] = xp['by_series'].get(s, 0) + cost
        xp['by_event'][ev] = xp['by_event'].get(ev, 0) + cost
        xp['count_by_event'][ev] = xp['count_by_event'].get(ev, 0) + 1
    return xp


def exposure_fits(xp, legs):
    """Check one candidate against every portfolio cap.
    legs = [(ticker, cost_cents), ...] — singles pass one pair; combos pass
    one per leg so multi-series combos charge each series correctly.
    Returns (ok, reason)."""
    total_add = sum(c for _, c in legs)
    if xp['total_c'] + total_add > MAX_IN_PLAY_CENTS:
        return (False,
                f'$10 in-play cap: have ${xp["total_c"] / 100:.2f}, '
                f'adding ${total_add / 100:.2f} would exceed '
                f'${MAX_IN_PLAY_CENTS / 100:.2f}')
    seen_series, seen_event = {}, {}
    for t, c in legs:
        s, ev = fee_math.series_of(t), _event_bucket(t)
        seen_series[s] = seen_series.get(s, 0) + c
        seen_event[ev] = seen_event.get(ev, 0) + c
    for s, add in seen_series.items():
        if xp['by_series'].get(s, 0) + add > MAX_COMMIT_PER_SERIES_CENTS:
            return (False,
                    f'per-series cap (${MAX_COMMIT_PER_SERIES_CENTS / 100:.2f}) '
                    f'on {s}: have ${xp["by_series"].get(s, 0) / 100:.2f}, '
                    f'adding ${add / 100:.2f} refused')
    for ev, add in seen_event.items():
        if xp['by_event'].get(ev, 0) + add > MAX_COMMIT_PER_EVENT_CENTS:
            return (False,
                    f'per-event cap (${MAX_COMMIT_PER_EVENT_CENTS / 100:.2f}) '
                    f'on {ev}: have ${xp["by_event"].get(ev, 0) / 100:.2f}, '
                    f'adding ${add / 100:.2f} refused')
        if xp['count_by_event'].get(ev, 0) + 1 > MAX_TRADES_PER_EVENT:
            return (False,
                    f'max {MAX_TRADES_PER_EVENT} trades per event bucket '
                    f'({ev})')
    return (True, '')


def charge_exposure(xp, legs):
    """Record a placement against the exposure tracker: legs =
    [(ticker, cost_cents), ...]. Phase B runs in rank order, so later
    candidates see earlier placements' commitment."""
    for t, c in legs:
        xp['total_c'] += c
        s, ev = fee_math.series_of(t), _event_bucket(t)
        xp['by_series'][s] = xp['by_series'].get(s, 0) + c
        xp['by_event'][ev] = xp['by_event'].get(ev, 0) + c
        xp['count_by_event'][ev] = xp['count_by_event'].get(ev, 0) + 1
    return xp


def settled_trades():
    """CANONICAL settled-trade accounting — the single count every guard
    and report must use.

    n = unique trade_ids with a booked outcome (action='settle' with
    pnl_cents), excluding voided trades (action='settle_void').
    realized_cents = sum of booked pnl + sum of settle_adjust deltas.

    Resolves the 2026-09-24 count conflict: '13 daily / ~35 account-wide'
    came from counting placed(16)+settle(13)+dry_run(6)=35 log EVENTS as
    settlements. Only booked outcomes are settlements: 12 real index
    trades on 2026-09-24 (the 13th was a phantom with zero official fills,
    voided)."""
    n_by_id, pnl = {}, 0
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                tid = e.get('trade_id')
                if not tid:
                    continue
                a = e.get('action')
                if a == 'settle' and 'pnl_cents' in e:
                    try:
                        n_by_id[tid] = int(e['pnl_cents'])
                    except (TypeError, ValueError):
                        pass
                elif a == 'settle_void':
                    n_by_id.pop(tid, None)
                elif a == 'settle_adjust':
                    try:
                        pnl += int(e.get('adjustment_cents', 0))
                    except (TypeError, ValueError):
                        pass
    except FileNotFoundError:
        return (0, 0)
    return (len(n_by_id), sum(n_by_id.values()) + pnl)


# ---------------- settlement / P&L ----------------
def _fill_cashflows(fills, entry_order_id):
    """Split official fills for one ticker into entry vs exit cashflows.

    Entry = fills on our entry order (order_id match). Exit = fills on the
    same ticker/outcome side from any other order (reduce_only closes).
    Returns (entry_qty, entry_cost_c, entry_fee_c, exit_qty, exit_proceeds_c,
    exit_fee_c). Prices come from the fill's OUTCOME-side price
    (no_price_dollars when side='no'), never from local logs.

    2026-09-24 lesson: local 'placed' records are claims, not facts. An
    order can be accepted, rest 36s, get canceled with ZERO fills (the
    T7669.9999 phantom), and the old code still booked a full loss on it.
    Settlement now books only what the exchange's fill history proves."""
    entry_qty = exit_qty = 0.0
    entry_cost = entry_fee = exit_proceeds = exit_fee = 0.0
    for f in fills:
        try:
            c = float(f.get('count_fp') or 0)
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        side = f.get('side')
        px_key = 'no_price_dollars' if side == 'no' else 'yes_price_dollars'
        try:
            px = float(f.get(px_key) or 0)
        except (TypeError, ValueError):
            px = 0.0
        try:
            fee = float(f.get('fee_cost') or 0)
        except (TypeError, ValueError):
            fee = 0.0
        if entry_order_id and f.get('order_id') == entry_order_id:
            entry_qty += c
            entry_cost += c * px * 100
            entry_fee += fee * 100
        else:
            # Any other fill on this ticker/side is an exit (we only ever
            # buy entries; exits are reduce_only closes).
            exit_qty += c
            exit_proceeds += c * px * 100
            exit_fee += fee * 100
    return (entry_qty, entry_cost, entry_fee, exit_qty, exit_proceeds,
            exit_fee)


def settle_check():
    """Book P&L for placed trades whose market settled — from OFFICIAL
    exchange data only.

    For each placed trade with no outcome yet: fetch the market; when it is
    settled/finalized with a yes/no result, pull the official fill history
    for the ticker and book realized P&L as
        exit_proceeds + settlement_proceeds - entry_cost - official_fees
    where settlement_proceeds covers only contracts still held at
    settlement. A placed trade with ZERO official fills is logged as
    phantom_unfilled and booked at $0 — never from the local record.

    Net of official fees (convention changed 2026-09-24: the books now
    match the exchange to the cent; the old gross-of-fees convention hid
    the fee drag the phantom incident exposed)."""
    entries = []
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    entries.append(json.loads(ln))
                except Exception:
                    pass
    except FileNotFoundError:
        return 0
    done_ids = {e['trade_id'] for e in entries
                if e.get('trade_id') and (
                    (e.get('action') == 'settle' and 'pnl_cents' in e) or
                    e.get('action') == 'settle_void')}
    pnl = load_pnl()
    dirty = False
    new_settled = 0
    for e in entries:
        # Singles log action='placed'; combo legs log action='placed_leg'.
        # The combo-level 'placed' entry (kind='combo') is accounting only —
        # its legs settle individually.
        if e.get('action') not in ('placed', 'placed_leg') or not e.get('trade_id'):
            continue
        if e.get('kind') == 'combo':
            continue
        if e['trade_id'] in done_ids:
            continue
        tid, ticker = e['trade_id'], e['ticker']
        try:
            m = trade_client.get_market(ticker)
        except Exception as ex:
            log_event(action='settle', trade_id=tid, ticker=ticker,
                      status='fetch_failed', reason=str(ex)[:120])
            continue
        # Kalshi moves markets open -> closed -> settled -> finalized quickly;
        # by the time a 2-min worker polls, many are already 'finalized'.
        # A determined result is a determined result: book on either.
        if m.get('status') not in ('settled', 'finalized'):
            continue
        result = m.get('result')  # 'yes' / 'no'
        if result not in ('yes', 'no'):
            continue
        # Official fills decide everything from here. Fail closed: if the
        # fills API is unreachable, book nothing this run.
        try:
            fills = trade_client.get_fills(ticker=ticker)
        except Exception as ex:
            log_event(action='settle', trade_id=tid, ticker=ticker,
                      status='fills_fetch_failed', reason=str(ex)[:120])
            continue
        (entry_qty, entry_cost, entry_fee, exit_qty, exit_proceeds,
         exit_fee) = _fill_cashflows(fills, e.get('order_id'))
        entry_qty = int(round(entry_qty))
        exit_qty = int(round(exit_qty))
        if entry_qty <= 0:
            # The exchange has no record of us ever holding this: the
            # 2026-09-24 phantom shape (accepted then canceled, 0 fills).
            # Book $0 and void the trade so it never counts as settled.
            log_event(action='settle_void', trade_id=tid, ticker=ticker,
                      date=e.get('date', today_str()), side=e.get('side'),
                      price_cents=e.get('price_cents'),
                      contracts=e.get('contracts'),
                      official_fills=0,
                      reason='phantom: zero official fills on entry order; '
                             'no position ever existed; booked $0')
            print(f'  settle VOID {ticker}: zero official fills (phantom)')
            done_ids.add(tid)
            continue
        held = max(entry_qty - exit_qty, 0)
        won = (result == 'yes') == ((e.get('side') or '').lower() == 'yes')
        settle_proceeds = held * (100 if won else 0)
        pnl_c = int(round(exit_proceeds + settle_proceeds
                          - entry_cost - entry_fee - exit_fee))
        day = e.get('date', today_str())
        d = pnl.setdefault(day, {'realized_cents': 0, 'trades_settled': 0})
        d['realized_cents'] += pnl_c
        d['trades_settled'] += 1
        dirty = True
        new_settled += 1
        log_event(action='settle', trade_id=tid, ticker=ticker, date=day,
                  side=e['side'], result=result,
                  official_entry_qty=entry_qty,
                  official_avg_price_cents=round(entry_cost / entry_qty, 2),
                  official_entry_fee_cents=round(entry_fee, 2),
                  official_exit_qty=exit_qty,
                  official_exit_proceeds_cents=round(exit_proceeds, 2),
                  official_exit_fee_cents=round(exit_fee, 2),
                  contracts_held_at_settle=held,
                  pnl_cents=pnl_c, source='official_fills')
        done_ids.add(tid)
    if dirty:
        save_pnl(pnl)
    return new_settled


def tripwire_check():
    """50-trade tripwire (RISK.md standing rule, enforced in code 2026-09-24).

    Counts via settled_trades() — the ONE canonical count: unique trade_ids
    with a booked outcome, voided trades excluded, adjustments included.
    Returns (tripped, n_settled, pnl_cents). Trips when 50+ trades have
    settled and their total realized P&L (net of official fees since
    2026-09-24) is <= $0 -- the models are not beating the market, so live
    trading halts until they are repaired.
    """
    n, pnl = settled_trades()
    return (n >= TRIPWIRE_MIN_SETTLED and pnl <= 0, n, pnl)


def count_placed_today():
    day = today_str()
    n = 0
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get('action') == 'placed' and e.get('date') == day:
                    n += 1
    except FileNotFoundError:
        pass
    return n


# ---------------- scan ----------------
def run_scan():
    # NOTE 2026-09-24: timeout raised 180 -> 270. The scan now sweeps the full
    # ~14k-event board every run (~105s clean: ~50s dedicated models + ~55s
    # parallel sweep); the sweep self-caps at 100s so scan + re-verification
    # stays under the 300s cron period. On TimeoutExpired everything is still
    # discarded (partial stdout is unusable — an EDGE printed at 100s may have
    # a dead book by 270s).
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, 'edge_scan.py')],
                           capture_output=True, text=True, timeout=270)
    except subprocess.TimeoutExpired:
        print('scan timed out', file=sys.stderr)
        return []
    cands = []
    for line in (p.stdout or '').splitlines():
        if line.startswith('EDGE:'):
            c = parse_candidate(line[5:].strip())
            if c:
                cands.append(c)
            elif 'live bid sum' in line or 'bid sum=' in line or 'locks ' in line:
                log_event(action='skipped', reason='field/multi-leg flag: no single ticker, needs human review',
                          raw=line[5:128])
    return cands


CAND_RE = re.compile(
    # NOTE: side must DIRECTLY precede the ticker (\s+, no .*? between them).
    # This keeps two-leg arb lines (e.g. "buy ...-T4.00 YES @ 45c / sell ...-T4.25
    # YES @ 60c locks 15c") from misparsing as single-ticker candidates.
    # The third ticker alternative is the generic SWEEP form: any non-KX or
    # odd-suffix ticker (e.g. KXNEWPOPE-70-PPIZ, GOVPARTYAL-26-D). It only
    # matches when an asset tag + YES/NO directly precedes it, so existing
    # formats still hit their specific alternatives first.
    r'\b(BTC|ETH|SOL|GOLD|SPX|NDX|WTI|SILVER|POL|ECON|WX|SWEEP)\b.*?\b(YES|NO)\b\s+'
    r'(KX[A-Z0-9]+-[A-Za-z0-9.]+-(?:T|B)[\d.]+|SENATE[A-Z]{2}-26-[DR]|[A-Z][A-Z0-9]*-[A-Za-z0-9.\-]+)\b')


def parse_candidate(line):
    m = COMBO_RE.search(line)
    if m:
        return parse_combo_candidate(m)
    m = CAND_RE.search(line)
    if not m:
        return None
    asset, side, ticker = m.group(1), m.group(2).lower(), m.group(3)
    km = re.search(r'-T([\d.]+)$', ticker)
    strike = float(km.group(1)) if km else None  # politics tickers carry no strike
    return {'kind': 'single', 'asset': asset, 'side': side, 'ticker': ticker,
            'strike': strike, 'raw': line[:160]}


# ---------------- synthetic combos ----------------
# EDGE line shape (from edge_scan.py §9):
#   COMBO legs=YES|BTC|KXBTCD-26SEP17-T112000|42|58+NO|SPX|KXINX-26SEP17-T6500|30|45
#         edge_c=21 fee_c=4 net_c=17 maxpay_c=88 contracts=2 corr=decorr rule=take_if_net>=15c
# Leg spec: SIDE|ASSET|TICKER|pay_cents|fair_pct. pay = scan-time cents we'd pay.
COMBO_RE = re.compile(
    r'COMBO legs=(\S+)'
    r'\s+edge_c=(-?\d+)\s+fee_c=(\d+)\s+net_c=(-?\d+)\s+maxpay_c=(-?\d+)'
    r'\s+contracts=(\d+)\s+corr=(decorr|corr)\s+rule=(\S+)')


def parse_combo_candidate(m):
    legs = []
    for part in m.group(1).split('+'):
        part = part.strip()
        if not part:
            continue
        s = part.split('|')
        if len(s) != 5:
            return None
        side, asset, ticker, pay_c, fair_pct = s[0].lower(), s[1], s[2], s[3], s[4]
        if side not in ('yes', 'no'):
            return None
        try:
            pay_c, fair_pct = int(pay_c), int(fair_pct)
        except ValueError:
            return None
        km = re.search(r'-T([\d.]+)$', ticker)
        legs.append({'asset': asset, 'side': side, 'ticker': ticker,
                     'strike': float(km.group(1)) if km else None,
                     'scan_pay_c': pay_c, 'scan_fair': fair_pct / 100.0})
    if len(legs) < 2:
        return None
    return {'kind': 'combo', 'asset': 'COMBO', 'side': 'combo',
            'ticker': 'COMBO:' + '+'.join(l['ticker'] for l in legs),
            'strike': None, 'legs': legs, 'raw': m.group(0)[:200],
            'scan_edge_c': int(m.group(2)), 'scan_fee_c': int(m.group(3)),
            'scan_net_c': int(m.group(4)), 'scan_maxpay_c': int(m.group(5)),
            'scan_contracts': int(m.group(6)), 'scan_corr': m.group(7),
            'rule': m.group(8)}


def combo_shard_needs(legs_rvs, n):
    """Per-shard collateral need {shard: cents} for a verified combo, plus
    the first leg ticker with an unknown shard (None if all known). The
    exchange checks each leg's collateral ONLY against its own market's
    shard, so legs must be grouped by shard first. Shared by reverify_combo
    (Phase A) and place_combo_candidate (Phase B recheck)."""
    need_by_shard = {}
    bad = None
    for leg, rv in legs_rvs:
        s = rv.get('exchange_index')
        if s is None:
            bad = bad or leg['ticker']
            continue
        need_by_shard[s] = need_by_shard.get(s, 0) + n * rv['price_cents'] + \
            exact_fee_cents(n, rv['price_cents'], rv.get('fee_meta'))
    return need_by_shard, bad


def reverify_combo_shard_check(legs_rvs, n, shard_bal):
    """Phase-A shard pre-flight for a combo: fail closed with the transfer
    hint when any leg's shard cannot cover its collateral."""
    need_by_shard, bad = combo_shard_needs(legs_rvs, n)
    if bad:
        return {'ok': False,
                'reason': f"leg {bad}: unknown exchange shard"}
    for s, need in need_by_shard.items():
        have = shard_bal.get(s, 0)
        if need + FEE_SLACK_CENTS > have:
            xfer = plan_shard_transfer(shard_bal, s, need + FEE_SLACK_CENTS)
            hint = (f'; transfer plan: {xfer}' if xfer
                    else '; portfolio cannot cover even after transfers')
            return {'ok': False,
                    'reason': f'leg shard {s}: need ${need / 100:.2f}, '
                              f'have ${have / 100:.2f} — exchange would '
                              f'reject{hint}'}
    return {'ok': True}


def reverify_combo(cand, balance_c, shard_bal=None):
    """Re-verify every leg on a FRESH book + fresh fair value, then apply the
    combo take/pass rule. Each leg must still show >=5c edge (combo_math.
    LEG_MIN_VERIFY_C); the combo net (edges minus exact per-leg fees) must
    clear 15c (decorrelated) or 20c (any correlated pair)."""
    legs = cand.get('legs') or []
    if len(legs) < 2:
        return {'ok': False, 'reason': 'combo needs >=2 legs'}
    seen = set()
    for leg in legs:
        if leg['ticker'] in seen:
            return {'ok': False, 'reason': f"duplicate leg {leg['ticker']}"}
        seen.add(leg['ticker'])
    rvs = []
    for leg in legs:
        lc = {'kind': 'single', 'asset': leg['asset'], 'side': leg['side'],
              'ticker': leg['ticker'], 'strike': leg['strike']}
        rv = reverify(lc, edge_bar=combo_math.LEG_MIN_VERIFY_C / 100.0)
        if not rv['ok']:
            return {'ok': False, 'reason': f"leg {leg['ticker']}: {rv['reason']}"}
        rvs.append((leg, rv))
    assets = [l['asset'] for l in legs]
    corr = len(set(assets)) < len(assets)
    bar_c = combo_math.BAR_CORR_C if corr else combo_math.BAR_DECORR_C
    edge_c = sum(round(rv['edge'] * 100) for _, rv in rvs)
    total_price_c = sum(rv['price_cents'] for _, rv in rvs)
    if total_price_c <= 0:
        return {'ok': False, 'reason': 'bad combo pricing'}
    # Unified sizing (2026-09-24): a combo is a bundle of SEPARATE binary
    # contracts, each re-verified +EV standalone (>=5c/leg), so each leg gets
    # its own half-Kelly contract count and the combo takes the MINIMUM.
    # Why not Kelly on a "combined probability": the desk has no joint
    # distribution model, and Kelly punishes invented p's hardest exactly
    # when legs are correlated. Why the min: execution buys equal-size legs,
    # so no leg may exceed its own half-Kelly; simultaneous legs share one
    # bankroll, which makes the min conservative in the right direction
    # (true multi-bet Kelly <= sum of single-bet Kellys). The old flat
    # min($2, 35% of balance) is gone -- same flaw as singles (arbitrary at
    # large balances, overshoots Kelly at small ones). $2 hard cap on the
    # whole combo's cost is kept.
    leg_ns = []
    for leg, rv in rvs:
        side_l = (leg.get('side') or '').lower()
        p_win = rv['fair'] if side_l == 'yes' else 1.0 - rv['fair']
        leg_ns.append(size_contracts(balance_c, rv['price_cents'], p_win,
                                    rv.get('fee_meta')))
    n = min(leg_ns) if leg_ns else 0
    if total_price_c > 0:
        n = min(n, int(MAX_RISK_DOLLARS * 100) // total_price_c)
    # Depth gate: FOK needs the full size resting at the touch on every leg.
    try:
        min_depth = min(int(rv.get('size') or 0) for _, rv in rvs)
    except ValueError:
        min_depth = 0
    n = min(n, min_depth)
    if n < 1:
        return {'ok': False,
                'reason': f'cannot size >=1 unit (per-leg half-Kelly allows '
                          f'{leg_ns}, depth allows {min_depth})'}
    # Exact per-leg ORDER fees for n contracts (one order per leg), from the
    # series' fee_type — replaces the old flat 7%-per-contract estimate.
    leg_fee_c = [exact_fee_cents(n, rv['price_cents'], rv.get('fee_meta'))
                 for _, rv in rvs]
    fee_c = sum(leg_fee_c)
    net_c = edge_c * n - fee_c
    if net_c < bar_c * n:
        return {'ok': False,
                'reason': f'combo net {net_c / n:.1f}c/unit < {bar_c}c bar '
                          f'({"corr" if corr else "decorr"}, exact fees {fee_c}c)'}
    total_cost_c = n * total_price_c
    if total_cost_c + fee_c + FEE_SLACK_CENTS > balance_c:
        return {'ok': False, 'reason': 'insufficient balance for combo'}
    if shard_bal is not None:
        chk = reverify_combo_shard_check(rvs, n, shard_bal)
        if not chk['ok']:
            return chk
    return {'ok': True, 'legs': rvs, 'contracts': n, 'edge_c': edge_c,
            'fee_c': fee_c, 'net_c': net_c, 'total_price_c': total_price_c,
            'total_cost_c': total_cost_c, 'corr': corr, 'bar_c': bar_c}


def execute_combo(cand, cv, live, tid):
    """Place every leg simultaneously as fill_or_kill. FOK = full fill or
    nothing per leg, so there are no partial fills WITHIN a leg. Across legs
    the failure mode is some-legs-fill / others-die; every leg was re-verified
    +EV standalone (>=5c), so holding the filled subset degrades gracefully.
    Returns (fills, status) where status is 'full', 'partial', or 'none'."""
    legs_rvs, n = cv['legs'], cv['contracts']
    fills = []
    # SPORTS GATE (live path backstop): any sports leg aborts the whole
    # combo — a partially-blocked combo is not a combo we modeled.
    for leg, rv in legs_rvs:
        sb = sports_block_reason(leg['ticker'])
        if sb:
            for l, r in legs_rvs:
                fills.append({'ticker': l['ticker'], 'side': l['side'],
                              'price_cents': r['price_cents'], 'contracts': n,
                              'fill_count': 0, 'order_id': None,
                              'error': f'sports gate: '
                                       f'{sports_block_reason(l["ticker"])}'})
            log_event(action='blocked', kind='combo', trade_id=tid,
                      tickers=[l['ticker'] for l, _ in legs_rvs],
                      reason=f'sports gate (live path): '
                             f'leg {leg["ticker"]}: {sb}')
            print(f'  BLOCKED COMBO: sports gate on leg {leg["ticker"]}')
            return fills, 'none'
    if live:
        for i, (leg, rv) in enumerate(legs_rvs):
            try:
                # FOK per leg + idempotent client_order_id per leg: a retry
                # after a network hiccup can never double-place a leg.
                r = trade_client.place_order(leg['ticker'], leg['side'],
                                             rv['price_cents'], n,
                                             time_in_force='fill_or_kill',
                                             client_order_id=f'{tid}L{i}')
                order = r.get('order') or {}
                fills.append({'ticker': leg['ticker'], 'side': leg['side'],
                              'price_cents': rv['price_cents'], 'contracts': n,
                              'fill_count': int(order.get('fill_count') or 0),
                              'order_id': order.get('order_id')})
            except Exception as ex:
                fills.append({'ticker': leg['ticker'], 'side': leg['side'],
                              'price_cents': rv['price_cents'], 'contracts': n,
                              'fill_count': 0, 'order_id': None,
                              'error': str(ex)[:160]})
    else:
        # Dry-run: show exactly what would be sent; simulate full FOK fills
        # so the logged combo shape matches the intended execution.
        for leg, rv in legs_rvs:
            print(f"  [dry-run] would place FOK buy {leg['side'].upper()} "
                  f"{leg['ticker']} {n}x @ {rv['price_cents']}c")
            fills.append({'ticker': leg['ticker'], 'side': leg['side'],
                          'price_cents': rv['price_cents'], 'contracts': n,
                          'fill_count': n, 'order_id': None, 'dry_run': True})
    filled = [f for f in fills if f['fill_count'] >= n]
    partial = [f for f in fills if 0 < f['fill_count'] < n]
    if partial:
        # Should not happen under FOK (all-or-nothing); scream if it does.
        log_event(action='combo_anomaly', trade_id=tid,
                  reason='FOK leg partially filled — exchange behavior changed',
                  fills=fills)
    if len(filled) == len(fills):
        status = 'full'
    elif filled:
        status = 'partial'
    else:
        status = 'none'
    return fills, status


def market_kind(ticker):
    if re.match(r'KX(BTC|ETH|SOL)15M', ticker):
        return 'crypto15m'
    if re.match(r'KX(BTC|ETH|SOL)D', ticker):
        return 'cryptodaily'
    if re.match(r'KX(CPICORE|ECONSTATCPICORE|ECONSTATCORECPIYOY)-', ticker):
        return 'econ'
    if re.match(r'KX(HIGH|LOWT)[A-Z]+-', ticker):
        return 'weather'
    if re.match(r'SENATE[A-Z]{2}-26-[DR]$', ticker):
        return 'politics'
    return 'index'


# ---------------- politics: Polymarket cross-venue re-verification ----------------
# Mirrors the POL section of edge_scan.py (do not drift from it). Pairs verified
# live 2026-09-24; do not add a pair without verifying it.
POL_PM = {
    'SENATENC': 'north-carolina-senate-election-winner',
    'SENATEGA': 'georgia-senate-election-winner',
    'SENATENH': 'new-hampshire-senate-election-winner',
}


def polymarket_side(slug, side):
    """(bestBid, bestAsk) for the party side on Polymarket, or (None, None)
    if the event is missing, closed, thin, or the quote looks stale."""
    try:
        d = _get(f'https://gamma-api.polymarket.com/events?slug={slug}')
    except Exception:
        return None, None
    if not d:
        return None, None
    e = d[0] if isinstance(d, list) else d
    try:
        end = datetime.datetime.fromisoformat(str(e.get('endDate', '')).replace('Z', '+00:00'))
    except Exception:
        return None, None
    if not e.get('active') or e.get('closed') or end <= datetime.datetime.now(datetime.timezone.utc):
        return None, None
    try:
        if float(e.get('volume') or 0) < 25000:
            return None, None
    except Exception:
        return None, None
    want = 'democrat' if side == 'D' else 'republican'
    other = 'republican' if side == 'D' else 'democrat'
    cands = []
    for m in (e.get('markets') or []):
        q = (m.get('question') or '').lower()
        if want in q and other not in q and 'senate' in q and '2026' in q:
            cands.append(m)
    if len(cands) != 1:
        return None, None
    m = cands[0]
    try:
        bb = float(m.get('bestBid')); ba = float(m.get('bestAsk'))
        op_raw = m.get('outcomePrices')
        if isinstance(op_raw, str):  # gamma sometimes returns a JSON-encoded string
            op_raw = json.loads(op_raw)
        op = float((op_raw or [None])[0])
    except Exception:
        return None, None
    if not (0 < bb < ba < 1) or (ba - bb) > 0.05:
        return None, None
    if not (bb - 0.005 <= op <= ba + 0.005):  # gamma caches; divergence = stale
        return None, None
    return bb, ba


def reverify_politics(cand, t, yb, ya, mins_left, edge_bar=EDGE_BAR):
    """Re-verify a POL candidate against a FRESH Polymarket quote. Never trusts
    the scan-time fair value."""
    pm = re.match(r'(SENATE[A-Z]{2})-26-([DR])$', t)
    if not pm:
        return {'ok': False, 'reason': 'unrecognized politics ticker'}
    slug = POL_PM.get(pm.group(1))
    if not slug:
        return {'ok': False, 'reason': 'no polymarket pair mapped'}
    if not (0 < yb < ya < 1):
        return {'ok': False, 'reason': 'no executable two-sided Kalshi book'}
    if (ya - yb) > 0.06:
        return {'ok': False, 'reason': f'kalshi spread {(ya - yb) * 100:.0f}c > 6c, thin book'}
    pm_bid, pm_ask = polymarket_side(slug, pm.group(2))
    if pm_bid is None:
        return {'ok': False, 'reason': 'polymarket quote stale/unavailable'}
    if cand['side'] == 'yes':
        fair = pm_bid
        edge = pm_bid - ya
        price_cents = round(ya * 100)
    else:
        fair = 1 - pm_ask
        edge = yb - pm_ask          # == fair_NO - no_ask, since no_ask = 1 - yb
        price_cents = round((1 - yb) * 100)
    if not (0 < price_cents < 100):
        return {'ok': False, 'reason': f'bad limit price {price_cents}c'}
    if edge < edge_bar:
        return {'ok': False, 'reason': f'cross-venue gap {edge * 100:.1f}c < 10c bar'}
    return {'ok': True, 'fair': fair, 'edge': edge, 'price_cents': price_cents,
            'minutes_left': mins_left, 'spot': fair}


# ---------------- economics: Cleveland Fed nowcast re-verification ----------------
# Mirrors the ECON section of edge_scan.py (do not drift from it). Only the
# CPI-anchored single-ticker contracts are re-verifiable here; Fed fields,
# ladder arbs and synthetics are multi-leg/flag-only by design.
ECON_MON = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
            'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
ECON_SIGMA_MM = 0.10   # pp, core CPI m/m nowcast error (measured 2026-09-24)
ECON_SIGMA_YOY = 0.11  # pp, propagated + vintage slop
# Aug 2026 core CPI y/y (SA), BLS CUSR0000SA0L1E 337.765/329.700-1.
# Published fact; refresh monthly (scanner warns via stderr when >45d old).
ECON_YOY_BASE = {'2026-9': (2.4463, '2026-09-24')}

_econ_nowcast_cache = {}


def econ_nowcast(target_ym):
    """(asof_date, core_mm_pct) for target_ym like '2026-9', or (None, None).
    Shares /tmp/econ_nowcast.json with the scanner (30-min fetch cache);
    staleness is always judged from the data's own timestamp, never the cache."""
    if target_ym in _econ_nowcast_cache:
        return _econ_nowcast_cache[target_ym]
    out = (None, None)
    raw = None
    cache = '/tmp/econ_nowcast.json'
    try:
        if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 1800:
            with open(cache) as f:
                raw = json.load(f)
    except Exception:
        raw = None
    if raw is None:
        try:
            raw = _get('https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en')
            try:
                with open(cache, 'w') as f:
                    json.dump(raw, f)
            except Exception:
                pass
        except Exception:
            _econ_nowcast_cache[target_ym] = out
            return out
    try:
        asof = None; core = None; n = 0; released = False
        for chart in raw:
            if chart.get('chart', {}).get('subcaption') != target_ym:
                continue
            try:
                asof = datetime.datetime.strptime(
                    chart['chart'].get('_comment', ''), '%Y-%m-%d %H:%M').date()
            except Exception:
                asof = None
            ds = {s.get('seriesname'): s.get('data', []) for s in chart.get('dataset', [])}
            vals = [x.get('value') for x in ds.get('Core CPI Inflation', [])
                    if x.get('value') not in (None, '')]
            n = len(vals)
            core = float(vals[-1]) if vals else None
            act = [x.get('value') for x in ds.get('Actual Core CPI Inflation', [])
                   if x.get('value') not in (None, '')]
            released = bool(act)
        if core is None or asof is None or released:
            _econ_nowcast_cache[target_ym] = out
            return out
        age = (datetime.datetime.now(datetime.timezone.utc).date() - asof).days
        if age < 0 or age > 4 or n < 8:
            _econ_nowcast_cache[target_ym] = out
            return out
        out = (asof, core)
    except Exception:
        out = (None, None)
    _econ_nowcast_cache[target_ym] = out
    return out


_CALIB_CACHE = None


def calib_adjustment(model):
    """YES-probability shift to apply to a model's fair value.

    Learned from settled outcomes by learn_from_settlements.py: shrunk
    toward zero on small samples and hard-capped at +/-3c at write time.
    Fail-safe: any read/parse problem returns 0.0 (no adjustment).
    """
    global _CALIB_CACHE
    if _CALIB_CACHE is None:
        try:
            with open(os.path.join(HIDDEN, 'calibration.json')) as f:
                _CALIB_CACHE = json.load(f)
        except Exception:
            _CALIB_CACHE = {}
    try:
        adj = float(_CALIB_CACHE.get('models', {}).get(model, {}).get('adjustment', 0.0))
    except Exception:
        return 0.0
    return max(-0.03, min(0.03, adj))


def reverify_econ(cand, t, yb, ya, mins_left, edge_bar=EDGE_BAR):
    """Re-verify a CPI-anchored ECON candidate against a FRESH Cleveland Fed
    nowcast. Never trusts the scan-time fair value."""
    m = re.match(r'(KXCPICORE|KXECONSTATCPICORE|KXECONSTATCORECPIYOY)-(\d{2})([A-Z]{3})-T(-?[\d.]+)$', t)
    if not m:
        return {'ok': False, 'reason': 'unrecognized econ ticker'}
    series, yy, mon, thr = m.group(1), m.group(2), m.group(3), float(m.group(4))
    ym = f'20{yy}-{ECON_MON.get(mon, 0)}'
    if ym.endswith('-0'):
        return {'ok': False, 'reason': 'bad event month'}
    asof, c_mm = econ_nowcast(ym)
    if asof is None:
        return {'ok': False, 'reason': 'nowcast stale/unavailable'}
    if series == 'KXCPICORE':
        center, sigma = c_mm, ECON_SIGMA_MM
        fair = _N((center - thr) / sigma)
    else:
        if series == 'KXECONSTATCORECPIYOY':
            base = ECON_YOY_BASE.get(ym)
            if not base:
                return {'ok': False, 'reason': f'no BLS y/y base for {ym}'}
            bv, _ = base
            center = ((1 + bv / 100) * (1 + c_mm / 100) - 1) * 100
            sigma = ECON_SIGMA_YOY
        else:
            center, sigma = c_mm, ECON_SIGMA_MM
        # bucket half-width from live book spacing (same convention as scanner)
        hw = 0.05
        try:
            et = t.rsplit('-T', 1)[0]
            ev = _get(f'https://api.elections.kalshi.com/trade-api/v2/events/{et}?with_nested_markets=true').get('event', {})
            thrs = sorted({float(tm.group(1)) for mk in ev.get('markets', [])
                           for tm in [re.search(r'-T(-?[\d.]+)$', mk.get('ticker', ''))] if tm})
            gaps = [b - a for a, b in zip(thrs, thrs[1:]) if b > a]
            if gaps:
                hw = min(gaps) / 2
        except Exception:
            pass
        fair = _N((thr + hw - center) / sigma) - _N((thr - hw - center) / sigma)
    adj = calib_adjustment('econ')
    if adj:
        # Learned bias correction (shrunk, capped at +/-3c). Small samples
        # barely move this number; that is intentional.
        fair = min(max(fair + adj, 0.001), 0.999)
    if cand['side'] == 'yes':
        if not (0 < ya < 1):
            return {'ok': False, 'reason': 'no executable ask'}
        edge = fair - ya
        price_cents = round(ya * 100)
    else:
        if yb < 0.01:
            return {'ok': False, 'reason': 'no YES bid to sell into for NO'}
        edge = yb - fair
        price_cents = round((1 - yb) * 100)
    if not (0 < price_cents < 100):
        return {'ok': False, 'reason': f'bad limit price {price_cents}c'}
    if edge < edge_bar:
        return {'ok': False, 'reason': f'edge {edge * 100:.1f}c < 10c bar'}
    return {'ok': True, 'fair': fair, 'edge': edge, 'price_cents': price_cents,
            'minutes_left': mins_left, 'spot': center}


# ---------------- weather: deterministic station-extreme re-verification ----------------
# Mirrors section 7 of edge_scan.py (do not drift from it). Only deterministic
# kills/locks (fair exactly 0 or 1) derived from the RUNNING station extreme
# are re-verifiable; there is no probabilistic weather model. Station map is
# MEASURED (2026-09-24, 64/64 exact TWC-vs-ASOS matches), not assumed:
# CHI=MDW, DAL=DFW, NYC=Central Park, HOU=HOU.
_WX_RE = {  # series: (hi|lo, ICAO, IEM station, IEM network, tz)
    'KXHIGHCHI':  ('hi', 'KMDW', 'MDW', 'IL_ASOS', 'America/Chicago'),
    'KXHIGHTOKC': ('hi', 'KOKC', 'OKC', 'OK_ASOS', 'America/Chicago'),
    'KXHIGHTSEA': ('hi', 'KSEA', 'SEA', 'WA_ASOS', 'America/Los_Angeles'),
    'KXHIGHLAX':  ('hi', 'KLAX', 'LAX', 'CA_ASOS', 'America/Los_Angeles'),
    'KXHIGHMIA':  ('hi', 'KMIA', 'MIA', 'FL_ASOS', 'America/New_York'),
    'KXHIGHDEN':  ('hi', 'KDEN', 'DEN', 'CO_ASOS', 'America/Denver'),
    'KXHIGHAUS':  ('hi', 'KAUS', 'AUS', 'TX_ASOS', 'America/Chicago'),
    'KXHIGHPHIL': ('hi', 'KPHL', 'PHL', 'PA_ASOS', 'America/New_York'),
    'KXHIGHTATL': ('hi', 'KATL', 'ATL', 'GA_ASOS', 'America/New_York'),
    'KXHIGHTDC':  ('hi', 'KDCA', 'DCA', 'VA_ASOS', 'America/New_York'),
    'KXHIGHTDAL': ('hi', 'KDFW', 'DFW', 'TX_ASOS', 'America/Chicago'),
    'KXHIGHTBOS': ('hi', 'KBOS', 'BOS', 'MA_ASOS', 'America/New_York'),
    'KXHIGHTPHX': ('hi', 'KPHX', 'PHX', 'AZ_ASOS', 'America/Phoenix'),
    'KXHIGHTNOLA': ('hi', 'KMSY', 'MSY', 'LA_ASOS', 'America/Chicago'),
    'KXHIGHNY':   ('hi', 'KNYC', 'NYC', 'NY_ASOS', 'America/New_York'),
    'KXLOWTSEA':  ('lo', 'KSEA', 'SEA', 'WA_ASOS', 'America/Los_Angeles'),
    'KXLOWTPHIL': ('lo', 'KPHL', 'PHL', 'PA_ASOS', 'America/New_York'),
    'KXLOWTATL':  ('lo', 'KATL', 'ATL', 'GA_ASOS', 'America/New_York'),
    'KXLOWTMIA':  ('lo', 'KMIA', 'MIA', 'FL_ASOS', 'America/New_York'),
    'KXLOWTLAX':  ('lo', 'KLAX', 'LAX', 'CA_ASOS', 'America/Los_Angeles'),
    'KXLOWTDEN':  ('lo', 'KDEN', 'DEN', 'CO_ASOS', 'America/Denver'),
    'KXLOWTOKC':  ('lo', 'KOKC', 'OKC', 'OK_ASOS', 'America/Chicago'),
    'KXLOWTCHI':  ('lo', 'KMDW', 'MDW', 'IL_ASOS', 'America/Chicago'),
    'KXLOWTDC':   ('lo', 'KDCA', 'DCA', 'VA_ASOS', 'America/New_York'),
    'KXLOWTBOS':  ('lo', 'KBOS', 'BOS', 'MA_ASOS', 'America/New_York'),
    'KXLOWTAUS':  ('lo', 'KAUS', 'AUS', 'TX_ASOS', 'America/Chicago'),
    'KXLOWTHOU':  ('lo', 'KHOU', 'HOU', 'TX_ASOS', 'America/Chicago'),
    'KXLOWTNYC':  ('lo', 'KNYC', 'NYC', 'NY_ASOS', 'America/New_York'),
}
_WX_STD = {'America/Chicago': -6, 'America/New_York': -5, 'America/Denver': -7,
           'America/Los_Angeles': -8, 'America/Phoenix': -7}


def _wx_station_extreme(kind, icao, stn, network, tzname):
    """Running max (hi) / min (lo) of today's station obs in F, or None.
    NWS primary, IEM ASOS fallback. Day window is local STANDARD time."""
    off = _WX_STD[tzname]
    ds = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=off)
    day_start = (ds.replace(hour=0, minute=0, second=0, microsecond=0)
                 - datetime.timedelta(hours=off))
    vals = []
    try:
        d = _get(f'https://api.weather.gov/stations/{icao}/observations?limit=300')
        for feat in d.get('features', []) or []:
            p = feat.get('properties', {}) or {}
            try:
                ts = datetime.datetime.fromisoformat(p['timestamp'])
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts < day_start:
                continue
            t = (p.get('temperature') or {}).get('value')
            if t is not None:
                vals.append(t * 9 / 5 + 32)
    except Exception:
        pass
    if not vals:
        try:
            from zoneinfo import ZoneInfo
            import csv
            from urllib.parse import urlencode
            today = datetime.datetime.now(datetime.timezone.utc).astimezone(ZoneInfo(tzname)).date()
            q = urlencode({'station': stn, 'data': 'tmpf',
                           'year1': today.year, 'month1': today.month, 'day1': today.day,
                           'year2': today.year, 'month2': today.month, 'day2': today.day,
                           'tz': tzname, 'format': 'onlycomma', 'latlon': 'no', 'elev': 'no',
                           'missing': 'empty', 'trace': 'empty', 'direct': 'no'})
            req = urllib.request.Request(
                'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + q,
                headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                txt = r.read().decode()
            for row in csv.DictReader(txt.splitlines()):
                try:
                    vals.append(float(row['tmpf']))
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
    if not vals:
        return None
    return max(vals) if kind == 'hi' else min(vals)


def _wx_deterministic(kind, stype, f, c, m):
    """Deterministic fair: 1.0 (locked), 0.0 (dead), None (unknown).
    Integer guard bands — safe under any plausible TWC rounding."""
    if kind == 'hi':
        if stype == 'less' and m >= c:
            return 0.0
        if stype == 'between' and m >= c + 1:
            return 0.0
        if stype == 'greater' and m >= f + 1:
            return 1.0
    else:
        if stype == 'greater' and m <= f:
            return 0.0
        if stype == 'between' and m <= f - 1:
            return 0.0
        if stype == 'less' and m <= c - 1:
            return 1.0
    return None


def reverify_weather(cand, t, yb, ya, mins_left, mkt, edge_bar=EDGE_BAR):
    """Re-verify a WX candidate against FRESH station obs. Never trusts the
    scan-time extreme; the kill must still hold right now."""
    m = re.match(r'(KX(?:HIGH|LOWT)[A-Z]+)-(\d{2}[A-Z]{3}\d{2})-[TB][\d.]+$', t)
    if not m:
        return {'ok': False, 'reason': 'unrecognized weather ticker'}
    series, datecode = m.group(1), m.group(2)
    cfg = _WX_RE.get(series)
    if not cfg:
        return {'ok': False, 'reason': 'station not mapped'}
    kind, icao, stn, network, tzname = cfg
    try:
        from zoneinfo import ZoneInfo
        today_dc = (datetime.datetime.now(datetime.timezone.utc)
                    .astimezone(ZoneInfo(tzname)).strftime('%y%b%d').upper())
    except Exception:
        return {'ok': False, 'reason': 'tz unavailable'}
    if datecode != today_dc:
        return {'ok': False, 'reason': f'event date {datecode} != today {today_dc}'}
    stype = mkt.get('strike_type')
    try:
        f = int(float(mkt['floor_strike'])) if mkt.get('floor_strike') is not None else None
        c = int(float(mkt['cap_strike'])) if mkt.get('cap_strike') is not None else None
    except (TypeError, ValueError):
        return {'ok': False, 'reason': 'bad strikes'}
    if stype not in ('less', 'greater', 'between'):
        return {'ok': False, 'reason': f'unhandled strike_type {stype}'}
    ext = _wx_station_extreme(kind, icao, stn, network, tzname)
    if ext is None:
        return {'ok': False, 'reason': 'no station obs today'}
    fair = _wx_deterministic(kind, stype, f, c, ext)
    if fair is None:
        return {'ok': False, 'reason': 'deterministic kill no longer holds'}
    if cand['side'] == 'yes':
        if fair != 1.0:
            return {'ok': False, 'reason': 'YES needs a locked strike (fair 1)'}
        if not (0 < ya < 1):
            return {'ok': False, 'reason': 'no executable ask'}
        edge = 1.0 - ya
        price_cents = round(ya * 100)
    else:
        if fair != 0.0:
            return {'ok': False, 'reason': 'NO needs a dead strike (fair 0)'}
        if yb < 0.01:
            return {'ok': False, 'reason': 'no YES bid to sell into for NO'}
        edge = yb  # fair_NO(1) - no_ask(1-yb)
        price_cents = round((1 - yb) * 100)
    if not (0 < price_cents < 100):
        return {'ok': False, 'reason': f'bad limit price {price_cents}c'}
    if edge < edge_bar:
        return {'ok': False, 'reason': f'deterministic edge {edge * 100:.1f}c < 10c bar'}
    return {'ok': True, 'fair': fair, 'edge': edge, 'price_cents': price_cents,
            'minutes_left': mins_left, 'spot': ext}


# ---------------- execution metadata ----------------
def _attach_exec(rv, m, cand):
    """Attach fee_meta + resting size to an ok reverify result. Leaves
    failures untouched. Size = resting contracts at our side's touch price,
    used by the combo depth gate (FOK needs full size resting).
    Also attaches exchange_index: the shard this market clears on. The
    exchange checks order collateral ONLY against that shard's balance —
    the aggregate balance is not spendable cross-shard."""
    if not rv.get('ok'):
        return rv
    rv['fee_meta'] = fee_meta_for(cand['ticker'], m)
    try:
        rv['exchange_index'] = int(m.get('exchange_index'))
    except (TypeError, ValueError):
        rv['exchange_index'] = None
    try:
        if cand['side'] == 'yes':
            rv['size'] = int(float(m.get('yes_ask_size_fp') or 0))
        else:
            rv['size'] = int(float(m.get('yes_bid_size_fp') or 0))
    except Exception:
        rv['size'] = 0
    return rv


# ---------------- exact fee plumbing ----------------
def fee_meta_for(ticker, market=None):
    """Inputs for fee_math.order_fee_cents for one order on `ticker`.
    fee_type comes from GET /series/{ticker}, cached on disk (fees.py).
    An unexpired fee waiver on the market zeroes the fee. Unknown series ->
    the conservative standard taker rate (documented in fees.py)."""
    try:
        wt = (market or {}).get('fee_waiver_expiration_time')
        if wt and datetime.datetime.fromisoformat(
                wt.replace('Z', '+00:00')) > datetime.datetime.now(datetime.timezone.utc):
            return {'series': fee_math.series_of(ticker), 'fee_type': None,
                    'fee_multiplier': 1.0, 'waived': True}
    except Exception:
        pass
    series = fee_math.series_of(ticker)
    fee_type, mult = fee_math.get_fee_info(series, fetcher=trade_client.get_series)
    return {'series': series, 'fee_type': fee_type,
            'fee_multiplier': mult}


def exact_fee_cents(contracts, price_cents, meta):
    """Exact fee for one taker-intent order, in cents."""
    if not meta or meta.get('waived'):
        return 0
    return fee_math.order_fee_cents(contracts, price_cents, meta['series'],
                                   meta.get('fee_type'),
                                   meta.get('fee_multiplier', 1.0))


# ---------------- atomic re-verification ----------------
# ---------------- sweep: result-set single-ticker re-verification ----------------
# Model-free: the market's result is already set (yes/no) but it is still
# active and quotable, so the $1/$0 payout is known. Re-check the result is
# STILL set on a fresh fetch, require real resting size (market-level quotes
# can be stale), and demand the usual 15c edge. No external data needed.
def reverify_sweep(cand, t, yb, ya, mins_left, m, edge_bar=EDGE_BAR):
    r = (m.get('result') or '').lower()

    def _f(x):
        try:
            return float(x or 0)
        except Exception:
            return 0

    if cand['side'] == 'yes':
        if r != 'yes':
            return {'ok': False, 'reason': f'result={r!r}, expected yes'}
        if not (0 < ya < 1):
            return {'ok': False, 'reason': 'no executable ask'}
        if _f(m.get('yes_ask_size_fp')) <= 0:
            return {'ok': False, 'reason': 'no resting ask size (stale quote)'}
        edge = 1.0 - ya  # YES pays $1
        price_cents = round(ya * 100)
        fair = 1.0
    else:
        if r != 'no':
            return {'ok': False, 'reason': f'result={r!r}, expected no'}
        if yb < 0.01:
            return {'ok': False, 'reason': 'no YES bid to sell into for NO'}
        if _f(m.get('yes_bid_size_fp')) <= 0:
            return {'ok': False, 'reason': 'no resting bid size (stale quote)'}
        edge = yb  # YES pays $0; selling YES at the bid locks yb
        price_cents = round((1 - yb) * 100)
        fair = 0.0
    if not (0 < price_cents < 100):
        return {'ok': False, 'reason': f'bad limit price {price_cents}c'}
    if edge < edge_bar:
        return {'ok': False, 'reason': f'edge {edge * 100:.1f}c < 10c bar'}
    return {'ok': True, 'fair': fair, 'edge': edge, 'price_cents': price_cents,
            'minutes_left': mins_left, 'spot': None}


def reverify(cand, edge_bar=EDGE_BAR):
    t = cand['ticker']
    kind = market_kind(t)
    try:
        m = trade_client.get_market(t)
    except Exception as ex:
        return {'ok': False, 'reason': f'book fetch failed: {ex}'}
    if m.get('status') != 'active':
        return {'ok': False, 'reason': f"status={m.get('status')}"}
    try:
        ct = datetime.datetime.fromisoformat(m['close_time'].replace('Z', '+00:00'))
    except Exception:
        return {'ok': False, 'reason': 'bad close_time'}
    mins_left = (ct - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 60
    if mins_left < MIN_MINUTES_TO_CLOSE:
        return {'ok': False, 'reason': f'only {mins_left:.1f}min to close (<10)'}
    try:
        yb = float(m.get('yes_bid_dollars') or 0)
        ya = float(m.get('yes_ask_dollars') or 0)
    except Exception:
        return {'ok': False, 'reason': 'bad book'}
    if cand.get('asset') == 'SWEEP':
        # Result-set singles re-verify against the fresh market object itself;
        # the function validates book, size, and result per side.
        return _attach_exec(reverify_sweep(cand, t, yb, ya, mins_left, m, edge_bar), m, cand)
    if kind == 'politics':
        # Politics re-verifies against a fresh Polymarket quote and does its
        # own book validation (NO side only needs the YES bid).
        return _attach_exec(reverify_politics(cand, t, yb, ya, mins_left, edge_bar), m, cand)
    if kind == 'weather':
        # Deterministic station-extreme kills re-verify against fresh obs;
        # the function validates the book per side itself. mkt carries the
        # strike fields from the already-fetched market object.
        return _attach_exec(reverify_weather(cand, t, yb, ya, mins_left, m, edge_bar), m, cand)
    if kind == 'econ':
        # CPI-anchored contracts re-verify against a fresh nowcast; the
        # function validates the book per side itself.
        return _attach_exec(reverify_econ(cand, t, yb, ya, mins_left, edge_bar), m, cand)
    if not (0 < ya < 1):
        return {'ok': False, 'reason': 'no executable ask'}

    asset = cand['asset']
    if kind in ('crypto15m', 'cryptodaily'):
        try:
            spot = float(_get(f'https://api.coinbase.com/v2/prices/{asset}-USD/spot')['data']['amount'])
        except Exception:
            return {'ok': False, 'reason': 'spot fetch failed'}
        rv, drift = crypto_realized(asset)
        if drift is not None and abs(drift) > 0.01:
            return {'ok': False, 'reason': f'crash/meltup regime, drift {drift * 100:+.2f}%'}
        v15, vh = CRYPTO_VOL[asset]
        if kind == 'crypto15m':
            vol = max(v15, (rv / 2) if rv else 0)
            sigma = spot * vol * math.sqrt(max(mins_left, 0.5) / 15)
        else:
            vol = max(vh, rv or 0)
            sigma = spot * vol * math.sqrt(max(mins_left, 1) / 60)
    else:
        ysym = INDEX_YAHOO.get(asset)
        if not ysym:
            return {'ok': False, 'reason': f'no feed for {asset}'}
        vol, spot = yahoo_spot_vol(ysym)
        if not vol or not spot:
            return {'ok': False, 'reason': 'yahoo feed stale/unavailable'}
        sigma = spot * vol * math.sqrt(max(mins_left, 1) / 60)

    K = cand['strike']
    fair = _N((spot - K) / sigma) if sigma > 0 else 0.5  # fair YES probability
    if cand['side'] == 'yes':
        edge = fair - ya
        price_cents = round(ya * 100)
    else:
        if yb < 0.01:
            return {'ok': False, 'reason': 'no YES bid to sell into for NO'}
        edge = yb - fair  # == fair_NO - no_ask
        price_cents = round((1 - yb) * 100)
    if not (0 < price_cents < 100):
        return {'ok': False, 'reason': f'bad limit price {price_cents}c'}
    if edge < edge_bar:
        return {'ok': False, 'reason': f'edge {edge * 100:.1f}c < 10c bar'}
    return _attach_exec({'ok': True, 'fair': fair, 'edge': edge, 'price_cents': price_cents,
                         'minutes_left': mins_left, 'spot': spot}, m, cand)


# ---------------- sizing ----------------
def kelly_stake_cents(balance_cents, price_cents, p_win, kelly_frac=0.5,
                      fee_per_contract_cents=0.0):
    """Half-Kelly dollar stake (cents) for one binary contract.

    p_win = model win probability for the side being bought (0..1).
    The all-in cost per contract is price + per-contract fee; payout odds
    on all-in cost b = (1-c_eff)/c_eff; Kelly fraction f* = p - (1-p)/b.
    Returns min($2 hard cap, kelly_frac * f* * balance). 0 => skip.

    Study hall session 1 (2026-09-24): the old flat min($2, 35%) was too
    cold on big edges (bet 37% of Kelly on a 27c edge) and overshot Kelly
    ~2x at the minimum 15c edge whenever balance < $5.71 -- hot exactly
    when ruin hurts most. Half-Kelly keeps ~80% of log-growth at ~1/4 the
    variance; the 10c bar stays as overstatement insurance.

    Fee-aware (2026-09-24): taker fees shift the optimal stake ~5% (e.g.
    $1.50 -> $1.42 on the canonical 15c/30%-win $17 case; 10 -> 8 contracts
    once the all-in cost is the divisor). Small next to p-error, but the
    bias is systematic (always toward overbetting) and the fix is one
    iteration, so it is applied. See CRAFT.md "fee-aware Kelly" note.
    """
    try:
        p_win = float(p_win)
    except (TypeError, ValueError):
        return 0
    if balance_cents <= 0 or not (0 < price_cents < 100):
        return 0
    p_win = min(max(p_win, 1e-6), 1.0 - 1e-6)
    c_eff = (price_cents + max(0.0, fee_per_contract_cents)) / 100.0
    if not (0 < c_eff < 1.0):
        return 0
    b = (1.0 - c_eff) / c_eff
    f_star = p_win - (1.0 - p_win) / b
    if f_star <= 0:
        return 0
    return min(int(MAX_RISK_DOLLARS * 100), int(kelly_frac * f_star * balance_cents))


def size_contracts(balance_cents, price_cents, p_win, fee_meta=None):
    """contracts = floor(half-Kelly stake / all-in ask), hard-capped at $2.

    One fixed-point iteration: size pre-fee, measure the exact per-contract
    fee for that size, re-size against the all-in cost. 0 => skip."""
    if price_cents <= 0 or balance_cents <= 0:
        return 0
    stake_c = kelly_stake_cents(balance_cents, price_cents, p_win)
    n0 = int(stake_c // price_cents)
    if n0 < 1 or not fee_meta:
        return n0
    fee_c = exact_fee_cents(n0, price_cents, fee_meta)
    fpc = fee_c / n0
    if fpc <= 0:
        return n0
    stake_c2 = kelly_stake_cents(balance_cents, price_cents, p_win,
                                fee_per_contract_cents=fpc)
    return int(stake_c2 // (price_cents + fpc))


def plan_shard_transfer(balances, dest_shard, need_c):
    """Greedy plan to fund `need_c` on `dest_shard` from surplus shards.

    balances: {exchange_index: cents}. Returns a list of
    (source_shard, cents) covering the deficit, largest surplus first
    (minimizes the number of non-idempotent transfer POSTs), or None when
    the portfolio cannot cover the deficit. Pure planner — never POSTs.
    Execution happens in auto_fund_shard() under the standing delegation
    (per-transfer $2.00 cap, daily $6.00 cap).
    """
    have = balances.get(dest_shard, 0)
    deficit = need_c - have
    if deficit <= 0:
        return []
    sources = sorted(((s, c) for s, c in balances.items()
                      if s != dest_shard and c > 0),
                     key=lambda sc: -sc[1])
    plan, remaining = [], deficit
    for s, c in sources:
        take = min(c, remaining)
        plan.append((s, take))
        remaining -= take
        if remaining <= 0:
            break
    return plan if remaining <= 0 else None


# ---------------- auto shard-transfer (standing delegation) ----------------
# Jeremiah (2026-09-24): "Move the money how you wanna" — standing approval
# for INTRA-Kalshi shard collateral transfers. The pre-flight below used to
# only log a plan ("needs operator approval"); it now auto-executes under
# tight guardrails. Never deposits/withdraws outside money — shard-to-shard
# only, and transfer_collateral is non-idempotent (single-shot, never
# auto-retried on ambiguous failure).
AUTO_XFER_PER_CAP_C = 200    # max auto-transfer per candidate: $2.00
AUTO_XFER_DAILY_CAP_C = 600  # max auto-transferred per calendar day: $6.00
AUTO_XFER_SETTLE_WAIT_S = 15  # seconds to wait for async settlement
AUTO_XFER_STATE_PATH = os.path.join(HIDDEN, 'auto_xfer_daily.json')


def _chicago_today():
    """Calendar day string in America/Chicago (Jeremiah's day)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('America/Chicago')
    except Exception:
        tz = datetime.timezone(datetime.timedelta(hours=-5))  # CDT fallback
    return datetime.datetime.now(tz).strftime('%Y-%m-%d')


def auto_xfer_spent_today():
    """Cents auto-transferred today (America/Chicago). 0 on a new day."""
    day = _chicago_today()
    try:
        d = json.load(open(AUTO_XFER_STATE_PATH))
    except Exception:
        return 0
    if d.get('day') != day:
        return 0
    try:
        return int(d.get('cents', 0))
    except (TypeError, ValueError):
        return 0


def auto_xfer_record(cents):
    """Add `cents` to today's auto-transfer total (America/Chicago day)."""
    day = _chicago_today()
    try:
        d = json.load(open(AUTO_XFER_STATE_PATH))
    except Exception:
        d = {}
    if d.get('day') != day:
        d = {'day': day, 'cents': 0}
    d['cents'] = int(d.get('cents', 0)) + int(cents)
    with open(AUTO_XFER_STATE_PATH, 'w') as f:
        json.dump(d, f)


def auto_fund_shard(shard_bal, dest_shard, need_c, live, ticker=''):
    """Auto-fund `need_c` cents on `dest_shard` via intra-account transfer.

    Returns {'ok': True, ...} when shard_bal was refreshed (or simulated in
    dry-run) and the caller should re-run the pre-flight check; otherwise
    {'ok': False, 'reason': ...} and the candidate must be skipped.

    Guardrails: single planned transfer <= $2.00, daily total <= $6.00
    (America/Chicago). Single-shot per candidate per run — an ambiguous
    failure (raise/timeout) is never retried. DRY_RUN never POSTs.
    Updates shard_bal in place when balances are refreshed/simulated.
    """
    have_c = shard_bal.get(dest_shard, 0)
    shortfall_c = int(math.ceil(need_c - have_c))
    if shortfall_c <= 0:
        return {'ok': True, 'reason': 'no shortfall'}
    plan = plan_shard_transfer(shard_bal, dest_shard, need_c)
    if not plan:
        return {'ok': False,
                'reason': f'shard {dest_shard} short ${shortfall_c / 100:.2f} '
                          f'and portfolio cannot cover even after transfers'}
    total_c = int(sum(c for _, c in plan))
    if total_c > AUTO_XFER_PER_CAP_C:
        return {'ok': False,
                'reason': f'auto-transfer ${total_c / 100:.2f} exceeds '
                          f'per-transfer cap ${AUTO_XFER_PER_CAP_C / 100:.2f} '
                          f'— skipped'}
    spent_c = auto_xfer_spent_today()
    if spent_c + total_c > AUTO_XFER_DAILY_CAP_C:
        return {'ok': False,
                'reason': f'daily auto-transfer cap '
                          f'${AUTO_XFER_DAILY_CAP_C / 100:.2f} would be exceeded '
                          f'(already moved ${spent_c / 100:.2f} today) — skipped'}
    if not live:
        # DRY-RUN: never POST; simulate the funding for downstream logic.
        log_event(action='auto_transfer', mode='DRY-RUN', ticker=ticker,
                  dest_shard=dest_shard, amount_cents=total_c, plan=plan,
                  reason='dry-run: no transfer executed')
        print(f'  [dry-run] would auto-transfer ${total_c / 100:.2f} '
              f'-> shard {dest_shard} {plan}')
        for s, c in plan:
            shard_bal[s] = shard_bal.get(s, 0) - int(c)
        shard_bal[dest_shard] = shard_bal.get(dest_shard, 0) + total_c
        return {'ok': True, 'reason': 'dry-run simulated', 'dry_run': True}
    # LIVE: single-shot, never retried on ambiguous failure.
    tids = []
    try:
        for src, c in plan:
            r = trade_client.transfer_collateral(int(src), int(dest_shard),
                                                int(c))
            tid = (r or {}).get('transfer_id')
            tids.append(tid)
            log_event(action='auto_transfer', ticker=ticker,
                      source_shard=int(src), dest_shard=int(dest_shard),
                      amount_cents=int(c), transfer_id=tid)
            print(f'  auto-transfer ${int(c) / 100:.2f} shard {src}->'
                  f'{dest_shard} (id {tid})')
        auto_xfer_record(total_c)
    except Exception as ex:
        # Ambiguous failure (e.g. read timeout after the POST landed): the
        # money may or may not have moved. NEVER retry — skip the candidate;
        # balances get re-read fresh next run.
        log_event(action='auto_transfer_failed', ticker=ticker,
                  dest_shard=dest_shard, amount_cents=total_c,
                  reason=f'transfer raised; not retried (non-idempotent): '
                         f'{str(ex)[:200]}')
        print(f'  auto-transfer FAILED ({ex}); not retrying — skipping '
              f'{ticker}', file=sys.stderr)
        return {'ok': False,
                'reason': f'auto-transfer failed ambiguously '
                          f'({str(ex)[:120]}); not retried — skipped'}
    time.sleep(AUTO_XFER_SETTLE_WAIT_S)
    try:
        fresh = trade_client.get_shard_balances()
    except Exception as ex:
        log_event(action='auto_transfer_unverified', ticker=ticker,
                  dest_shard=dest_shard, transfer_ids=tids,
                  reason=f'transfer posted but shard re-read failed: {ex}')
        return {'ok': False,
                'reason': f'transfer posted (ids {tids}) but balances '
                          f'unreadable — skipped rather than risk double-spend'}
    shard_bal.clear()
    shard_bal.update(fresh)
    return {'ok': True, 'reason': f'transferred ${total_c / 100:.2f}',
            'transfer_ids': tids}


class HeldTickersError(Exception):
    """held_tickers() failed to read the book — the run must halt."""


def held_tickers():
    """Tickers we already hold or have resting orders in (avoid doubling).

    FAILS CLOSED (2026-09-24 auditor finding): any API error raises
    HeldTickersError instead of returning an empty set. Trading as if
    nothing were held after a positions/orders fetch failure is how a
    bot doubles down into a book it cannot see."""
    out = set()
    try:
        positions = trade_client.get_positions().get('market_positions', [])
    except Exception as ex:
        raise HeldTickersError(f'positions fetch failed: {ex}')
    for mp in positions:
        if mp.get('ticker'):
            out.add(mp['ticker'])
    try:
        orders = trade_client.list_orders('resting').get('orders', [])
    except Exception as ex:
        raise HeldTickersError(f'resting-orders fetch failed: {ex}')
    for o in orders:
        if o.get('ticker'):
            out.add(o['ticker'])
    return out


# ---------------- stale-order management ----------------
# Every entry order carries an expiration_time (GTC+expiry), and this pass
# runs each cycle: cancel any resting order whose edge died, faded below the
# bar, or sat longer than the per-kind limit. Stale fills after the edge is
# gone lose real money — this is the primary defense (expiration is the
# backstop for when the bot itself is down).
def _order_age_min(o):
    """Resting-order age in minutes, defensive across field shapes."""
    for k in ('created_time', 'created_ts_ms', 'ts_ms', 'created_at'):
        v = o.get(k)
        if v is None:
            continue
        if isinstance(v, str):
            try:
                dt = datetime.datetime.fromisoformat(v.replace('Z', '+00:00'))
                return (datetime.datetime.now(datetime.timezone.utc)
                        - dt).total_seconds() / 60
            except Exception:
                continue
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        ms = v * 1000 if v < 1e12 else v  # seconds-vs-ms heuristic
        return (time.time() * 1000 - ms) / 60000
    return None


_STALE_ASSET = {
    'KXGOLDH': 'GOLD', 'KXGOLDD': 'GOLD',
    'KXINXU': 'SPX', 'KXINX': 'SPX',
    'KXNASDAQ100U': 'NDX', 'KXWTIH': 'WTI', 'KXSILVERH': 'SILVER',
}


def _stale_asset(ticker, kind):
    m = re.match(r'KX(BTC|ETH|SOL)', ticker)
    if m:
        return m.group(1)
    a = _STALE_ASSET.get(fee_math.series_of(ticker))
    if a:
        return a
    return {'econ': 'ECON', 'weather': 'WX', 'politics': 'POL'}.get(kind, 'SWEEP')


def _series_category(ticker):
    """Authoritative series category from the public API ('Sports', 'Crypto',
    'Economics', ...). Cheap; only called for resting orders (0-3 typical)."""
    try:
        return trade_client.get_series(
            fee_math.series_of(ticker)).get('category')
    except Exception:
        return None


# ---------------- sports gate ----------------
# Non-sports by default (Jeremiah standing rule; sports was authorized only
# for the 2026-09-22 evening window). The CAND_RE/SWEEP form accepts any
# ticker, so this is the hard backstop in the order path: a sports series
# ticker can never be ordered unless an explicitly authorized window is
# active. SPORTS_WINDOWS holds (start_utc_iso, end_utc_iso) tuples; the
# empty list (default) means sports are never tradable.
SPORTS_WINDOWS = [
    # Authorized by Jeremiah 2026-09-24 ~14:33 CDT: "Games tonight and shit just cook"
    ("2026-09-24T19:35:00+00:00", "2026-09-25T05:00:00+00:00"),  # tonight until midnight CDT
]

_SPORTS_SERIES_RE = re.compile(
    r'KX(?:NFL|NBA|MLB|NHL|SOCCER|TENNIS|GOLF|UFC|FIFA|GAME)[A-Z0-9]*')


def _ticker_is_sports(ticker):
    """True iff this ticker belongs to a sports series. Cheap series-prefix
    regex first (no network); authoritative API category as second opinion
    for catch-all forms the regex doesn't recognize."""
    try:
        if _SPORTS_SERIES_RE.match(fee_math.series_of(ticker or '')):
            return True
    except Exception:
        pass
    try:
        return _series_category(ticker) == 'Sports'
    except Exception:
        return False


def _sports_window_active():
    """True iff right now falls inside an explicitly authorized sports
    window. Default (no windows configured): never active."""
    now = datetime.datetime.now(datetime.timezone.utc)
    for start, end in SPORTS_WINDOWS:
        try:
            s = datetime.datetime.fromisoformat(str(start).replace('Z', '+00:00'))
            e = datetime.datetime.fromisoformat(str(end).replace('Z', '+00:00'))
        except Exception:
            continue
        if s <= now <= e:
            return True
    return False


def sports_block_reason(ticker):
    """Non-None reason string iff this ticker is a sports series AND no
    sports window is currently authorized. Check before any order placement
    (Phase A verification AND the live placement path)."""
    try:
        is_sports = _ticker_is_sports(ticker)
    except Exception as ex:
        return f'could not classify ticker {ticker} — failing closed ({ex})'
    if is_sports and not _sports_window_active():
        return 'sports ticker outside authorized window (non-sports by default)'
    return None


def _stale_verifiable(kind, asset):
    """Can a model re-verify this order's edge? 'index' is a catch-all in
    market_kind() — only index assets with a Yahoo feed (SPX/NDX/GOLD/...)
    are verifiable; sports and other catch-alls have no model here and must
    NEVER be judged by the wrong one (a wrong-model kill is worse than a
    stale order). Unverifiable orders are governed by age alone."""
    if asset == 'SWEEP':
        return True   # result-set: reverify_sweep is its model
    if kind in ('crypto15m', 'cryptodaily', 'econ', 'weather', 'politics'):
        return True
    return kind == 'index' and asset in INDEX_YAHOO


def cancel_stale_orders():
    """Cancel resting orders whose edge died or which sat too long.
    Returns count cancelled. Never cancels blindly: age alone only cancels
    when the edge still verifies (otherwise the edge-death reason fires)."""
    try:
        orders = trade_client.list_orders('resting').get('orders', [])
    except Exception as ex:
        log_event(action='stale_pass', status='fetch_failed',
                  reason=str(ex)[:120])
        return 0
    cancelled = 0
    for o in orders:
        t = o.get('ticker')
        oid = o.get('order_id')
        if not t or not oid:
            continue
        side = 'yes' if (o.get('side') or '').lower() == 'bid' else 'no'
        kind = market_kind(t)
        asset = _stale_asset(t, kind)
        # Sports (and any non-modeled category) have no re-verification model:
        # age alone governs them. Never judge an order by the wrong model.
        verifiable = (_stale_verifiable(kind, asset)
                      and _series_category(t) != 'Sports')
        limit = STALE_LIMIT_MIN.get(kind, STALE_DEFAULT_MIN)
        age = _order_age_min(o)
        if not verifiable:
            # No model can re-verify this edge (e.g. sports): age alone
            # governs. Never judge it by the wrong model.
            if age is not None and age > limit:
                why = (f'resting {age:.0f}min > {limit}min limit '
                       f'(unverifiable kind {kind}, no model to re-check edge)')
            else:
                continue
        else:
            km = re.search(r'-T([\d.]+)$', t)
            cand = {'kind': 'single', 'asset': asset, 'side': side,
                    'ticker': t, 'strike': float(km.group(1)) if km else None,
                    'raw': 'stale-pass'}
            try:
                rv = reverify(cand)
            except Exception as ex:
                rv = {'ok': False, 'reason': f'reverify crashed: {str(ex)[:80]}'}
            why = None
            if not rv.get('ok'):
                why = f"edge dead: {rv['reason']}"
            elif rv['edge'] * 100 < EDGE_BAR * 100:
                why = f"edge faded to {rv['edge'] * 100:.1f}c < 10c bar"
            elif age is not None and age > limit:
                why = (f'resting {age:.0f}min > {limit}min limit '
                       f'(edge still {rv["edge"] * 100:.1f}c)')
        if not why:
            continue
        try:
            trade_client.cancel_order(oid)
            cancelled += 1
            log_event(action='cancel_stale', ticker=t, side=side,
                      order_id=oid, reason=why)
            print(f'  cancel_stale {t}: {why}')
        except Exception as ex:
            log_event(action='cancel_stale', ticker=t, side=side,
                      order_id=oid, reason=why,
                      cancel_error=str(ex)[:160])
            print(f'  cancel_stale {t} FAILED: {ex}', file=sys.stderr)
    if orders:
        log_event(action='stale_pass', resting=len(orders), cancelled=cancelled)
    return cancelled


# ---------------- main ----------------
def verify_single_candidate(cand, held, balance_c):
    """Phase-A verification for one single-market candidate: every gate
    that does not depend on placement order (book, model edge, half-Kelly
    sizing, 10c net-edge bar after exact fees). Returns a ready payload
    dict, or None when skipped (skip already logged). No money moves here;
    no balances are mutated."""
    t, side = cand['ticker'], cand['side']
    sb = sports_block_reason(t)
    if sb:
        # Sports gate (Phase A): a sports series ticker can never be
        # ordered outside an explicitly authorized window. The CAND_RE/SWEEP
        # form accepts any ticker, so this is the backstop.
        log_event(action='skipped', ticker=t, side=side,
                  reason=f'sports gate: {sb}')
        print(f'  skip {t}: {sb}')
        return None
    if t in held:
        log_event(action='skipped', ticker=t, side=side, reason='already hold / resting order')
        print(f'  skip {t}: already in book')
        return None
    rv = reverify(cand)
    if not rv['ok']:
        log_event(action='skipped', ticker=t, side=side, reason=rv['reason'])
        print(f"  skip {t}: {rv['reason']}")
        return None
    # Half-Kelly sizing: stake scales with the model's win probability for
    # the side we're buying (fair = YES prob; NO side uses 1 - fair).
    side_l = (side or '').lower()
    p_win = rv['fair'] if side_l == 'yes' else 1.0 - rv['fair']
    n = size_contracts(balance_c, rv['price_cents'], p_win,
                       rv.get('fee_meta'))
    if n < 1:
        log_event(action='skipped', ticker=t, side=side,
                  reason='cannot size >=1 contract within risk limit',
                  price_cents=rv['price_cents'], edge_cents=round(rv['edge'] * 100))
        print(f"  skip {t}: edge {rv['edge'] * 100:.1f}c but can't size 1 contract in risk")
        return None
    # Exact per-series fee for this order (replaces the old flat 10%
    # buffer). The 10c bar applies to the NET edge after fees.
    fee_c = exact_fee_cents(n, rv['price_cents'], rv.get('fee_meta'))
    net_c = rv['edge'] * 100 - fee_c / n
    if net_c < EDGE_BAR * 100:
        log_event(action='skipped', ticker=t, side=side,
                  reason=f'net edge {net_c:.1f}c < 10c bar after exact fees ({fee_c}c)',
                  price_cents=rv['price_cents'],
                  edge_cents=round(rv['edge'] * 100), fee_cents=fee_c)
        print(f"  skip {t}: net edge {net_c:.1f}c < 10c bar after {fee_c}c exact fees")
        return None
    hours_left = rv['minutes_left'] / 60.0
    bonus_c = sprint_bonus_cents(hours_left)
    rank_c = net_c + bonus_c
    log_event(action='sprint_rank', ticker=t, side=side,
              hours_to_close=round(hours_left, 1),
              sprint_qualifies=bool(hours_left <= SPRINT_HOURS),
              sprint_bonus_cents=bonus_c,
              net_edge_cents=round(net_c, 1),
              rank_cents=round(rank_c, 1),
              reason=f'verified: rank = net {net_c:.1f}c + sprint bonus {bonus_c:.0f}c')
    return {'kind': 'single', 'cand': cand, 'rv': rv, 'n': n, 'fee_c': fee_c,
            'net_c': net_c, 'hours_left': hours_left, 'bonus_c': bonus_c,
            'rank_c': rank_c}


def place_single_candidate(payload, live, mode, day, held, balance_c,
                           shard_bal, xp):
    """Phase-B placement for a verified single: the order-dependent gates
    (aggregate balance, per-shard collateral with auto-funding, portfolio
    in-play / correlated-risk caps) re-run here in rank order, then the
    order is placed. Returns (balance_c, rejected): rejected=True when the
    exchange refused the order — the caller circuit-breaks on repeats."""
    cand, rv = payload['cand'], payload['rv']
    t, side = cand['ticker'], cand['side']
    n, fee_c, net_c = payload['n'], payload['fee_c'], payload['net_c']
    if t in held:
        # A higher-ranked trade this run took this ticker first.
        log_event(action='skipped', ticker=t, side=side,
                  reason='already hold / resting order (taken by higher-ranked trade)')
        print(f'  skip {t}: already in book')
        return balance_c, False
    cost_c = n * rv['price_cents']
    need_c = cost_c + fee_c + FEE_SLACK_CENTS
    if need_c > balance_c:
        log_event(action='skipped', ticker=t, side=side,
                  reason=f'insufficient balance: need ~${need_c / 100:.2f}, '
                         f'have ${balance_c / 100:.2f}',
                  price_cents=rv['price_cents'], contracts=n, fee_cents=fee_c)
        print(f'  skip {t}: insufficient balance')
        return balance_c, False
    # SHARD PRE-FLIGHT: simulate the exchange's collateral check locally.
    # The exchange holds cost+fee ONLY against the market's shard
    # (rv['exchange_index']); the aggregate balance is not spendable
    # cross-shard. Log "would be rejected" instead of burning an order
    # attempt that the exchange will 400. (2026-09-24 08:45 CDT: 18
    # insufficient_balance rejections in ~9s fired with no pre-flight;
    # this gate plus the run circuit breaker exist so that never recurs.)
    shard = rv.get('exchange_index')
    shard_have_c = shard_bal.get(shard) if shard is not None else None
    if shard is None or shard_have_c is None:
        log_event(action='skipped', ticker=t, side=side,
                  reason='unknown exchange shard — cannot pre-flight '
                         'balance; failing closed',
                  price_cents=rv['price_cents'], contracts=n)
        print(f'  skip {t}: unknown exchange shard')
        return balance_c, False
    if need_c > shard_have_c:
        # Standing delegation (Jeremiah 2026-09-24): auto-fund the shard
        # under caps instead of merely logging a plan. Single-shot per
        # candidate per run — never retried on ambiguous failure.
        res = auto_fund_shard(shard_bal, shard, need_c, live, ticker=t)
        shard_have_c = shard_bal.get(shard, 0)
        if not res['ok'] or need_c > shard_have_c:
            why = res['reason'] if not res['ok'] else (
                f'auto-transfer completed but shard {shard} still short: '
                f'have ${shard_have_c / 100:.2f}, '
                f'need ${need_c / 100:.2f}')
            log_event(action='skipped', ticker=t, side=side,
                      reason=f'EXCHANGE WOULD REJECT (insufficient_balance): '
                             f'need ${need_c / 100:.2f} on shard {shard}, '
                             f'have ${shard_have_c / 100:.2f}; {why}',
                      price_cents=rv['price_cents'], contracts=n,
                      fee_cents=fee_c, exchange_index=shard,
                      shard_balance_cents=shard_have_c)
            print(f'  skip {t}: shard {shard} has ${shard_have_c / 100:.2f}, '
                  f'need ${need_c / 100:.2f} — {why}')
            return balance_c, False
        print(f'  shard {shard} auto-funded ({res["reason"]}) — proceeding')
    # PORTFOLIO CAPS: $10 in play, per-series and per-event correlated-risk
    # limits, max trades per event bucket. Charged in rank order so the
    # best edges get the scarce risk budget first.
    ok, why = exposure_fits(xp, [(t, cost_c)])
    if not ok:
        log_event(action='skipped', ticker=t, side=side,
                  reason=f'portfolio cap: {why}',
                  price_cents=rv['price_cents'], contracts=n)
        print(f'  skip {t}: {why}')
        return balance_c, False
    tid = uuid.uuid4().hex[:12]
    edge_c = round(rv['edge'] * 100)
    # TIF discipline: crypto15m is taker-intent on a seconds fuse -> IOC
    # (a resting taker-intent order is a stale-order accident). Everything
    # else rests as GTC but ALWAYS with expiration_time = min(close, 24h).
    # post_only=False by design: entries cross the spread (taker-intent);
    # post_only is only for maker-intent orders, which we don't place.
    # reduce_only=False: these are entries, not exits.
    kind = market_kind(t)
    if kind == 'crypto15m':
        tif, exp = 'immediate_or_cancel', None
    else:
        tif = 'good_till_canceled'
        exp = int(time.time() + min(rv['minutes_left'] * 60,
                                   ENTRY_MAX_REST_HOURS * 3600))
    # SPORTS GATE (live path backstop): belt-and-suspenders with the Phase-A
    # check — a sports ticker can never reach the exchange outside an
    # explicitly authorized window, no matter how it got this far.
    sb = sports_block_reason(t)
    if sb:
        log_event(action='blocked', ticker=t, side=side, date=day,
                  reason=f'sports gate (live path): {sb}')
        print(f'  BLOCKED {t}: {sb}')
        return balance_c, False
    if live:
        try:
            r = trade_client.place_order(t, side, rv['price_cents'], n,
                                         time_in_force=tif,
                                         client_order_id=tid,
                                         expiration_time=exp)
            order = r.get('order') or {}
            oid = order.get('order_id') or r.get('order_id')
            # Fill count is the EXCHANGE's number, never an assumption:
            # `or n` here is what fabricated the 2026-09-24 T7669.9999
            # phantom (order accepted, canceled 36s later, 0 fills, logged
            # as 4). Unknown/absent => 0; settle_check confirms via fills.
            filled = 0
            for k in ('fill_count', 'fill_count_fp'):
                v = order.get(k)
                if v is not None:
                    try:
                        filled = int(float(v))
                        break
                    except (TypeError, ValueError):
                        pass
            log_event(action='placed', trade_id=tid, ticker=t, side=side,
                      asset=cand.get('asset'),
                      price_cents=rv['price_cents'], contracts=n,
                      fill_count=filled, edge_cents=edge_c,
                      fair_cents=round(rv['fair'] * 100),
                      net_edge_cents=round(net_c, 1), fee_cents=fee_c,
                      sprint_bonus_cents=payload['bonus_c'],
                      hours_to_close=round(payload['hours_left'], 1),
                      order_id=oid, client_order_id=tid,
                      time_in_force=tif, expiration_time=exp,
                      minutes_left=round(rv['minutes_left'], 1))
            print(f'  PLACED buy {side.upper()} {t} {n}x @ {rv["price_cents"]}c '
                  f'(net edge {net_c:.1f}c, fee {fee_c}c, {tif}'
                  f'{"" if exp is None else ", expires"})')
            spent_c = filled * rv['price_cents']  # exchange-confirmed fills only
            balance_c -= spent_c
            if shard is not None:
                shard_bal[shard] = shard_bal.get(shard, 0) - spent_c
            charge_exposure(xp, [(t, spent_c)])
            held.add(t)
        except Exception as ex:
            log_event(action='skipped', trade_id=tid, ticker=t, side=side,
                      reason=f'order failed: {str(ex)[:200]}')
            print(f'  FAILED {t}: {ex}', file=sys.stderr)
            return balance_c, True
    else:
        log_event(action='dry_run', trade_id=tid, ticker=t, side=side,
                  asset=cand.get('asset'),
                  price_cents=rv['price_cents'], contracts=n, edge_cents=edge_c,
                  fair_cents=round(rv['fair'] * 100),
                  net_edge_cents=round(net_c, 1), fee_cents=fee_c,
                  sprint_bonus_cents=payload['bonus_c'],
                  hours_to_close=round(payload['hours_left'], 1),
                  client_order_id=tid, time_in_force=tif, expiration_time=exp,
                  minutes_left=round(rv['minutes_left'], 1),
                  reason=f'would buy {n}x {side.upper()} @ {rv["price_cents"]}c')
        print(f'  [dry-run] would BUY {side.upper()} {t} {n}x @ {rv["price_cents"]}c '
              f'(net edge {net_c:.1f}c, fee {fee_c}c, {tif}, {rv["minutes_left"]:.0f}min left)')
        charge_exposure(xp, [(t, cost_c)])  # paper mirror of the cap logic
    return balance_c, False


def verify_combo_candidate(cand, held, balance_c, shard_bal):
    """Phase-A verification for one synthetic combo: held-leg check plus
    reverify_combo (fresh books, per-leg +EV, combo net bar, unified
    half-Kelly sizing, balance and shard pre-flight against run-start
    funds). Returns a ready payload dict, or None when skipped (skip
    already logged). No money moves here."""
    leg_tickers = [l['ticker'] for l in cand.get('legs', [])]
    tag = 'COMBO[' + ','.join(t.split('-')[0][-8:] for t in leg_tickers) + ']'
    if any(t in held for t in leg_tickers):
        log_event(action='skipped', kind='combo', tickers=leg_tickers,
                  reason='a leg already held / resting order')
        print(f'  skip {tag}: leg already in book')
        return None
    for lt in leg_tickers:
        sb = sports_block_reason(lt)
        if sb:
            log_event(action='skipped', kind='combo', tickers=leg_tickers,
                      reason=f'sports gate: leg {lt}: {sb}')
            print(f'  skip {tag}: sports gate on leg {lt}')
            return None
    cv = reverify_combo(cand, balance_c, shard_bal)
    if not cv['ok']:
        log_event(action='skipped', kind='combo', tickers=leg_tickers,
                  reason=cv['reason'])
        print(f"  skip {tag}: {cv['reason']}")
        return None
    hours_left = max(rv['minutes_left'] for _, rv in cv['legs']) / 60.0
    per_unit_c = cv['net_c'] / cv['contracts']
    bonus_c = sprint_bonus_cents(hours_left)
    rank_c = per_unit_c + bonus_c
    log_event(action='sprint_rank', kind='combo', tickers=leg_tickers,
              hours_to_close=round(hours_left, 1),
              sprint_qualifies=bool(hours_left <= SPRINT_HOURS),
              sprint_bonus_cents=bonus_c,
              net_edge_cents=round(per_unit_c, 1),
              rank_cents=round(rank_c, 1),
              reason=f'verified: rank = net {per_unit_c:.1f}c/unit + sprint bonus {bonus_c:.0f}c')
    return {'kind': 'combo', 'cand': cand, 'cv': cv, 'tag': tag,
            'tickers': leg_tickers, 'hours_left': hours_left,
            'bonus_c': bonus_c, 'rank_c': rank_c, 'per_unit_c': per_unit_c}


def place_combo_candidate(payload, live, mode, day, held, balance_c,
                            shard_bal, xp):
    """Phase-B placement for a verified combo. Affordability is re-checked
    fail-closed: Phase A verified against run-start funds, and higher-ranked
    combos placed first may have spent since. Returns (balance_c, rejected)."""
    cand, cv = payload['cand'], payload['cv']
    leg_tickers, tag = payload['tickers'], payload['tag']
    if any(t in held for t in leg_tickers):
        log_event(action='skipped', kind='combo', tickers=leg_tickers,
                  reason='a leg already held / resting order (taken by higher-ranked trade)')
        print(f'  skip {tag}: leg already in book')
        return balance_c, False
    if cv['total_cost_c'] + cv['fee_c'] + FEE_SLACK_CENTS > balance_c:
        log_event(action='skipped', kind='combo', tickers=leg_tickers,
                  reason='insufficient balance: capital committed to higher-ranked trades')
        print(f'  skip {tag}: insufficient balance')
        return balance_c, False
    if shard_bal is not None:
        need_by_shard, bad = combo_shard_needs(cv['legs'], cv['contracts'])
        short = bad or any(need + FEE_SLACK_CENTS > shard_bal.get(s, 0)
                           for s, need in need_by_shard.items())
        if short:
            log_event(action='skipped', kind='combo', tickers=leg_tickers,
                      reason='shard collateral short after higher-ranked placements '
                             '-- exchange would reject')
            print(f'  skip {tag}: shard collateral short')
            return balance_c, False
    # Portfolio caps ($10 in play, per-series / per-event correlated risk).
    ok, why = exposure_fits(xp, [(leg['ticker'], rv['price_cents'] * n)
                                    for leg, rv in cv['legs']])
    if not ok:
        log_event(action='skipped', kind='combo', tickers=leg_tickers,
                  reason=f'portfolio cap: {why}')
        print(f'  skip {tag}: {why}')
        return balance_c, False
    tid = uuid.uuid4().hex[:12]
    n = cv['contracts']
    if live:
        fills, status = execute_combo(cand, cv, True, tid)
        if status == 'none':
            log_event(action='skipped', kind='combo', trade_id=tid,
                      tickers=leg_tickers,
                      reason='FOK: no legs filled, combo aborted clean')
            print(f'  {tag}: FOK filled nothing — aborted, no exposure')
            return balance_c, False
        # Log the combo as ONE placed trade (counts toward 3/day cap)...
        log_event(action='placed', kind='combo', trade_id=tid,
                  tickers=leg_tickers, contracts=n, status=status,
                  net_edge_cents=cv['net_c'], fee_cents=cv['fee_c'],
                  sprint_bonus_cents=payload['bonus_c'],
                  hours_to_close=round(payload['hours_left'], 1),
                  total_cost_cents=cv['total_cost_c'],
                  corr=cv['corr'], bar_cents=cv['bar_c'],
                  fills=[{k: f[k] for k in ('ticker', 'side', 'price_cents',
                                            'fill_count', 'order_id') if k in f}
                         for f in fills])
        # ...and each FILLED leg individually so settle_check books P&L.
        spent_c = 0
        for f in fills:
            if f['fill_count'] < 1:
                continue
            leg_n = f['fill_count']
            log_event(action='placed_leg', trade_id=tid, ticker=f['ticker'],
                      side=f['side'], price_cents=f['price_cents'],
                      contracts=leg_n, order_id=f.get('order_id'),
                      combo_status=status, date=day)
            spent_c += leg_n * f['price_cents']
            held.add(f['ticker'])
            if shard_bal is not None:
                for _leg, _rv in cv['legs']:
                    if _leg['ticker'] == f['ticker'] and \
                            _rv.get('exchange_index') is not None:
                        shard_bal[_rv['exchange_index']] = \
                            shard_bal.get(_rv['exchange_index'], 0) - \
                            leg_n * f['price_cents']
                        break
        balance_c -= spent_c  # keep later sizing honest within this run
        charge_exposure(xp, [(f['ticker'], f['fill_count'] * f['price_cents'])
                             for f in fills if f['fill_count'] >= 1])
        rejected = any('insufficient_balance' in str(f.get('error', ''))
                       for f in fills)
        if status == 'partial':
            missing = [f['ticker'] for f in fills if f['fill_count'] < 1]
            print(f'  PLACED {tag} PARTIAL: filled '
                  f'{[f["ticker"] for f in fills if f["fill_count"] >= 1]}, '
                  f'missed {missing} (each filled leg was +EV standalone)')
        else:
            print(f'  PLACED {tag} {n}x/leg net edge {cv["net_c"]}c '
                  f'(fees {cv["fee_c"]}c)')
    else:
        fills, _ = execute_combo(cand, cv, False, tid)
        log_event(action='dry_run', kind='combo', trade_id=tid,
                  tickers=leg_tickers, contracts=n, net_edge_cents=cv['net_c'],
                  fee_cents=cv['fee_c'], total_cost_cents=cv['total_cost_c'],
                  corr=cv['corr'],
                  sprint_bonus_cents=payload['bonus_c'],
                  hours_to_close=round(payload['hours_left'], 1),
                  reason=f'would FOK {n}x/leg, net edge {cv["net_c"]}c')
        print(f'  [dry-run] would BUILD {tag} {n}x/leg '
              f'(net edge {cv["net_c"]}c, fees {cv["fee_c"]}c)')
        charge_exposure(xp, [(leg['ticker'], rv['price_cents'] * n)
                             for leg, rv in cv['legs']])  # paper mirror
        rejected = False
    return balance_c, rejected


def _acquire_run_lock():
    """flock-based mutual exclusion for the scan process. Overlapping
    2-minute scans must never double-trade or race ledger writes (2026-09-24
    auditor finding: no run-level lock). Returns the lock file handle, or
    None when another scan already holds it (non-blocking attempt). The
    handle must stay open for the whole run; closing it releases the lock."""
    import fcntl
    os.makedirs(HIDDEN, exist_ok=True)
    fh = open(os.path.join(HIDDEN, 'auto_trade.lock'), 'w')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    try:
        fh.write(f'{os.getpid()}\n')
        fh.flush()
    except Exception:
        pass
    return fh


def main(argv):
    live = '--live' in argv
    trade_client.DRY_RUN = not live
    mode = 'LIVE' if live else 'DRY-RUN'
    lock_fh = _acquire_run_lock()
    if lock_fh is None:
        log_event(action='run', mode=mode, status='lock_contention',
                  reason='another scan holds the run lock; exiting without trading')
        print(f'[{mode}] another scan holds the run lock; exiting without '
              f'trading.', file=sys.stderr)
        return 0
    try:
        return _main(argv, live, mode)
    finally:
        try:
            lock_fh.close()
        except Exception:
            pass


def stop_clear_authorized_today(day):
    """True iff Jeremiah explicitly authorized clearing `day`'s stop-loss
    (log action 'stop_clear_authorized' with date == the Chicago day).
    The authorization lifts THAT DAY's stop only — the stop rule itself
    stays in code for all future days. Auditable via the log entry."""
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get('action') == 'stop_clear_authorized' and e.get('date') == day:
                    return True
    except FileNotFoundError:
        pass
    return False


def _main(argv, live, mode):
    day = today_str()

    new_settled = settle_check()  # book P&L for anything that settled since last run
    if new_settled:
        # Post-trade learning: update model calibration from settled outcomes.
        # Runs ONLY when something actually settled — never on the empty
        # 5-min scans. Fail-safe: a learner crash must never break trading.
        try:
            import learn_from_settlements as _lfl
            _res = _lfl.run_learning()
            print(f'  [learn] consumed {_res["consumed"]} settled trades; '
                  f'adjustments: {_res["adjustments"]}')
        except Exception as ex:
            print(f'  [learn] skipped: {ex}', file=sys.stderr)

    cancel_stale_orders()  # kill resting orders whose edge died / sat too long

    tripped, n_settled, pnl_all = tripwire_check()
    if tripped:
        # 50-trade tripwire: models are not beating the market. Live trading
        # halts; the run continues in paper mode so scanning + learning keep
        # producing data, but no money moves until the models are repaired.
        log_event(action='tripwire',
                  reason=f'{n_settled} settled trades, realized '
                         f'{pnl_all / 100:+.2f} <= $0: LIVE HALTED, paper only')
        print(f'[{mode}] 50-TRADE TRIPWIRE: {n_settled} settled trades, '
              f'total realized {pnl_all / 100:+.2f} <= $0.00. '
              f'Live trading HALTED -- paper mode until models repaired.')
        live = False
        trade_client.DRY_RUN = True
        mode = 'DRY-RUN'
    elif n_settled >= TRIPWIRE_MIN_SETTLED:
        print(f'[{mode}] tripwire check: {n_settled} settled, '
              f'realized {pnl_all / 100:+.2f} -- models still beating the market.')

    realized = load_pnl().get(day, {}).get('realized_cents', 0)
    if realized <= STOP_LOSS_CENTS and not stop_clear_authorized_today(day):
        log_event(action='stop_loss', reason=f'realized {realized}c <= -300c')
        print(f'[{mode}] STOP-LOSS: today realized {realized / 100:+.2f} <= -$3.00. No trading.')
        return 0
    if realized <= STOP_LOSS_CENTS:
        log_event(action='stop_loss_cleared', date=day,
                  reason=f'{day} stop cleared by Jeremiah explicit authorization; '
                         f'realized {realized}c — trading tonight under his direction')
        print(f'[{mode}] STOP-LOSS CLEARED for {day} by Jeremiah authorization '
              f'(realized {realized / 100:+.2f}) — rule stays on the books for future days.')

    # (no daily trade-count cap: lifted by Jeremiah 2026-09-24)

    try:
        bal = trade_client.get_balance()
        balance_c = int(bal.get('balance', 0))
    except Exception as ex:
        log_event(action='skipped', reason=f'balance fetch failed: {ex}')
        print(f'[{mode}] cannot verify balance ({ex}). No trading.', file=sys.stderr)
        return 1
    if balance_c <= 0:
        log_event(action='skipped', reason=f'balance {balance_c}c, nothing to trade')
        print(f'[{mode}] balance is {balance_c}c. No trading.')
        return 0
    # Per-shard balances: the exchange checks order collateral ONLY against
    # the shard the market clears on (market.exchange_index). The aggregate
    # above is NOT spendable cross-shard — sizing against it alone is what
    # produced the 2026-09-24 insufficient_balance rejections (aggregate
    # $5.70, shard 0 $0.00). Fail closed when unreadable.
    try:
        shard_bal = trade_client.get_shard_balances()
    except Exception as ex:
        log_event(action='skipped', reason=f'shard balance fetch failed: {ex}')
        print(f'[{mode}] cannot verify per-shard balance ({ex}). No trading.',
              file=sys.stderr)
        return 1
    print(f"[{mode}] shards: " +
          ", ".join(f"{s}=${c / 100:.2f}" for s, c in sorted(shard_bal.items())))

    cands = run_scan()
    log_event(action='run', mode=mode, candidates=len(cands), balance_cents=balance_c)
    print(f'[{mode}] scan: {len(cands)} candidate(s), balance ${balance_c / 100:.2f}')

    try:
        held = held_tickers()
    except HeldTickersError as ex:
        # Fail closed: if we cannot read positions/resting orders, the run
        # halts instead of trading as if nothing were held.
        log_event(action='skipped', date=day,
                  reason=f'held_tickers failed ({ex}) — failing closed, no trading')
        print(f'[{mode}] cannot verify held positions ({ex}). No trading.',
              file=sys.stderr)
        return 1
    # ---- Phase A: verify every candidate. No money moves here; every gate
    # that does not depend on placement order runs now (books, models,
    # sizing, net-edge bar). Balance/shard collateral + placement run in
    # Phase B in rank order, so scarce capital goes to the highest-ranked
    # edge first.
    # ---- Sprint ranking: rank = net edge per unit + sprint bonus
    # (SPRINT_BONUS_CENTS iff the position settles within SPRINT_HOURS, so
    # realized P&L lands inside tonight's sprint window). Ordering
    # preference only -- never a filter, never a gate. Combos keep their
    # existing first place (one execution places N +EV legs).
    ranked = []  # (kind_rank, -rank_cents, seq, payload)
    for seq, cand in enumerate(cands):
        if cand.get('kind') == 'combo':
            payload = verify_combo_candidate(cand, held, balance_c, shard_bal)
        else:
            payload = verify_single_candidate(cand, held, balance_c)
        if payload is None:
            continue
        kind_rank = 0 if cand.get('kind') == 'combo' else 1
        ranked.append((kind_rank, -payload['rank_c'], seq, payload))
    ranked.sort(key=lambda r: (r[0], r[1], r[2]))
    # ---- Phase B: place in rank order. Collateral gates re-run here
    # because higher-ranked placements consume balance/shard funds first.
    # Portfolio exposure starts from the local log (open trades) plus
    # currently-resting official orders, then charges each placement —
    # the $10 in-play rule and the per-series / per-event correlated-risk
    # caps bind here, in rank order, best edges first.
    xp = add_resting_exposure(open_exposure())
    print(f'[{mode}] in-play exposure: ${xp["total_c"] / 100:.2f} '
          f'(cap ${MAX_IN_PLAY_CENTS / 100:.2f})')
    consec_rejects = 0
    for _, _, _, payload in ranked:
        if payload['kind'] == 'combo':
            balance_c, rejected = place_combo_candidate(
                payload, live, mode, day, held, balance_c, shard_bal, xp)
        else:
            balance_c, rejected = place_single_candidate(
                payload, live, mode, day, held, balance_c, shard_bal, xp)
        # Circuit breaker: consecutive exchange rejections mean our
        # pre-flight model is wrong (or the account is dry) — stop firing
        # orders this run instead of spraying doomed attempts. 2026-09-24
        # 08:45 CDT proved the failure mode: 18 attempts in ~9s.
        if rejected:
            consec_rejects += 1
            if consec_rejects >= MAX_CONSEC_REJECTS:
                log_event(action='circuit_breaker',
                          reason=f'{consec_rejects} consecutive exchange '
                                 f'order rejections — aborting run',
                          date=day)
                print(f'[{mode}] CIRCUIT BREAKER: {consec_rejects} consecutive '
                      f'exchange rejections — aborting run.')
                break
        else:
            consec_rejects = 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
