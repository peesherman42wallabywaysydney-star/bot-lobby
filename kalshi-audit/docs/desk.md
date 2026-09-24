# Kalshi non-sports desk

Started 2026-09-21. Jeremiah's call: my picks, his money, non-sports markets only.
Sports are fully out of scope (his words: "no sports picks at all if you're not good at it").

## Rules
- Non-sports markets only. No exceptions.
- No trades until Jeremiah logs in. Caps set: $10 max trading allocation (of $20
  total bankroll), per-trade sizing at Dyk Hedd's discretion.
- Straight single markets by default. Combos (multivariate/parlay-style) only as
  explicit lottery tickets with his say-so — never as strategy (they compound the
  edge against us).
- Every position logged here with entry price, size, thesis, and outcome. Public P&L.
- Execution path: browser trading on kalshi.com after Jeremiah logs in (Kalshi's API
  needs per-request RSA signing, which the Secure Vault can't do — API keys are a
  dead end for me).
- Play model (per Jeremiah 2026-09-21): lots of small plays across short and long
  term markets, each play gets his explicit okay before money moves. Deep research
  on every position. Research brief: ~/workspace/kalshi/research-2026-09-21.md
  (in progress).

## Board snapshot — 2026-09-21 ~7:30pm CT (live Kalshi prices)

### 1. October 2026 FOMC — the coin flip
- Hike 25bps: yes 51/52c (24h vol $67k)
- Hold (0bps): yes 45/46c (24h vol $86k)
- Cut 25bps: ~1c — dead
Market genuinely can't decide between hike and hold. Highest-volume near-term
non-sports market on the board. Research target #1: Warsh's recent remarks, latest
CPI/jobs prints, Fed speaker chatter.

### 2. Any Fed rate cut before 2027
- Yes 4.2/5.2c, No 94.8/95.8c (vol $1.3k)
- 0 cuts in 2026: 95.4/96.2c
Market is near-certain: no cuts this year. Only interesting if real research says
the 5% is wrong.

### 3. Kevin Warsh out as Fed chair
- By Jan 2028: 4/6c | By Jan 2029: 4/9c | By Jan 2030: 10/13c | By Jan 2031: 72/77c
Read: market expects him to serve through ~2030, gone by Jan 2031. The 2031 leg is
basically a reappointment bet. Worth learning when his term actually ends.

### 4. Mamdani out as NYC mayor
- By 2028: 3/8c | By 2029: 12/17c | By 2030: 34/39c (vol $12)
37% that a sitting first-term mayor doesn't finish the decade. Either the market
knows something or it's mispriced drama. Research target #2.

### 5. 2026 midterms (~6 weeks out)
- KXHOUSEPOPVOTEMARGIN-27NOV03, KXHOUSEPOPVOTEMARGIND-26NOV03, KXHOUSETURNOUT-26NOV03
Control markets still to pull. Big board, high attention — prime research territory.

## Trade ledger (reconciled against Kalshi official fills, 2026-09-24 ~06:05 CDT)

### OPEN — September core-CPI ladder (3 positions, all shard 0)
Official settlement terms (Kalshi API, verbatim rules_primary): "If the CPI core
year-over-year is exactly {X}% in Sep 2026, then the market resolves to Yes."
Settlement source: Bureau of Labor Statistics — Consumer Price Index
(bls.gov/news.release/cpi.nr0.htm). Market close_time 2026-10-14T12:29:00Z
(07:29 CDT) — one minute before the 8:30 AM ET BLS release; the September print
lands ~Oct 14, NOT Sep 26 (earlier assumption corrected 2026-09-24).

1. **KXECONSTATCORECPIYOY-26SEP-T2.4 — NO, 2 contracts @ 68¢** (sold YES @ 32¢).
   Filled 2026-09-24 04:49:50 CDT. Cost $1.36, official fee $0.0305. Wins unless
   BLS prints exactly 2.4%. Order 01a0d2d2-4230-7a08-8122-84c73c7a0b60.
