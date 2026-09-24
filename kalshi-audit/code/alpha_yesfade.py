#!/usr/bin/env python3
"""Alpha module #2 — YES-bias retail fade, CALIBRATED (SHADOW ONLY).

Study-hall update (2026-09-24, LEARNING_LOG.md Lesson 2): the flat version of
this overlay ("+2c extra edge for YES on retail-heavy, tilt size to NO") was
uncomfortably close to the blanket fade that LOST 8.1c/contract in a
5,000-market replay. "Fade only >20pp off 0.50" lost more. Only
calibrated-curve trading at >=4c of MEASURED disagreement made money
(+11.5c/contract): "the further a market is from 0.50, the more accurate it
is."

So the overlay is now a CALIBRATED DISAGREEMENT GATE, not a flat rule:
  * An isotonic P(YES|quoted) curve is pre-seeded from Kalshi's public
    settled history (calibration_backfill.py -> hidden_files/yesfade_calibration.json).
  * For each candidate we compute disagreement_c = (quoted_YES - empirical_YES)*100.
  * The tilt/fade applies ONLY where |disagreement| >= 4c AND the direction
    supports the trade:
      - YES entry while YES is overpriced >=4c -> FADE (bar 17c, half size)
      - NO entry while YES is overpriced >=4c -> CONFIRMED (bar 15c, full size)
      - YES entry while YES is underpriced >=4c -> CONFIRMED (bar 15c, full size)
      - |disagreement| < 4c -> NO OVERLAY AT ALL (bar 15c, full size).
        This is the key change: most markets get no fade, because the data
        says blanket fading loses.
  * No calibration file -> overlay fully OFF (never a flat fallback).

The UCD favorite-longshot bias (cheap YES overpriced) now works as a PRIOR
INSIDE the calibrated curve, not as a standalone trigger.

SHADOW MODE ONLY. Never places orders, never moves money, never POSTs
transfers, never calls order endpoints. Logs through shadow.py
(action="shadow_candidate"/"shadow_run"); the live trader (auto_trade.py)
parses EDGE stdout lines and NEVER the trade log, so a shadow record can
never trigger an order. Stays shadow until our own fills validate it.

Usage:
    python3 alpha_yesfade.py            # one edge_scan run, fade, shadow-log, summary
    python3 alpha_yesfade.py --selftest # offline self-test, no scan, no logging

Exit code is 0 even with zero candidates.
"""
import bisect
import json
import os
import re
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HIDDEN = os.path.join(HERE, 'hidden_files')
sys.path.insert(0, HERE)
from shadow import shadow_candidate, shadow_run
import combo  # fee_cents(), leg_edge_cents() — math only, no live paths

MODULE = 'yesfade'
BASE_BAR_C = 15.0        # desk live net bar (cents)
FADE_EXTRA_C = 2.0       # extra bar ONLY when calibrated fade triggers
DISAGREEMENT_GATE_C = 4.0  # study-hall: only >=4c measured disagreement made money
CALIB_PATH = os.path.join(HIDDEN, 'yesfade_calibration.json')
COMBO_DECORR_BAR_C = 15.0
COMBO_CORR_BAR_C = 20.0

# ---------------- retail vs sharp classification ----------------
SHARP_ASSETS = {'BTC', 'ETH', 'SOL', 'GOLD', 'SPX', 'NDX', 'WTI', 'SILVER', 'ECON'}
NO_OVERLAY_ASSETS = {'WX', 'SWEEP'}   # weather/sweep: no YES-bias research basis

RETAIL_POLITICS = ('SENATE', 'PRES', 'GOV', 'HOUSE', 'MAYOR', 'ELECT',
                   'CONGRESS', 'NOM', 'DEM', 'GOP')
RETAIL_SPORTS = ('NFL', 'NBA', 'MLB', 'NHL', 'CFB', 'CBB', 'SOCCER', 'TENNIS',
                 'GOLF', 'UFC', 'MMA', 'GAME', 'MATCH', 'CHAMP', 'PLAYOFF',
                 'TOURN', 'BOWL', 'PARLAY', 'TOUCHDOWN', 'WRESTLE', 'BOXING',
                 'RACING', 'OLYMP', 'SUPERBOWL', 'WORLDCUP')
