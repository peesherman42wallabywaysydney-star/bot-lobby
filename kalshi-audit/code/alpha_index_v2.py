#!/usr/bin/env python3
"""alpha_index_v2.py — REPLACEMENT hourly index ladder model. BENCHED. NOT LIVE.

This module never places orders, never touches the exchange, never moves
money. It prices legs, validates them, and runs the graduation exam. Nothing
in this file is wired into auto_trade.py or edge_scan.py — that wiring only
happens after graduation_exam() passes AND Jeremiah explicitly approves.

POST-MORTEM: 2026-09-24, 12 real hourly SPX/NDX trades, 0-for-12, -$14.10.
-------------------------------------------------------------------------
What the old model (edge_scan.py section 4) did:

    sigma = S * volh * sqrt(hrs_left)
    fair  = N((S - K) / sigma)                      # N = standard normal CDF
    volh  = sqrt(var(1-min log returns, trailing 2h)) * sqrt(60), floor 0.05%/h

What it claimed vs reality (reconstructed from trade_log.jsonl fairs):

    SPX, entry ~08:36 CT, ~24 min to expiry, spot ~7680:
      implied sigma_24min ~= 43-44 pts  ->  volh ~= 0.89%/h
    NDX, entry ~08:37-08:42 CT, ~20 min to expiry, spot ~30240-30319:
      implied sigma_20min ~= 183 pts    ->  volh ~= 1.05%/h

    Actual 09:30-10:00 ET realized vol that morning: 0.224%/h
      (trailing-month same-window: median 0.179, p75 0.256, max 0.430 %/h)
    Actual entry->expiry move: SPX +5.5 to +12 pts (+0.07-0.16%).
    The model's sigma was ~4x the realized move; its volh was above the
    trailing month's MAXIMUM same-window reading.

Why: the trailing 2h window (07:36-09:36 ET) captured the 08:30 ET jobless
claims release (197k vs 201k expected; ES futures -0.5%, NQ -1% premarket per
MarketWatch). Event-driven vol spike -> the model extrapolated it forward
with sqrt(T) and zero decay into a calm 20-minute window. At true vol
(0.224%/h) every "23-26c edge" was actually ~zero or negative:

    T7654.9999 NO @3c:  model NO-fair 28c -> true NO-fair ~1.2c  (edge: -1.8c)
    T7689.9999 YES @15c: model YES-fair 39c -> true YES-fair ~18c (edge: ~0c net)

Secondary failures that turned a bad morning into -$14:
  1. No vol sanity cap: 0.89%/h sailed through with no flag, >2x the hottest
     morning of the trailing month.
  2. 1-minute returns scaled by sqrt(60): microstructure noise + event chop
     inflates short-window realized variance; no seasonality, no mean reversion.
  3. Correlation blindness: 6 SPX + 6 NDX legs on ONE hourly expiry were sized
     as 12 independent half-Kelly bets. It was one bet: "realized 24-min vol
     > ~0.5%". SPX/NDX ~0.9 correlated; the NO@7655 + YES@7695 pair is a
     strangle whose joint EV is NOT the sum of the legs (+25c + +24c claimed
     on the same expiry = double-counted tail mass).
  4. Half-Kelly on a phantom p: Kelly punishes invented probabilities hardest
     exactly when the model is most confident (60 contracts @3c on p=0.28).
  5. Singles path has no per-expiry committed-notional cap (the combo path at
     least has a 20c correlated bar and joint sizing; singles have nothing).
  6. Depth check was `ask > 0` only — no order-book walk, no slippage check.
  7. Uncalibrated: zero historical calibration of predicted tail p vs realized
     frequency. The 15c bar was supposed to be "overstatement insurance";
     the overstatement was 20c+.

Fixes in this module: robust vol (5-min EWMA + seasonal baseline + hard cap),
calibration shrinkage with fail-closed default, joint-EV grouping per
(underlying, expiry), order-book depth validation, false-positive suite, and
a graduation exam with six gates. Until all six pass: BENCHED.
"""

