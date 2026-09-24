#!/usr/bin/env python3
"""Alpha module #3 — cross-event logical containment (SHADOW ONLY).

Two checks, both pure logic on Kalshi's own books (no external data):

  STEP 1 (verify): enumerate open series and confirm whether any *listed*
  combo/parlay-shaped markets exist. KEY FACT (combo.py docstring, verified
  2026-09-24): Kalshi has NO public combo order books — listed combos are
  per-user RFQ mints with private quotes. This step re-verifies live and
  classifies every combo/parlay-named series (single-instrument AND-question
  vs sports parlay vs RFQ book).

  STEP 2 (pivot — the real build): touch-vs-terminal containment on crypto.
  "BTC trimmed-mean touches K at any point before T" (one-touch monthly
  ladders: KXBTCMAXMON / KXBTCMINMON / ...) is a SUPERSET of "BTC closes
  above K at T'" for any T' inside the touch window (KXBTCD / KXETHD / ...
  hourly ladders). Hence, modulo settlement-aggregation cracks documented
  below, fair(touch YES) >= fair(terminal YES) at the same threshold.
  Violation (executable), above-direction:  touch_yes_ask < terminal_yes_bid  (net of fees)
  Trade: buy touch YES @ ask + buy terminal-above NO @ (100 - term_yes_bid).
  Violation (executable), below-direction:  touch_yes_ask < terminal_no_bid  (net of fees)
  Trade: buy touch YES @ ask + buy terminal-ABOVE YES @ (100 - term_no_bid)
  (replicates buying terminal-below NO up to the 1c strike gap). Only ONE
  direction locks (see module docstring).

  STEP 3 (listed combos): the *COMBO econ series (KXCPICOMBO, KXFEDCOMBO,
  KXEMPLOYMENTCOMBO, KXBALANCEPOWERCOMBO) ARE listed single-instrument
  AND-question markets with live books. Map combo -> leg markets, flag
  combo_bid > PROD(leg YES-equiv asks) and the reverse as *directional
  signals* (no atomic multi-leg execution; correlation risk; size accordingly).

SHADOW MODE ONLY. Nothing here places orders, moves money, or POSTs
anything. Logs via shadow.py (module='contain'); the live trader never
reads the trade log.

Usage:
  python3 alpha_contain.py            # full run, shadow-logged (default)
  python3 alpha_contain.py --selftest # offline math checks, no API, no logging
"""
import json
import math
import os
import re
import sys
import time
import datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from combo import fee_cents
from shadow import shadow_candidate, shadow_run

API = 'https://api.elections.kalshi.com/trade-api/v2'
UA = {'User-Agent': 'Mozilla/5.0'}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def book_top(ticker, depth=3):
    """Executable top-of-book from the LIVE orderbook endpoint.

    NOTE (2026-09-24): /events?with_nested_markets and /markets/{t} top-of-book
    fields were returning nulls across the board while orderbook_fp showed
    deep live ladders. Executable quotes MUST come from here.
    Returns dict(yes_bid, yes_bid_size, no_bid, no_bid_size) in cents/ctrs,
    None where the side has no resting orders.
    """
    try:
        ob = get(f'{API}/markets/{ticker}/orderbook?depth={depth}')['orderbook_fp']
    except Exception:
        return None
    yb = ob.get('yes_dollars') or []
    nb = ob.get('no_dollars') or []
    out = {'yes_bid': None, 'yes_bid_size': 0.0, 'no_bid': None, 'no_bid_size': 0.0}
    if yb:
        i = max(range(len(yb)), key=lambda k: float(yb[k][0]))
        out['yes_bid'] = int(round(float(yb[i][0]) * 100))
        out['yes_bid_size'] = sum(float(s) for _, s in yb)
    if nb:
        i = max(range(len(nb)), key=lambda k: float(nb[k][0]))
        out['no_bid'] = int(round(float(nb[i][0]) * 100))
        out['no_bid_size'] = sum(float(s) for _, s in nb)
    return out


def yes_ask_of(book):
    return 100 - book['no_bid'] if book and book['no_bid'] is not None else None


def no_ask_of(book):
    return 100 - book['yes_bid'] if book and book['yes_bid'] is not None else None


