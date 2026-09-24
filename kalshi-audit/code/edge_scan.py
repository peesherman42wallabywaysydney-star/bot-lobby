#!/usr/bin/env python3
"""Kalshi edge scanner — fast version. Uses nested markets (bid/ask inline), one API call per event."""
import json, math, re, sys, time, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)

def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

NOW_UTC = datetime.datetime.now(datetime.timezone.utc)
EDGES = []

def edge(msg):
    EDGES.append(msg)
    print('EDGE:', msg)


# ---------------- structured legs for the combo constructor (§9) ----------------
# Sections with probabilistic single-ticker edges call record_leg() next to
# every edge() call. pay_cents = actual cents we'd pay for `side`;
# fair_yes in [0,1]. Deterministic/result-set legs (WX, SWEEP) and multi-leg
# flags are deliberately NOT recorded — combos are built from live models.
STRUCT_LEGS = []


def record_leg(asset, side, ticker, fair_yes, pay_cents, kind, strike=None):
    if not (0 < pay_cents < 100):
        return
    if not (0 <= fair_yes <= 1):
        return
    STRUCT_LEGS.append({'asset': asset, 'side': side, 'ticker': ticker,
                        'fair_yes': fair_yes, 'pay_cents': pay_cents,
                        'kind': kind, 'strike': strike})

def evs_for(series):
    try:
        return get(f'https://api.elections.kalshi.com/trade-api/v2/events?series_ticker={series}&status=open&limit=30').get('events', [])
    except Exception:
        return []

def event_nested(et):
    try:
        return get(f'https://api.elections.kalshi.com/trade-api/v2/events/{et}?with_nested_markets=true')['event']
    except Exception:
        return None

def spot(ids):
    # Coinbase spot — fast, no key, no rate-limit pain (CoinGecko was timing out the scan)
    out = {}
    mapping = {'bitcoin': 'BTC', 'ethereum': 'ETH', 'solana': 'SOL'}
    for cid in ids:
        sym = mapping.get(cid, cid)
        try:
            d = get(f'https://api.coinbase.com/v2/prices/{sym}-USD/spot')
            out[cid] = float(d['data']['amount'])
        except Exception:
            pass
    return out

T0 = datetime.datetime.now(datetime.timezone.utc)
def time_left():
    return 240 - (datetime.datetime.now(datetime.timezone.utc) - T0).total_seconds()

# Trailing-30m realized hourly vol from Coinbase 1m candles, per symbol.
# Crypto fair values must never be MORE confident than recent realized vol
# justifies — during a directional crash the fixed assumptions (0.35%/h BTC
# etc.) print phantom "edges" on both sides of the ladder as the market
# prices tail risk the thin-tailed model can't see (2026-09-23: BTC realized
# hit 0.97%/h vs 0.35% assumed; ETH 1.19%/h vs 0.40%). Use max(assumed,
# realized) everywhere a fixed crypto vol feeds a fair value.
_rvol_cache = {}
def realized_volh(sym):
    """Returns (hourly_vol, drift_30m) from trailing-30m Coinbase 1m candles.
    (None, None) on failure."""
    if sym in _rvol_cache:
        return _rvol_cache[sym]
    v, drift = None, None
    try:
        d = get(f'https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=60')
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

def crypto_regime_ok(sym, coin_label):
    """False during crash/meltup regimes where the zero-drift lognormal model
    is invalid: |30m drift| > 1% means the market is pricing directional risk
    the model can't see. Skip the coin entirely in that case."""
    v, drift = realized_volh(sym)
    if drift is not None and abs(drift) > 0.01:
        print(f'skipping {coin_label}: crash/meltup regime, 30m drift {drift*100:+.2f}%', file=sys.stderr)
        return False
    return True

TODAY = NOW_UTC.strftime('%y%b%d').upper()  # e.g. 26SEP22 — date-dynamic

# ---------- 1. Crypto 15-min markets ----------
try:
    px = spot(['bitcoin', 'ethereum', 'solana'])
    cfg = {'BTC': ('bitcoin', 'KXBTC15M', 0.0011), 'ETH': ('ethereum', 'KXETH15M', 0.0013), 'SOL': ('solana', 'KXSOL15M', 0.0018)}
    for coin, (cid, series, vol15) in cfg.items():
        S = px.get(cid)
        if not S:
            continue
        sym = {'BTC': 'BTC', 'ETH': 'ETH', 'SOL': 'SOL'}[coin]
        if not crypto_regime_ok(sym, coin):
            continue
        rv, _ = realized_volh(sym)
        vol15_eff = max(vol15, (rv / 2) if rv else 0)  # hourly -> 15-min scale
        for e in evs_for(series)[:4]:
            et = e.get('event_ticker', '')
            m = re.search(r'-(\d{2})(\d{2})$', et)  # HHMM ET close
            if not m:
                continue
            hh, mm = int(m.group(1)), int(m.group(2))
            close = datetime.datetime(NOW_UTC.year, NOW_UTC.month, NOW_UTC.day, hh + 4, mm, tzinfo=datetime.timezone.utc)
            mins_left = (close - NOW_UTC).total_seconds() / 60
            if mins_left < 2 or mins_left > 20:
                continue
            ev = event_nested(et)
            if not ev:
                continue
            for mk in ev.get('markets', []):
                t = mk.get('ticker', '')
                tm = re.search(r'-T([\d\.]+)$', t)
                if not tm:
                    continue
                target = float(tm.group(1))
                ask = float(mk.get('yes_ask_dollars') or 0); bid = float(mk.get('yes_bid_dollars') or 0)
                if ask >= 1 or ask <= 0:
                    continue
                sigma = S * vol15_eff * math.sqrt(mins_left / 15)
                fair = N((S - target) / sigma) if sigma > 0 else 0.5
                if fair - ask >= 0.10:
                    edge(f'{coin} 15m YES {t} ask {ask*100:.0f}c vs fair {fair:.0%} ({mins_left:.0f}min left, spot {S:,.2f})')
                    record_leg(coin, 'yes', t, fair, ask*100, 'crypto15m', target)
                elif bid >= 0.10 and bid - fair >= 0.10:
                    edge(f'{coin} 15m NO {t} — YES bid {bid*100:.0f}c vs fair {fair:.0%} ({mins_left:.0f}min left)')
                    record_leg(coin, 'no', t, fair, (1-bid)*100, 'crypto15m', target)
except Exception as ex:
    print('crypto15m check failed:', ex, file=sys.stderr)

# ---------- 2. Crypto daily rungs near spot (3pm/5pm closes) ----------
try:
    px = spot(['bitcoin', 'ethereum', 'solana'])
    cfg = {'BTC': ('bitcoin', 'KXBTCD', 0.0035), 'ETH': ('ethereum', 'KXETHD', 0.0040), 'SOL': ('solana', 'KXSOLD', 0.0055)}
    for coin, (cid, series, volh) in cfg.items():
        S = px.get(cid)
        if not S:
            continue
        sym = {'BTC': 'BTC', 'ETH': 'ETH', 'SOL': 'SOL'}[coin]
        if not crypto_regime_ok(sym, coin):
            continue
        rv, _ = realized_volh(sym)
        volh_eff = max(volh, rv or 0)  # never more confident than realized
        for e in evs_for(series):
            et = e.get('event_ticker', '')
            m = re.search(TODAY[2:] + r'(\d{2})$', et)
            if not m:
                continue
            close_et = int(m.group(1))
            # NOTE 2026-09-23: close_et is a 24h ET hour. Old code did
            # close_et+4 inline, which throws ValueError when >= 24
            # (e.g. a 10pm ET close) and mislabeled everything "pmET"
            # (a 3am close printed as "3pmET", which misled verification
            # into using the wrong expiry). Handle rollover + label right.
            close_utc = datetime.datetime(NOW_UTC.year, NOW_UTC.month, NOW_UTC.day, tzinfo=datetime.timezone.utc) \
                + datetime.timedelta(hours=close_et + 4)
            hrs_left = (close_utc - NOW_UTC).total_seconds() / 3600
            ampm = 'am' if close_et < 12 else 'pm'
            et_label = f'{close_et % 12 or 12}{ampm}ET'
            if hrs_left < 0.05 or hrs_left > 12:
                continue
            ev = event_nested(et)
            if not ev:
                continue
            for mk in ev.get('markets', []):
                t = mk.get('ticker', '')
                tm = re.search(r'-T([\d\.]+)$', t)
                if not tm:
                    continue
                K = float(tm.group(1))
                if abs(K - S) / S > 0.02:
                    continue
                ask = float(mk.get('yes_ask_dollars') or 0); bid = float(mk.get('yes_bid_dollars') or 0)
                if ask >= 1 or ask <= 0:
                    continue
                sigma = S * volh_eff * math.sqrt(hrs_left)
                fair = N((S - K) / sigma) if sigma > 0 else 0.5
                if fair - ask >= 0.10:
                    edge(f'{coin} {et_label} YES {t} ask {ask*100:.0f}c vs fair {fair:.0%} ({hrs_left:.1f}h left, spot {S:,.2f})')
                    record_leg(coin, 'yes', t, fair, ask*100, 'cryptodaily', K)
                elif bid >= 0.10 and bid - fair >= 0.10:
                    edge(f'{coin} {et_label} NO {t} — YES bid {bid*100:.0f}c vs fair {fair:.0%} ({hrs_left:.1f}h left)')
                    record_leg(coin, 'no', t, fair, (1-bid)*100, 'cryptodaily', K)