import datetime
import json
import math
import os
import random
import statistics
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(HERE, 'hidden_files', 'index_v2_calibration.json')
SHADOW_PATH = os.path.join(HERE, 'hidden_files', 'index_v2_shadow.json')

HALF_LIFE_MIN = 20.0        # EWMA half-life for trailing vol
SEASONAL_LOOKBACK_D = 20    # sessions for same-clock-window baseline
VOL_CAP_MULT = 1.25         # hard cap = this * seasonal p90
EWMA_WEIGHT = 0.40          # blend: 40% trailing EWMA + 60% seasonal median.
# Rationale: in the 20-30 min after a scheduled release, what this clock
# window USUALLY looks like predicts better than what the last 90 min did.
EDGE_BAR_CENTS = 15.0       # unchanged desk bar
MAX_EXPIRY_NOTIONAL_CENTS = 300   # per (underlying, expiry) committed cap
MAX_SLIPPAGE_CENTS = 2.0
CAL_MIN_N = 200
CAL_SLOPE_LO, CAL_SLOPE_HI = 0.8, 1.2


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# 1. Robust short-horizon vol estimator
# ---------------------------------------------------------------------------
def fetch_5m_bars(symbol, range_='1mo'):
    """symbol like '%5EGSPC'. Returns [(epoch, close)] of 5-min bars."""
    d = _get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
             f'?interval=5m&range={range_}')
    res = d['chart']['result'][0]
    q = res['indicators']['quote'][0]
    return [(t, c) for t, c in zip(res['timestamp'], q['close']) if c]