SHARP_SERIES = ('ECONSTAT', 'FED', 'INFLATION', 'CPI', 'PAYROLLS', 'GDP',
                'UNEMP', 'RATE', 'BTC', 'ETH', 'SOL', 'INX', 'NASDAQ', 'GOLD',
                'WTI', 'SILVER', 'SPX', 'NDX')


def series_of(ticker):
    """Series ticker = everything before the first dash, uppercased."""
    return (ticker or '').split('-')[0].upper()


def _series_class(ticker):
    s = series_of(ticker)
    core = s[2:] if s.startswith('KX') else s
    for p in RETAIL_POLITICS:
        if core.startswith(p):
            return 'retail', f'politics series {s}'
    for p in RETAIL_SPORTS:
        if p in core:
            return 'retail', f'sports/parlay series {s}'
    for p in SHARP_SERIES:
        if core.startswith(p) or p in core:
            return 'sharp', f'sharp/nowcast series {s}'
    return 'neutral', f'unclassified series {s}'


def classify(ticker, asset=None, kind=None, legs=None):
    """Classify a candidate as retail-heavy / sharp / neutral.

    Returns (bucket, reason). bucket in ('retail', 'sharp', 'neutral').
    Parlays/combos are retail-heavy when they carry a YES leg on a
    retail-heavy series (the classic retail parlay shape).
    """
    asset = (asset or '').upper()
    if kind == 'combo' or asset == 'COMBO':
        yes_retail = [l for l in (legs or [])
                      if (l.get('side') or '').lower() == 'yes'
                      and _series_class(l.get('ticker', ''))[0] == 'retail']
        if yes_retail:
            return ('retail',
                    'combo w/ YES leg on retail-heavy series '
                    f"({', '.join(series_of(l.get('ticker')) for l in yes_retail[:3])})")
        return 'neutral', 'combo w/ no retail-heavy YES leg'
    if asset == 'POL':
        return 'retail', 'politics (asset tag)'
    if asset in SHARP_ASSETS:
        return 'sharp', f'{asset} nowcast/model-driven (asset tag)'
    if asset in NO_OVERLAY_ASSETS:
        return 'neutral', f'{asset}: no YES-bias research basis'
    return _series_class(ticker)


# ---------------- calibrated disagreement gate ----------------
# Isotonic P(YES|quoted) curves pre-seeded from Kalshi's public settled
# history (calibration_backfill.py). The fade/tilt fires ONLY on >=4c of
# SHRUNK measured disagreement — never as a flat rule (study-hall Lesson 2).
#
# CONVERGENCE TRAP (verified 2026-09-24): settled crypto/sports/weather
# markets carry CONVERGED last prices (binary 0.01/0.99), not tradeable-time
# predictions — a curve fit on them is circular. The backfill therefore fits
# ONLY the ECON_MACRO super-family (scheduled macro releases that close
# BEFORE the print: CPI, Fed, payrolls, GDP, ECB). There is deliberately NO
# global fallback: a macro-bracket curve must never score a crypto/sports/
# weather quote. Tickers whose series is not in series_map get tilt
# 'no_calib' and the overlay stays OFF for them.

# Shrinkage for thin blocks (same philosophy as the learning loop's
# n/(n+20)): shrunk = raw * n_block / (n_block + SHRINK_K). A block with
# fewer than MIN_BLOCK_N samples never moves the gate.
SHRINK_K = 20
MIN_BLOCK_N = 10


def load_calibration(path=CALIB_PATH):
    """Load the isotonic calibration doc. Returns None when missing/invalid —
    in which case the overlay is fully OFF (no flat fallback, ever)."""
    try:
        with open(path) as f:
            doc = json.load(f)
        fams = doc.get('families') or {}
        if not fams or not doc.get('series_map'):
            return None
        # every family must carry block sample counts
        if any(not e.get('xs') or not e.get('ys') or not e.get('ns')
               for e in fams.values()):
            return None
        return doc
    except Exception:
        return None


def _curve_lookup(xs, ys, ns, p):
    """Stepwise lookup on left-edge knots. Returns (empirical, block_n)."""
    p = max(0.0, min(1.0, p))
    i = bisect.bisect_right(xs, p) - 1
    i = max(0, min(i, len(ys) - 1))
    return ys[i], ns[i]


