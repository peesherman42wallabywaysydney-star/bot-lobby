#!/usr/bin/env python3
"""Post-trade learning loop for the Kalshi desk.

For every settled position, joins the model's fair value at entry (from
trade_log.jsonl) with the actual outcome, then updates per-model
calibration stats: bias (mean predicted YES prob minus realized rate),
Brier score, and a shrunk bias adjustment.

Small samples = wide humility: the adjustment is shrunk toward zero by
n/(n+K) so a couple of lucky/unlucky trades can't move pricing, and it
is hard-capped at +/-3c no matter what the raw bias says.

Reads : ~/workspace/kalshi/hidden_files/trade_log.jsonl
Writes: ~/workspace/kalshi/hidden_files/calibration.json
        ~/workspace/kalshi/hidden_files/LEARNING_LOG.md (only when new
        settlements were consumed)
Safe  : never places orders, never moves money. Pure file I/O.

Usage: python3 learn_from_settlements.py [--dry-run]
"""

import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HIDDEN = os.path.join(HERE, 'hidden_files')
TRADE_LOG = os.path.join(HIDDEN, 'trade_log.jsonl')
CALIB_PATH = os.path.join(HIDDEN, 'calibration.json')
LEARN_LOG = os.path.join(HIDDEN, 'LEARNING_LOG.md')

# Shrinkage prior strength: adjustment = -bias * n / (n + SHRINK_K).
# With 2 settled trades the raw bias counts for ~9%; with 20 it counts
# for 50%; with 100 for ~83%. Small sample, small opinion.
SHRINK_K = 20
# Hard cap on any adjustment, in probability units (3c).
MAX_ADJ = 0.03
# Minimum settled trades before we even record stats for a model is 1;
# shrinkage handles the humility, so there is no separate n-gate.


def model_of(ticker, asset=None):
    """Map a ticker (and optional asset tag) to the model that priced it."""
    import re
    if asset == 'SWEEP':
        return 'sweep'
    if re.match(r'KX(BTC|ETH|SOL)15M', ticker or ''):
        return 'crypto15m'
    if re.match(r'KX(BTC|ETH|SOL)D', ticker or ''):
        return 'cryptodaily'
    if re.match(r'KX(CPICORE|ECONSTATCPICORE|ECONSTATCORECPIYOY)-', ticker or ''):
        return 'econ'
    if re.match(r'KX(HIGH|LOWT)[A-Z]+-', ticker or ''):
        return 'weather'
    if re.match(r'SENATE[A-Z]{2}-26-[DR]$', ticker or ''):
        return 'politics'
    return 'index'


def fair_yes_of(placed):
    """Recover the model's entry-time fair YES probability.

    Newer log entries carry fair_cents directly. Older ones only have
    price + raw edge, so reconstruct: edge_yes = fair_yes - ask_yes;
    edge_no = bid_yes - fair_yes (== fair_no - ask_no). Rounding noise
    of ~1c is acceptable; shrinkage absorbs it.
    """
    if placed.get('fair_cents') is not None:
        return max(0.001, min(0.999, placed['fair_cents'] / 100.0))
    p = placed.get('price_cents')
    e = placed.get('edge_cents')
    if p is None or e is None:
        return None
    if placed.get('side') == 'yes':
        f = (p + e) / 100.0
    else:
        f = (100 - p - e) / 100.0
    return max(0.001, min(0.999, f))


def load_calib():
    try:
        with open(CALIB_PATH) as f:
            return json.load(f)
    except Exception:
        return {'meta': {}, 'seen_trade_ids': [], 'models': {}}