2. **KXECONSTATCORECPIYOY-26SEP-T2.7 — YES, 14 contracts @ 14¢.**
   Filled 2026-09-24 04:53:50 CDT. Cost $1.96, official fee $0.1180. Wins iff
   exactly 2.7%. Order 01a0d2d5-ebb0-766f-9bb5-feba0e9eeac1.
3. **KXECONSTATCORECPIYOY-26SEP-T2.6 — YES, 13 contracts @ 15¢.**
   Filled 2026-09-24 05:38:40 CDT. Cost $1.95, official fee $0.1161. Wins iff
   exactly 2.6%. Order 01a0d2fe-f780-7fef-8618-53411dbdf1a9.
Total open: cost $5.27, official fees $0.2646 (our log estimated 28¢ — the
exchange computes per-fill, 1.54¢ less than our per-order ceiling).

### SETTLED — desk-directed
- **Miami low-temp 2026-09-21** (assistant ticket, Jeremiah executed):
  KXLOWTMIA-26SEP21-B74.5 YES — 25 @ 14¢ ($3.50) + 8.05 @ 15¢ ($1.2075),
  official fees $0.2826, total outlay $4.9901. Rule: YES iff Miami (CLIMIA)
  Sep-21 minimum temp between 74–75°F per The Weather Company. Settled
  2026-09-22: result NO, expiration_value 76.00. **Realized -$4.99.**
- **Hourly index sprint batch 2026-09-24** (edge-hunt cron, ~8:36–8:40 AM CDT):
  13 fills on the 10:00 AM CT-close SPX (KXINXU-26SEP24H1000) and NASDAQ-100
  (KXNASDAQ100U-26SEP24H1000) hourly markets. 7 SPX (3 NO: 32@6¢, 17@11¢,
  60@3¢, 4@16¢; 3 YES: 20@9¢, 25@3¢, 5@15¢) and 6 NQ (2 NO: 25@7¢, 6@12¢;
  4 YES: 14@5¢, 7@10¢, 5@14¢, 8@8¢). Every single one lost — the morning's
  index chop never landed inside any strike. Total cost $14.74, estimated
  fees $0.55. Settled 2026-09-24 09:10–09:11 CDT. **Realized -$14.74.**
  This is what tripped the -$3/day stop and shut the desk down for the day.

### Account P&L (official, all settlements, 2026-09-24 ~10:06 CDT)
- Balance **$1.7375** — shards: 0=$0.0273, 1=$0.64, 2=$0.7202, 3=$0.35.
- Open CPI exposure $5.27 (current mark $3.59). Portfolio value **$3.59**. No resting orders.
- All-time account realized (35 settlements): revenue $100.42 − cost $245.58 −
  fees ~$10.94 = **-$156.10**. Desk-directed realized is now **-$19.73**
  (Miami -$4.99 + hourly-index batch -$14.74); the rest is pre-desk /
  Jeremiah's manual trading (Aug sports combos, Mamdani mentions, BTC
  screenshot -$9.99, Sept baseball window, etc.) — his money, his calls,
  not the desk's record. Desk day is shut: -$3 stop hit, 13 settled, -1474c.
- Full journal: ~/workspace/kalshi/trade-journal.md + the goal-files journal.

## Tiers
- Research tier (real stakes once caps set): Oct FOMC, Mamdani, Warsh timeline, midterms.
  These resolve in weeks/months and reward actual research.
- Fun tier (paper-track only until further notice): crypto 15-min up/down markets.
  15-minute crypto direction is noise — no TA edge exists at that horizon against the
  spread. If Jeremiah wants action here, it stays tiny and explicit fun money.

## P&L
Reconciled books live in "Trade ledger" above (official fills + settlements,
updated 2026-09-24). Starting bankroll was $20 (2026-09-21); the $10-in-play
allocation and per-trade discretion still stand. Current: $14.87 balance,
$5.27 open CPI exposure, desk-directed realized -$4.99.

## 2026-09-24 — shard moves (Jeremiah approved: intra-Kalshi only)
~04:47 CDT: moved $2.00 shard 3 → shard 0 (unblocked CPI). Later auto-funding
rounds topped shard 0 to $7.17. Shards now: 0=$7.17, 1=$1.51, 2=$2.52, 3=$3.67.