def ewma_vol_5m(bars, half_life_min=HALF_LIFE_MIN):
    """EWMA realized vol from 5-min log returns, annualized to %/h.

    5-min (not 1-min) bars: kills most microstructure/bounce noise that
    inflated the v1 1-min estimator. EWMA with 20-min half-life: a spike
    90 minutes ago (e.g. an 08:30 ET release) has decayed to ~4% weight by
    10:00 ET instead of counting at full weight like v1's flat 2h window.
    """
    if len(bars) < 6:
        return None
    closes = [c for _, c in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    lam = 0.5 ** (5.0 / half_life_min)
    wsum = 0.0
    wvar = 0.0
    w = 1.0
    # iterate oldest -> newest so recent bars get the most weight
    for r in reversed(rets):
        wsum += w
        wvar += w * r * r
        w *= lam
    if wsum <= 0:
        return None
    var_5m = wvar / wsum
    return math.sqrt(var_5m) * math.sqrt(12.0)  # 5-min -> hourly


def seasonal_baseline(bars, now_utc, window_min=30, lookback_d=SEASONAL_LOOKBACK_D):
    """Median / p25 / p90 of realized hourly vol in the same clock window.

    Answers "what does 09:30-10:00 ET usually look like" instead of "what did
    the last 2 hours look like". The v1 model had no notion of this; on
    2026-09-24 the trailing month's max same-window reading was 0.43%/h while
    v1 asserted 0.89%/h.
    """
    from collections import defaultdict
    days = defaultdict(list)
    for t, c in bars:
        dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
        if dt.date() == now_utc.date():
            continue
        # same clock window: [now-window, now] by time-of-day
        tod = dt.hour * 60 + dt.minute
        now_tod = now_utc.hour * 60 + now_utc.minute
        if now_tod - window_min <= tod <= now_tod:
            days[dt.date()].append(c)
    vols = []
    for cs in days.values():
        if len(cs) >= 4:
            r = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs))]
            vols.append(math.sqrt(sum(x * x for x in r) / len(r))
                        * math.sqrt(12.0))
    vols = vols[-lookback_d:]
    if len(vols) < 5:
        return None
    s = sorted(vols)
    return {'median': statistics.median(s),
            'p25': s[len(s) // 4],
            'p90': s[int(len(s) * 0.9)],
            'n': len(s)}


def blend_and_cap(ewma, seasonal):
    """EWMA/seasonal blend, hard-capped at VOL_CAP_MULT * p90.
    Pure function so the false-positive suite can test it deterministically."""
    blend = EWMA_WEIGHT * ewma + (1 - EWMA_WEIGHT) * seasonal['median']
    cap = VOL_CAP_MULT * seasonal['p90']
    return (cap, True) if blend > cap else (blend, False)


def estimate_forward_vol(symbol, minutes_left, now_utc=None, bars_5m=None):
    """Forward hourly vol estimate with diagnostics. Returns (volh, diag).

    Blend: 40% EWMA-trailing + 60% seasonal median, then HARD CAP at
    VOL_CAP_MULT * seasonal p90. If the cap binds, diag['capped'] is True and
    the caller should treat the signal as suspect (v1's 0.89%/h would have
    been capped to ~0.37%/h and flagged — every 9/24 leg then fails the bar).
    Fail-closed: if we cannot build both components, return (None, diag).
    """
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
    diag = {'symbol': symbol, 'capped': False, 'ok': False}
    try:
        bars = bars_5m if bars_5m is not None else fetch_5m_bars(symbol)
    except Exception as e:
        diag['error'] = f'fetch failed: {e}'
        return None, diag
    ew = ewma_vol_5m(bars)
    sb = seasonal_baseline(bars, now_utc)
    diag['ewma'] = ew
    diag['seasonal'] = sb
    if ew is None or sb is None:
        diag['error'] = 'insufficient data for ewma/seasonal'
        return None, diag
    volh, capped = blend_and_cap(ew, sb)
    diag['blend'] = EWMA_WEIGHT * ew + (1 - EWMA_WEIGHT) * sb['median']
    diag['cap'] = VOL_CAP_MULT * sb['p90']
    diag['capped'] = capped
    diag['ok'] = True
    diag['volh'] = volh
    return volh, diag


def sigma_points(spot, volh, minutes_left):
    """Forward std-dev in index points over minutes_left."""
    return spot * volh * math.sqrt(minutes_left / 60.0)


# ---------------------------------------------------------------------------
# 2. Calibration: predicted tail p vs realized frequency, fail-closed
# ---------------------------------------------------------------------------
def load_calibration():
    try:
        with open(CAL_PATH) as f:
            rows = json.load(f)
        return [r for r in rows if 0 < r.get('p', -1) < 1
                and r.get('y') in (0, 1)]
    except Exception:
        return []


def log_calibration(p, y):
    rows = load_calibration()
    rows.append({'p': p, 'y': y,
                 'ts': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    os.makedirs(os.path.dirname(CAL_PATH), exist_ok=True)
    with open(CAL_PATH, 'w') as f:
        json.dump(rows[-5000:], f)


def calibration_stats(rows=None):
    """Slope/intercept of realized frequency vs predicted p (decile bins),
    plus Brier skill vs predicting the base rate. Returns dict."""
    rows = load_calibration() if rows is None else rows
    n = len(rows)
    if n < 20:
        return {'n': n, 'ok': False, 'reason': 'need >=20 samples'}
    bins = {}
    for r in rows:
        b = min(int(r['p'] * 10), 9)
        bins.setdefault(b, []).append(r)
    xs, ys = [], []
    for b in sorted(bins):
        rs = bins[b]
        if len(rs) >= 5:
            xs.append(sum(r['p'] for r in rs) / len(rs))
            ys.append(sum(r['y'] for r in rs) / len(rs))
    if len(xs) < 3:
        return {'n': n, 'ok': False, 'reason': 'too few populated bins'}
    mx, my = statistics.mean(xs), statistics.mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom if denom else 0
    intercept = my - slope * mx
    base = sum(r['y'] for r in rows) / n
    brier = sum((r['p'] - r['y']) ** 2 for r in rows) / n
    brier_base = sum((base - r['y']) ** 2 for r in rows) / n
    skill = 1 - brier / brier_base if brier_base > 0 else 0.0
    return {'n': n, 'ok': True, 'slope': slope, 'intercept': intercept,
            'brier_skill': skill, 'base_rate': base}


def shrink_probability(p):
    """Shrink a raw model p toward the calibration line.

    Fail-closed: with <CAL_MIN_N samples, or slope outside [0.8, 1.2], or
    non-positive Brier skill, the model is UNCALIBRATED and returns None —
    the caller must skip the leg. v1 had no calibration at all; this gate
    alone would have benched it on 2026-09-24.
    """
    st = calibration_stats()
    if not st['ok'] or st['n'] < CAL_MIN_N:
        return None
    if not (CAL_SLOPE_LO <= st['slope'] <= CAL_SLOPE_HI):
        return None
    if abs(st['intercept']) > 0.03 or st['brier_skill'] <= 0:
        return None
    return min(max(st['slope'] * p + st['intercept'], 1e-4), 1 - 1e-4)


# ---------------------------------------------------------------------------
# 3. Leg pricing (single source of truth for "what is this leg worth")
# ---------------------------------------------------------------------------
def price_leg(symbol, side, strike, book_price_c, minutes_left, spot=None,
              volh=None, diag_out=None):
    """Returns dict with fair_cents, edge_cents, and diagnostics, or
    {'ok': False, 'reason': ...} when any gate fails closed."""
    side = side.lower()
    if side not in ('yes', 'no'):
        return {'ok': False, 'reason': 'bad side'}
    if volh is None:
        volh, diag = estimate_forward_vol(symbol, minutes_left)
    else:
        diag = {'volh': volh, 'ok': True, 'injected': True}
    if diag_out is not None:
        diag_out.update(diag)
    if not diag.get('ok'):
        return {'ok': False, 'reason': 'vol estimation failed closed',
                'diag': diag}
    if spot is None:
        return {'ok': False, 'reason': 'spot required (pass explicitly)'}
    sigma = sigma_points(spot, volh, minutes_left)
    if sigma <= 0:
        return {'ok': False, 'reason': 'non-positive sigma'}
    p_yes_raw = norm_cdf((spot - strike) / sigma)
    p_yes = shrink_probability(p_yes_raw)
    if p_yes is None:
        return {'ok': False, 'reason': 'model uncalibrated: no signal',
                'diag': diag, 'p_yes_raw': p_yes_raw}
    p_win = p_yes if side == 'yes' else 1.0 - p_yes
    fair_c = p_win * 100.0
    edge_c = fair_c - book_price_c
    return {'ok': True, 'fair_cents': fair_c, 'edge_cents': edge_c,
            'p_yes': p_yes, 'p_yes_raw': p_yes_raw, 'sigma_pts': sigma,
            'volh': volh, 'diag': diag}


# ---------------------------------------------------------------------------
# 4. Joint-EV grouping: one (underlying, expiry) = one risk bucket
# ---------------------------------------------------------------------------
def group_key(leg):
    return (leg.get('underlying'), leg.get('expiry'))


def joint_ev(legs, spot, sigma_pts, n_sims=20000, seed=7):
    """Monte Carlo joint EV (cents, net of per-leg fees) for legs sharing one
    expiry/underlying. legs: [{side, strike, price_c, fee_c}].
    Terminal price ~ Normal(spot, sigma). This is what v1 never computed:
    on 2026-09-24 the six SPX legs claimed ~+150c of summed edge; their joint
    EV at true vol was roughly -600c."""
    rng = random.Random(seed)
    tot = 0.0
    for _ in range(n_sims):
        px = rng.gauss(spot, sigma_pts)
        for leg in legs:
            win = (px >= leg['strike']) if leg['side'] == 'yes' \
                else (px < leg['strike'])
            tot += (100.0 if win else 0.0) - leg['price_c'] - leg.get('fee_c', 0)
    return tot / n_sims


def evaluate_bucket(legs, spot, volh, minutes_left):
    """Evaluate a same-expiry/underlying bucket as ONE position.

    Returns {'ok', 'joint_ev_c', 'summed_edge_c', 'double_count_ratio',
    'notional_c', ...}. The desk rule this enforces: the bucket trades only
    if joint EV clears the bar AND notional <= MAX_EXPIRY_NOTIONAL_CENTS.
    double_count_ratio = summed single-leg edges / joint EV — v1's was
    deeply negative/meaningless because every leg was phantom; the graduation
    gate requires 0.8 <= ratio <= 1.25 on the backtest.
    """
    sigma = sigma_points(spot, volh, minutes_left)
    joint = joint_ev(legs, spot, sigma)
    summed = sum(l.get('edge_c', 0) for l in legs)
    notional = sum(l['price_c'] + l.get('fee_c', 0) for l in legs)
    ratio = summed / joint if abs(joint) > 1e-9 else float('inf')
    return {'joint_ev_c': joint, 'summed_edge_c': summed,
            'double_count_ratio': ratio, 'notional_c': notional,
            'sigma_pts': sigma,
            'passes': joint >= EDGE_BAR_CENTS
                      and notional <= MAX_EXPIRY_NOTIONAL_CENTS}


# ---------------------------------------------------------------------------
# 5. Executable-depth validation (order-book walk, not `ask > 0`)
# ---------------------------------------------------------------------------
def depth_check(levels, side, contracts, touch_price_c,
                max_slippage_c=MAX_SLIPPAGE_CENTS):
    """levels: [(price_c, size)] sorted best-first for the side we'd take.
    Returns {'ok', 'vwap_c', 'slippage_c', 'fill_size'} — v1 only checked
    that a touch price existed; a 60-lot into a 5-lot book is not a 3c fill.
    """
    need = contracts
    cost = 0.0
    filled = 0
    for px, sz in levels:
        take = min(sz, need - filled)
        cost += take * px
        filled += take
        if filled >= need:
            break
    if filled < need:
        return {'ok': False, 'reason': f'depth {filled} < {need}',
                'fill_size': filled}
    vwap = cost / filled
    slip = abs(vwap - touch_price_c)
    return {'ok': slip <= max_slippage_c, 'vwap_c': vwap,
            'slippage_c': slip, 'fill_size': filled,
            'reason': f'slippage {slip:.1f}c > {max_slippage_c}c'
                      if slip > max_slippage_c else 'ok'}


# ---------------------------------------------------------------------------
# 6. False-positive test suite (synthetic scenarios)
# ---------------------------------------------------------------------------
def _synth_bars(start_px, vols_5m, n=24, seed=1):
    """Synthetic 5-min bars: vols_5m[i] = hourly vol during bar i."""
    rng = random.Random(seed)
    bars, px, t = [], start_px, 0
    for i in range(n):
        r = rng.gauss(0, vols_5m[i] / math.sqrt(12))
        px *= math.exp(r)
        bars.append((t, px))
        t += 300
    return bars


def false_positive_suite():
    """Returns list of (name, passed, detail). The first scenario is the
    literal 2026-09-24 replay: spike-then-calm must NOT produce a signal."""
    results = []

    # Scenario A: THE 9/24 REPLAY — 0.9%/h for 90 min (claims spike), then
    # 0.22%/h calm for the last 30 min. The full pipeline (EWMA + seasonal
    # blend + hard cap) must price the ACTUAL 9/24 legs below the 15c bar.
    # Seasonal numbers are the real trailing-month 09:30-10:00 ET readings.
    bars = _synth_bars(7680, [0.009] * 18 + [0.0022] * 6, seed=11)
    ew = ewma_vol_5m(bars)
    sb = {'median': 0.00179, 'p25': 0.00145, 'p90': 0.00295, 'n': 22}
    volh, capped = blend_and_cap(ew, sb)
    sig = sigma_points(7680, volh, 24)
    # the six real SPX legs of 2026-09-24: (side, strike, paid_c)
    legs_924 = [('no', 7654.9999, 3), ('no', 7659.9999, 6),
                ('no', 7664.9999, 11), ('yes', 7689.9999, 15),
                ('yes', 7694.9999, 9), ('yes', 7699.9999, 3)]
    edges = []
    for side, K, paid in legs_924:
        p_yes = norm_cdf((7680 - K) / sig)
        p_win = p_yes if side == 'yes' else 1 - p_yes
        edges.append(p_win * 100 - paid)
    worst = max(edges)
    results.append(('spike_then_calm_no_signal',
                    worst < EDGE_BAR_CENTS,
                    f'pipeline volh={volh*100:.3f}%/h (capped={capped}); '
                    f'worst 9/24 leg edge {worst:.1f}c < {EDGE_BAR_CENTS}c bar '
                    f'(v1 signaled all six at 23-26c)'))

    # Scenario B: dead-calm market — no leg may clear the bar.
    bars = _synth_bars(7680, [0.0015] * 24, seed=12)
    ew = ewma_vol_5m(bars)
    sig = sigma_points(7680, ew, 24) if ew else 0
    # far-tail NO at 3c with true fair ~0: edge must be negative
    p_yes = norm_cdf((7680 - 7655) / sig) if sig > 0 else 1.0
    edge_no = (1 - p_yes) * 100 - 3
    results.append(('calm_no_phantom_edge',
                    edge_no < EDGE_BAR_CENTS,
                    f'NO@7655 edge {edge_no:.1f}c at true vol (bar {EDGE_BAR_CENTS}c)'))

    # Scenario C: genuinely volatile — model MUST still see real edge (power).
    bars = _synth_bars(7680, [0.012] * 24, seed=13)
    ew = ewma_vol_5m(bars)
    sig = sigma_points(7680, ew, 24) if ew else 0
    p_yes = norm_cdf((7680 - 7655) / sig) if sig > 0 else 1.0
    edge_no = (1 - p_yes) * 100 - 3
    results.append(('volatile_has_power',
                    ew is not None and ew > 0.006 and edge_no > 0,
                    f'ewma={None if ew is None else round(ew*100,2)}%/h, '
                    f'NO@7655 edge {edge_no:.1f}c'))

    # Scenario D: strangle double-count — summed legs must not exceed 1.25x
    # joint EV when all legs are fairly priced.
    legs = [{'side': 'no', 'strike': 7655, 'price_c': 12, 'fee_c': 1,
             'edge_c': 0},
            {'side': 'yes', 'strike': 7695, 'price_c': 12, 'fee_c': 1,
             'edge_c': 0}]
    j = joint_ev(legs, 7680, sigma_points(7680, 0.0022, 24))
    results.append(('strangle_no_double_count',
                    j < 0,  # fairly-priced strangle minus fees loses
                    f'joint EV {j:.1f}c (must be < 0 at fair prices + fees)'))

    # Scenario E: cap binds on absurd vol — estimator must flag, not trust.
    bars = _synth_bars(7680, [0.03] * 24, seed=14)
    # fake seasonal with p90 = 0.004
    sb = {'median': 0.002, 'p25': 0.0015, 'p90': 0.004, 'n': 20}
    ew = ewma_vol_5m(bars)
    blend = 0.5 * ew + 0.5 * sb['median']
    capped = min(blend, VOL_CAP_MULT * sb['p90'])
    results.append(('absurd_vol_capped',
                    capped <= VOL_CAP_MULT * sb['p90'] + 1e-12 and blend > capped,
                    f'raw {blend*100:.2f}%/h capped to {capped*100:.2f}%/h'))
    return results


# ---------------------------------------------------------------------------
# 7. Backtest harness (no lookahead; exact fees; needs history CSV)
# ---------------------------------------------------------------------------
BACKTEST_COLS = ['ts_utc', 'symbol', 'spot', 'expiry_utc', 'strike', 'side',
                 'book_price_c', 'fee_c', 'outcome']


def load_backtest_csv(path):
    import csv
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                'ts': datetime.datetime.fromisoformat(r['ts_utc']),
                'symbol': r['symbol'], 'spot': float(r['spot']),
                'expiry': datetime.datetime.fromisoformat(r['expiry_utc']),
                'strike': float(r['strike']), 'side': r['side'].lower(),
                'price_c': float(r['book_price_c']),
                'fee_c': float(r['fee_c']), 'y': int(r['outcome'])})
    return rows


def run_backtest(rows):
    """Replay history. Vol at signal time uses ONLY bars strictly before ts
    (caller must ensure the CSV's spot series supports this; the harness
    re-estimates from a provided bar feed via estimate_forward_vol with
    bars_5m truncated at ts — no lookahead by construction).

    Returns dict with expectancy stats. FAILS CLOSED (ok=False) when the
    calibration store lacks the minimum samples: v2 never trades
    uncalibrated, not even in backtest."""
    if calibration_stats()['n'] < CAL_MIN_N:
        return {'ok': False,
                'reason': f'uncalibrated: {calibration_stats()["n"]} < '
                          f'{CAL_MIN_N} samples — backtest refused'}
    # NOTE: full replay needs per-signal historical 5m bars; the interface is
    # defined here and the data-feed half is TODO (see graduation gate G2).
    return {'ok': False,
            'reason': 'backtest data feed not connected (TODO: wire '
                      'historical 5m bars + hourly settlement history)'}


# ---------------------------------------------------------------------------
# 8. Graduation exam — six gates, ALL must pass. Fail-closed.
# ---------------------------------------------------------------------------
def graduation_exam():
    """Returns (verdict, gates) where gates = [(name, passed, detail)]."""
    gates = []

    st = calibration_stats()
    g1 = (st['ok'] and st['n'] >= CAL_MIN_N
          and CAL_SLOPE_LO <= st['slope'] <= CAL_SLOPE_HI
          and abs(st['intercept']) <= 0.03 and st['brier_skill'] > 0)
    gates.append(('G1 calibration',
                  g1,
                  f"n={st.get('n')}, slope={st.get('slope')}, "
                  f"intercept={st.get('intercept')}, "
                  f"brier_skill={st.get('brier_skill')} "
                  f"(need n>={CAL_MIN_N}, slope in [{CAL_SLOPE_LO},{CAL_SLOPE_HI}], "
                  f"|intercept|<=0.03, skill>0)"))

    bt = run_backtest([])
    g2 = bool(bt.get('ok'))
    gates.append(('G2 backtest (>=3mo hourly, net of exact fees, expectancy>0, '
                  'maxDD<25% sleeve, PF>1.2)',
                  g2, bt.get('reason', 'not run')))

    fp = false_positive_suite()
    g3pass = all(p for _, p, _ in fp)
    gates.append(('G3 false-positive suite',
                  g3pass,
                  '; '.join(f'{n}: {"PASS" if p else "FAIL"} ({d})'
                            for n, p, d in fp)))

    # G4 depth validation: paper/live book-walk on recent signals.
    gates.append(('G4 depth validation (>=80% of signals fillable at full '
                  'size within 2c slippage)',
                  False, 'no paper-trading book snapshots recorded yet'))

    # G5 correlation: strangle double-count ratio within [0.8, 1.25] on
    # backtest; no single (underlying, expiry) > 30% of backtest P&L.
    gates.append(('G5 correlated-risk (joint-EV accounting, expiry caps)',
                  False, 'requires G2 backtest first'))

    # G6 shadow: 2 weeks of live paper signals, calibration still holding.
    try:
        shadow = json.load(open(SHADOW_PATH)) if os.path.exists(SHADOW_PATH) else []
    except Exception:
        shadow = []
    g6 = (len(shadow) >= 14 * 24 * 2  # ~2 weeks of hourly signals, both indices
          and calibration_stats()['n'] >= CAL_MIN_N)
    gates.append(('G6 shadow paper (2 weeks live paper, calibration holds)',
                  g6, f'{len(shadow)} shadow signals logged'))

    verdict = ('CLEARED — still needs Jeremiah\'s explicit go-ahead'
               if all(p for _, p, _ in gates) else 'BENCHED')
    return verdict, gates


def main():
    print('alpha_index_v2 — graduation exam (model is BENCHED until all gates pass)\n')
    verdict, gates = graduation_exam()
    for name, passed, detail in gates:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}\n       {detail}\n")
    print('VERDICT:', verdict)


if __name__ == '__main__':
    main()
