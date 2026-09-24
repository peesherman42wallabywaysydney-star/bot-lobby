#!/usr/bin/env python3
"""Exact Kalshi per-series fee math. See PLATFORM.md §4.

Per-ORDER (not per-contract) ceiling:
    fee = ceil_to_cent(rate * C * P * (1 - P))
where C = contracts in the order, P = fill price in dollars.

- Taker rate 0.07; HALF rate 0.035 on INX* / NASDAQ100* index series.
- Maker fees apply ONLY where fee_type says so
  (quadratic_with_maker_fees / quadratic_with_combo_maker_fees, e.g. sports):
  0.0175, half 0.00875 on index series.
- fee_multiplier (usually 1) scales the rate.
- Unknown / 'flat' fee_type: falls back to the standard taker rate
  (conservative; the flat schedule amount isn't published in our captures).

fee_type is read from GET /series/{ticker} and cached on disk
(hidden_files/fee_type_cache.json) so we don't re-fetch every run.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, 'hidden_files', 'fee_type_cache.json')

TAKER_RATE = 0.07
MAKER_RATE = 0.0175
HALF_TAKER_RATE = 0.035
HALF_MAKER_RATE = 0.00875
MAKER_FEE_TYPES = ('quadratic_with_maker_fees', 'quadratic_with_combo_maker_fees')

_cache = None


def series_of(ticker):
    """Series ticker = everything before the first dash."""
    return (ticker or '').split('-')[0].upper()


def is_half_rate(series):
    core = series[2:] if series.startswith('KX') else series
    return core.startswith('INX') or core.startswith('NASDAQ100')


def taker_rate(series, fee_multiplier=1.0):
    r = HALF_TAKER_RATE if is_half_rate(series) else TAKER_RATE
    return r * (fee_multiplier or 1.0)


def maker_rate(series, fee_type=None, fee_multiplier=1.0):
    if fee_type not in MAKER_FEE_TYPES:
        return 0.0
    r = HALF_MAKER_RATE if is_half_rate(series) else MAKER_RATE
    return r * (fee_multiplier or 1.0)


def _ceil_cents(dollars):
    return int(math.ceil(dollars * 100 - 1e-9))


def order_fee_cents(contracts, price_cents, series, fee_type=None,
                    fee_multiplier=1.0, maker=False):
    """Exact fee for ONE order, in cents. Our entries are taker-intent
    (maker=False). Returns 0 when no fee applies."""
    if contracts <= 0:
        return 0
    p = max(0.0, min(1.0, price_cents / 100.0))
    r = (maker_rate(series, fee_type, fee_multiplier) if maker
         else taker_rate(series, fee_multiplier))
    if r <= 0:
        return 0
    return _ceil_cents(r * contracts * p * (1 - p))


def _load_cache():
    global _cache
    if _cache is None:
        try:
            _cache = json.load(open(CACHE_PATH))
        except Exception:
            _cache = {}
    return _cache


def get_fee_info(series, fetcher=None):
    """(fee_type, fee_multiplier) for a series, cached on disk.
    fetcher(series) -> dict with 'fee_type'/'fee_multiplier' (tests pass a
    stub; live callers pass trade_client.get_series). On any failure returns
    (None, 1.0) — the conservative taker-rate default."""
    cache = _load_cache()
    if series in cache:
        e = cache[series]
        return e.get('fee_type'), e.get('fee_multiplier', 1.0)
    fee_type, mult = None, 1.0
    if fetcher is not None:
        try:
            d = fetcher(series) or {}
            fee_type = d.get('fee_type')
            mult = float(d.get('fee_multiplier') or 1.0)
        except Exception:
            fee_type, mult = None, 1.0
    cache[series] = {'fee_type': fee_type, 'fee_multiplier': mult}
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        json.dump(cache, open(CACHE_PATH, 'w'), indent=1)
    except Exception:
        pass
    return fee_type, mult


if __name__ == '__main__':
    # Unit tests against the worked examples in PLATFORM.md §4.
    assert order_fee_cents(4, 50, 'KXBTCD') == 7        # 0.07*4*.25 = .07
    assert order_fee_cents(4, 80, 'KXBTCD') == 5        # .0448 -> .05
    assert order_fee_cents(4, 10, 'KXBTCD') == 3        # .0252 -> .03
    assert order_fee_cents(100, 50, 'KXBTCD') == 175    # 1.75 exact
    assert order_fee_cents(100, 50, 'KXINX') == 88     # half rate .875 -> .88
    assert order_fee_cents(100, 50, 'KXNASDAQ100U') == 88
    assert order_fee_cents(4, 50, 'KXNBAGAME',
                           'quadratic_with_maker_fees', maker=True) == 2  # .0175 -> .02
    assert order_fee_cents(4, 50, 'KXBTCD', 'quadratic', maker=True) == 0  # no maker fee
    assert order_fee_cents(1, 50, 'KXBTCD') == 2        # ceil(1.75c)
    assert order_fee_cents(1, 1, 'KXBTCD') == 1         # ceil(.0693c) -> 1c
    assert order_fee_cents(0, 50, 'KXBTCD') == 0
    assert series_of('KXBTCD-26SEP24-T95000') == 'KXBTCD'
    assert series_of('SENATENC-26-D') == 'SENATENC'
    assert is_half_rate('KXINX') and is_half_rate('KXNASDAQ100U')
    assert not is_half_rate('KXBTCD') and not is_half_rate('KXNBAGAME')
    # cache round-trip with a stub fetcher
    ft, m = get_fee_info('KXTESTSERIES',
                         fetcher=lambda s: {'fee_type': 'quadratic_with_maker_fees',
                                            'fee_multiplier': 2})
    assert (ft, m) == ('quadratic_with_maker_fees', 2.0), (ft, m)
    ft2, m2 = get_fee_info('KXTESTSERIES', fetcher=lambda s: (_ for _ in ()).throw(Exception('no refetch')))
    assert (ft2, m2) == ('quadratic_with_maker_fees', 2.0)  # served from cache
    assert order_fee_cents(4, 50, 'KXTESTSERIES', ft2, m2) == 14  # 2x multiplier
    print('fees.py: all unit tests passed')