def yes_equiv(book, side):
    """Implied (YES-bid, YES-ask) in cents for proposition P where P is
    `side` ('yes'|'no', case-insensitive) of market M. None-safe."""
    if not book:
        return (None, None)
    if side.lower() == 'yes':
        return (book['yes_bid'], yes_ask_of(book))
    return (book['no_bid'], no_ask_of(book))


def nested(event_ticker):
    try:
        return get(f'{API}/events/{event_ticker}?with_nested_markets=true')['event']
    except Exception:
        return None


def series_events(series, limit=50):
    try:
        return get(f'{API}/events?series_ticker={series}&status=open&limit={limit}')['events']
    except Exception:
        return []


def all_open_series():
    out, cursor = [], None
    while True:
        u = f'{API}/series?status=open&limit=1000'
        if cursor:
            u += f'&cursor={cursor}'
        d = get(u)
        out += d['series']
        cursor = d.get('cursor')
        if not cursor:
            break
    return out


# ---------------------------------------------------------------------------
# STEP 1 — verify listed combo/parlay markets
# ---------------------------------------------------------------------------
COMBO_RE = re.compile(r'combo|parlay|multi-?leg|multi-?way|parl[ae]y', re.I)
SPORTS_RE = re.compile(r'NCAAM|NCAAF|NBA|NFL|NHL|MLB|WCGOAL|SGP|PREPACK|GOLF|TENNIS|SOCCER|UFC', re.I)


def verify_combos(all_series=None):
    """Returns dict with counts + classification of combo-shaped series."""
    series = all_series if all_series is not None else all_open_series()
    hits = [s for s in series
            if COMBO_RE.search(s.get('ticker') or '') or COMBO_RE.search(s.get('title') or '')]
    sports, andq, other = [], [], []
    for s in hits:
        t = s.get('ticker') or ''
        if SPORTS_RE.search(t):
            sports.append(t)
            continue
        # inspect first open event: AND-question single markets vs anything else
        evs = series_events(t, limit=2)
        kind = 'andq?'
        if evs:
            det = nested(evs[0]['event_ticker'])
            if det and det.get('markets'):
                titles = [m.get('title') or '' for m in det['markets'][:6]]
                if any(' AND ' in x for x in titles):
                    kind = 'andq'
                elif any('parlay' in x.lower() for x in titles):
                    kind = 'parlayq'
                else:
                    kind = 'single?'
        (andq if kind in ('andq', 'parlayq') else other).append((t, kind))
    return {'total_series': len(series), 'combo_named': len(hits),
            'sports': sports, 'andq': andq, 'other': other,
            'rfq_books': 0}  # no public RFQ book endpoint exists; listed = single markets


# ---------------------------------------------------------------------------
# STEP 2 — touch vs terminal containment (crypto)
# ---------------------------------------------------------------------------
TOUCH_RE = re.compile(r'^(KX)?([A-Z]{2,5})(MAX|MIN)(MON|M|W)$')
TERMINAL_BY_COIN = {'BTC': 'KXBTCD', 'ETH': 'KXETHD', 'SOL': 'KXSOLD',
                    'DOGE': 'KXDOGED', 'XRP': 'KXXRPD', 'HYPE': 'KXHYPED',
                    'BNB': 'KXBNBD'}
