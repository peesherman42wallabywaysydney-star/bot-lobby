#!/usr/bin/env python3
"""Synthetic combo construction math, shared by edge_scan.py (§9) and auto_trade.py.

Kalshi has no public combo order books — listed combos are per-user RFQ mints
with private, take-it-or-leave-it maker quotes (verified 2026-09-24: zero
combo-shaped series among open events; see combo-rfq-research.md). So we BUILD
combos: N single-leg YES/NO limit orders, placed simultaneously as one trade
decision.

Economics:
  * EV is LINEAR across legs. There is no combo instrument and no maker quote,
    so the RFQ "maker tax" (+1.1c decorrelated / +2.5c same-game over the
    independence product) does not apply here. Each leg is bought at its own
    book price; combined edge = sum of per-leg edges minus per-leg fees.
  * Correlation does NOT change EV — it concentrates RISK (correlated legs win
    and lose together). So correlated baskets clear a HIGHER bar (20c) instead
    of getting a fair-value haircut. Decorrelated baskets: 15c bar.
  * Every leg must be +EV standalone (>=10c at scan, >=5c on fresh
    re-verification). Then a partial fill degrades gracefully: the worst case
    is holding a subset of +EV legs, never an unintended donation.

Fees (measured against Kalshi docs + combo-rfq-research.md):
  taker fee per contract per leg = ceil(7c * p * (1-p)), p = execution price.
  Fees MULTIPLY across legs — a 3-leg combo at 50c/leg pays ~6c in fees.

Fill risk (the hard problem):
  Kalshi has no atomic multi-leg execution. Design: every leg is placed as
  fill_or_kill (FOK) — fully fills immediately or dies, so there are NO
  partial fills within a leg. Across legs the only failure mode is
  some-legs-fill / others-die, leaving a subset of +EV legs (acceptable by
  construction). A depth gate (resting size >= contracts on every leg, from a
  book fetched seconds before) makes FOK failures rare. See CRAFT.md §9.
"""
import math

TAKER_RATE = 0.07          # Kalshi taker fee rate
LEG_MIN_SCAN_C = 10        # per-leg edge (cents) required at scan time
LEG_MIN_VERIFY_C = 5       # per-leg edge (cents) required on fresh re-verify
BAR_DECORR_C = 15          # combo take bar, decorrelated legs
BAR_CORR_C = 20            # combo take bar, any correlated pair
SCAN_BAR_C = 10            # combo scan bar (trader re-verifies at 15/20)


def fee_cents(price_cents):
    """Exact taker fee per contract, in cents: ceil(7 * p * (1-p))."""
    p = max(0.0, min(1.0, price_cents / 100.0))
    return int(math.ceil(TAKER_RATE * 100 * p * (1 - p) - 1e-9))


def leg_edge_cents(side, fair_yes, price_cents):
    """Per-contract edge in cents for one leg. price_cents = cents we pay
    for `side`; fair_yes in [0,1]."""
    if side == 'yes':
        return (fair_yes - price_cents / 100.0) * 100.0
    return ((1.0 - fair_yes) - price_cents / 100.0) * 100.0


def combo_report(legs, corr=False, risk_budget_cents=200):
    """legs: list of {'side','fair_yes','price_cents'} (price = pay price).
    Returns the full construction: per-leg edges, fees, net edge, max
    payable, suggested contracts for the risk budget, correlation flag,
    take/pass at scan bar, and the take/pass rule string."""
    edges = [leg_edge_cents(l['side'], l['fair_yes'], l['price_cents']) for l in legs]
    fees = [fee_cents(l['price_cents']) for l in legs]
    edge_c = int(round(sum(edges)))
    fee_c = int(sum(fees))
    net_c = edge_c - fee_c
    # combined fair value of one combo unit (1 contract per leg), in cents
    fair_c = int(round(sum(
        (l['fair_yes'] if l['side'] == 'yes' else (1.0 - l['fair_yes'])) * 100
        for l in legs)))
    bar_c = BAR_CORR_C if corr else BAR_DECORR_C
    legs_ok = all(e >= LEG_MIN_SCAN_C for e in edges)
    take_scan = legs_ok and net_c >= SCAN_BAR_C
    total_pay_c = int(round(sum(l['price_cents'] for l in legs)))
    contracts = max(0, int(risk_budget_cents // total_pay_c)) if total_pay_c > 0 else 0
    # max payable for the unit while still clearing the take bar after fees
    maxpay_c = fair_c - bar_c - fee_c
    rule = (f"take iff fresh reverify: every leg >= {LEG_MIN_VERIFY_C}c, "
            f"combo net >= {bar_c}c, all legs FOK-fill")
    return {
        'n_legs': len(legs),
        'leg_edges_c': [int(round(e)) for e in edges],
        'edge_c': edge_c,
        'fee_c': fee_c,
        'net_c': net_c,
        'fair_c': fair_c,
        'bar_c': bar_c,
        'corr': corr,
        'take_scan': take_scan,
        'legs_ok': legs_ok,
        'total_pay_c': total_pay_c,
        'contracts': contracts,
        'maxpay_c': maxpay_c,
        'rule': rule,
    }


if __name__ == '__main__':
    # sanity checks
    assert fee_cents(50) == 2      # ceil(7*.5*.5)=ceil(1.75)
    assert fee_cents(30) == 2      # ceil(1.47)
    assert fee_cents(10) == 1      # ceil(0.63)
    assert fee_cents(90) == 1
    assert fee_cents(1) == 1       # minimum 1c even at extremes
    r = combo_report([
        {'side': 'yes', 'fair_yes': 0.58, 'price_cents': 42},
        {'side': 'yes', 'fair_yes': 0.51, 'price_cents': 38},
    ])
    assert r['leg_edges_c'] == [16, 13], r['leg_edges_c']
    assert r['edge_c'] == 29 and r['fee_c'] == 4 and r['net_c'] == 25, r
    assert r['take_scan'] and not r['corr'] and r['bar_c'] == 15
    r2 = combo_report([
        {'side': 'yes', 'fair_yes': 0.58, 'price_cents': 42},
        {'side': 'yes', 'fair_yes': 0.51, 'price_cents': 38},
    ], corr=True)
    assert r2['bar_c'] == 20 and r2['take_scan']
    r3 = combo_report([
        {'side': 'yes', 'fair_yes': 0.55, 'price_cents': 42},   # 13c edge
        {'side': 'no', 'fair_yes': 0.60, 'price_cents': 30},    # fair_no .40, 10c edge
    ])
    assert r3['leg_edges_c'] == [13, 10], r3['leg_edges_c']
    # donation leg fails legs_ok
    r4 = combo_report([
        {'side': 'yes', 'fair_yes': 0.58, 'price_cents': 42},
        {'side': 'yes', 'fair_yes': 0.45, 'price_cents': 42},   # 3c edge
    ])
    assert not r4['take_scan'] and not r4['legs_ok']
    print('combo.py self-tests pass')