except Exception as ex:
    print('cryptoD check failed:', ex, file=sys.stderr)

# ---------- 2b. DOGE/XRP daily brackets: bucket-sum check (LIVE bids, not stale lasts) ----------
# NOTE 2026-09-22: last_price_dollars on these brackets goes stale (e.g. DOGE
# B0.097 showed last 78c vs live 55/66 book), producing phantom "field
# mispriced" flags. Sum live YES bids instead: for mutually-exclusive brackets
# sum(bids) should sit just under 1.00. Flag only real dislocations.
try:
    for series in ['KXDOGE', 'KXXRP']:
        for e in evs_for(series):
            et = e.get('event_ticker', '')
            if not re.search(TODAY[2:] + r'\d{2}$', et):
                continue
            ev = event_nested(et)
            if not ev:
                continue
            total = 0; ask_total = 0; favp = 0; favt = ''
            for mk in ev.get('markets', []):
                b = float(mk.get('yes_bid_dollars') or 0)
                total += b
                # NOTE 2026-09-22: bid-sum flags are phantoms when the ask side is
                # dead (stale/no-liquidity asks summed to $2-$16). A missing ask
                # counts as 1.00 (unbuyable) so the gate only passes executable books.
                a = mk.get('yes_ask_dollars')
                ask_total += float(a) if a else 1.0
                if b > favp:
                    favp = b; favt = mk.get('ticker', '')
            if total > 0 and ((total < 0.85 and ask_total < 0.95) or total > 1.05):
                edge(f'{et} live bid sum={total:.2f} ask sum={ask_total:.2f} (fav {favt}={favp:.0%}) — field mispriced')
except Exception as ex:
    print('dogexrp check failed:', ex, file=sys.stderr)

# ---------- 3. Weather HIGH today: DISABLED 2026-09-22 ----------
# Root cause: used Open-Meteo current temp, but Kalshi settles on The Weather
# Company's daily HIGH/LOW. Current temp != daily high, and Open-Meteo != TWC.
# Generated a false Dallas edge (claimed 96.3F, actual KDFW 93.2F). Do not
# re-enable until we have The Weather Company settlement-source data.
# (Original code preserved in git history if needed.)

# ---------- 4. Index/commodity hourly+daily ladders (ADAPTIVE vol from realized) ----------
if time_left() < 60:
    print('skipping index ladders: time budget', file=sys.stderr)
else:
    try:
        def realized_hourly_vol(yahoo_sym):
            try:
                d = get(f'https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1m&range=2h')
                res = d['chart']['result'][0]
                closes = [c for c in res['indicators']['quote'][0]['close'] if c]
                ts = res.get('timestamp', [])
                # STALENESS CHECK: last bar must be within 5 min of now (Yahoo futures often freeze)
                if not ts or not closes or len(closes) < 20:
                    return None, None
                last_ts = datetime.datetime.fromtimestamp(ts[-1], datetime.timezone.utc)
                if (NOW_UTC - last_ts).total_seconds() > 300:
                    return None, None
                rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
                mean = sum(rets) / len(rets)
                var = sum((r - mean) ** 2 for r in rets) / len(rets)
                return max(math.sqrt(var) * math.sqrt(60), 0.0005), closes[-1]
            except Exception:
                return None, None

        idx_cfgs = [
            ('GOLD', 'KXGOLDH', 'GC=F', r'-T([\d\.]+)$', 0.006),
            ('GOLD', 'KXGOLDD', 'GC=F', r'-T([\d\.]+)$', 0.006),
            ('SPX', 'KXINXU', '%5EGSPC', r'-T([\d\.]+)$', 0.004),
            ('SPX', 'KXINX', '%5EGSPC', r'-T([\d\.]+)$', 0.004),
            ('NDX', 'KXNASDAQ100U', '%5ENDX', r'-T([\d\.]+)$', 0.005),
            ('WTI', 'KXWTIH', 'CL=F', r'-T([\d\.]+)$', 0.006),
            ('SILVER', 'KXSILVERH', 'SI=F', r'-T([\d\.]+)$', 0.008),
        ]
        for name, series, ysym, tpat, band in idx_cfgs:
            volh, S = realized_hourly_vol(ysym)
            if not volh or not S:
                continue
            for e in evs_for(series)[:4]:
                et = e.get('event_ticker', '')
                # parse close hour from ticker suffix
                m = re.search(TODAY[2:] + r'(?:H)?(\d{2,4})$', et)
                if not m:
                    continue
                suf = m.group(1)
                ch = int(suf[:2])  # ET close hour
                close_utc = datetime.datetime(NOW_UTC.year, NOW_UTC.month, NOW_UTC.day, ch + 4, tzinfo=datetime.timezone.utc)
                hrs_left = (close_utc - NOW_UTC).total_seconds() / 3600
                if hrs_left < 0.03 or hrs_left > 14:
                    continue
                ev = event_nested(et)
                if not ev:
                    continue
                for mk in ev.get('markets', []):
                    t = mk.get('ticker', '')
                    tm = re.search(tpat, t)
                    if not tm:
                        continue
                    K = float(tm.group(1))
                    if abs(K - S) / S > band:
                        continue
                    ask = float(mk.get('yes_ask_dollars') or 0); bid = float(mk.get('yes_bid_dollars') or 0)
                    if ask <= 0 or ask >= 1:
                        continue
                    sigma = S * volh * math.sqrt(hrs_left)
                    fair = N((S - K) / sigma) if sigma > 0 else 0.5
                    if fair - ask >= 0.10:
                        edge(f'{name} {et} YES {t} ask {ask*100:.0f}c vs fair {fair:.0%} (spot {S:,.1f}, rvol {volh*100:.2f}%/h)')
                        record_leg(name, 'yes', t, fair, ask*100, 'index', K)
                    elif bid >= 0.10 and bid - fair >= 0.10:
                        edge(f'{name} {et} NO {t} — YES bid {bid*100:.0f}c vs fair {fair:.0%} (rvol {volh*100:.2f}%/h)')
                        record_leg(name, 'no', t, fair, (1-bid)*100, 'index', K)
    except Exception as ex:
        print('index ladder check failed:', ex, file=sys.stderr)

