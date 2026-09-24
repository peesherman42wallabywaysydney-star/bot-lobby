# Auto-trading rules — plain English

The bot only trades when the math is overwhelmingly in our favor, and it can
never touch your money beyond placing bets. Here's exactly what it does:

## When it trades
- It scans the markets every few minutes, same as before.
- It only fires when a **fresh double-check** still shows an edge of **15 cents or
  more** per contract. (The old bar for telling you about a ticket by hand was
  12c — the bot holds itself to a higher bar since no human is sanity-checking.)
- It skips anything closing in **under 10 minutes** — no last-second gambles.
- It skips a market entirely if prices are crashing or spiking hard (the model's
  blind spot).

## How much it bets
- **Half-Kelly sizing, hard-capped at $2 per trade.** The stake scales with the
  model's win probability for the side bought (Kelly fraction
  f* = p − (1−p)/b, halved; b = payout odds on the ALL-IN cost including exact
  taker fees). Fee-aware since 2026-09-24: fees shift the optimal stake ~5%
  ($1.50 → $1.42 on the canonical 15¢/30%-win/$17 case) — small next to model
  error, but the bias is systematic (always toward overbetting) and the fix is
  one fixed-point iteration, so it is applied. Thin 15¢ edges bet ~$1.35–$1.50
  on a $17 bankroll; big edges still cap at $2. Never more than the $2 cap on
  one trade. (Changed 2026-09-24 after study-hall math showed the old flat
  min($2, 35%) was too cold on big edges and overshot Kelly ~2× at minimum
  edge whenever the balance sat under $5.71.)
- **Combos use the same half-Kelly philosophy:** each leg is a separate binary
  contract, re-verified +EV standalone, so each leg gets its own half-Kelly
  size and the combo takes the minimum across legs (execution buys equal-size
  legs; simultaneous legs share one bankroll). No joint win probability is
  invented — the desk has no joint-distribution model and Kelly punishes
  invented p's hardest. $2 hard cap on the whole combo's cost. (Unified
  2026-09-24; the old flat min($2, 35%) combo rule had the same flaws as the
  single-trade one it replaced.)
- **No daily cap on number of trades** (Jeremiah lifted it 2026-09-24) — but every
  trade still has to clear the 15¢ edge bar on its own, and the guards below bind.
- **Max $10 committed in play** (original rule, restored in code 2026-09-24 — it
  was never canceled, the code just stopped enforcing it): total entry cost of
  all open trades plus resting orders may never exceed $10.
- **Correlated-risk caps** (added 2026-09-24 after 13 correlated hourly-index
  trades lost ~$13 in one expiry window): max $5 committed per event series,
  max $3 and max 5 trades per single event/expiry bucket. One correlated
  bucket can never single-handedly blow the daily stop.
- **Daily stop-loss: if the bot is down $3 or more on the day, it stops** until
  tomorrow. It can't dig a deep hole.
- **Settlement accounting is official-data-only** (2026-09-24): P&L is booked
  from the exchange's fill history — actual fill prices, quantities, and fees —
  never from the bot's local "placed" records. A placed trade with zero
  official fills is voided, not booked. Realized P&L is **net of official
  fees** (convention changed 2026-09-24; the books now match the exchange to
  the cent).
- **50-trade tripwire (standing rule, 2026-09-24, ENFORCED IN CODE):** if
  50+ trades have settled with total realized P&L at or below zero,
  `tripwire_check()` in auto_trade.py halts live trading and the run continues
  in paper mode until the models are repaired. Checked on every run, after the
  settlement pass, in both live and dry-run. (Net of official fees since
  2026-09-24. Counted by `settled_trades()` — the one canonical count: unique
  trade_ids with a booked outcome, voided trades excluded. The 2026-09-24
  "13 vs ~35" confusion came from counting placed+dry_run log events as
  settlements; only booked outcomes count.)

## What it can never do
- **It cannot add money.** There is no deposit, withdraw, or transfer function
  anywhere in its code — only buy and cancel orders. If you ever want more money
  in, that's your call and yours alone.
- If the account can't cover a trade, it skips it and writes down why.
- It never doubles down on something it already holds.

## How you watch it
- Every single decision — trades placed, trades skipped and why, stop-loss hits —
  is written to a log file. Nothing happens silently.
- It runs in **practice mode (dry-run) until you say otherwise**: it logs exactly
  what it *would* have bought, without spending a cent. You can review a day of
  those and decide if you trust it before flipping it live.

## The honest part
No edge is a lock. A 15c edge means the math says the bet is worth about 15c
more than its price — over many bets that should win, but any single bet can
lose. The stop-loss and the $2 cap are there so a bad day stings instead of
kills.