MON_RE = re.compile(r'-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})$')
EVT_RE = re.compile(r'-(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d{2})$')
TRM_RE = re.compile(r'-T(\d+(?:\.\d+)?)$')
MONTHS = {m: i + 1 for i, m in enumerate(
    ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'])}

MIN_TOP_SIZE = 5      # contracts required at the top of each used side
TOUCH_FLAG_C = 0      # flag any positive net edge; >=5c highlighted
CRACK_NOTE = ('RULE-CRACK: touch settles on trimmed-mean minute path vs terminal '
              '60s simple avg + 1c strike gap (X=K-0.01); near-lock, not pure lock.')


def parse_touch_market(series_ticker, event_ticker, market_ticker):
    m = TOUCH_RE.match(series_ticker)
    if not m:
        return None
    coin = m.group(2)
    direction = 'above' if m.group(3) == 'MAX' else 'below'
    mt = market_ticker.rsplit('-', 1)[-1]
    if not mt.isdigit():
        return None
    strike = int(mt) / 100.0
    me = MON_RE.search(event_ticker)
    if not me:
        return None
    yy, mon, dd = int(me.group(1)), MONTHS[me.group(2)], int(me.group(3))
    end = datetime.datetime(2000 + yy, mon, dd, 23, 59)  # ET wall time
    return {'coin': coin, 'direction': direction, 'strike': strike,
            'touch_end': end, 'event': event_ticker, 'ticker': market_ticker}


def parse_terminal_event(event_ticker):
    m = EVT_RE.search(event_ticker)
    if not m:
        return None
    yy, mon, dd, hh = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)), int(m.group(4))
    return datetime.datetime(2000 + yy, mon, dd, hh, 0)  # ET wall time


def touch_terminal_pairs(all_series=None):
    """Yield candidate (touch, terminal) pairs with books attached."""
    pairs, notes = [], []
    series = all_series if all_series is not None else all_open_series()
    touch_series = [s['ticker'] for s in series if TOUCH_RE.match(s.get('ticker') or '')]
    notes.append(f'touch-shaped series open: {len(touch_series)}')
    term_cache = {}

    def term_ladders(coin):
        # [(expiry, event_ticker, {strike: ticker})], fetched once per coin
        if coin in term_cache:
            return term_cache[coin]
        ladders, tser = [], TERMINAL_BY_COIN.get(coin)
        if tser:
            for te in series_events(tser, limit=10):
                exp = parse_terminal_event(te['event_ticker'])
                if not exp:
                    continue
                det = nested(te['event_ticker'])
                if not det:
                    continue
                strikes = {}
                for tmk in det.get('markets', []):
                    mt = TRM_RE.search(tmk['ticker'])
                    if mt:
                        strikes[float(mt.group(1))] = tmk['ticker']
                ladders.append((exp, te['event_ticker'], strikes))
        term_cache[coin] = ladders
        return ladders

    for ts in touch_series:
        for e in series_events(ts, limit=4):
            det = nested(e['event_ticker'])
            if not det:
                continue
            for mk in det.get('markets', []):
                tm = parse_touch_market(ts, e['event_ticker'], mk['ticker'])
                if not tm:
                    continue
                ladders = term_ladders(tm['coin'])
                if not ladders:
                    notes.append(f"no terminal ladder for coin {tm['coin']}; skipped")
                    continue
                want_x = tm['strike'] - 0.01  # terminal .99-strike convention
                for exp, evt, strikes in ladders:
                    if exp > tm['touch_end']:
                        continue  # (b) expiry outside touch window -> not pairable
                    for x, xt in strikes.items():
                        if abs(x - want_x) < 0.005:
                            pairs.append({'touch': tm, 'term_ticker': xt,
                                          'term_event': evt, 'term_exp': exp})
                            break
    return pairs, notes