# ---------- 5. POLITICS: cross-venue Senate-race dislocations (Kalshi vs Polymarket) ----------
# DESIGN (2026-09-24):
#   Polling aggregation was rejected: no free live polling API exists on a
#   30s budget (538 discontinued, RCP has no API, Silver Bulletin paywalled,
#   GitHub mirrors are stale). Cross-venue dislocation is the only defensible
#   free-data signal: the same binary outcome (Dem wins / Rep wins a 2026
#   Senate race) priced on both Kalshi and Polymarket. A 10c+ roundtrip gap
#   between executable quotes is a real edge, not a model opinion.
#   Matching is mechanical and conservative: Kalshi series SENATE<ST>-26 with
#   '-D'/'-R' subticker suffixes vs the Polymarket event whose question
#   contains 'democrat(s)'/'republican(s)' + 'senate' + '2026'. Anything
#   ambiguous -> skip. Thin books (spread > 6c) -> skip. Stale PM quotes
#   (outcomePrices outside the live best bid/ask) -> skip.
#   Threshold: 10c roundtrip gap. Fees are ~1-2c/side and both venues settle
#   the same Nov-2026 election outcome, so 10c leaves a wide margin.
#   Pairs verified live 2026-09-24 (do not add a pair without verifying it):
try:
    if time_left() < 15:
        print('skipping POL: time budget', file=sys.stderr)
    else:
        POL_PAIRS = [
            ('SENATENC', 'north-carolina-senate-election-winner', 'NC-Senate'),
            ('SENATEGA', 'georgia-senate-election-winner', 'GA-Senate'),
            ('SENATENH', 'new-hampshire-senate-election-winner', 'NH-Senate'),
        ]

        def _pm_event(slug):
            # STALENESS: event must be active, unclosed, settling in the future
            try:
                d = get(f'https://gamma-api.polymarket.com/events?slug={slug}')
            except Exception:
                return None
            if not d:
                return None
            e = d[0] if isinstance(d, list) else d
            try:
                end = datetime.datetime.fromisoformat(str(e.get('endDate', '')).replace('Z', '+00:00'))
            except Exception:
                return None
            if not e.get('active') or e.get('closed') or end <= NOW_UTC:
                return None
            try:
                if float(e.get('volume') or 0) < 25000:  # dead market -> stale prices
                    return None
            except Exception:
                return None
            return e

        def _pm_side(e, side):
            # Conservative name match: exactly one market mentioning the party
            # and 'senate'/'2026', never the Person-A/B placeholders.
            want = 'democrat' if side == 'D' else 'republican'
            other = 'republican' if side == 'D' else 'democrat'
            cands = []
            for m in (e.get('markets') or []):
                q = (m.get('question') or '').lower()
                if want in q and other not in q and 'senate' in q and '2026' in q:
                    cands.append(m)
            if len(cands) != 1:
                return None
            m = cands[0]
            try:
                bb = float(m.get('bestBid')); ba = float(m.get('bestAsk'))
                op_raw = m.get('outcomePrices')
                if isinstance(op_raw, str):  # gamma sometimes returns a JSON-encoded string
                    op_raw = json.loads(op_raw)
                op = float((op_raw or [None])[0])
            except Exception:
                return None
            # STALENESS + liquidity: real two-sided book, tight spread, and the
            # reference outcomePrices must agree with the live book (gamma
            # caches aggressively; a divergence means the quote is stale).
            if not (0 < bb < ba < 1) or (ba - bb) > 0.05:
                return None
            if not (bb - 0.005 <= op <= ba + 0.005):
                return None
            return bb, ba

        for kseries, pmslug, label in POL_PAIRS:
            if time_left() < 8:
                break
            pm = _pm_event(pmslug)
            if not pm:
                print(f'POL {label}: polymarket event unavailable/stale, skipping', file=sys.stderr)
                continue
            kx_ev = None
            for ev0 in evs_for(kseries):
                et0 = ev0.get('event_ticker', '')
                if et0 == f'{kseries}-26':  # the 2026 race only, not -28
                    kx_ev = event_nested(et0)
                    break
            if not kx_ev:
                continue
            for side in ('D', 'R'):
                pmq = _pm_side(pm, side)
                if not pmq:
                    continue
                pm_bid, pm_ask = pmq
                kx_mk = None
                for mk in kx_ev.get('markets', []):
                    if mk.get('ticker', '').endswith(f'-{side}'):
                        kx_mk = mk
                        break
                if not kx_mk:
                    continue
                try:
                    kb = float(kx_mk.get('yes_bid_dollars')); ka = float(kx_mk.get('yes_ask_dollars'))
                except Exception:
                    continue
                # STALENESS + thin-book gate on Kalshi: executable two-sided
                # quotes only, spread <= 6c (rejects 51/90 zombies like
                # KXSAMEPARTYCONGRESS).
                if not (0 < kb < ka < 1) or (ka - kb) > 0.06:
                    continue
                t = kx_mk.get('ticker', '')
                gap_long = pm_bid - ka   # buy Kalshi YES at ask, sell PM YES at bid
                gap_short = kb - pm_ask  # buy Kalshi NO (sell D), buy PM YES at ask
                if gap_long >= 0.10:
                    edge(f'POL {label} {side} YES {t} ask {ka*100:.0f}c vs fair {pm_bid:.0%} '
                         f'(PM {side} bid {pm_bid*100:.0f}c, cross-venue gap {gap_long*100:.0f}c)')
                    record_leg('POL', 'yes', t, pm_bid, ka*100, 'politics')
                elif gap_short >= 0.10:
                    # NO ask = 1 - YES bid (the price we'd actually pay to buy NO)
                    no_pay = (1 - kb) * 100; no_fair = (1 - pm_ask) * 100
                    edge(f'POL {label} {side} NO {t} ask {no_pay:.0f}c vs fair {no_fair:.0f}% '
                         f'(Kalshi {side} YES bid {kb*100:.0f}c > PM {side} ask {pm_ask*100:.0f}c, gap {gap_short*100:.0f}c)')
                    record_leg('POL', 'no', t, pm_ask, no_pay, 'politics')
except Exception as ex:
    print('politics check failed:', ex, file=sys.stderr)

# NOTE 2026-09-24: the following were checked and DELIBERATELY excluded —
# document before re-adding:
#   KXHOUSE / KXSENATE / HOUSE / SENATE (party-control binaries): 0 open events.
#   Polymarket HAS "which-party-will-win-the-house/senate-in-2026" but there is
#   no open Kalshi side to match -> skip.
#   KXAPCALLHOUSE / KXAPCALLSENATE: "when will AP call..." timing ladders, not
#   party binaries -> not matchable to PM party markets.
#   KXSAMEPARTYCONGRESS-27FEB01: bid 0.51 / ask 0.90 — unexecutable thin book.
#   KXDSENATESEATS-27 / KXHOUSEPOPVOTEMARGIN-27NOV03: liquid ladders but no
#   matching PM ladder found -> skip.
#   Bill/legislation series (KXFARMBILL-26MAY live: JAN01 bid .15/ask .23;
#   KXTARIFFBILL, KXBORDERBILL, KXGOVTFUNDLENGTH, KXGOVTFUNDCOUNT, KXACAHOUSEVOTE:
#   0 open): no Polymarket counterpart found -> skip.
#   KXMISENATE-26 / KXAKSENATE-26NOV03: person markets, no clean PM match.

# ---------- 6. ECONOMICS: CPI fair-value (Cleveland Fed nowcast) + Fed bucket-sum/synthetics ----------
# Observed 2026-09-24 (public Kalshi API). Series/event/market ticker formats:
#   KXCPICORE-26SEP / KXCPICORE-26SEP-T0.2            "above X%" ladder, core CPI m/m, BLS SA
#   KXECONSTATCPICORE-26SEP / ...-T0.2                "exactly X%" buckets (0.1pp wide), core m/m
#   KXECONSTATCORECPIYOY-26SEP / ...-T2.5             "exactly X%" buckets (0.1pp wide), core y/y
#   KXFEDDECISION-26OCT / ...-C25,-C26,-H0,-H25,-H26  5 mutually-exclusive buckets: cut>25,cut25,hold,hike25,hike>25
#   KXFED-26OCT / ...-T4.00                          "upper bound of fed funds rate above X%" ladder
#   KXFEDDECISION-26OCT-H25 + KXFED-26OCT-T4.00       synthetic pair (given current upper = 4.00%)
#   KXFOMCDISSENTCOUNT-26OCT / ...-0..-5              exact dissent-count buckets (not exhaustive: 6+ possible)
#   KXPAYROLLS-26SEP / ...-T80000  "above X jobs" ladder | KXU3-26SEP / ...-T4.0  "above X%" ladder
# Fair-value anchors (all free, no keys, none market-implied):
#   core m/m: Cleveland Fed inflation nowcast, daily JSON, timestamped (chart _comment).
#     sigma = 0.10pp: measured 2026-09-24 as the same-stage (23rd-of-month) nowcast RMSE
#     over Sep2024-Aug2026 (n=16, sd=0.096); full-history sd=0.160 (COVID regime) — using recent.
#   core y/y: (1+Aug y/y SA)*(1+Sep m/m nowcast)-1 on current-vintage BLS index (CUSR0000SA0L1E).
#     NOTE 2026-09-24: the Cleveland Fed's own y/y nowcast (2.39%) is on REAL-TIME vintage and
#     undershoots current-vintage settlement by the BLS revision wedge (~0.26pp); compounding on
#     current vintage (center ~2.65%) matches the settlement basis. sigma = 0.11pp.
#     SA-vs-NSA settlement basis checked 2026-09-24: Aug NSA core y/y (2.446%) == SA y/y (2.446%)
#     to 3dp (BLS CUUR0000SA0L1E vs CUSR0000SA0L1E) — the 12-month seasonal wedge is negligible.
#   Fed: NO independent real-time anchor exists (Fed funds futures/CME FedWatch are market-implied;
#     WSJ survey paywalled; SEP dot plot quarterly/static). Single-contract Fed fair-value is OUT.
#     Covered instead with anchor-free checks: field bucket-sum + KXFED ladder arb + the
#     KXFED-26OCT-T4.00 vs KXFEDDECISION-{H25,H26} synthetic (pure Kalshi-vs-Kalshi relative value).
#   Payrolls / unemployment: OUT — no fetchable free consensus (ForexFactory only publishes this-week
#     calendar, 404 on next-week; DailyFX 403; WSJ paywalled). A trailing-average NFP model would be a
#     forecast, not a consensus, and risks phantom edges — left out deliberately. Ladder-arbitrage
#     (executable, needs no model) is still checked.
#   GDP: no open GDP bracket markets (GDPW/GDPUSMIN/KXDEFGDP-as-brackets all closed) — nothing to cover.
#   KXCPINDEX (headline NSA index ladder): book dead (all asks 1.00) and needs an NSA seasonal model — out.
# Staleness: nowcast _comment asof must be <=4 days old; >=8 daily values for the target month
#   (fail closed early-month); target-month chart must exist and not show an actual (released).
#   BLS y/y base is a published fact with a measured-date; warns via stderr when older than 45d.
if time_left() < 25:
    print('skipping economics: time budget', file=sys.stderr)