def run_learning(dry_run=False):
    """Consume newly settled trades and update calibration.

    Returns a summary dict. With dry_run=True, nothing is written.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    calib = load_calib()
    seen = set(calib.get('seen_trade_ids', []))
    models = calib.get('models', {})

    placed, settles = {}, []
    voided = set()
    try:
        with open(TRADE_LOG) as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                a = e.get('action')
                if a == 'placed' and e.get('trade_id') and e.get('kind') != 'combo':
                    placed[e['trade_id']] = e
                elif a == 'placed_leg' and e.get('trade_id'):
                    # Combo legs settle individually; attribute each leg to
                    # the combo model, not the single-leg model.
                    placed[e['trade_id']] = dict(e, _combo_leg=True)
                elif a == 'settle_void' and e.get('trade_id'):
                    # 2026-09-24 phantom: zero official fills — the model
                    # never had a position, so its outcome teaches nothing.
                    voided.add(e['trade_id'])
                elif a == 'settle' and e.get('trade_id') and e.get('result') in ('yes', 'no'):
                    settles.append(e)
    except FileNotFoundError:
        settles = []

    new_trades = []
    for s in settles:
        tid = s['trade_id']
        if tid in seen or tid in voided:
            continue
        p = placed.get(tid)
        if not p or not p.get('ticker'):
            continue  # settled something we have no entry record for
        f = fair_yes_of(p)
        if f is None:
            continue
        outcome = 1.0 if s['result'] == 'yes' else 0.0
        model = 'combo' if p.get('_combo_leg') else model_of(p['ticker'], p.get('asset'))
        new_trades.append({
            'trade_id': tid, 'ticker': p['ticker'], 'model': model,
            'side': p.get('side'), 'price_cents': p.get('price_cents'),
            'fair_yes': round(f, 4), 'outcome_yes': outcome,
            'pnl_cents': s.get('pnl_cents'),
        })

    per_model = {}
    for t in new_trades:
        m = per_model.setdefault(t['model'], {'n': 0, 'bias_sum': 0.0,
                                              'brier_sum': 0.0, 'won': 0,
                                              'still_pass': 0, 'trades': []})
        err = t['fair_yes'] - t['outcome_yes']
        m['n'] += 1
        m['bias_sum'] += err
        m['brier_sum'] += err * err
        won = (t['outcome_yes'] == 1.0) == (t['side'] == 'yes')
        m['won'] += 1 if won else 0
        m['trades'].append(t)

    summary = {'ts': now, 'consumed': len(new_trades), 'adjustments': {},
               'models': {}, 'dry_run': dry_run}
    for model, m in sorted(per_model.items()):
        n = m['n']
        bias = m['bias_sum'] / n                      # >0 means model overpredicts YES
        brier = m['brier_sum'] / n
        raw_adj = -bias * n / (n + SHRINK_K)           # shrink toward zero
        adj = max(-MAX_ADJ, min(MAX_ADJ, raw_adj))     # hard 3c cap
        prev = models.get(model, {})
        # Merge with history: keep a running n so shrinkage strengthens
        # as evidence accumulates across runs.
        hist_n = int(prev.get('n', 0))
        hist_bias_sum = float(prev.get('bias_sum', 0.0))
        hist_brier_sum = float(prev.get('brier_sum', 0.0))
        tot_n = hist_n + n
        tot_bias = (hist_bias_sum + m['bias_sum']) / tot_n
        tot_brier = (hist_brier_sum + m['brier_sum']) / tot_n
        tot_adj = max(-MAX_ADJ, min(MAX_ADJ, -tot_bias * tot_n / (tot_n + SHRINK_K)))
        # Sanity check: would the new adjustment have kept these trades
        # above the 15c bar? (Honest counterfactual, not a decision.)
        still = 0
        for t in m['trades']:
            fa = max(0.001, min(0.999, t['fair_yes'] + tot_adj))
            if t['side'] == 'yes':
                edge = fa * 100 - t['price_cents']
            else:
                edge = (100 - t['price_cents']) - (1 - fa) * 100
            if edge >= 15:
                still += 1
        if not dry_run:
            models[model] = {
                'n': tot_n,
                'bias': round(tot_bias, 4),
                'bias_sum': round(hist_bias_sum + m['bias_sum'], 4),
                'brier': round(tot_brier, 4),
                'brier_sum': round(hist_brier_sum + m['brier_sum'], 4),
                'adjustment': round(tot_adj, 4),   # YES-prob shift models apply
                'updated': now,
            }
        summary['models'][model] = {
            'new_n': n, 'total_n': tot_n,
            'bias': round(bias, 4), 'total_bias': round(tot_bias, 4),
            'brier': round(brier, 4), 'total_brier': round(tot_brier, 4),
            'win_rate': f"{m['won']}/{n}",
            'adjustment': round(tot_adj, 4),
            'prev_adjustment': round(float(prev.get('adjustment', 0.0)), 4),
            'still_above_bar': f"{still}/{n}",
        }
        summary['adjustments'][model] = round(tot_adj, 4)

    if dry_run:
        return summary

    for t in new_trades:
        seen.add(t['trade_id'])
    calib['seen_trade_ids'] = sorted(seen)
    calib['models'] = models
    meta = calib.get('meta', {})
    meta['last_run'] = now
    meta['runs'] = int(meta.get('runs', 0)) + 1
    calib['meta'] = meta
    with open(CALIB_PATH, 'w') as f:
        json.dump(calib, f, indent=2)

    if new_trades:
        _append_learn_log(now, summary, new_trades)
    return summary


def _fmt_adj(a):
    return f"{a * 100:+.2f}c"


def _append_learn_log(now, summary, new_trades):
    """Plain-English, no-fluff record of what the run learned."""
    lines = [f"\n## {now[:10]} {now[11:16]} UTC — learning run",
             f"Consumed {len(new_trades)} newly settled trade(s)."]
    for model, s in sorted(summary['models'].items()):
        tickers = ', '.join(t['ticker'] for t in new_trades if t['model'] == model)
        lines.append(
            f"- **{model}**: {s['new_n']} new (lifetime {s['total_n']}). "
            f"Bias {s['total_bias']:+.3f} "
            f"({'overpredicts YES' if s['total_bias'] > 0 else 'underpredicts YES' if s['total_bias'] < 0 else 'dead even'}), "
            f"Brier {s['total_brier']:.3f}, our bets went {s['win_rate']}. "
            f"Adjustment {_fmt_adj(s['prev_adjustment'])} -> {_fmt_adj(s['adjustment'])}. "
            f"With the new adjustment, {s['still_above_bar']} of these would still have cleared the 15c bar. "
            f"Tickers: {tickers}.")
        if s['total_n'] < 10:
            lines.append(f"  Sample is tiny ({s['total_n']} trades) — shrinkage is doing "
                         f"most of the work here, and that's the point. Don't trust this number yet.")
    pnl = sum(t.get('pnl_cents') or 0 for t in new_trades)
    lines.append(f"Settled P&L on these trades: {pnl:+d}c.")
    lines.append("")
    header = ("# Learning Log — what the models got wrong\n"
              "Machine-appended after every learning run. Raw and honest: "
              "small samples get called out, not hidden.\n")
    if not os.path.exists(LEARN_LOG):
        with open(LEARN_LOG, 'w') as f:
            f.write(header)
    with open(LEARN_LOG, 'a') as f:
        f.write('\n'.join(lines) + '\n')
    return LEARN_LOG


def main(argv):
    dry = '--dry-run' in argv
    s = run_learning(dry_run=dry)
    print(f"[learn{' dry-run' if dry else ''}] consumed {s['consumed']} settled trades")
    for model, m in sorted(s['models'].items()):
        print(f"  {model}: n={m['total_n']} bias={m['total_bias']:+.4f} "
              f"brier={m['total_brier']:.4f} win={m['win_rate']} "
              f"adj={m['prev_adjustment'] * 100:+.2f}c -> {m['adjustment'] * 100:+.2f}c "
              f"still_above_bar={m['still_above_bar']}")
    if s['consumed'] == 0:
        print("  nothing settled since last run — no calibration changes. "
              "That's honest: the models learn nothing until trades resolve.")


if __name__ == '__main__':
    main(sys.argv)
