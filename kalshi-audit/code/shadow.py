#!/usr/bin/env python3
"""Shared shadow-mode logging for Kalshi alpha modules.

Every new alpha module (yesfade, xvenue, contain, soccer, nfl) logs its
candidates through here. Shadow records go to hidden_files/trade_log.jsonl
with action="shadow_candidate" / "shadow_run" — the live trader
(auto_trade.py) parses EDGE stdout lines, NEVER the trade log, so a shadow
record can never trigger an order. Shadow mode is the default and only mode
for unvalidated modules: nothing here places orders, moves money, or POSTs
anything.

Usage:
    from shadow import shadow_candidate, shadow_run
    shadow_candidate(module='xvenue', ticker='KXFED-...', side='yes',
                     fair_yes=0.62, price_cents=45, edge_c=17.0,
                     net_c=15.0, note='PM 60c vs KX 45c')
    shadow_run(module='xvenue', n_candidates=3, note='5 pairs checked')
"""
import json
import os
import datetime

try:
    from zoneinfo import ZoneInfo
    CHI = ZoneInfo('America/Chicago')
except Exception:
    CHI = None

HERE = os.path.dirname(os.path.abspath(__file__))
TRADE_LOG = os.path.join(HERE, 'hidden_files', 'trade_log.jsonl')


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _chicago_date():
    try:
        return _now().astimezone(CHI).strftime('%Y-%m-%d')
    except Exception:
        return _now().strftime('%Y-%m-%d')


def _append(rec):
    rec['ts'] = _now().isoformat()
    rec.setdefault('date', _chicago_date())
    os.makedirs(os.path.dirname(TRADE_LOG), exist_ok=True)
    with open(TRADE_LOG, 'a') as f:
        f.write(json.dumps(rec) + '\n')
    return rec


def shadow_candidate(module, ticker, side, fair_yes, price_cents, edge_c,
                     net_c=None, note='', extra=None):
    """Log one shadow candidate. side in ('yes','no'). fair_yes in [0,1].
    edge_c / net_c in cents. Never places an order — log only."""
    if side not in ('yes', 'no'):
        raise ValueError(f'side must be yes/no, got {side!r}')
    rec = {
        'action': 'shadow_candidate',
        'mode': 'SHADOW',
        'module': module,
        'ticker': ticker,
        'side': side,
        'fair_yes': round(float(fair_yes), 4),
        'price_cents': int(price_cents),
        'edge_c': round(float(edge_c), 1),
        'net_c': round(float(net_c), 1) if net_c is not None else None,
        'would_take_live_bar': (net_c is not None and net_c >= 15),
        'note': note,
    }
    if extra:
        rec['extra'] = extra
    return _append(rec)


def shadow_run(module, n_candidates, note='', extra=None):
    """Log a per-run summary for a shadow module."""
    rec = {
        'action': 'shadow_run',
        'mode': 'SHADOW',
        'module': module,
        'candidates': int(n_candidates),
        'note': note,
    }
    if extra:
        rec['extra'] = extra
    return _append(rec)


if __name__ == '__main__':
    print('shadow.py self-test: logging one synthetic shadow record')
    r = shadow_candidate(module='selftest', ticker='KXSELFTEST-26-T1.0',
                         side='yes', fair_yes=0.6, price_cents=45,
                         edge_c=15.0, net_c=13.0, note='self-test, not a real market')
    print('wrote:', r['ts'], r['action'], r['module'])
    print('OK — delete this line from the trade log if you want a clean book.')