else:
    try:
        try:
            import os as _os, time as _time
        except Exception:
            _os = _time = None

        _ECON_MON = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                     'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        _ECON_SIGMA_MM = 0.10      # pp, core CPI m/m nowcast error (see header)
        _ECON_SIGMA_YOY = 0.11     # pp, propagated + vintage slop
        # Aug 2026 core CPI y/y (SA): BLS CUSR0000SA0L1E 337.765/329.700 - 1. Published fact; refresh monthly.
        _ECON_YOY_BASE = {'2026-9': (2.4463, '2026-09-24')}

        def _econ_nowcast(target_ym):
            """Returns (asof_date, core_mm_pct, n_days) for target_ym like '2026-9', or None."""
            raw = None
            cache = '/tmp/econ_nowcast.json'
            try:
                if _os and _time and _os.path.exists(cache) \
                        and _time.time() - _os.path.getmtime(cache) < 1800:
                    with open(cache) as f:
                        raw = json.load(f)
            except Exception:
                raw = None
            if raw is None:
                try:
                    raw = get('https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en')
                    try:
                        with open(cache, 'w') as f:
                            json.dump(raw, f)
                    except Exception:
                        pass
                except Exception as ex:
                    print('econ nowcast fetch failed:', ex, file=sys.stderr)
                    return None
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
                if core is None or asof is None:
                    print(f'econ nowcast: no data for {target_ym}', file=sys.stderr)
                    return None
                if released:
                    print(f'econ nowcast: {target_ym} already released, skipping', file=sys.stderr)
                    return None
                age = (NOW_UTC.date() - asof).days
                if age < 0 or age > 4:
                    print(f'econ nowcast stale: asof {asof} ({age}d)', file=sys.stderr)
                    return None
                if n < 8:
                    print(f'econ nowcast: only {n} daily values for {target_ym}, too early in month',
                          file=sys.stderr)
                    return None
                return asof, core, n
            except Exception as ex:
                print('econ nowcast parse failed:', ex, file=sys.stderr)
                return None

        def _econ_ym(et):
            m = re.search(r'-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)$', et)
            if not m:
                return None
            return f"20{m.group(1)}-{_ECON_MON[m.group(2)]}"

        def _econ_books(ev):
            """ticker-suffix -> (bid, ask, full_ticker) for an event's markets."""
            out = {}
            for mk in ev.get('markets', []):
                t = mk.get('ticker', '')
                tm = re.search(r'-T(-?[\d\.]+)$', t)
                if not tm:
                    continue
                try:
                    thr = float(tm.group(1))
                except Exception:
                    continue
                bid = float(mk.get('yes_bid_dollars') or 0)
                ask = float(mk.get('yes_ask_dollars') or 0)
                out[thr] = (bid, ask, t)
            return out

        def _econ_ladder_edges(label, books, asof, center, sigma):
            for thr in sorted(books):
                bid, ask, t = books[thr]
                if ask <= 0 or ask >= 1:
                    continue
                fair = N((center - thr) / sigma)
                if fair - ask >= 0.10:
                    edge(f'ECON {label} YES {t} ask {ask*100:.0f}c vs fair {fair:.0%} '
                         f'(nowcast {center:.2f}%, {asof})')
                    record_leg('ECON', 'yes', t, fair, ask*100, 'econ', thr)
                elif bid >= 0.10 and bid - fair >= 0.10:
                    edge(f'ECON {label} NO {t} — YES bid {bid*100:.0f}c vs fair {fair:.0%} '
                         f'(nowcast {center:.2f}%, {asof})')
                    record_leg('ECON', 'no', t, fair, (1-bid)*100, 'econ', thr)

        def _econ_bucket_edges(label, et, books, center, sigma, gate_lo=1.02, gate_hi=0.90):
            """'Exactly X' buckets. half-width inferred from min spacing. Field gates for
            human review (fields are NOT exhaustive — tails can all resolve NO)."""
            thrs = sorted(books)
            if len(thrs) < 3:
                return
            gaps = [b - a for a, b in zip(thrs, thrs[1:]) if b > a]
            hw = min(gaps) / 2 if gaps else 0.05
            bid_sum = 0.0; ask_sum = 0.0
            for thr in thrs:
                bid, ask, t = books[thr]
                bid_sum += bid
                ask_sum += ask if ask > 0 else 1.0  # missing/stale ask = 1.00 (unbuyable)
                if ask <= 0 or ask >= 1:
                    continue
                fair = N((thr + hw - center) / sigma) - N((thr - hw - center) / sigma)
                if fair - ask >= 0.10:
                    edge(f'ECON {label} YES {t} ask {ask*100:.0f}c vs fair {fair:.0%} '
                         f'(center {center:.2f}%)')
                    record_leg('ECON', 'yes', t, fair, ask*100, 'econ', thr)
                elif bid >= 0.10 and bid - fair >= 0.10:
                    edge(f'ECON {label} NO {t} — YES bid {bid*100:.0f}c vs fair {fair:.0%} '
                         f'(center {center:.2f}%)')
                    record_leg('ECON', 'no', t, fair, (1-bid)*100, 'econ', thr)
            if bid_sum > gate_lo:
                edge(f'ECON {label} {et} bid sum={bid_sum:.2f} — field overbid')
            elif ask_sum < gate_hi:
                edge(f'ECON {label} {et} ask sum={ask_sum:.2f} — field underask')

        def _econ_field_sum(label, et, ev, over=1.05, under=0.95):
            """Mutually-exclusive field dislocation check (DOGE/XRP convention)."""
            bid_sum = 0.0; ask_sum = 0.0; n = 0
            for mk in ev.get('markets', []):
                bid_sum += float(mk.get('yes_bid_dollars') or 0)
                a = mk.get('yes_ask_dollars')
                ask_sum += float(a) if a else 1.0  # missing/stale ask = 1.00
                n += 1
            if n < 2:
                return
            if bid_sum > over:
                edge(f'ECON {label} {et} bid sum={bid_sum:.2f} ask sum={ask_sum:.2f} — field overbid')
            elif ask_sum < under:
                edge(f'ECON {label} {et} bid sum={bid_sum:.2f} ask sum={ask_sum:.2f} — field underask')

        # ---- E1/E2/E3: CPI anchored on Cleveland Fed nowcast ----
        for series, kind in [('KXCPICORE', 'ladder'), ('KXECONSTATCPICORE', 'bucket'),
                             ('KXECONSTATCORECPIYOY', 'bucket-yoy')]:
            if time_left() < 15:
                print('econ CPI: time budget', file=sys.stderr)
                break
            for e in evs_for(series)[:3]:
                et = e.get('event_ticker', '')
                ym = _econ_ym(et)
                if not ym:
                    continue
                nc = _econ_nowcast(ym)
                if not nc:
                    continue
                asof, c_mm, _ = nc
                ev = event_nested(et)
                if not ev:
                    continue
                books = _econ_books(ev)
                if kind == 'ladder':
                    _econ_ladder_edges('coreCPI m/m', books, asof, c_mm, _ECON_SIGMA_MM)
                elif kind == 'bucket':
                    _econ_bucket_edges('coreCPI m/m', et, books, c_mm, _ECON_SIGMA_MM)
                else:
                    base = _ECON_YOY_BASE.get(ym)
                    if not base:
                        print(f'econ y/y: no BLS base for {ym}, skipping', file=sys.stderr)
                        continue
                    bv, measured = base
                    try:
                        age_b = (NOW_UTC.date() - datetime.date(*map(int, measured.split('-')))).days
                        if age_b > 45:
                            print(f'econ y/y base {measured} is {age_b}d old — refresh BLS value',
                                  file=sys.stderr)
                    except Exception:
                        pass
                    c_yoy = ((1 + bv / 100) * (1 + c_mm / 100) - 1) * 100
                    _econ_bucket_edges('coreCPI y/y', et, books, c_yoy, _ECON_SIGMA_YOY)

        # ---- E4: Fed decision field bucket-sum (5 mutually-exclusive buckets) ----
        if time_left() >= 15:
            for e in evs_for('KXFEDDECISION')[:2]:
                et = e.get('event_ticker', '')
                ev = event_nested(et)
                if ev:
                    _econ_field_sum('FED decision', et, ev)

        # ---- E5: Fed funds upper-bound ladder arb + decision cross-market synthetic ----
        if time_left() >= 10:
            dec_by_suffix = {}
            for e in evs_for('KXFEDDECISION')[:3]:
                det = e.get('event_ticker', '')
                suf = re.search(r'-(\d{2}[A-Z]{3})$', det)
                if not suf:
                    continue
                dev = event_nested(det)
                if not dev:
                    continue
                books_d = {}
                for mk in dev.get('markets', []):
                    t = mk.get('ticker', '')
                    sfx = t.rsplit('-', 1)[-1]  # C26/C25/H0/H25/H26
                    books_d[sfx] = (float(mk.get('yes_bid_dollars') or 0),
                                    float(mk.get('yes_ask_dollars') or 0), t)
                dec_by_suffix[suf.group(1)] = books_d
            kxfed_events = evs_for('KXFED')[:2]
            for e in kxfed_events:
                et = e.get('event_ticker', '')
                ev = event_nested(et)
                if not ev:
                    continue
                books = _econ_books(ev)
                thrs = sorted(books)
                # ladder arb: {above hi} subset {above lo} — buy lo @ask, sell hi @bid
                for lo, hi in zip(thrs, thrs[1:]):
                    b_lo, a_lo, t_lo = books[lo]
                    b_hi, a_hi, t_hi = books[hi]
                    if a_lo <= 0 or a_lo >= 1 or b_hi <= 0:
                        continue
                    if b_hi - a_lo >= 0.10:
                        edge(f'ECON FED ladder {et}: buy {t_lo} YES @ {a_lo*100:.0f}c / '
                             f'sell {t_hi} YES @ {b_hi*100:.0f}c locks {(b_hi-a_lo)*100:.0f}c')
            # synthetic vs the decision field: ONLY valid for the nearest upcoming FOMC meeting,
            # because later meetings start from a rate that depends on earlier outcomes.
            e0 = (kxfed_events or [{}])[0]
            et = e0.get('event_ticker', '')
            if et:
                ev = event_nested(et)
                books = _econ_books(ev) if ev else {}
                # synthetic: T4.00 "upper bound above 4.00%" == H25+H26 "hike >=25bps",
                # given current upper = 4.00% (guarded below). MUST match the same meeting month.
                msuf = re.search(r'-(\d{2}[A-Z]{3})$', et)
                dec_books = dec_by_suffix.get(msuf.group(1)) if msuf else None
                if dec_books and 3.75 in books and 4.00 in books and 4.25 in books \
                        and 'H25' in dec_books and 'H26' in dec_books:
                    b375, _, _ = books[3.75]
                    b400, a400, t400 = books[4.00]
                    b425, a425, t425 = books[4.25]
                    bh25, ah25, th25 = dec_books['H25']
                    bh26, ah26, th26 = dec_books['H26']
                    if b375 >= 0.95 and 0.05 < (b400 + a400) / 2 < 0.95:
                        p1 = b400 - ah25 - ah26          # sell T4.00, buy H25+H26
                        p2 = (bh25 + bh26) - a400        # buy T4.00, sell H25+H26
                        if a400 < 1 and ah25 < 1 and ah26 < 1 and p1 >= 0.10:
                            edge(f'ECON FED synthetic: sell {t400} YES @ {b400*100:.0f}c / '
                                 f'buy {th25}+{th26} YES @ {(ah25+ah26)*100:.0f}c '
                                 f'locks {p1*100:.0f}c')
                        elif a400 < 1 and p2 >= 0.10:
                            edge(f'ECON FED synthetic: buy {t400} YES @ {a400*100:.0f}c / '
                                 f'sell {th25}+{th26} YES @ {(bh25+bh26)*100:.0f}c '
                                 f'locks {p2*100:.0f}c')
                        q1 = b425 - ah26                # sell T4.25, buy H26 ("hike >25bps")
                        q2 = bh26 - a425                # buy T4.25, sell H26
                        if 0.05 < (b425 + a425) / 2 < 0.95:
                            if a425 < 1 and ah26 < 1 and q1 >= 0.10:
                                edge(f'ECON FED synthetic: sell {t425} YES @ {b425*100:.0f}c / '
                                     f'buy {th26} YES @ {ah26*100:.0f}c locks {q1*100:.0f}c')
                            elif a425 < 1 and q2 >= 0.10:
                                edge(f'ECON FED synthetic: buy {t425} YES @ {a425*100:.0f}c / '
                                     f'sell {th26} YES @ {bh26*100:.0f}c locks {q2*100:.0f}c')

        # ---- E6: FOMC dissent-count field bucket-sum (not exhaustive: 6+ possible) ----
        if time_left() >= 8:
            for e in evs_for('KXFOMCDISSENTCOUNT')[:1]:
                et = e.get('event_ticker', '')
                ev = event_nested(et)
                if ev:
                    _econ_field_sum('FED dissent', et, ev, over=1.05, under=0.80)

        # ---- E7: jobs/u3 "above X" ladder arbitrage (no model — pure executable arb) ----
        if time_left() >= 8:
            for series, label in [('KXPAYROLLS', 'jobs'), ('KXU3', 'u3')]:
                for e in evs_for(series)[:1]:
                    et = e.get('event_ticker', '')
                    ev = event_nested(et)
                    if not ev:
                        continue
                    books = _econ_books(ev)
                    thrs = sorted(books)
                    for lo, hi in zip(thrs, thrs[1:]):
                        b_lo, a_lo, t_lo = books[lo]
                        b_hi, a_hi, t_hi = books[hi]
                        if a_lo <= 0 or a_lo >= 1 or b_hi <= 0:
                            continue
                        if b_hi - a_lo >= 0.10:
                            edge(f'ECON {label} ladder {et}: buy {t_lo} YES @ {a_lo*100:.0f}c / '
                                 f'sell {t_hi} YES @ {b_hi*100:.0f}c locks {(b_hi-a_lo)*100:.0f}c')
    except Exception as ex:
        print('economics check failed:', ex, file=sys.stderr)

