#!/usr/bin/env python3
"""Atomic edge re-verification (per-candidate CLI args).
In ONE run: fresh Coinbase spot + fresh realized hourly vol per coin,
fresh nested books for the candidate events. Fair value uses the
scanner's vol assumptions: volh_eff = max(assumed, realized); skip the
coin entirely if |30m drift| > 1% (crash/meltup regime). Keep only
candidates with fair - ask >= 0.12 on the ticket side.

Usage:
  python3 verify_edge.py BTC:D,KXBTCD-26SEP2413,KXBTCD-26SEP2413-T90000.00,YES BTC:15m,KXBTC15M-26SEP24-0030,KXBTC15M-26SEP24-0030-T90000,NO
"""
import json, math, re, sys, datetime, urllib.request

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)

def N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

NOW = datetime.datetime.now(datetime.timezone.utc)
VOL15 = {'BTC': 0.0011, 'ETH': 0.0013, 'SOL': 0.0018}
VOLD = {'BTC': 0.0035, 'ETH': 0.0040, 'SOL': 0.0055}

C = []
for arg in sys.argv[1:]:
    spec, et, t, side = arg.split(',')
    coin, kind = spec.split(':')
    C.append((coin, kind, et, t, side))

def coin_state(sym):
    S = None
    try:
        d = get(f'https://api.coinbase.com/v2/prices/{sym}-USD/spot')
        S = float(d['data']['amount'])
    except Exception:
        pass
    rv, drift = None, None
    try:
        d = get(f'https://api.exchange.coinbase.com/products/{sym}-USD/candles?granularity=60')
        closes = [c[4] for c in d if c and c[4]][:31]
        if len(closes) >= 12:
            rets = [math.log(closes[i] / closes[i + 1]) for i in range(len(closes) - 1)]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            rv = math.sqrt(var) * math.sqrt(60)
            drift = math.log(closes[0] / closes[-1])
    except Exception:
        pass
    regime_ok = not (drift is not None and abs(drift) > 0.01)
    return S, rv, regime_ok, drift

states = {}
for coin, _, _, _, _ in C:
    if coin not in states:
        states[coin] = coin_state(coin)
        S, rv, ok, drift = states[coin]
        ds = f'{drift*100:+.2f}%' if drift is not None else 'n/a'
        rv_s = f'{rv:.4f}' if rv is not None else 'n/a'
        print(f'{coin}: spot={S}, rvol_h={rv_s}, regime_ok={ok}, drift30m={ds}', flush=True)

ev = {}
for et in sorted({c[2] for c in C}):
    try:
        ev[et] = get(f'https://api.elections.kalshi.com/trade-api/v2/events/{et}?with_nested_markets=true')['event']
    except Exception as ex:
        print(f'EVENT FETCH FAILED {et}: {ex}')
        ev[et] = None

mkt = {}
for et, e in ev.items():
    if e:
        for mk in e.get('markets', []):
            mkt[mk['ticker']] = mk

print(f'verify run at {NOW.isoformat()}')
survivors = []
for coin, kind, et, t, side in C:
    S, rv, ok, _ = states[coin]
    if not ok or S is None:
        print(f'DROPPED {t}: regime/spot'); continue
    if kind == '15m':
        veff = max(VOL15[coin], (rv / 2) if rv else 0)
        m = re.search(r'-(\d{2})(\d{2})$', et)
        close_utc = datetime.datetime(NOW.year, NOW.month, NOW.day, int(m.group(1)) + 4, int(m.group(2)), tzinfo=datetime.timezone.utc)
        hrs_left = (close_utc - NOW).total_seconds() / 3600
        if hrs_left * 60 < 2:
            print(f'DROPPED {t}: expired'); continue
        sigma_scale = math.sqrt(hrs_left * 4)   # 15-min periods
        scale_label = f'{hrs_left*60:.1f}m'
    else:
        veff = max(VOLD[coin], rv or 0)
        m = re.search(r'(\d{2})$', et)
        close_utc = datetime.datetime(NOW.year, NOW.month, NOW.day, tzinfo=datetime.timezone.utc) + datetime.timedelta(hours=int(m.group(1)) + 4)
        hrs_left = (close_utc - NOW).total_seconds() / 3600
        if hrs_left < 0.03:
            print(f'DROPPED {t}: expired ({hrs_left:.2f}h)'); continue
        sigma_scale = math.sqrt(hrs_left)
        scale_label = f'{hrs_left:.2f}h'
    mk = mkt.get(t)
    if not mk:
        print(f'DROPPED {t}: not in book'); continue
    K = float(t.split('-T')[-1])
    sigma = S * veff * sigma_scale
    fair_y = N((S - K) / sigma) if sigma > 0 else 0.5
    yask = float(mk.get('yes_ask_dollars') or 0)
    ybid = float(mk.get('yes_bid_dollars') or 0)
    if not (0 < yask < 1):
        print(f'DROPPED {t}: no yes ask'); continue
    if side == 'YES':
        edge = fair_y - yask
        px = yask
        print(f'{"KEEP " if edge >= 0.12 else "drop"} {t} YES: ask {yask*100:.0f}c bid {ybid*100:.0f}c fair {fair_y:.0%} edge {edge*100:+.1f}c (spot {S:,.2f}, {scale_label})')
        if edge >= 0.12:
            survivors.append((t, 'YES', yask, fair_y, edge, hrs_left))
    else:
        fair_n = 1 - fair_y
        edge = ybid - fair_y   # bid vs fair on the YES book
        print(f'{"KEEP " if edge >= 0.12 else "drop"} {t} NO: YES bid {ybid*100:.0f}c vs fair {fair_y:.0%} edge {edge*100:+.1f}c (spot {S:,.2f}, {scale_label})')
        if edge >= 0.12:
            survivors.append((t, 'NO', ybid, fair_n, edge, hrs_left))

print(f'\n{len(survivors)} survivor(s)')
for t, side, px, fair, edge, hrs in survivors:
    print(f'SURVIVOR: {side} {t} live px {px*100:.0f}c vs fair {fair:.0%} (+{edge*100:.1f}c, {hrs:.1f}h left)')