def _family_for_ticker(ticker, calib):
    """series_map lookup. Returns the family entry or None — never a
    cross-type fallback."""
    fam = (calib.get('series_map') or {}).get(series_of(ticker))
    if fam is None:
        return None, None
    entry = (calib.get('families') or {}).get(fam)
    return fam, entry


def calibrated_disagreement_c(yes_price, ticker, calib):
    """Shrunk disagreement_c = (quoted_YES - empirical_YES) * 100 * n/(n+K).

    Positive => the market overprices YES vs settled history (favors NO).
    Returns (disagreement_c, family_used, block_n). calib=None or ticker not
    in series_map -> (None, None, 0): overlay disabled for this quote.
    """
    if calib is None:
        return None, None, 0
    fam, entry = _family_for_ticker(ticker, calib)
    if entry is None:
        return None, None, 0
    q, n_block = _curve_lookup(entry['xs'], entry['ys'], entry['ns'],
                               yes_price)
    if n_block < MIN_BLOCK_N:
        return None, fam, n_block
    raw = (yes_price - q) * 100.0
    shrunk = raw * n_block / (n_block + SHRINK_K)
    return shrunk, fam, n_block


def apply_fade(candidates, calib=None):
    """Pure function: apply the CALIBRATED disagreement gate to candidates.

    Each candidate is a dict with at least {ticker, side, net_c, asset} and
    optionally {kind ('single'|'combo'), edge_c, legs, corr, pay_cents}.
    calib: calibration doc from load_calibration(), or None to disable the
    overlay entirely.

    Returns a NEW list; each result carries the original fields plus:
      retail_class, class_reason (informational only — no longer moves the bar),
      disagreement_c, calib_family, calib_n, tilt_dir, faded (bool),
      bar_c, base_bar_c, passed (bool), size_mult, fade_note.

    tilt_dir in {None, 'fade_yes', 'confirm_no', 'confirm_yes', 'no_calib'}.
    """
    results = []
    for c in candidates:
        kind = c.get('kind', 'single')
        side = (c.get('side') or '').lower()
        legs = c.get('legs') or []
        bucket, reason = classify(c.get('ticker', ''), c.get('asset'), kind, legs)

        base_bar = BASE_BAR_C
        if kind == 'combo':
            base_bar = (COMBO_CORR_BAR_C if c.get('corr') == 'corr'
                        else COMBO_DECORR_BAR_C)

        # yes-equivalent quoted price per leg (singles: one leg)
        if kind == 'combo':
            leg_yes = []
            for l in legs:
                lp = (l.get('scan_pay_c') or 0) / 100.0
                ls = (l.get('side') or '').lower()
                leg_yes.append((l.get('ticker', ''),
                                lp if ls == 'yes' else 1.0 - lp,
                                ls))
        else:
            pay = (c.get('pay_cents') or 0) / 100.0
            leg_yes = [(c.get('ticker', ''),
                        pay if side == 'yes' else 1.0 - pay, side)]

        disaggs = []
        for lticker, yq, ls in leg_yes:
            d, fam_used, n_fam = calibrated_disagreement_c(yq, lticker, calib)
            disaggs.append({'ticker': lticker, 'side': ls, 'yes_price': round(yq, 4),
                            'disagreement_c': (None if d is None else round(d, 1)),
                            'family': fam_used, 'n': n_fam})

        bar = base_bar
        size_mult = 1.0
        faded = False
        tilt_dir = None

        if calib is None:
            tilt_dir = 'no_calib'
        elif disaggs and disaggs[0]['disagreement_c'] is None \
                and disaggs[0]['family'] is None:
            # calibration exists but this series has no curve (convergence-
            # trap exclusion): overlay stays OFF, never a cross-type fallback.
            tilt_dir = 'no_curve'
        elif kind == 'combo':
            worst = max((g['disagreement_c'] for g in disaggs
                         if g['disagreement_c'] is not None
                         and g['side'] == 'yes'),
                        default=None)
            if worst is not None and worst >= DISAGREEMENT_GATE_C:
                faded, tilt_dir = True, 'fade_yes'
                bar, size_mult = base_bar + FADE_EXTRA_C, 0.5
        elif side == 'yes':
            d = disaggs[0]['disagreement_c']
            if d is not None and d >= DISAGREEMENT_GATE_C:
                faded, tilt_dir = True, 'fade_yes'      # YES overpriced: fade it
                bar, size_mult = base_bar + FADE_EXTRA_C, 0.5
            elif d is not None and d <= -DISAGREEMENT_GATE_C:
                tilt_dir = 'confirm_yes'                # YES underpriced: confirmed
        elif side == 'no':
            d = disaggs[0]['disagreement_c']
            if d is not None and d >= DISAGREEMENT_GATE_C:
                tilt_dir = 'confirm_no'                 # YES overpriced: NO confirmed

        net_c = c.get('net_c')
        passed = net_c is not None and net_c >= bar

        d_str = ('n/a' if disaggs[0]['disagreement_c'] is None
                 else f"{disaggs[0]['disagreement_c']:+.1f}c")
        note = (f"yesfade[calibrated]: class={bucket} ({reason}); side={side or kind}; "
                f"disagreement(shrunk)={d_str} (gate {DISAGREEMENT_GATE_C:g}c, "
                f"curve={disaggs[0]['family']}, block_n={disaggs[0]['n']}); "
                f"tilt={tilt_dir}; bar={bar:g}c (base {base_bar:g}c); "
                f"net={net_c if net_c is not None else '?'}c -> "
                f"{'PASS' if passed else 'FADED OUT'}; size_mult={size_mult:g}")
        results.append({**c, 'retail_class': bucket, 'class_reason': reason,
                        'disagreement_c': disaggs[0]['disagreement_c'],
                        'calib_family': disaggs[0]['family'],
                        'calib_n': disaggs[0]['n'],
                        'tilt_dir': tilt_dir, 'leg_disagreements': disaggs,
                        'faded': faded, 'bar_c': bar, 'base_bar_c': base_bar,
                        'passed': passed, 'size_mult': size_mult,
                        'fade_note': note})
    return results