# ---------- 7. Weather daily HIGH/LOW (settles on The Weather Company) ----------
# Settlement source: The Weather Company reported station max/min (per the series'
# settlement_sources field). MEASURED 2026-09-24: Kalshi TWC expiration_value ==
# IEM ASOS daily max/min at the mapped airport station on 64/64 station-days
# re-verified this session (8 stations x 8 days, all diff 0.0), extending the
# earlier ~118 station-day check. Station map is MEASURED, not assumed:
# CHI=MDW (not ORD), DAL=DFW (not DAL), NYC=Central Park "NYC" (not LGA/JFK),
# HOU=HOU (not IAH).
#
# DETERMINISTIC-ONLY. The running station extreme is a hard bound on the final
# (HIGH: final >= running max; LOW: final <= running min), so strikes it kills
# are fair 0 and strikes it locks are fair 1 -- no forecast model, no sigma, no
# calibration risk. Guard bands are INTEGER (1F) so every rule below is safe
# under ANY plausible TWC rounding of fractional temps (round-half-up,
# truncation, ceil all covered); boundary-near cases are skipped, never guessed.
# Probabilistic weather pricing stays OFF until per-city/lead-time forecast bias
# is MEASURED. Each run logs (nws_fc, om_fc) per station-day to
# ~/workspace/kalshi/wx_fc_log.csv so that bias CAN be measured later.
#
# Verified 2026-09-24: overnight quotes go stale (19h old) while the market still
# trades, and uncalibrated forecast models disagree with the book by 1.5-4.5F --
# a forecast tier printed 37 phantom edges at 4am (incl. a 50c "edge" that was
# really a 0.7F forecast difference). Hence: no forecast tier, no quote-age
# filter (a stale quote against a deterministic kill is the opportunity, and the
# trader re-verifies live). Obs need only be from the settlement day (local
# standard-time window); age doesn't weaken the bound.
# Strike semantics (verified from API fields 2026-09-24):
#   less (cap c)      -> YES wins iff final <= c-1
#   between (floor f, cap c) -> YES wins iff f <= final <= c
#   greater (floor f) -> YES wins iff final >= f+1
if time_left() < 60:
    print('skipping weather: time budget', file=sys.stderr)