def check_touch_terminal(pairs):
    """Returns (flags, kills, table_rows). Executable quotes only."""
    flags, kills, rows = [], [], []

    def probe(p):
        tb = book_top(p['touch']['ticker'])
        eb = book_top(p['term_ticker'])
        return p, tb, eb

    with ThreadPoolExecutor(12) as ex:
        probed = list(ex.map(probe, pairs))
    for p, tb, eb in probed:
        t, coin, K = p['touch'], p['touch']['coin'], p['touch']['strike']
        row = {'touch': t['ticker'], 'term': p['term_ticker'], 'K': K,
               'dir': t['direction'], 'term_exp': p['term_exp'].strftime('%m-%d %H:%M'),
               'touch_ask': None, 'term_bid': None, 'edge_c': None, 'verdict': ''}
        # need: touch YES ask (resting NO bids); terminal side checked per direction below
        if not tb or tb['no_bid'] is None:
            row['verdict'] = 'KILL(c): no touch NO bids -> no executable touch ask'
            kills.append(row['verdict'] + ' ' + t['ticker']); rows.append(row); continue
        if tb['no_bid_size'] < MIN_TOP_SIZE:
            row['verdict'] = f"KILL(c): thin touch top (touch_no_sz={tb['no_bid_size']:.0f})"
            kills.append(row['verdict']); rows.append(row); continue
        touch_ask = 100 - tb['no_bid']  # executable touch YES ask (resting NO bids)
        if t['direction'] == 'above':
            # touch-up TD(K) superset terminal-above TA(K-0.01):
            # lock = buy touch YES @ touch_ask + buy terminal NO @ (100 - term_yes_bid)
            if not eb or eb['yes_bid'] is None:
                row['verdict'] = 'KILL(c): no terminal YES bids'
                kills.append(row['verdict'] + ' ' + p['term_ticker']); rows.append(row); continue
            if tb['no_bid_size'] < MIN_TOP_SIZE or eb['yes_bid_size'] < MIN_TOP_SIZE:
                row['verdict'] = f"KILL(c): thin top (touch_no_sz={tb['no_bid_size']:.0f}, term_yes_sz={eb['yes_bid_size']:.0f})"
                kills.append(row['verdict']); rows.append(row); continue
            term_px = eb['yes_bid']
            term_leg_cost = 100 - term_px  # terminal NO ask
            edge = term_px - touch_ask - fee_cents(touch_ask) - fee_cents(term_leg_cost)
            row.update(touch_ask=touch_ask, term_bid=term_px, edge_c=edge)
            leg_txt = f"touch YES ask {touch_ask}c < terminal YES bid {term_px}c"
        else:
            # touch-down TD(K) superset terminal-BELOW(K) ~= terminal-above NO:
            # lock = buy touch YES @ touch_ask + buy terminal-ABOVE YES @ (100 - term_no_bid)
            # (buying TA YES replicates buying terminal-below NO up to the 1c strike gap)
            if not eb or eb['no_bid'] is None:
                row['verdict'] = 'KILL(c): no terminal NO bids'
                kills.append(row['verdict'] + ' ' + p['term_ticker']); rows.append(row); continue
            if tb['no_bid_size'] < MIN_TOP_SIZE or eb['no_bid_size'] < MIN_TOP_SIZE:
                row['verdict'] = f"KILL(c): thin top (touch_no_sz={tb['no_bid_size']:.0f}, term_no_sz={eb['no_bid_size']:.0f})"
                kills.append(row['verdict']); rows.append(row); continue
            term_px = eb['no_bid']
            term_leg_cost = 100 - term_px  # terminal-ABOVE YES ask
            edge = term_px - touch_ask - fee_cents(touch_ask) - fee_cents(term_leg_cost)
            row.update(touch_ask=touch_ask, term_bid=term_px, edge_c=edge)
            leg_txt = f"touch YES ask {touch_ask}c < terminal NO bid {term_px}c"
        if edge > TOUCH_FLAG_C:
            row['verdict'] = f'FLAG edge={edge}c' + (' STRONG' if edge >= 5 else '')
            flags.append({**row, 'touch_book': tb, 'term_book': eb,
                          'note': (f"{leg_txt} net of fees (edge {edge}c). {CRACK_NOTE}")})
        else:
            row['verdict'] = f'clean (edge {edge}c)'
        rows.append(row)
    return flags, kills, rows


# ---------------------------------------------------------------------------
# STEP 3 — listed combo (AND-question) vs leg markets
# ---------------------------------------------------------------------------
# combo series -> list of (leg_no, leg_series, event_ticker, spec_parser)
# spec forms: ('YES', suffix) | ('NO', suffix) | None (unmappable)
def _cpi_spec(frag):
    m = re.match(r'([\d.]+)% or below', frag)
    if m:
        return ('NO', 'T' + m.group(1))
    m = re.match(r'([\d.]+)% or above', frag)
    if m:
        x = float(m.group(1)) - 0.1  # tenth-granular prints: >=X  <=>  >X-0.1
        return ('YES', 'T' + ('%g' % x))
    return None  # 'Exactly X' -> two-market leg, unmappable here