# ---------------- EDGE-line parsing (patterns copied from auto_trade.py) ----------------
# Copied verbatim from auto_trade.py CAND_RE (~line 252) — NOT imported, per the
# rule that this module never touches the live path.
CAND_RE = re.compile(
    r'\b(BTC|ETH|SOL|GOLD|SPX|NDX|WTI|SILVER|POL|ECON|WX|SWEEP)\b.*?\b(YES|NO)\b\s+'
    r'(KX[A-Z0-9]+-[A-Za-z0-9.]+-(?:T|B)[\d.]+|SENATE[A-Z]{2}-26-[DR]|[A-Z][A-Z0-9]*-[A-Za-z0-9.\-]+)\b')

COMBO_RE = re.compile(
    r'COMBO legs=(\S+)'
    r'\s+edge_c=(-?\d+)\s+fee_c=(\d+)\s+net_c=(-?\d+)\s+maxpay_c=(-?\d+)'
    r'\s+contracts=(\d+)\s+corr=(decorr|corr)\s+rule=(\S+)')


def parse_price_fair(msg, asset, side):
    """Extract (pay_cents, fair_yes) from an EDGE message.

    YES lines:  '... YES {ticker} ask {p}c vs fair {f}%'
    NO lines:   '... NO {ticker} — YES bid {b}c vs fair {f}%'
                (NO pay = 100 - YES bid, NO fair = 1 - YES fair)
    POL NO is special: fair printed is the NO-side fair.
    WX NO: '... NO {t} — YES bid {b}c vs fair 0%'.
    Returns None when the message carries no parseable numbers (ladder,
    synthetic, field-misprice flags — those are multi-leg/human-review).
    """
    if side == 'yes':
        m = re.search(r'ask (\d+)c vs fair (\d+)%', msg)
        if m:
            return int(m.group(1)), int(m.group(2)) / 100.0
        return None
    m = re.search(r'YES bid (\d+)c vs fair (\d+)%', msg)
    if m:
        bid = int(m.group(1))
        return 100 - bid, int(m.group(2)) / 100.0
    if (asset or '').upper() == 'POL':
        m = re.search(r'ask (\d+)c vs fair (\d+)%', msg)
        if m:
            return int(m.group(1)), 1.0 - int(m.group(2)) / 100.0
    return None