else:
    try:
        from concurrent.futures import ThreadPoolExecutor as _WXPool
        from zoneinfo import ZoneInfo as _WXZone
        import csv as _wx_csv
        import os as _wx_os
        from urllib.parse import urlencode as _wx_urlencode

        # series: (hi|lo, label, ICAO, IEM station, IEM network, tz, NWS office, gridx, gridy)
        _WX_CFG = {
            'KXHIGHCHI':  ('hi', 'CHI',  'KMDW', 'MDW', 'IL_ASOS', 'America/Chicago',     'LOT', 72, 69),
            'KXHIGHTOKC': ('hi', 'OKC',  'KOKC', 'OKC', 'OK_ASOS', 'America/Chicago',     'OUN', 94, 90),
            'KXHIGHTSEA': ('hi', 'SEA',  'KSEA', 'SEA', 'WA_ASOS', 'America/Los_Angeles', 'SEW', 124, 60),
            'KXHIGHLAX':  ('hi', 'LAX',  'KLAX', 'LAX', 'CA_ASOS', 'America/Los_Angeles', 'LOX', 149, 41),
            'KXHIGHMIA':  ('hi', 'MIA',  'KMIA', 'MIA', 'FL_ASOS', 'America/New_York',    'MFL', 105, 51),
            'KXHIGHDEN':  ('hi', 'DEN',  'KDEN', 'DEN', 'CO_ASOS', 'America/Denver',      'BOU', 75, 65),
            'KXHIGHAUS':  ('hi', 'AUS',  'KAUS', 'AUS', 'TX_ASOS', 'America/Chicago',     'EWX', 158, 87),
            'KXHIGHPHIL': ('hi', 'PHIL', 'KPHL', 'PHL', 'PA_ASOS', 'America/New_York',    'PHI', 48, 75),
            'KXHIGHTATL': ('hi', 'ATL',  'KATL', 'ATL', 'GA_ASOS', 'America/New_York',    'FFC', 49, 81),
            'KXHIGHTDC':  ('hi', 'DC',   'KDCA', 'DCA', 'VA_ASOS', 'America/New_York',    'LWX', 97, 69),
            'KXHIGHTDAL': ('hi', 'DAL',  'KDFW', 'DFW', 'TX_ASOS', 'America/Chicago',     'FWD', 80, 109),
            'KXHIGHTBOS': ('hi', 'BOS',  'KBOS', 'BOS', 'MA_ASOS', 'America/New_York',    'BOX', 73, 101),
            'KXHIGHTPHX': ('hi', 'PHX',  'KPHX', 'PHX', 'AZ_ASOS', 'America/Phoenix',     'PSR', 161, 57),
            'KXHIGHTNOLA':('hi', 'NOLA', 'KMSY', 'MSY', 'LA_ASOS', 'America/Chicago',     'LIX', 61, 90),
            'KXHIGHNY':   ('hi', 'NYC',  'KNYC', 'NYC', 'NY_ASOS', 'America/New_York',    'OKX', 34, 45),
            'KXLOWTSEA':  ('lo', 'SEA',  'KSEA', 'SEA', 'WA_ASOS', 'America/Los_Angeles', 'SEW', 124, 60),
            'KXLOWTPHIL': ('lo', 'PHIL', 'KPHL', 'PHL', 'PA_ASOS', 'America/New_York',    'PHI', 48, 75),
            'KXLOWTATL':  ('lo', 'ATL',  'KATL', 'ATL', 'GA_ASOS', 'America/New_York',    'FFC', 49, 81),
            'KXLOWTMIA':  ('lo', 'MIA',  'KMIA', 'MIA', 'FL_ASOS', 'America/New_York',    'MFL', 105, 51),
            'KXLOWTLAX':  ('lo', 'LAX',  'KLAX', 'LAX', 'CA_ASOS', 'America/Los_Angeles', 'LOX', 149, 41),
            'KXLOWTDEN':  ('lo', 'DEN',  'KDEN', 'DEN', 'CO_ASOS', 'America/Denver',      'BOU', 75, 65),
            'KXLOWTOKC':  ('lo', 'OKC',  'KOKC', 'OKC', 'OK_ASOS', 'America/Chicago',     'OUN', 94, 90),
            'KXLOWTCHI':  ('lo', 'CHI',  'KMDW', 'MDW', 'IL_ASOS', 'America/Chicago',     'LOT', 72, 69),
            'KXLOWTDC':   ('lo', 'DC',   'KDCA', 'DCA', 'VA_ASOS', 'America/New_York',    'LWX', 97, 69),
            'KXLOWTBOS':  ('lo', 'BOS',  'KBOS', 'BOS', 'MA_ASOS', 'America/New_York',    'BOX', 73, 101),
            'KXLOWTAUS':  ('lo', 'AUS',  'KAUS', 'AUS', 'TX_ASOS', 'America/Chicago',     'EWX', 158, 87),
            'KXLOWTHOU':  ('lo', 'HOU',  'KHOU', 'HOU', 'TX_ASOS', 'America/Chicago',     'HGX', 66, 89),
            'KXLOWTNYC':  ('lo', 'NYC',  'KNYC', 'NYC', 'NY_ASOS', 'America/New_York',    'OKX', 34, 45),
        }
        _WX_LATLON = {  # ICAO -> (lat, lon) for the Open-Meteo batch call (forecast log)
            'KMDW': (41.786, -87.7524), 'KOKC': (35.3889, -97.6006), 'KSEA': (47.4447, -122.3144),
            'KPHL': (39.8734, -75.2266), 'KATL': (33.6301, -84.4418), 'KMSY': (29.9933, -90.2511),
            'KMIA': (25.788, -80.3169), 'KDEN': (39.8328, -104.6575), 'KAUS': (30.183, -97.6799),
            'KDCA': (38.8472, -77.0346), 'KDFW': (32.8968, -97.038), 'KBOS': (42.3606, -71.0097),
            'KPHX': (33.4343, -112.0116), 'KLAX': (33.9382, -118.3865), 'KNYC': (40.779, -73.9692),
            'KHOU': (29.6375, -95.2824),
        }
        # fixed standard-time offsets: Kalshi's daily window is local STANDARD time
        # (strike_date 2026-09-25T06:00Z = Sep 24 00:00 CST for Chicago)
        _WX_STD = {'America/Chicago': -6, 'America/New_York': -5, 'America/Denver': -7,
                   'America/Los_Angeles': -8, 'America/Phoenix': -7}

        def _wx_text(url, timeout=15):
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode()

        def _wx_day_window(tzname):
            off = _WX_STD[tzname]
            day_start = NOW_UTC + datetime.timedelta(hours=off)
            day_start = day_start.replace(hour=0, minute=0, second=0, microsecond=0)
            return day_start - datetime.timedelta(hours=off)

        def _wx_obs(icao, stn, tzname):
            """All of today's (standard-time window) obs temps in F. [] if none."""
            day_start = _wx_day_window(tzname)
            vals = []
            try:
                d = get(f'https://api.weather.gov/stations/{icao}/observations?limit=300')
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
            except Exception as ex:
                print(f'wx {icao}: nws obs failed: {ex}', file=sys.stderr)
            if not vals:  # IEM fallback
                try:
                    tzinf = _WXZone(tzname)
                    today = NOW_UTC.astimezone(tzinf).date()
                    q = _wx_urlencode({'station': stn, 'data': 'tmpf',
                        'year1': today.year, 'month1': today.month, 'day1': today.day,
                        'year2': today.year, 'month2': today.month, 'day2': today.day,
                        'tz': tzname, 'format': 'onlycomma', 'latlon': 'no', 'elev': 'no',
                        'missing': 'empty', 'trace': 'empty', 'direct': 'no'})
                    txt = _wx_text('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + q)
                    for r in _wx_csv.DictReader(txt.splitlines()):
                        try:
                            vals.append(float(r['tmpf']))
                        except (TypeError, ValueError):
                            pass
                except Exception as ex:
                    print(f'wx {stn}: iem obs failed: {ex}', file=sys.stderr)
            return vals

        def _wx_nws_fc(kind, tzname, off, gx, gy, stn):
            """NWS gridpoint forecast high/low for today (for the bias log only)."""
            try:
                tz = _WXZone(tzname)
                today = NOW_UTC.astimezone(tz).date()
                f = get(f'https://api.weather.gov/gridpoints/{off}/{gx},{gy}/forecast')
                props = f.get('properties', {}) or {}
                try:
                    gen = datetime.datetime.fromisoformat(props.get('generatedAt') or '')
                    if (NOW_UTC - gen).total_seconds() / 3600 > 12:
                        return None
                except Exception:
                    return None
                want_day = (kind == 'hi')
                for per in props.get('periods', []) or []:
                    try:
                        ps = datetime.datetime.fromisoformat(per['startTime']).astimezone(tz)
                    except Exception:
                        continue
                    if ps.date() != today or bool(per.get('isDaytime')) != want_day:
                        continue
                    if kind == 'lo' and ps.hour >= 12:
                        continue
                    try:
                        return float(per['temperature'])
                    except (TypeError, ValueError):
                        continue
            except Exception as ex:
                print(f'wx {stn}: nws forecast failed: {ex}', file=sys.stderr)
            return None

        def _wx_deterministic(kind, stype, f, c, m):
            """Deterministic fair value: 1.0 (locked), 0.0 (dead), or None (unknown).
            Integer guard bands: safe under any TWC rounding of fractional temps."""
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

        def _wx_find(s):
            cfg = _WX_CFG[s]
            try:
                tz = _WXZone(cfg[5])
            except Exception:
                return None
            dc = NOW_UTC.astimezone(tz).strftime('%y%b%d').upper()
            for e in evs_for(s):
                et = e.get('event_ticker', '')
                if et.endswith('-' + dc):
                    return (s, cfg, et)
            return None

        with _WXPool(max_workers=10) as _pool:
            _found = [r for r in _pool.map(_wx_find, _WX_CFG) if r]
        if not _found:
            print('wx: no today-events found in mapped series', file=sys.stderr)
        _stkeys = {}
        for _s, _cfg, _et in _found:
            _stkeys.setdefault((_cfg[0], _cfg[2]),
                              (_cfg[0], _cfg[2], _cfg[3], _cfg[5], _cfg[6], _cfg[7], _cfg[8]))
        # station obs (unique stations, parallel)
        def _wx_fetch_obs(kv):
            (_k, _icao), (_kk, _cc, _stn, _tz, _off, _gx, _gy) = kv
            return ((_k, _icao), _wx_obs(_icao, _stn, _tz))
        with _WXPool(max_workers=8) as _pool:
            _obs = dict(_pool.map(_wx_fetch_obs, _stkeys.items()))
        _stdata = {}
        for (_k, _icao), _vals in _obs.items():
            if _vals:
                _stdata[(_k, _icao)] = max(_vals) if _k == 'hi' else min(_vals)
            else:
                print(f'wx {_icao}: no obs today, skipping station', file=sys.stderr)
        # ---- forecast bias log (one row per station-day; enables future calibration) ----
        try:
            _logp = _wx_os.path.expanduser('~/workspace/kalshi/wx_fc_log.csv')
            _seen = set()
            if _wx_os.path.exists(_logp):
                with open(_logp) as _lf:
                    for _ln in _lf.read().splitlines()[1:]:
                        _p = _ln.split(',')
                        if len(_p) >= 3:
                            _seen.add((_p[0], _p[1], _p[2]))
            _ul = sorted({_cfg[2] for _, _cfg, _ in _found})
            _om = {}
            try:
                _lats = ','.join(str(_WX_LATLON[_u][0]) for _u in _ul)
                _lons = ','.join(str(_WX_LATLON[_u][1]) for _u in _ul)
                _d = get(f'https://api.open-meteo.com/v1/forecast?latitude={_lats}&longitude={_lons}'
                         f'&daily=temperature_2m_max,temperature_2m_min&temperature_unit=fahrenheit'
                         f'&timezone=auto&forecast_days=1')
                _dl = _d if isinstance(_d, list) else [_d]
                for _u, _e in zip(_ul, _dl):
                    try:
                        _om[_u] = (float(_e['daily']['temperature_2m_max'][0]),
                                   float(_e['daily']['temperature_2m_min'][0]))
                    except (TypeError, ValueError, KeyError, IndexError):
                        pass
            except Exception as ex:
                print(f'wx: open-meteo batch failed: {ex}', file=sys.stderr)
            def _wx_fetch_nws(kv):
                (_k, _icao), (_kk, _cc, _stn, _tz, _off, _gx, _gy) = kv
                return ((_k, _icao), _wx_nws_fc(_k, _tz, _off, _gx, _gy, _stn))
            with _WXPool(max_workers=8) as _pool:
                _nwsf = dict(_pool.map(_wx_fetch_nws, _stkeys.items()))
            _rows = []
            for (_k, _icao), (_kk, _cc, _stn, _tz, _off, _gx, _gy) in _stkeys.items():
                _dc = NOW_UTC.astimezone(_WXZone(_tz)).strftime('%Y-%m-%d')
                if (_dc, _icao, _k) in _seen:
                    continue
                _nf = _nwsf.get((_k, _icao))
                _of = _om.get(_icao, (None, None))[0 if _k == 'hi' else 1]
                if _nf is None and _of is None:
                    continue
                _rows.append(f"{_dc},{_icao},{_k},{_nf if _nf is not None else ''},"
                             f"{_of if _of is not None else ''}\n")
                _seen.add((_dc, _icao, _k))
            if _rows:
                _new = not _wx_os.path.exists(_logp)
                with open(_logp, 'a') as _lf:
                    if _new:
                        _lf.write('date,station,kind,nws_fc,om_fc\n')
                    _lf.writelines(_rows)
        except Exception as ex:
            print(f'wx: forecast log failed: {ex}', file=sys.stderr)
        # ---- price the deterministic kills ----
        with _WXPool(max_workers=10) as _pool:
            _nested = dict(_pool.map(lambda item: (item[2], event_nested(item[2])), _found))
        for _s, _cfg, _et in _found:
            _kind, _label, _icao = _cfg[0], _cfg[1], _cfg[2]
            _m = _stdata.get((_kind, _icao))
            if _m is None:
                continue
            _ev = _nested.get(_et)
            if not _ev:
                continue
            _tag = f'{_label}-{"hi" if _kind == "hi" else "lo"}'
            _ctx = f"(running {'max' if _kind == 'hi' else 'min'} {'%.1f' % _m})"
            for _mk in _ev.get('markets', []) or []:
                if _mk.get('status') not in (None, 'active'):
                    continue
                _t = _mk.get('ticker', '')
                _stype = _mk.get('strike_type')
                try:
                    _f = int(float(_mk['floor_strike'])) if _mk.get('floor_strike') is not None else None
                    _c = int(float(_mk['cap_strike'])) if _mk.get('cap_strike') is not None else None
                except (TypeError, ValueError):
                    continue
                if _stype == 'less' and _c is None:
                    continue
                if _stype == 'greater' and _f is None:
                    continue
                if _stype == 'between' and (_f is None or _c is None):
                    continue
                if _stype not in ('less', 'greater', 'between'):
                    continue
                _fair = _wx_deterministic(_kind, _stype, _f, _c, _m)
                if _fair is None:
                    continue
                try:
                    _ask = float(_mk.get('yes_ask_dollars') or 0)
                    _bid = float(_mk.get('yes_bid_dollars') or 0)
                except (TypeError, ValueError):
                    continue
                if _fair == 1.0 and _ask > 0 and 1 - _ask >= 0.10:
                    edge(f'WX {_tag} YES {_t} ask {_ask*100:.0f}c vs fair 100% {_ctx}')
                elif _fair == 0.0 and _bid >= 0.10:
                    edge(f'WX {_tag} NO {_t} — YES bid {_bid*100:.0f}c vs fair 0% {_ctx}')
    except Exception as ex:
        print('weather check failed:', ex, file=sys.stderr)

# ---------- 9. SYNTHETIC COMBOS: multi-leg baskets assembled from single-leg edges ----------
# Kalshi has no public combo order books (verified 2026-09-24: zero combo-shaped
# series among open events; listed combos are per-user RFQ mints with private
# maker quotes — see combo-rfq-research.md). So we BUILD combos: 2 single-leg
# orders placed simultaneously as ONE trade decision (1 slot of the 3/day cap).
# EV is linear across legs (no maker quote, no maker tax); correlation only
# concentrates risk, so correlated pairs clear 20c instead of 15c. Every leg
# must be +EV standalone (>=10c scan / >=5c reverify) so a partial FOK fill
# degrades gracefully — worst case is holding a subset of +EV legs, never a
# donation. Full math + fill-risk design: combo.py and CRAFT.md §9.
# Runs BEFORE the §8 sweep; needs time_left() > 30.
try:
    import combo as _combo
    if time_left() > 30 and len(STRUCT_LEGS) >= 2:
        def _ev_ticker(_t):
            # event-level key: strip the strike/bucket suffix for same-event detection
            _b = re.sub(r'-[TB]-?[\d.]+$', '', _t)
            return re.sub(r'-[TB][\d.]+$', '', _b)

        _pairs = []
        _seen = set()
        for _i in range(len(STRUCT_LEGS)):
            for _j in range(_i + 1, len(STRUCT_LEGS)):
                _a, _b = STRUCT_LEGS[_i], STRUCT_LEGS[_j]
                if _a['ticker'] == _b['ticker']:
                    continue
                if _ev_ticker(_a['ticker']) == _ev_ticker(_b['ticker']):
                    continue  # same event: overlapping exposure, skip for v1
                _key = tuple(sorted((_a['ticker'], _b['ticker'])))
                if _key in _seen:
                    continue
                _seen.add(_key)
                _corr = _a['asset'] == _b['asset']
                _legs = [{'side': _a['side'], 'fair_yes': _a['fair_yes'],
                          'price_cents': _a['pay_cents']},
                         {'side': _b['side'], 'fair_yes': _b['fair_yes'],
                          'price_cents': _b['pay_cents']}]
                _rep = _combo.combo_report(_legs, corr=_corr)
                if _rep['take_scan']:
                    _pairs.append((_rep['net_c'], _a, _b, _rep))
        _pairs.sort(key=lambda _x: _x[0], reverse=True)
        for _net, _a, _b, _rep in _pairs[:3]:
            _spec = '+'.join(
                f"{_l['side'].upper()}|{_l['asset']}|{_l['ticker']}|"
                f"{int(round(_l['pay_cents']))}|{int(round(_l['fair_yes'] * 100))}"
                for _l in (_a, _b))
            edge(f"COMBO legs={_spec} edge_c={_rep['edge_c']} fee_c={_rep['fee_c']} "
                 f"net_c={_rep['net_c']} maxpay_c={_rep['maxpay_c']} "
                 f"contracts={_rep['contracts']} corr={'corr' if _rep['corr'] else 'decorr'} "
                 f"rule=take_if_net>={_rep['bar_c']}c")
        if _pairs:
            print(f'combos: {len(_pairs)} pair(s) at scan bar, top net {_pairs[0][0]}c',
                  file=sys.stderr)
    else:
        print('skipping combos: time budget or <2 legs', file=sys.stderr)
except Exception as ex:
    print('combo constructor failed:', ex, file=sys.stderr)

# ---------- 9. MLB TOTALS: pitching-matchup model (v1.1, 2026-09-24) ----------
# Dedicated fair-value model for KXMLBTOTAL full-game totals ladders, in
# mlb_totals.py. Mean from probable-pitcher ERA + IP-weighted bullpen ERA
# (daily roster hydrate; team-ERA fallback) + team runs/game vs league avg,
# times verified park factor (RotoWire 2023-2025, CRAFT.md); sd calibrated
# from the market's own ladder; only the MEAN is ours.
# FLAG-ONLY (research): v1.1 closed the fixable gaps (real pen ERA, parks) but
# the model still disagrees with the (efficient, 1c-spread) market by ~0.7 runs
# avg — the market prices lineup/weather/September effects no free API gives
# us. Disagreements are logged, never traded. Promote to EDGE only after
# lineup/weather inputs land and the gap is measured gone. See CRAFT.md §9.
if time_left() > 90:
    try:
        import mlb_totals
        for _fl in mlb_totals.scan_all():
            print(f'FLAG: {_fl}', flush=True)
    except Exception as ex:
        print('mlb totals check failed:', ex, file=sys.stderr)
else:
    print('skipping MLB totals: time budget', file=sys.stderr)

# Series handled by dedicated models (§1-§7, §9) — the universal sweep skips
# these so models and sweep never double-signal. (Sports are swept via
# model-free checks.)
_COVERED_PREFIX = (
    'KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXBTCD', 'KXETHD', 'KXSOLD',
    'KXDOGE', 'KXXRP', 'KXGOLDH', 'KXGOLDD', 'KXINXU', 'KXINX',
    'KXNASDAQ100U', 'KXWTIH', 'KXSILVERH', 'KXCPICORE', 'KXECONSTAT',
    'KXFED', 'KXPAYROL', 'KXUNEMP', 'KXHIGH', 'KXLOW', 'KXRAIN',
    'KXTEMP', 'SENATE',
)
# ---------- 8. UNIVERSAL SWEEP: model-free dislocation checks on every other series ----------
# NOTE 2026-09-24: inline pipelined full-board sweep (reverted from the
# separate kalshi-sweep cron job — two overlapping 5-min jobs contended on
# the API/proxy and produced PARTIAL sweeps, RemoteDisconnected failures,
# and >280s runs. Inline = one process, zero overlap possible).
# Pipeline: fast sequential cursor-walk (plain events, no nested books)
# submits each page's with_nested_markets=true fetch to a 14-worker pool as
# it goes, through one shared requests.Session (keep-alive). Measured
# 2026-09-24: FULL BOARD 71 pages / 13,732 events in 27s clean.
# Budget: 120s. auto_trade.py re-verifies every sweep candidate ATOMICALLY
# on a fresh book (reverify_sweep) before any order — sweep-time quotes are
# never acted on directly. Crossed books and field sums print FLAG lines
# (human review only, never auto-traded).
try:
    _SW_T0 = time.monotonic()
    _SW_BUDGET = 120
    _sw_left = lambda: _SW_BUDGET - (time.monotonic() - _SW_T0)
    _SW_BASE = ('https://api.elections.kalshi.com/trade-api/v2/events'
                '?status=open&limit=200')
    _SW_NESTED = _SW_BASE + '&with_nested_markets=true'
    try:
        import requests as _sw_rq
        _sw_sess = _sw_rq.Session()
        _sw_sess.headers.update({'User-Agent': 'Mozilla/5.0'})
        def _sw_get(url):
            for _att in (0, 1):  # one 429 backoff (5s), then give up the page
                _r = _sw_sess.get(url, timeout=12)
                if _r.status_code == 429 and _att == 0:
                    print('sweep 429: backing off 5s', file=sys.stderr)
                    time.sleep(5)
                    continue
                _r.raise_for_status()
                return _r.json()
    except ImportError:
        def _sw_get(url):
            _req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(_req, timeout=12) as _r:
                    return json.load(_r)
            except urllib.error.HTTPError as _he:
                if _he.code == 429:
                    time.sleep(5)
                    with urllib.request.urlopen(_req, timeout=12) as _r2:
                        return json.load(_r2)
                raise
    def _sw_process(e):
        _cands, _flags = [], []
        if e.get('series_ticker', '').startswith(_COVERED_PREFIX):
            return _cands, _flags
        _mkts = [m for m in e.get('markets', []) if m.get('status') == 'active']
        if not _mkts:
            return _cands, _flags
        for _m in _mkts:
            _t = _m.get('ticker', '')
            _r = (_m.get('result') or '').lower()
            _yb = float(_m.get('yes_bid_dollars') or 0)
            _yaq = _m.get('yes_ask_dollars')
            _ya = float(_yaq) if _yaq else 0
            if _r == 'yes' and 0 < _ya < 0.97:
                _cands.append(('yes', _t,
                    f'SWEEP YES {_t} ask {_ya*100:.0f}c (result=yes set, payout $1)'))
            elif _r == 'no' and _yb > 0.03:
                _cands.append(('no', _t,
                    f'SWEEP NO {_t} \u2014 YES bid {_yb*100:.0f}c (result=no set, payout $0)'))
            elif _ya > 0 and _yb > _ya:
                _flags.append(f'FLAG: CROSSED {_t} bid {_yb*100:.0f}c > ask {_ya*100:.0f}c')
        if e.get('mutually_exclusive') and len(_mkts) >= 3:
            try:
                _ct = min(datetime.datetime.fromisoformat(m['close_time'].replace('Z', '+00:00'))
                          for m in _mkts if m.get('close_time'))
            except Exception:
                _ct = None
            if _ct is not None and (_ct - NOW_UTC).total_seconds() <= 7 * 86400:
                _bids = [float(m.get('yes_bid_dollars') or 0) for m in _mkts]
                _asks = [float(m.get('yes_ask_dollars')) if m.get('yes_ask_dollars') else None
                         for m in _mkts]
                _bs = sum(_bids)
                _asum = sum(a for a in _asks if a is not None)
                if _bs > 1.15 and sum(1 for b in _bids if b > 0) >= 3:
                    _flags.append(f'FLAG: SELL-FIELD {e.get("event_ticker")} bid_sum={_bs:.2f} \u2014 '
                                  f'sell-all-YES arb under true exclusivity')
                if _asum < 0.85 and sum(1 for a in _asks if a is not None) >= 3:
                    _flags.append(f'FLAG: BUY-FIELD {e.get("event_ticker")} ask_sum={_asum:.2f} \u2014 '
                                  f'arb ONLY if candidates exhaust outcome space')
        return _cands, _flags
    _sw_futs, _sw_cursor, _sw_pages, _sw_n, _sw_partial = [], None, 0, 0, False
    _sw_pool = ThreadPoolExecutor(max_workers=14)
    try:
        while _sw_left() > 20:
            _u = _SW_BASE + (f'&cursor={_sw_cursor}' if _sw_cursor else '')
            try:
                _d = _sw_get(_u)
            except Exception as _ex:
                print(f'sweep cursor-walk page failed: {_ex}', file=sys.stderr)
                _sw_partial = True
                break
            _sw_futs.append(_sw_pool.submit(_sw_get, _SW_NESTED +
                                            (f'&cursor={_sw_cursor}' if _sw_cursor else '')))
            _sw_cursor = _d.get('cursor')
            _sw_pages += 1
            if not _sw_cursor:
                break
        else:
            if _sw_cursor:
                _sw_partial = True
        _sw_drain = max(5.0, _sw_left() - 5)
        try:
            for _f in as_completed(_sw_futs, timeout=_sw_drain):
                try:
                    _nd = _f.result()
                except Exception as _ex:
                    print(f'sweep nested page failed: {_ex}', file=sys.stderr)
                    _sw_partial = True
                    continue
                for _e in _nd.get('events', []) or []:
                    try:
                        _c, _fl = _sw_process(_e)
                    except Exception:
                        continue
                    _sw_n += 1
                    for _side, _t, _raw in _c:
                        EDGES.append({'asset': 'SWEEP', 'side': _side, 'ticker': _t,
                                      'raw': 'EDGE: ' + _raw})
                    for _fl2 in _fl:
                        print(_fl2, flush=True)
        except TimeoutError:
            print('sweep: drain timed out, partial board', file=sys.stderr)
            _sw_partial = True
    finally:
        _sw_pool.shutdown(wait=False, cancel_futures=True)
    print(f'sweep {"PARTIAL" if _sw_partial else "FULL BOARD"}: {_sw_pages} pages, '
          f'{_sw_n} events in {time.monotonic() - _SW_T0:.0f}s', file=sys.stderr)
except Exception as ex:
    print('universal sweep failed:', ex, file=sys.stderr)

print('SCAN OK - no edges' if not EDGES else f'{len(EDGES)} edge(s) found')
