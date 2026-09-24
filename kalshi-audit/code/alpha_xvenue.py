#!/usr/bin/env python3
"""alpha_xvenue.py -- Polymarket<->Kalshi cross-venue divergence signal.

SHADOW MODE ONLY. This module logs divergences; it never places orders,
never moves money, never POSTs anything. Polymarket order execution is
explicitly OUT OF SCOPE (no wallet; needs Jeremiah's go-ahead). The live
trader (auto_trade.py) parses EDGE stdout lines and NEVER reads the trade
log, so shadow records can never trigger an order.

Signal: fade the stale book. For each hand-verified (Kalshi event,
Polymarket event) pair describing the SAME event with the SAME resolution
source, take the Polymarket-implied fair value and the Kalshi YES ask
(executable, not mid). If the Kalshi YES ask is >=15c cheaper than the
PM-implied fair (after Kalshi taker fees via combo.fee_cents), log a
shadow_candidate with module='xvenue'.

Only the Kalshi-YES-cheap direction is monitored: the reverse trade would
require buying on Polymarket, which is out of scope (no wallet), so it
cannot be acted on.

Every mapping in PM_MAP was hand-verified live on 2026-09-24: both sides
were fetched and the questions + resolution sources confirmed to describe
the same event. Rejected pairs (fuzzy/false matches) are documented in
hidden_files/craft_sections/alpha_xvenue.md and NOT in the table.

Usage:
    python3 alpha_xvenue.py            # shadow mode (default): scans + logs
    python3 alpha_xvenue.py --shadow    # same
"""
import json
import math
import os
import sys
import time
import datetime
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from shadow import shadow_candidate, shadow_run
from combo import fee_cents

GAMMA = 'https://gamma-api.polymarket.com'
KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'

PM_VOL_GATE = 25000.0      # event-level volume gate, Senate pattern
PM_MKT_VOL_GATE = 5000.0   # market-level volume gate, sports moneylines only
PM_MAX_SPREAD = 0.05       # PM two-sided book max spread
KX_MAX_SPREAD = 0.06       # Kalshi max spread (Senate pattern)
EDGE_BAR_C = 15.0          # Kalshi YES ask must be >=15c cheaper than PM fair

