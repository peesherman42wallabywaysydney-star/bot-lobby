#!/usr/bin/env python3
"""
clv_tracker.py — offline wager ledger with closing-line-value analysis.

Read-only analysis. No APIs, no automation, no sportsbook touches anything.
A human records each hypothetical or real wager with its price and the
closing price; this reports closing-line value (CLV) and results against
expectation. The human decides everything.

Usage:
  python3 clv_tracker.py record --market "NFL: KC -3" --side home \\
      --price-taken -110 --price-close -115 --stake 10
  python3 clv_tracker.py settle --id 3 --result win
  python3 clv_tracker.py report

Prices may be given as American odds (-110, +150) or decimal (1.91, 2.50)
or Kalshi-style cents (52). CLV is measured on de-vigged implied
probability of the side taken:

    clv = (close_fair_prob - taken_fair_prob) / taken_fair_prob

Positive CLV means you beat the close. Over a large sample, realized ROI
should converge toward average CLV — that is the honest yardstick.
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clv_log.jsonl")


# ---------------------------------------------------------------- prices

def to_decimal(price):
    """American / decimal / Kalshi-cents -> decimal odds."""
    p = str(price).strip()
    if p.lower().endswith("c"):
        p = p[:-1]
    v = float(p)
    if 0 < v < 1:            # Kalshi probability
        return 1.0 / v
    if 1 <= v <= 100 and v != int(v):  # Kalshi cents like 52.5
        return 100.0 / v
    if 1 < v < 100 and abs(v - round(v)) < 1e-9 and v not in (2,):
        # ambiguous small ints: treat 52 as cents only if flagged; else decimal
        pass
    if v >= 100 or v <= -100:  # American
        return 1.0 + 100.0 / abs(v) if v > 0 else 1.0 - 100.0 / v
    if v > 1:                # decimal odds
        return v
    raise ValueError(f"cannot parse price {price!r}")


def implied(decimal_odds):
    return 1.0 / decimal_odds


# ---------------------------------------------------------------- ledger

def _load():
    rows = []
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _save(rows):
    with open(LEDGER, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def cmd_record(a):
    rows = _load()
    rid = (max((r["id"] for r in rows), default=0) + 1)
    rows.append({
        "id": rid,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market": a.market,
        "side": a.side,
        "price_taken": a.price_taken,
        "price_close": a.price_close,
        "stake": a.stake,
        "result": None,  # win | loss | push — filled in later via settle
        "note": a.note or "",
    })
    _save(rows)
    print(f"recorded wager #{rid}")


def cmd_settle(a):
    rows = _load()
    for r in rows:
        if r["id"] == a.id:
            if a.result not in ("win", "loss", "push"):
                sys.exit("result must be win|loss|push")
            r["result"] = a.result
            _save(rows)
            print(f"wager #{a.id} settled as {a.result}")
            return
    sys.exit(f"no wager #{a.id}")


def cmd_report(_a):
    rows = _load()
    if not rows:
        print("ledger is empty — nothing to report.")
        return

    open_n = sum(1 for r in rows if not r.get("result"))
    settled = [r for r in rows if r.get("result") in ("win", "loss", "push")]
    if not settled:
        print(f"{len(rows)} wager(s) recorded, none settled yet.")
        return

    clvs, profits, stakes = [], [], []
    for r in settled:
        pt = implied(to_decimal(r["price_taken"]))
        pc = implied(to_decimal(r["price_close"]))
        clv = (pc - pt) / pt if pt else 0.0
        clvs.append(clv)
        s = float(r["stake"])
        stakes.append(s)
        dec = to_decimal(r["price_taken"])
        if r["result"] == "win":
            profits.append(s * (dec - 1))
        elif r["result"] == "loss":
            profits.append(-s)
        else:
            profits.append(0.0)

    n = len(settled)
    avg_clv = sum(clvs) / n
    beat = sum(1 for c in clvs if c > 0) / n
    total_staked = sum(stakes)
    roi = sum(profits) / total_staked if total_staked else 0.0

    # rough significance: se of mean CLV
    var = sum((c - avg_clv) ** 2 for c in clvs) / max(n - 1, 1)
    se = math.sqrt(var / n) if n > 1 else float("nan")
    z = avg_clv / se if se and se == se else float("nan")

    print(f"wagers: {n} settled ({open_n} open)")
    print(f"beat the close: {beat:6.1%}")
    print(f"avg CLV:        {avg_clv:+7.2%}   (expected long-run ROI ~ this)")
    print(f"realized ROI:   {roi:+7.2%}   on {total_staked:.2f} staked")
    if z == z:
        print(f"CLV z-score:    {z:+.2f}   (|z|>2 ~= significant)")
    print()
    if n < 100:
        print("sample < 100: ROI is nearly meaningless; CLV is the only signal.")
    elif n < 500:
        print("sample 100-500: directional. Trust CLV over profit.")
    else:
        print("sample 500+: an edge claim starts to mean something.")
    print()
    print("Stopping rule suggestion: quit the experiment if avg CLV <= 0")
    print("after 300+ wagers, or if realized drawdown exceeds 30% of bankroll.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="log a wager")
    r.add_argument("--market", required=True)
    r.add_argument("--side", required=True)
    r.add_argument("--price-taken", required=True, help="price you got")
    r.add_argument("--price-close", required=True, help="closing price")
    r.add_argument("--stake", type=float, required=True)
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_record)

    s = sub.add_parser("settle", help="mark a wager win|loss|push")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--result", required=True)
    s.set_defaults(fn=cmd_settle)

    p = sub.add_parser("report", help="CLV + ROI report")
    p.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