def parse_combo_candidate(m, msg):
    legs = []
    for part in m.group(1).split('+'):
        part = part.strip()
        if not part:
            continue
        s = part.split('|')
        if len(s) != 5:
            return None
        lside, lasset, lticker, lpay, lfair = s
        lside = lside.lower()
        if lside not in ('yes', 'no'):
            return None
        try:
            lpay, lfair = int(lpay), int(lfair)
        except ValueError:
            return None
        legs.append({'asset': lasset, 'side': lside, 'ticker': lticker,
                     'scan_pay_c': lpay, 'scan_fair': lfair / 100.0})
    if len(legs) < 2:
        return None
    return {'kind': 'combo', 'asset': 'COMBO', 'side': 'combo',
            'ticker': 'COMBO:' + '+'.join(l['ticker'] for l in legs),
            'legs': legs, 'corr': m.group(7), 'rule': m.group(8),
            'edge_c': float(m.group(2)), 'fee_c': float(m.group(3)),
            'net_c': float(m.group(4)), 'raw': msg[:200]}


def parse_edge_lines(stdout):
    """Parse edge_scan stdout into candidate dicts. Returns (candidates, stats)."""
    candidates = []
    n_edge_lines = 0
    n_unparseable = 0
    for line in (stdout or '').splitlines():
        line = line.strip()
        if not line.startswith('EDGE:'):
            continue
        n_edge_lines += 1
        msg = line[5:].strip()
        mc = COMBO_RE.search(msg)
        if mc:
            c = parse_combo_candidate(mc, msg)
            if c:
                candidates.append(c)
            else:
                n_unparseable += 1
            continue
        m = CAND_RE.search(msg)
        if not m:
            # field-misprice flags, ladder/synthetic two-leg lines, etc.
            n_unparseable += 1
            continue
        asset, side, ticker = m.group(1), m.group(2).lower(), m.group(3)
        pf = parse_price_fair(msg, asset, side)
        if pf is None:
            n_unparseable += 1
            continue
        pay_c, fair_yes = pf
        edge_c = combo.leg_edge_cents(side, fair_yes, pay_c)
        net_c = edge_c - combo.fee_cents(pay_c)
        candidates.append({'kind': 'single', 'asset': asset, 'side': side,
                           'ticker': ticker, 'pay_cents': int(round(pay_c)),
                           'fair_yes': round(fair_yes, 4),
                           'edge_c': round(edge_c, 1),
                           'net_c': round(net_c, 1), 'raw': msg[:160]})
    # Dedupe by (kind, ticker, side), keep best net_c.
    best = {}
    for c in candidates:
        key = (c.get('kind'), c.get('ticker'), c.get('side'))
        if key not in best or (c.get('net_c') or -1e9) > (best[key].get('net_c') or -1e9):
            best[key] = c
    stats = {'edge_lines': n_edge_lines, 'parsed': len(candidates),
             'unique': len(best), 'unparseable': n_unparseable}
    return list(best.values()), stats