COMBO_DEFS = {
    # KXCPICOMBO: "Will Headline be {H} AND Core be {C} for Sep 2026?"
    'KXCPICOMBO-26SEP': {
        'legs': [('Headline', 'KXCPI-26SEP', _cpi_spec), ('Core', 'KXCPICORE-26SEP', _cpi_spec)],
        'note': 'tenth-granular CPI prints: "X% or above" <=> YES T{X-0.1}; "or below" <=> NO TX',
    },
    # KXFEDCOMBO: "…Rate Decision be {D} AND Dissents be {N} for Oct…"
    'KXFEDCOMBO-26OCT': {
        'legs': [('Decision', 'KXFEDDECISION-26OCT',
                  lambda f: {'No change': ('YES', 'H0'), '25bp cut': ('YES', 'C25'),
                             '25bp hike': ('YES', 'H25')}.get(f)),
                 ('Dissents', 'KXFOMCDISSENTCOUNT-26OCT',
                  lambda f: {'0': ('YES', '0'), '>0': ('NO', '0')}.get(f))],
        'note': 'dissent leg via FOMC dissent-count market (-0 suffix)',
    },
    # KXEMPLOYMENTCOMBO: "Will U3 be {U} AND NFP growth be {N} for Sep 2026?"
    'KXEMPLOYMENTCOMBO-26SEP': {
        'legs': [('U3', 'KXU3-26SEP',
                  lambda f: ('NO', 'T4.1') if f == '4.1% or below' else None),
                 ('NFP', 'KXPAYROLLS-26SEP',
                  lambda f: ('NO', 'T50000') if f == 'Below 50k' else None)],
        'note': '"4.2%"/"50-99k"/"100k or above" legs need 2 markets or missing rungs -> skipped',
    },
    # KXBALANCEPOWERCOMBO: "Will House Control be {H} AND Senate Control be {S} for Feb 2027?"
    'KXBALANCEPOWERCOMBO-27FEB': {
        'legs': [('House', 'CONTROLH-2026',
                  lambda f: ('YES', 'D') if f == 'Democratic' else (('YES', 'R') if f == 'Republican' else None)),
                 ('Senate', 'CONTROLS-2026',
                  lambda f: ('YES', 'D') if f == 'Democratic' else (('YES', 'R') if f == 'Republican' else None))],
        'note': 'combo settles Feb 2027 vs legs Nov 2026: same midterm outcome, different settlement dates',
    },
}
COMBO_RE_TITLE = re.compile(r'Will (.+?) be (.+?) AND (.+?) be (.+?) for', re.I)
COMBO_FLAG_C = 10  # flag only net mispricing >= the desk's 10c scan bar;
# sub-bar rows still print in the table but do NOT become shadow candidates
# (combo signals are directional, not locks: correlation can break them)


def parse_combo_title(title):
    m = COMBO_RE_TITLE.search(title or '')
    if not m:
        return None
    return [(m.group(1).strip(), m.group(2).strip()), (m.group(3).strip(), m.group(4).strip())]


def find_leg_market(event_ticker, suffix):
    det = nested(event_ticker)
    if not det:
        return None
    for mk in det.get('markets', []):
        if mk['ticker'].endswith('-' + suffix):
            return mk['ticker']
    return None