NOW_UTC = datetime.datetime.now(datetime.timezone.utc)


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# --------------------------------------------------------------------------
# PM_MAP -- hand-verified 2026-09-24. Do NOT add a pair without fetching both
# sides live and confirming the questions + resolution sources match.
#
# Entry fields:
#   label      short id
#   kx_event   fixed Kalshi event ticker (or None for date-keyed sports)
#   kx_series  Kalshi series (used to locate date-keyed sports events)
#   kx_date    'YYYY-MM-DD' the entry is valid for (sports only; others None)
#   kx_teams   sports only: list of (suffix, pm_team_name)
#   pm_slug    Polymarket event slug
#   pm_mode    'group'      -> single PM market matched by groupItemTitle,
#                            YES = outcomes[0]
#              'sum'        -> Kalshi rung vs sum of PM brackets at/above a cut
#              'moneyline'  -> sports moneyline market, outcomes = team names
#   pm_group   for 'group': the groupItemTitle to match
#   pm_legs    for 'sum': list of (kx_suffix, cut_pct, label) where the PM
#              fair for Kalshi "above <cut>" = sum of bracket prices for
#              prints >= cut+0.1 (one-decimal prints), every bracket gated
#   kx_suffixes sports only: derived from kx_teams
#   note       resolution-source note
# --------------------------------------------------------------------------
PM_MAP = [
    {
        'label': 'FED-OCT-25BP',
        'kx_event': 'KXFEDDECISION-26OCT',
        'kx_suffix': '-H25',
        'kx_subtitle': 'Hike 25bps',
        'pm_slug': 'fed-decision-in-october-20260617190323537',
        'pm_mode': 'group',
        'pm_group': '25 bps increase',
        'pm_vol_mode': 'event',
        'note': 'FOMC Oct 2026 meeting; change in the upper bound of the '
                'federal funds target range vs prior meeting. PM op 68.5c '
                'vs KX 67/68c at verification.',
    },
    {
        'label': 'FED-OCT-HOLD',
        'kx_event': 'KXFEDDECISION-26OCT',
        'kx_suffix': '-H0',
        'kx_subtitle': 'Hike 0bps (hold)',
        'pm_slug': 'fed-decision-in-october-20260617190323537',
        'pm_mode': 'group',
        'pm_group': 'No change',
        'pm_vol_mode': 'event',
        'note': 'Same FOMC Oct 2026 event as FED-OCT-25BP; hold leg. PM op '
                '29.5c vs KX 32/33c at verification.',
    },
    {
        'label': 'CPI-CORE-YOY-SEP',
        'kx_event': 'KXCPICOREYOY-26SEP',
        'pm_slug': 'core-cpi-yoy-september-2026',
        'pm_mode': 'sum',
        'pm_legs': [
            ('-T2.3', 2.3, 'core CPI YoY >2.3%'),
            ('-T2.4', 2.4, 'core CPI YoY >2.4%'),
            ('-T2.5', 2.5, 'core CPI YoY >2.5%'),
        ],
        'pm_vol_mode': 'event',
        'note': 'Both = CPI-U ex food+energy, 12mo to Sep 2026, one-decimal '
                'BLS print. Kalshi "above X" (one-decimal print > X) = sum of '
                'PM brackets at >= X+0.1. BLS release ~Oct 14 2026.',
    },
    {
        'label': 'MLB-TB-NYY',
        'kx_series': 'KXMLBGAME',
        'kx_event': 'KXMLBGAME-26SEP241905TBNYY',
        'kx_date': '2026-09-24',
        'kx_teams': [('-TB', 'Tampa Bay Rays'), ('-NYY', 'New York Yankees')],
        'pm_slug': 'mlb-tb-nyy-2026-09-24',
        'pm_mode': 'moneyline',
        'pm_vol_mode': 'market',
        'note': 'Rays @ Yankees, Sep 24 7:05pm ET. Winner of the game, both '
                'sides. PM moneyline vol $9.8k, 1c spread at verification.',
    },
    {
        'label': 'MLB-CLE-BOS',
        'kx_series': 'KXMLBGAME',
        'kx_event': 'KXMLBGAME-26SEP241845CLEBOS',
        'kx_date': '2026-09-24',
        'kx_teams': [('-CLE', 'Cleveland Guardians'), ('-BOS', 'Boston Red Sox')],
        'pm_slug': 'mlb-cle-bos-2026-09-24',
        'pm_mode': 'moneyline',
        'pm_vol_mode': 'market',
        'note': 'Guardians @ Red Sox, Sep 24 6:45pm ET. Winner of the game, '
                'both sides. PM event vol $7.4k at verification.',
    },
    {
        'label': 'MLB-STL-PIT',
        'kx_series': 'KXMLBGAME',
        'kx_event': 'KXMLBGAME-26SEP241235STLPIT',
        'kx_date': '2026-09-24',
        'kx_teams': [('-STL', 'St. Louis Cardinals'), ('-PIT', 'Pittsburgh Pirates')],
        'pm_slug': 'mlb-stl-pit-2026-09-24',
        'pm_mode': 'moneyline',
        'pm_vol_mode': 'market',
        'note': 'Cardinals @ Pirates, Sep 24 12:35pm ET. Winner of the game, '
                'both sides. PM event vol $6.5k at verification.',
    },
]


# --------------------------------------------------------------------------
# Fetch helpers with the Senate-pattern staleness gates
# --------------------------------------------------------------------------
def pm_event(slug, vol_mode='event'):
    """Fetch a PM event; return None if stale/dead per the Senate gates.

    vol_mode='event': the Senate $25k event-volume gate. 'market': skip the
    event gate (sports moneyline legs gate on the compared market's own
    volume instead -- see scan_pair).
    """
    try:
        d = get(f'{GAMMA}/events?slug={slug}')
    except Exception:
        return None, 'fetch error'
    if not d:
        return None, 'empty'
    e = d[0] if isinstance(d, list) else d
    try:
        end = datetime.datetime.fromisoformat(
            str(e.get('endDate', '')).replace('Z', '+00:00'))
    except Exception:
        return None, 'bad endDate'
    if not e.get('active') or e.get('closed') or end <= NOW_UTC:
        return None, 'inactive/closed/expired'
    if vol_mode == 'event':
        try:
            if float(e.get('volume') or 0) < PM_VOL_GATE:
                return None, f"event vol ${float(e.get('volume') or 0):,.0f} < $25k"
        except Exception:
            return None, 'bad volume'
    return e, ''