# ---------------- runner ----------------
def run_scan_once(timeout=280):
    p = subprocess.run([sys.executable, os.path.join(HERE, 'edge_scan.py')],
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout or ''


def main(argv):
    if '--selftest' in argv:
        return selftest()
    if any(a for a in argv[1:] if a != '--shadow'):
        print('usage: python3 alpha_yesfade.py [--shadow] [--selftest]',
              file=sys.stderr)
        return 2

    try:
        stdout = run_scan_once()
        scan_ok = True
    except subprocess.TimeoutExpired:
        stdout, scan_ok = '', False
    except Exception as ex:
        print(f'edge_scan failed: {ex}', file=sys.stderr)
        stdout, scan_ok = '', False

    candidates, stats = parse_edge_lines(stdout)
    calib = load_calibration()
    calib_status = ('loaded' if calib is not None
                    else 'MISSING — overlay fully OFF (no flat fallback)')
    faded = apply_fade(candidates, calib)

    passed_singles = [c for c in faded if c['passed'] and c['kind'] == 'single']
    passed_combos = [c for c in faded if c['passed'] and c['kind'] == 'combo']
    faded_out = [c for c in faded if not c['passed']]

    # Shadow-log: one shadow_candidate per single that PASSES the faded bar.
    for c in passed_singles:
        shadow_candidate(
            module=MODULE, ticker=c['ticker'], side=c['side'],
            fair_yes=c['fair_yes'], price_cents=c['pay_cents'],
            edge_c=c['edge_c'], net_c=c['net_c'], note=c['fade_note'],
            extra={'retail_class': c['retail_class'], 'bar_c': c['bar_c'],
                   'faded': c['faded'], 'size_mult': c['size_mult'],
                   'disagreement_c': c['disagreement_c'],
                   'calib_family': c['calib_family'],
                   'tilt_dir': c['tilt_dir']})
    # Full detail for faded-out singles + passing combos lives in the
    # shadow_run extra so the counterfactual cohort stays recoverable for A/B
    # scoring without extra shadow_candidate rows.
    extra = {
        'scan_ok': scan_ok, 'edge_lines': stats['edge_lines'],
        'parsed': stats['parsed'], 'unique': stats['unique'],
        'unparseable': stats['unparseable'],
        'calibration': calib_status,
        'gate_c': DISAGREEMENT_GATE_C,
        'passed_singles': len(passed_singles),
        'passed_combos': len(passed_combos),
        'faded_out': [
            {'ticker': c['ticker'], 'side': c['side'],
             'fair_yes': c.get('fair_yes'), 'price_cents': c.get('pay_cents'),
             'edge_c': c.get('edge_c'), 'net_c': c.get('net_c'),
             'retail_class': c['retail_class'], 'bar_c': c['bar_c'],
             'faded': c['faded'], 'tilt_dir': c['tilt_dir'],
             'disagreement_c': c['disagreement_c']}
            for c in faded_out if c['kind'] == 'single'],
        'combo_decisions': [
            {'ticker': c['ticker'], 'net_c': c.get('net_c'),
             'bar_c': c['bar_c'], 'corr': c.get('corr'),
             'retail_class': c['retail_class'], 'faded': c['faded'],
             'tilt_dir': c['tilt_dir'], 'passed': c['passed']}
            for c in faded if c['kind'] == 'combo'],
    }
    shadow_run(
        module=MODULE, n_candidates=len(passed_singles),
        note=(f"scan: {stats['unique']} unique candidates, calib={calib_status}; "
              f"{len([c for c in faded_out if c['faded']])} faded by calibrated gate "
              f"({len(faded_out)} below bar incl. base 15c), "
              f"{len(passed_singles)} singles + {len(passed_combos)} combos passed"),
        extra=extra)

    # Stdout summary.
    print(f'yesfade scan: {stats["unique"]} unique candidates '
          f'({stats["parsed"]} parsed, {stats["unparseable"]} unparseable, '
          f'{stats["edge_lines"]} EDGE lines)')
    for c in faded:
        mark = 'PASS ' if c['passed'] else 'FADE '
        print(f"  [{mark}] {c.get('asset','?'):6s} {str(c.get('side','?')):6s} "
              f"{c.get('ticker','?')[:44]:44s} net={c.get('net_c')}c "
              f"bar={c['bar_c']:g}c class={c['retail_class']}")
    print(f'shadow: {len(passed_singles)} shadow_candidate rows + 1 shadow_run row logged')
    return 0


def _synth_calib():
    """Tiny synthetic calibration doc for the offline selftest.

    ECON_MACRO curve: quoted 0.30 -> empirical 0.20 (YES overpriced 10c raw,
    8.3c shrunk at block n=100: tilt zone); quoted 0.60 -> empirical 0.62
    (disagreement -1.7c shrunk: no-tilt zone); quoted 0.80 -> empirical 0.70
    (YES overpriced 8.3c shrunk: tilt zone). KXBTCD is NOT in series_map
    (convergence-trap exclusion) -> 'no_curve'.
    """
    return {
        'families': {'ECON_MACRO': {
            'xs': [0.0, 0.30, 0.60, 0.80, 1.0],
            'ys': [0.0, 0.20, 0.62, 0.70, 1.0],
            'ns': [100, 100, 100, 100, 100], 'n': 500}},
        'series_map': {'KXECONSTATCORECPIYOY': 'ECON_MACRO'},
    }


def selftest():
    """Offline check of calibrated-gate math. No scan, no logging."""
    calib = _synth_calib()
    # (candidate, use_calib, expected tilt_dir, expected bar, expected pass,
    #  expected size)
    cases = [
        # YES @30c on CPI, YES overpriced 8.3c shrunk -> calibrated FADE
        ({'kind': 'single', 'asset': 'ECON', 'side': 'yes', 'pay_cents': 30,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 16.0},
         True, 'fade_yes', 17.0, False, 0.5),
        # same but net 18c -> passes the faded bar
        ({'kind': 'single', 'asset': 'ECON', 'side': 'yes', 'pay_cents': 30,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 18.0},
         True, 'fade_yes', 17.0, True, 0.5),
        # NO on CPI, YES overpriced 8.3c shrunk -> CONFIRMED, base bar
        ({'kind': 'single', 'asset': 'ECON', 'side': 'no', 'pay_cents': 70,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 16.0},
         True, 'confirm_no', 15.0, True, 1.0),
        # YES @60c: disagreement -1.7c shrunk (|d|<4) -> NO OVERLAY
        ({'kind': 'single', 'asset': 'ECON', 'side': 'yes', 'pay_cents': 60,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 16.0},
         True, None, 15.0, True, 1.0),
        # YES @80c: YES overpriced 8.3c shrunk -> fade (gate is calibrated,
        # not class-based)
        ({'kind': 'single', 'asset': 'ECON', 'side': 'yes', 'pay_cents': 80,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 16.0},
         True, 'fade_yes', 17.0, False, 0.5),
        # no calibration doc -> overlay fully OFF, never a flat fallback
        ({'kind': 'single', 'asset': 'ECON', 'side': 'yes', 'pay_cents': 30,
          'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5', 'net_c': 16.0},
         False, 'no_calib', 15.0, True, 1.0),
        # series not in series_map (BTC: convergence-trap exclusion) ->
        # overlay OFF via 'no_curve', never a cross-type fallback
        ({'kind': 'single', 'asset': 'BTC', 'side': 'yes', 'pay_cents': 30,
          'ticker': 'KXBTCD-26SEP2407-T94799.99', 'net_c': 16.0},
         True, 'no_curve', 15.0, True, 1.0),
    ]
    fails = 0
    for c, use_calib, exp_tilt, exp_bar, exp_pass, exp_size in cases:
        r = apply_fade([c], calib if use_calib else None)[0]
        ok = (r['tilt_dir'] == exp_tilt and r['bar_c'] == exp_bar
              and r['passed'] == exp_pass and r['size_mult'] == exp_size)
        if not ok:
            fails += 1
            print(f"FAIL {c['ticker']}: got tilt={r['tilt_dir']}/bar={r['bar_c']}/"
                  f"pass={r['passed']}/size={r['size_mult']}, want "
                  f"{exp_tilt}/{exp_bar}/{exp_pass}/{exp_size} "
                  f"(d={r['disagreement_c']})")
        else:
            print(f"ok   {c['ticker'][:30]:30s} tilt={str(r['tilt_dir']):10s} "
                  f"bar={r['bar_c']:g}c pass={r['passed']} size={r['size_mult']:g} "
                  f"d={r['disagreement_c']}")
    # combo: YES leg on a calibrated series, overpriced 8.3c shrunk -> faded.
    # (A YES leg on an unmapped series contributes no disagreement and alone
    # cannot trigger the fade.)
    cc = {'kind': 'combo', 'asset': 'COMBO', 'side': 'combo', 'corr': 'decorr',
          'ticker': 'COMBO:A+B', 'net_c': 16.0,
          'legs': [{'side': 'yes',
                    'ticker': 'KXECONSTATCORECPIYOY-26SEP-T2.5',
                    'scan_pay_c': 30, 'scan_fair': 0.2},
                   {'side': 'no', 'ticker': 'KXBTCD-26SEP2407-T94799.99',
                    'scan_pay_c': 40, 'scan_fair': 0.6}]}
    r = apply_fade([cc], calib)[0]
    ok = r['tilt_dir'] == 'fade_yes' and r['bar_c'] == 17.0 and not r['passed']
    print(('ok   combo fade_yes bar=17' if ok else
           f'FAIL combo: {r["tilt_dir"]}/{r["bar_c"]}/{r["passed"]}'))
    fails += 0 if ok else 1
    n = len(cases) + 1
    print('selftest:', 'FAIL' if fails else 'ALL PASS', f'({n - fails}/{n})')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