def check_combos():
    flags, kills, skips, rows = [], [], [], []
    jobs = []
    for combo_event, cfg in COMBO_DEFS.items():
        det = nested(combo_event)
        if not det:
            skips.append(f'{combo_event}: event not open'); continue
        for cm in det.get('markets', []):
            parsed = parse_combo_title(cm.get('title'))
            if not parsed or len(parsed) != len(cfg['legs']):
                skips.append(f"{cm['ticker']}: title unparseable"); continue
            legs, ok = [], True
            for (lname, lseries, lspec), (cname, cfrag) in zip(cfg['legs'], parsed):
                spec = lspec(cfrag)
                if not spec:
                    skips.append(f"{cm['ticker']}: leg '{cname}={cfrag}' unmappable ({cfg['note']})")
                    ok = False; break
                side, suffix = spec
                lt = find_leg_market(lseries, suffix)
                if not lt:
                    skips.append(f"{cm['ticker']}: leg market {lseries}-{suffix} not found")
                    ok = False; break
                legs.append({'name': lname, 'side': side, 'ticker': lt, 'frag': cfrag})
            if ok:
                jobs.append((cm, cfg, legs))
    def probe(job):
        cm, cfg, legs = job
        cb = book_top(cm['ticker'])
        lbs = [book_top(l['ticker']) for l in legs]
        return cm, cfg, legs, cb, lbs
    with ThreadPoolExecutor(12) as ex:
        probed = list(ex.map(probe, jobs))
    for cm, cfg, legs, cb, lbs in probed:
        row = {'combo': cm['ticker'], 'legs': '+'.join(l['ticker'] for l in legs),
               'over_c': None, 'under_c': None, 'verdict': ''}
        if not cb or cb['yes_bid'] is None or cb['no_bid'] is None:
            row['verdict'] = 'KILL(c): combo book one-sided'
            kills.append(row['verdict'] + ' ' + cm['ticker']); rows.append(row); continue
        if any(not b for b in lbs):
            row['verdict'] = 'KILL(c): leg book missing'
            kills.append(row['verdict']); rows.append(row); continue
        yeq = [yes_equiv(b, l['side']) for b, l in zip(lbs, legs)]
        if any(b is None or a is None for b, a in yeq):
            row['verdict'] = 'KILL(c): leg one-sided book'
            kills.append(row['verdict']); rows.append(row); continue
        thin = [l['ticker'] for l, b in zip(legs, lbs)
                if (b['yes_bid_size'] if l['side'] == 'yes' else b['no_bid_size']) < MIN_TOP_SIZE
                or (b['no_bid_size'] if l['side'] == 'yes' else b['yes_bid_size']) < MIN_TOP_SIZE]
        if thin:
            row['verdict'] = f"KILL(c): thin leg book {thin[0]}"
            kills.append(row['verdict']); rows.append(row); continue
        combo_bid, combo_ask = cb['yes_bid'], 100 - cb['no_bid']
        leg_bids = [b for b, a in yeq]; leg_asks = [a for b, a in yeq]
        prod_ask = 1.0
        for a in leg_asks:
            prod_ask *= a / 100.0
        prod_bid = 1.0
        for b in leg_bids:
            prod_bid *= b / 100.0
        prod_ask_c, prod_bid_c = prod_ask * 100.0, prod_bid * 100.0
        # over: combo rich vs independence -> buy legs YES-equiv + combo NO
        fees_over = sum(fee_cents(a) for a in leg_asks) + fee_cents(100 - combo_bid)
        over = combo_bid - prod_ask_c - fees_over
        # under: combo cheap vs independence -> buy combo YES
        fees_under = sum(fee_cents(100 - b) for b in leg_bids) + fee_cents(combo_ask)
        under = prod_bid_c - combo_ask - fees_under
        row.update(over_c=round(over, 1), under_c=round(under, 1),
                   combo_bid_c=combo_bid, combo_ask_c=combo_ask,
                   prod_ask_c=round(prod_ask_c, 1), prod_bid_c=round(prod_bid_c, 1))
        if over > COMBO_FLAG_C or under > COMBO_FLAG_C:
            side = 'no' if over >= under else 'yes'
            row['verdict'] = f"FLAG over={over:.1f}c under={under:.1f}c"
            legstr = ' * '.join(f"{l['side']}@{l['ticker']}({b}/{a}c)"
                                for l, (b, a) in zip(legs, yeq))
            flags.append({**row, 'ticker': cm['ticker'], 'side': side,
                          'note': (f"combo YES bid {combo_bid}c ask {combo_ask}c vs legs [{legstr}]: "
                                   f"combo_bid {combo_bid}c > PROD(leg asks) {prod_ask_c:.1f}c "
                                   f"(over {over:.1f}c net) | PROD(leg bids) {prod_bid_c:.1f}c > "
                                   f"combo_ask {combo_ask}c (under {under:.1f}c net). "
                                   f"DIRECTIONAL SIGNAL ONLY: no atomic multi-leg execution; "
                                   f"correlation can break independence pricing; size accordingly. {cfg['note']}")})
        else:
            row['verdict'] = f"clean (over {over:.1f}c, under {under:.1f}c)"
        rows.append(row)
    return flags, kills, skips, rows