def pm_quote(m):
    """Executable quote for a PM Yes/No market's outcomes[0] side.

    Returns (bid, ask, op) or (None, reason). Gates: real two-sided book,
    spread <= 5c, outcomePrices agrees with the live book (Gamma caches
    aggressively).
    """
    try:
        bb = float(m.get('bestBid'))
        ba = float(m.get('bestAsk'))
        op_raw = m.get('outcomePrices')
        if isinstance(op_raw, str):
            op_raw = json.loads(op_raw)
        op = float((op_raw or [None])[0])
    except Exception:
        return None, 'bad quote fields'
    if not (0 < bb < ba < 1) or (ba - bb) > PM_MAX_SPREAD:
        return None, f'book fail (bid {bb:.3f} ask {ba:.3f})'
    if not (bb - 0.005 <= op <= ba + 0.005):
        return None, f'op {op:.3f} outside book [{bb:.3f},{ba:.3f}]'
    return (bb, ba, op), ''


def pm_group_market(e, group_title):
    cands = [m for m in (e.get('markets') or [])
             if (m.get('groupItemTitle') or '') == group_title]
    if len(cands) != 1:
        return None, f'group {group_title!r}: {len(cands)} matches'
    return cands[0], ''


def pm_outcomes(m):
    """Gamma sometimes returns outcomes as a JSON-encoded string."""
    outs = m.get('outcomes') or []
    if isinstance(outs, str):
        try:
            outs = json.loads(outs)
        except Exception:
            return []
    return outs if isinstance(outs, list) else []


def pm_moneyline_market(e):
    """The head-to-head winner market: outcomes are team names, not Yes/No."""
    for m in (e.get('markets') or []):
        outs = pm_outcomes(m)
        if len(outs) == 2 and outs[0] != 'Yes' and 'vs.' in (m.get('question') or ''):
            return m, ''
    return None, 'no moneyline market found'


def kx_event_nested(event_ticker):
    try:
        return get(f'{KALSHI}/events/{event_ticker}?with_nested_markets=true')['event']
    except Exception:
        return None


def kx_quote(mk):
    """Kalshi executable YES quote; gates: 0<bid<ask<1, spread <= 6c."""
    try:
        kb = float(mk.get('yes_bid_dollars'))
        ka = float(mk.get('yes_ask_dollars'))
    except Exception:
        return None, 'bad kx quote fields'
    if not (0 < kb < ka < 1) or (ka - kb) > KX_MAX_SPREAD:
        return None, f'kx book fail (bid {kb:.2f} ask {ka:.2f})'
    return (kb, ka), ''


def find_kx_market(kx_ev, suffix):
    for mk in kx_ev.get('markets', []):
        if mk.get('ticker', '').endswith(suffix):
            return mk
    return None


def parse_bracket_pct(title):
    """'2.5%' -> 2.5 ; '<=2.0%' -> 2.0 ; '>=2.9%' -> 2.9 ; else None."""
    t = (title or '').replace('≤', '<=').replace('≥', '>=').strip()
    try:
        return float(t.replace('%', '').replace('<=', '').replace('>=', ''))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Per-pair scan
# --------------------------------------------------------------------------
def scan_pair(entry):
    """Scan one PM_MAP entry. Returns (results_rows, n_candidates, skip_note)."""
    label = entry['label']
    rows = []
    n_cand = 0
    skip = ''

    # --- Polymarket side ---
    e, why = pm_event(entry['pm_slug'], vol_mode=entry.get('pm_vol_mode', 'event'))
    if not e:
        return rows, 0, f'PM gate: {why}'
    time.sleep(1.1)  # Gamma courtesy: <=1 req/s

    # --- Kalshi side ---
    kx_ev = kx_event_nested(entry['kx_event'])
    if not kx_ev:
        return rows, 0, f"Kalshi event {entry['kx_event']} not found"
    time.sleep(0.6)

    def check_leg(kx_suffix, fair_yes, leg_label, pm_quote_note):
        """Compare one leg: Kalshi YES ask vs PM-implied fair."""
        mk = find_kx_market(kx_ev, kx_suffix)
        if not mk:
            return (leg_label, 'skip', f'kx {kx_suffix} not found', '')
        kxq, why = kx_quote(mk)
        if not kxq:
            return (leg_label, 'skip', f'kx gate: {why}', '')
        kb, ka = kxq
        pay_c = int(round(ka * 100))
        edge_c = (fair_yes * 100.0) - pay_c
        net_c = edge_c - fee_cents(pay_c)
        row = (leg_label, f'{pay_c}c ask', f'{fair_yes * 100:.1f}c fair',
               f'{edge_c:+.1f}c edge', f'{net_c:+.1f}c net', pm_quote_note)
        return (leg_label, 'ok', row, (mk.get('ticker', ''), pay_c, edge_c, net_c))

    mode = entry['pm_mode']

    if mode == 'group':
        m, why = pm_group_market(e, entry['pm_group'])
        if not m:
            return rows, 0, f'PM group: {why}'
        q, why = pm_quote(m)
        if not q:
            return rows, 0, f'PM quote gate: {why}'
        bb, ba, op = q
        fair = op
        leg_label = f"{entry['kx_suffix']} ({entry.get('kx_subtitle', '')})"
        leg_label, status, payload, det = check_leg(
            entry['kx_suffix'], fair, leg_label,
            f"PM {entry['pm_group']}: bid {bb:.3f}/ask {ba:.3f} op {op:.3f}")
        if status == 'skip':
            return rows, 0, payload
        rows.append(payload)
        t, pay_c, edge_c, net_c = det
        if edge_c >= EDGE_BAR_C:
            n_cand += 1
            shadow_candidate(
                module='xvenue', ticker=t, side='yes', fair_yes=round(fair, 4),
                price_cents=pay_c, edge_c=round(edge_c, 1), net_c=round(net_c, 1),
                note=f"{label}: KX YES ask {pay_c}c vs PM fair {fair * 100:.1f}c "
                     f"(PM bid {bb:.3f}/ask {ba:.3f}). {entry['note']}")

    elif mode == 'sum':
        # Kalshi rung "above X" vs sum of PM one-decimal brackets >= X+0.1.
        # Every bracket must pass the quote gates or the leg is skipped.
        for kx_suffix, cut, leg_label in entry['pm_legs']:
            parts = []
            ok = True
            detail = ''
            for m in (e.get('markets') or []):
                pct = parse_bracket_pct(m.get('groupItemTitle') or m.get('question'))
                if pct is None or pct < cut + 0.05:
                    continue
                q, why = pm_quote(m)
                if not q:
                    ok = False
                    detail = f"PM bracket {pct}%: {why}"
                    break
                bb, ba, op = q
                parts.append((pct, op))
            if not ok:
                rows.append((leg_label, 'skip', detail, '', '', ''))
                continue
            if not parts:
                rows.append((leg_label, 'skip', 'no PM brackets found', '', '', ''))
                continue
            fair = sum(p for _, p in parts)
            l2, status, payload, det = check_leg(
                kx_suffix, fair, f"{kx_suffix} ({leg_label})",
                f"PM sum of {len(parts)} brackets = {fair * 100:.1f}c")
            if status == 'skip':
                rows.append((leg_label, 'skip', payload, '', '', ''))
                continue
            rows.append(payload)
            t, pay_c, edge_c, net_c = det
            if edge_c >= EDGE_BAR_C:
                n_cand += 1
                shadow_candidate(
                    module='xvenue', ticker=t, side='yes', fair_yes=round(fair, 4),
                    price_cents=pay_c, edge_c=round(edge_c, 1), net_c=round(net_c, 1),
                    note=f"{label}: KX YES ask {pay_c}c vs PM fair {fair * 100:.1f}c "
                         f"(sum of {len(parts)} brackets). {entry['note']}")

    elif mode == 'moneyline':
        # sports: market-level volume gate on the moneyline market itself
        m, why = pm_moneyline_market(e)
        if not m:
            return rows, 0, f'PM moneyline: {why}'
        try:
            mvol = float(m.get('volume') or 0)
        except Exception:
            mvol = 0
        if mvol < PM_MKT_VOL_GATE:
            return rows, 0, f'PM moneyline vol ${mvol:,.0f} < ${PM_MKT_VOL_GATE:,.0f}'
        q, why = pm_quote(m)
        if not q:
            return rows, 0, f'PM quote gate: {why}'
        bb, ba, op = q
        outs = pm_outcomes(m)
        op_raw = m.get('outcomePrices')
        if isinstance(op_raw, str):
            op_raw = json.loads(op_raw)
        for kx_suffix, team in entry['kx_teams']:
            try:
                idx = outs.index(team)
            except ValueError:
                rows.append((team, 'skip', f'{team!r} not in PM outcomes', '', '', ''))
                continue
            try:
                team_op = float(op_raw[idx])
            except Exception:
                rows.append((team, 'skip', 'bad outcomePrices', '', '', ''))
                continue
            # team YES price with its own two-sided book (complement of the
            # outcomes[0] book for idx 1); same 5c spread + op-agreement gates
            t_bid, t_ask = (bb, ba) if idx == 0 else (1.0 - ba, 1.0 - bb)
            if not (0 < t_bid < t_ask < 1) or (t_ask - t_bid) > PM_MAX_SPREAD \
                    or not (t_bid - 0.005 <= team_op <= t_ask + 0.005):
                rows.append((team, 'skip',
                             f'book fail (bid {t_bid:.3f} ask {t_ask:.3f} op {team_op:.3f})',
                             '', '', ''))
                continue
            fair = team_op
            l2, status, payload, det = check_leg(
                kx_suffix, fair, f"{kx_suffix} {team}",
                f"PM {team}: bid {t_bid:.3f}/ask {t_ask:.3f} op {team_op:.3f}")
            if status == 'skip':
                rows.append((team, 'skip', payload, '', '', ''))
                continue
            rows.append(payload)
            t, pay_c, edge_c, net_c = det
            if edge_c >= EDGE_BAR_C:
                n_cand += 1
                shadow_candidate(
                    module='xvenue', ticker=t, side='yes', fair_yes=round(fair, 4),
                    price_cents=pay_c, edge_c=round(edge_c, 1), net_c=round(net_c, 1),
                    note=f"{label}: KX YES ask {pay_c}c vs PM fair {fair * 100:.1f}c "
                         f"({team}). {entry['note']}")

    return rows, n_cand, skip


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------
def main():
    today = NOW_UTC.strftime('%Y-%m-%d')
    print(f'alpha_xvenue SHADOW scan {today} — {len(PM_MAP)} mapped pairs')
    print('=' * 100)
    total_cand = 0
    skipped = []
    for entry in PM_MAP:
        label = entry['label']
        # date-keyed sports entries self-skip off their date
        if entry.get('kx_date') and entry['kx_date'] != today:
            msg = f"entry date {entry['kx_date']} != today; skipping"
            skipped.append((label, msg))
            print(f'{label:18s} SKIP {msg}')
            continue
        print(f'{label:18s} {entry["pm_slug"]}')
        try:
            rows, n_cand, skip = scan_pair(entry)
        except Exception as ex:
            skipped.append((label, f'exception: {ex}'))
            print(f'{"":18s} SKIP exception: {ex}')
            continue
        if skip and not rows:
            skipped.append((label, skip))
            print(f'{"":18s} SKIP {skip}')
            continue
        for r in rows:
            print(f'{"":18s} ' + ' | '.join(str(x) for x in r))
        if skip:
            skipped.append((label, skip))
            print(f'{"":18s} note: {skip}')
        total_cand += n_cand
    print('=' * 100)
    print(f'candidates: {total_cand} | pairs skipped: {len(skipped)}')
    for label, msg in skipped:
        print(f'  skip {label}: {msg}')
    shadow_run(module='xvenue', n_candidates=total_cand,
               note=f'{len(PM_MAP)} pairs scanned; {len(skipped)} skipped',
               extra={'skipped': [f'{l}: {m}' for l, m in skipped]})
    print('shadow_run logged. Exiting 0 (zero candidates is a valid outcome).')
    return 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0] not in ('--shadow',):
        print(f'unknown arg {args[0]!r}; only --shadow (default) is supported',
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main())