# ---------------------------------------------------------------------------
# selftest (offline) + main runner
# ---------------------------------------------------------------------------
def selftest():
    ok = 0

    def chk(name, cond):
        nonlocal ok
        print(('PASS' if cond else 'FAIL'), name)
        ok += cond

    # fee math sanity (from combo.fee_cents)
    chk('fee(26c)==2', fee_cents(26) == 2)
    chk('fee(50c)==2', fee_cents(50) == 2)  # ceil(7*.25)=ceil(1.75)=2
    # YES-equivalence: P=NO(M): bid=no_bid, ask=100-yes_bid
    b = {'yes_bid': 30, 'yes_bid_size': 10, 'no_bid': 65, 'no_bid_size': 10}
    chk('yes_equiv NO', yes_equiv(b, 'no') == (65, 70))
    chk('yes_equiv YES', yes_equiv(b, 'yes') == (30, 35))
    # touch edge math: term_bid 40, touch_ask 26 -> 40-26-fee(26)-fee(60)
    e = 40 - 26 - fee_cents(26) - fee_cents(60)
    chk('touch edge=10c', e == 10)
    # combo product: legs 60c/70c asks, combo bid 45c -> 45-42-fees >0
    prod = 60 * 70 / 100.0
    ov = 45 - prod - fee_cents(60) - fee_cents(70) - fee_cents(55)
    chk('combo over=3-fees', abs(ov - (3 - fee_cents(60) - fee_cents(70) - fee_cents(55))) < 1e-9)
    # parsers
    tm = parse_touch_market('KXBTCMAXMON', 'KXBTCMAXMON-BTC-26SEP30', 'KXBTCMAXMON-BTC-26SEP30-8750000')
    chk('touch parse', tm and tm['coin'] == 'BTC' and tm['strike'] == 87500.0
        and tm['direction'] == 'above' and tm['touch_end'].day == 30)
    tm2 = parse_touch_market('KXBTCMINMON', 'KXBTCMINMON-BTC-26SEP30', 'KXBTCMINMON-BTC-26SEP30-6750000')
    chk('touch parse below', tm2 and tm2['direction'] == 'below' and tm2['strike'] == 67500.0)
    chk('terminal evt parse', parse_terminal_event('KXBTCD-26SEP2517').hour == 17)
    chk('terminal strike re', TRM_RE.search('KXBTCD-26SEP2517-T87499.99').group(1) == '87499.99')
    chk('strike match penny', abs((87500.00 - 0.01) - 87499.99) < 0.005)
    cp = parse_combo_title('Will Headline be 0.2% or below AND Core be 0.1% or below for Sep 2026?')
    chk('combo title parse', cp == [('Headline', '0.2% or below'), ('Core', '0.1% or below')])
    chk('cpi spec below', _cpi_spec('0.2% or below') == ('NO', 'T0.2'))
    chk('cpi spec above', _cpi_spec('0.5% or above') == ('YES', 'T0.4'))
    chk('cpi spec exact->None', _cpi_spec('Exactly 0.3%') is None)
    print(f'{ok}/15 selftests passed')
    return 0 if ok == 15 else 1


def run():
    t0 = time.time()
    print('=== STEP 1: listed combo/parlay verification ===')
    all_series = all_open_series()
    v = verify_combos(all_series)
    print(f"open series: {v['total_series']}; combo/parlay-named: {v['combo_named']}")
    print(f"sports (out of scope): {len(v['sports'])}")
    print(f"AND/parlay-question single markets: {len(v['andq'])}")
    for t, k in v['andq'][:20]:
        print(f'   {t} [{k}]')
    print(f"other/unclassified: {len(v['other'])} {v['other'][:5]}")
    print('RFQ-style public combo books: 0 (no such public endpoint; all listed combos are single markets)')

    print('\n=== STEP 2: touch vs terminal containment ===')
    pairs, pnotes = touch_terminal_pairs(all_series)
    for n in pnotes:
        print('note:', n)
    print(f'candidate pairs (same coin, strike, terminal expiry in touch window): {len(pairs)}')
    tflags, tkills, trows = check_touch_terminal(pairs)
    print(f"{'touch':44} {'terminal':32} {'K':>9} {'t_ask':>5} {'e_bid':>5} {'edge':>6} verdict")
    for r in trows:
        print(f"{r['touch'][-44:]:44} {r['term'][-32:]:32} {r['K']:>9.2f} "
              f"{str(r['touch_ask']):>5} {str(r['term_bid']):>5} {str(r['edge_c']):>6} {r['verdict']}")
    print(f'touch flags: {len(tflags)}; kills: {len(tkills)}')

    print('\n=== STEP 3: listed combo vs legs ===')
    cflags, ckills, cskips, crows = check_combos()
    for r in crows:
        print(f"{r['combo']:38} over={r['over_c']}c under={r['under_c']}c :: {r['verdict']}")
    print(f'combo flags: {len(cflags)}; kills: {len(ckills)}; unmappable skips: {len(cskips)}')
    for s in cskips[:12]:
        print('   skip:', s)

    # ---- shadow logging ----
    for f in tflags:
        strong = f['edge_c'] >= 5
        shadow_candidate(module='contain', ticker=f['touch'], side='yes',
                         fair_yes=round(f['term_bid'] / 100.0, 4),
                         price_cents=f['touch_ask'],
                         edge_c=round(f['term_bid'] - f['touch_ask'], 1),
                         net_c=round(f['edge_c'], 1),
                         note=('CONTAIN touch-vs-terminal: ' + f['note']
                               + (' STRONG>=5c' if strong else '')),
                         extra={'pair': 'touch-vs-terminal', 'term_ticker': f['term'],
                                'strike': f['K'], 'direction': f['dir'],
                                'term_exp': f['term_exp'],
                                'touch_ask_c': f['touch_ask'], 'term_bid_c': f['term_bid'],
                                'touch_no_bid_sz': f['touch_book']['no_bid_size'],
                                'term_yes_bid_sz': f['term_book']['yes_bid_size']})
    for f in cflags:
        if f['side'] == 'no':  # combo rich vs independence: buy combo NO + legs
            price_c = 100 - f['combo_bid_c']
            fair_yes = round(f['prod_ask_c'] / 100.0, 4)
            edge_c = round(f['combo_bid_c'] - f['prod_ask_c'], 1)
        else:  # combo cheap vs independence: buy combo YES
            price_c = f['combo_ask_c']
            fair_yes = round(f['prod_bid_c'] / 100.0, 4)
            edge_c = round(f['prod_bid_c'] - f['combo_ask_c'], 1)
        shadow_candidate(module='contain', ticker=f['combo'], side=f['side'],
                         fair_yes=fair_yes, price_cents=price_c,
                         edge_c=edge_c,
                         net_c=round(max(f['over_c'], f['under_c']), 1),
                         note=('CONTAIN combo-vs-legs: ' + f['note']),
                         extra={'pair': 'combo-vs-legs', 'legs': f['legs'],
                                'over_c': f['over_c'], 'under_c': f['under_c'],
                                'combo_bid_c': f['combo_bid_c'],
                                'combo_ask_c': f['combo_ask_c'],
                                'prod_ask_c': f['prod_ask_c'],
                                'prod_bid_c': f['prod_bid_c']})
    shadow_run(module='contain', n_candidates=len(tflags) + len(cflags),
               note=(f"{len(pairs)} touch/terminal pairs checked, {len(tflags)} flags "
                     f"({len(tkills)} killed); {len(crows)} combo-vs-legs checked, "
                     f"{len(cflags)} flags ({len(ckills)} killed, {len(cskips)} unmappable); "
                     f"{v['combo_named']} combo-named series, 0 RFQ books"),
               extra={'elapsed_s': round(time.time() - t0, 1),
                      'step1': {k: (v[k] if k in ('total_series', 'combo_named', 'rfq_books')
                                    else len(v[k])) for k in
                                ('total_series', 'combo_named', 'sports', 'andq', 'other', 'rfq_books')},
                      'touch_kills': tkills[:20], 'combo_kills': ckills[:20],
                      'combo_skips': cskips[:20]})
    print(f'\nshadow-logged {len(tflags) + len(cflags)} candidates. elapsed {time.time()-t0:.0f}s')
    return 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(run())
