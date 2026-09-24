# Learning Log — what the models got wrong
Machine-appended after every learning run. Raw and honest: small samples get called out, not hidden.

## 2026-09-24 10:21 UTC — learning loop goes live
The loop is built and wired in, but there is nothing to learn from yet.
Two trades are live (CPI T2.4 NO 2x @68c, CPI T2.7 YES 14x @14c) and neither
settles until the September CPI print on 2026-09-26. So: 0 settled trades
consumed, 0 calibration changes, all adjustments at +0.00c.

This is the honest starting line. The models get their first report card
when these two resolve. Until then the econ model prices exactly like it
always has — the calibration adjustment is a no-op at zero.

What the loop will do once trades settle:
- bias = mean(model fair YES prob - actual outcome). Positive means the
  model overpredicts YES.
- adjustment = -bias * n/(n+20), capped at +/-3c. With 2 settled trades the
  raw bias counts for ~9%. Small sample, small opinion.
- Brier score tracks whether the probabilities are sharp or mushy.
- If the new adjustment would have killed a trade's 15c bar, that's written
  down too — no hiding behind counterfactuals.

## 2026-09-24 10:50 UTC — STUDY HALL (first pass, ~30 min)

Jeremiah's directive: constantly learn. So I went and read what other people
learned the hard way, instead of paying tuition myself. Four write-ups, one
academic paper, one video I could only partially access. Everything below is
from those sources — no invented numbers. Where I couldn't verify something,
I say so.

### Sources (honest accounting)
1. **kalshiquant WRITEUP.md** (GitHub, pearlfisheryjersey8695/kalshiquant) —
   practitioner write-up, real Kalshi system, 5,000-market replay, 160 tests.
   The single best thing I found. Read the full doc.
2. **parallax-markets PROFITABILITY-STRATEGY-2026-06.md** (GitHub, akarode) —
   adversarial strategy review, triangulated across 7 research agents + Codex +
   Gemini. Brutally honest about base rates. Read the TL;DR + findings table.
3. **Burgi / Deng / Whelan, "Makers and Takers: The Economics of the Kalshi
   Prediction Market" (UCD, Jan 2026)** — academic paper, 300,000+ contracts
   of transaction-level data. Read the abstract + findings via search results;
   did NOT read the full 30-page PDF this pass.
4. **"The math that guarantees profit on Polymarket" (DevGenius) + WEEX
   "Arbitrage Bible"** — summaries of the $40M Polymarket arb paper
   (86M transactions, Apr 2024–Apr 2025). Execution-risk section is the
   valuable part. Did NOT read the underlying paper itself.
5. **YouTube: "I built a Kalshi NFL Prediction Market Bot in Python (it was
   too slow)"** — tried to pull the transcript three ways (yt-dlp blocked as
   bot, Invidious mirrors dead). FAILED to get captions. Only usable material:
   the video's own chapter titles and description, which state the conclusion
   plainly. Treating this as a weak source — one honest post-mortem data
   point, not a transcript I read.

### Lesson 1: Bootstrap calibration from Kalshi's public history — don't wait for our own fills
WHAT: kalshiquant didn't wait 6 weeks for paper trades to calibrate. They
pulled Kalshi's own settled-market history from the public REST API — every
settled market has a last-quoted price and a binary outcome, which is exactly
the (predicted_prob, outcome) pair a calibrator needs. 749 training samples in
12 seconds of HTTP calls. Then they fit an isotonic calibration curve and the
live risk model started making different decisions the same hour.
WHY IT APPLIES: our learning loop is live but has 0 settled trades and won't
get its first report card until the CPI print on 2026-09-26. The calibration
store is sitting at +0.00c doing nothing. We can pre-seed it TODAY from public
history instead of waiting.
TRY: build a backfill script that pulls settled markets from Kalshi's public
API, fits an isotonic curve per series family, and seeds calibration.json.
AVOID their near-miss bug (they caught it before shipping): they first labeled
training data as "did the market predict the right side" and got a degenerate
98% win rate. Correct labels: the QUOTE is the predicted probability, the
binary OUTCOME is the label. Report class balance or you're flying blind.
UNPROVEN FOR US: whether population-level calibration transfers to our
specific series (econ CPI brackets). Seed it, but keep the shrinkage cap until
our own fills confirm.

### Lesson 2: Don't blanket-fade — gate the YES-bias tilt on calibrated disagreement
WHAT: kalshiquant replayed 5,000 markets with three strategies. "Fade anything
not at 0.50" lost 8.1c/contract. "Fade only markets >20pp from 0.50" lost
7.5c/contract — WORSE. "Use the fitted calibration curve, trade only >=4c of
measured disagreement" made +11.5c/contract at 92% hit rate. Their words: "the
further a Kalshi market is from 0.50, the more accurate it is on average. Folk
wisdom about emotional retail flow piling into one-sided markets is the
opposite of what the data shows."
WHY IT APPLIES: our alpha module #2 (YES-bias retail fade) as currently
spec'd — "+2c extra edge for YES entries, tilt sizing to NO" — is uncomfortably
close to the blanket fade that lost money in their replay. The UCD paper's
favorite-longshot bias IS real (cheap YES overpriced: quoted 25% settles ~12%),
but it works as a PRIOR INSIDE a calibrated model, not as a standalone
trigger. Both findings can be true at once: unconditional cheap-YES is
overpriced, conditional blanket-fading without a model loses.
TRY: implement the fade as a calibrated rule — only apply the NO-tilt at price
levels where our isotonic curve (Lesson 1) shows >=4c of empirical
mispricing. Validate against our own fills before giving it size.
AVOID: a flat "always lean NO" tilt. That's the config the data killed.
UNPROVEN FOR US: our fill sample is 2 trades. The UCD result is
population-level (300k contracts); kalshiquant's is 5,000 markets. Neither is
*our* book. Shadow-log the fade, don't live-trade it, until our own numbers
exist.

### Lesson 3: Execution realism — maker-only, VWAP not quotes, fee-aware bars
WHAT: three converging facts. (a) UCD data via parallax: takers lose ~31%,
makers lose ~10% on Kalshi — "any strategy needing immediate fills is
structurally dead," and Kalshi's maker fee rounds to ~$0. (b) The Polymarket
arb paper: CLOB fills are SEQUENTIAL, not atomic — one leg fills, the market
moves, the other leg fills worse. They only counted opportunities with >5c of
margin because smaller spreads get eaten by execution risk. Price fills at
VWAP across depth, never at top-of-book. (c) kalshiquant: Kalshi's fee is
0.07*P*(1-P), which PEAKS at 50c — "a 4c edge at 0.50 is net-zero after
round-trip fees. The same nominal edge is profitable on one contract and
break-even on another."
WHY IT APPLIES: our 15c bar is flat and our edge math uses "executable depth"
(good), but: (1) I have not verified our limit orders actually rest as maker
vs crossing the spread — if we're accidentally taking, we're paying the
taker's 31% tax; (2) our combo module (#3) cannot assume atomic multi-leg
fills on Kalshi — same sequential-fill exposure as the arb paper; (3) our flat
15c bar underprices fee drag near 50c and overprices it at the wings.
TRY: audit our fills for maker-vs-taker; make the edge bar price-aware
(higher required edge near 50c where fees peak); combo shadow signals must
model sequential-fill slippage and demand margin above it.
UNPROVEN FOR US: the maker/taker split of our actual fills — that's a
five-minute audit, do it before the next live trade.

### Lesson 4: Stay out of the latency game — our 5-minute loop can't win short-duration markets
WHAT: the NFL-bot video post-mortem (chapters only, transcript blocked):
"small spike + not fast enough + fees = no profit." Builder had the faster
data feed (ESPN API vs TV stream) and STILL couldn't beat latency + fees on
in-play Kalshi NFL markets. Separately, a live-trading write-up of Polymarket
5-minute BTC binaries: 4W/11L, -49.5% ROI — "5-minute binaries approximate a
random walk at short horizons," win rates 25-27% vs ~53% breakeven.
WHY IT APPLIES: we run a 5-MINUTE cron and trade 15-minute crypto binaries
with IOC. That is exactly the segment both sources found structurally
unprofitable for slow machines. Our edge there isn't edge, it's hope with a
fee drag.
TRY: move 15-min crypto binaries to shadow-only until they show positive
closing-line value over a real sample; keep live fire on daily/weekly markets
(econ, etc.) where 5 minutes of staleness is noise, not death. Do NOT expand
live scope into in-play sports — that's the treadmill the video died on.
UNPROVEN FOR US: we haven't measured our own CLV on 15-min crypto. Shadow-log
it; if it's negative, kill it for live.

### Also noted (not full lessons, worth one line each)
- kalshiquant's latency monitor: 97% of their signal cycle was the PARLAY
  PRICER (42.6s of 44s); model inference was 25ms. "The bottleneck wasn't in
  any of my mental models." For our combo module: instrument per-stage
  latency before assuming the model is the slow part.
- Parallax's inverted funnel: run the TRADABILITY gate (liquidity, spread,
  resolution clarity) BEFORE the model, not after. Our pipeline already
  re-verifies before ordering — keep that order, don't let new modules skip it.
- Kalshi does NOT ban winners (CFTC DCM, doesn't take the other side) —
  unlike sportsbooks. Our desk's durability doesn't depend on staying
  under the radar. One less thing to worry about.
- Base rate honesty (parallax): 84% of Polymarket wallets lose; durable
  winners <1%, nearly all speed/arb bots. Our framing stays: cheap R&D,
  falsify-first, beer-money ceiling until 300+ settled trades say otherwise.

## 2026-09-24 — Maker/taker fill audit (study-hall follow-up)
Audited auto_trade.py: entries are taker-intent BY DESIGN (post_only=False, crossing the spread for immediate fills — see line ~1617). All 3 live fills today (T2.4 NO, T2.7 YES, T2.6 YES) were taker fills.
Study-hall lesson: UCD data shows takers -31% vs makers -10%; "any strategy needing immediate fills is structurally dead." Our defense: the 15c net edge bar is computed after exact fees, so spread cost is inside the bar — but this is an assumption, not a verified fact. Flagged for the learning loop: if settled taker entries systematically underperform the model's fair value by more than the bar accounts for, raise the bar or switch entries to maker-intent. Not changing live behavior on theory alone.

## 2026-09-24 — STUDY HALL — EXPANDED SESSION 1 (Jeremiah's order: "go crazy fr")

Three parallel research tracks, ~40 min. SOURCES, honestly labeled:
(1) ART OF WAR → desk rules: read the Lionel Giles translation directly (Project Gutenberg ebook 132, ch. 1,2,3,4,6,7,8,13) — all Sun Tzu quotes below are verbatim from it. No secondary/guru content.
(2) KELLY MATH for our binary bets: my own derivation, checked against Ed Thorp's paper "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market" (read via PDF mirror; original presented 1997, corrections 2005). Kelly 1956 cited via Thorp. All numbers are my own arithmetic, verified by computation. Poundstone's Fortune's Formula cited as book-only, not read.
(3) REAL PRACTITIONERS: Soros/Quantum Black Wednesday 1992 (Wikipedia citing NYT 1992-10-26 and UK Treasury estimates; the "$15B bet the whole fund" quote is secondhand — UNVERIFIED). FTX/Alameda 2022 (court-trial reporting: cryptonews, CoinDesk-via-Nasdaq, cointelegraph, thewrap; John Ray III testimony via coindition). Jesse Livermore (Reminiscences of a Stock Operator, 1923 — Edwin Lefèvre's NOVELIZED bio, dramatized not memoir; the "never lose >10%" rule is a blog paraphrase from brameshtechanalysis — secondhand; timeline via traderlife.co.uk). Billy Walters (book Gambler 2023 — self-reported record, UNVERIFIED; podcast quotes via covers.com 2024; line-manipulation plays secondhand via sharpestarena.com 2019). Zero guru content, zero fabricated quotes/stats.

Honest framing before the lessons: we have ZERO settled trades of our own, so every lesson below is theory until the learning loop eats real settlements. And one thing I own: the $2/35% sizing rule I built is backwards-shaped (see Lesson 1) — conservative where it's safe to be bold, hot where it's fatal. Fixing that is on me.

### Lesson 1: Our sizing is backwards — cold on top, hot at the bottom. Switch to proportional half-Kelly.
WHAT: Kelly for a binary bet: cost c, win prob p, net odds b=(1−c)/c → f* = p − q/b (my derivation: maximize g(f)=p·ln(1+fb)+q·ln(1−f); f*>0 ⟺ p>c, verified numerically). On our $17 bankroll: p=0.30/c=0.15 (15¢ edge) → Kelly 17.65% = $3.00, we bet $2 (⅔ Kelly, too cold). p=0.35/c=0.15 (20¢ edge) → Kelly $4.00, we bet $2 — exactly HALF-Kelly, which is a defensible place to be (half-Kelly keeps ~80% of full-Kelly log-growth at ~¼ the per-bet variance; Thorp p.403: overbetting is "much more severely penalized" than underbetting). p=0.42/c=0.15 (27¢ edge) → Kelly $5.40, we bet $2 (only 37% of Kelly). So flat $2 is never too hot at $17 — EXCEPT the rule flips below $5.71 balance, where the 35%-of-balance clause binds and overshoots Kelly ~2× at minimum edge: hot precisely when ruin hurts most. And full-Kelly dollars ($4–$5.67) are a trap: they assume p is known exactly; ours comes with real error bars.
WHY IT APPLIES: our bankroll SHRINKS and GROWS; a flat-dollar rule can't track either direction. The 35% clause is a landmine waiting for the first drawdown.
TRY: stake = ½·f*·(current balance), capped at $2, rounded down to whole contracts. Auto-scales both directions. AVOID: ever raising toward full-Kelly dollars because "the math says so" — scale the fraction, not the number.
UNPROVEN: assumes model edges are roughly calibrated. First weeks are calibration data — log model p vs realized hit rate before trusting bigger fractions. Also: a 10¢ optimistic p-error (true p=0.25, model says 0.35 at c=0.15) doubles the stake and cuts expected log-growth ~69% (0.0338 → 0.0106) — calibration error is the whole game.

### Lesson 2: The 15¢ bar is overstatement insurance, not just an EV filter. Guard it harder now that the trade-count cap is gone.
WHAT: Jeremiah lifted the daily trade cap today ("you can enter as much as you want"). That removed one selectivity gate — the 15¢ bar + stop-loss are now the ONLY things standing between the desk and death by volume. Kelly math says why the bar matters: at the 15¢ minimum, a 5–10¢ optimistic p-error still leaves true edge positive. Lower the bar to chase volume and overstatement flips true edge negative while the model still screams "bet" — then Kelly's true optimum is $0 and every dollar is guaranteed bleed.
WHY IT APPLIES: unlimited entries + a leaky edge estimate = the fastest way to convert a good model into a losing desk. Sun Tzu (Giles ch.4 §15): "The victorious strategist only seeks battle after the victory has been won" — the victory is won in the spreadsheet before the order, and the bar is what certifies it.
AVOID: lowering the bar without measured p-error data. If anything, when scan volume rises under the no-cap regime, the bar should get HARDER to clear on thin-book markets, not easier.

### Lesson 3: Sizing must be pre-committed and overrides pre-banned — every blow-up was an override problem, not a rule-writing problem.
WHAT: Walters (survivor): hard 1–3% of bankroll per bet, mechanical, small — "Ideally, you should not risk any more than 1 to 3 percent of your bankroll on any single bet" (his book). Soros (survivor): the ONLY oversize bets came with modeled bounded downside (UK could only defend the peg so far; if wrong, small loss — reportedly "go for the jugular" only after Druckenmiller's structure was in place). Livermore (blow-up): rules existed ON PAPER ("sell what shows you a loss," never average a loser) and he overrode every one — his own post-mortem: "What beat me was not having brains enough to stick to my own game." Alameda (blow-up): literally NO risk function — SBF on the stand: "we did not have a dedicated risk management team, we didn't have a chief risk officer" — while spending ~$8B of customer deposits. The blow-up wasn't a bad trade; it was the absence of every guardrail.
WHY IT APPLIES: our rules ($2/35% → soon half-Kelly, 15¢ bar, −$3 stop) are good Livermore-on-paper rules. They only work if overrides are pre-banned.
TRY: (a) journal line per trade: "sizing followed Y/N"; (b) hard pre-rule: NEVER increase size after a loss — no averaging, no revenge sizing; (c) tier the cap: default $1/trade (~6% at $17), $2 tier reserved for edges ≥25¢ AND structurally clean resolutions (weather, clean econ prints — the closest we get to Soros's bounded downside; ambiguous settlements never qualify).
UNPROVEN: the $1 default tier is directionally what every survivor did, not validated at our scale. The Y/N journaling is a cheap experiment — if overrides cluster, the rule needs teeth (code-enforced), not paper.

### Lesson 4: Put a tilt circuit breaker between the loss and the day stop.
WHAT: −$3/day is a good kill switch, but Livermore died in the gap BEFORE his rules triggered — overtrading after losses, full size, forever. Sun Tzu (Giles ch.8 §12): the general's dangerous faults include "a hasty temper, which can be provoked by insults" — and ch.3: the irritated general "will launch his men to the assault like swarming ants, with the result that one-third of his men are slain." That's a revenge-size trade on $17. Walters externalizes the stop (the % rule decides, not his mood); FTX is what "nobody sits above their own temptation" looks like at scale.
WHY IT APPLIES: the desk's largest behavioral risk isn't the model — it's the 5-minute loop offering a fresh "get even" trade 12 times an hour after every loser.
TRY: two consecutive losing trades → mandatory 30-min cooldown + one written sentence re-verifying the model edge in the journal before the next entry. (The Art of War track proposed halting for the day after ANY losing trade — I softened it; a full-day halt after one loss likely kneecaps good days. Test the cheaper version first.)
UNPROVEN: we haven't measured whether our post-loss trades are actually worse. Trial for a week: compare win rate on first trades of the day vs post-loss trades. If no difference, drop the rule.

### Lesson 5: Hunt undefended markets; evade superior strength. Make passing a tracked win.
WHAT: Sun Tzu (Giles ch.6 §7): "You can be sure of succeeding in your attacks if you only attack places which are undefended." Ch.1 §21: "If he is in superior strength, evade him." For us: undefended = thin, neglected, oddly-priced markets — obscure crypto expiries, weather markets with stale forecasts, small econ prints. Superior strength = liquid index/macro markets where professional market makers price us out — don't duel them where we're the sucker. And the timing principle (Giles ch.4 §§1–2): "first put themselves beyond the possibility of defeat, and then waited for an opportunity" — protection is ours (sizing, stop), profit is the market's gift on its schedule. Flat days with no 15¢ edge are good days, not wasted ones. Spies = intel (ch.13): before entry, check three things — real book depth at our price (not just top quote), the EXACT settlement source/timing (a misread rule is a blown campaign), and the news calendar.
WHY IT APPLIES: $17 bankroll means our only structural advantage is ponds too small for big players. And with no trade-count cap, "scan and pass" has to become a first-class outcome or we'll invent edges to fill the time.
TRY: (a) daily pass-log line: date, best market scanned, why it failed the bar — review weekly; (b) for one week log rough book depth at target price next to realized edge, testing whether thinner markets actually yield bigger edges for us.
UNPROVEN: assumes soft markets exist for us on Kalshi and our models price them better — neither demonstrated yet. Falsify-first: if thin markets show worse realized edges, flip the rule.

### Also noted (one line each)
- Thorp's asymmetry is the single most important sentence from today: overbetting punished FAR worse than underbetting — when in doubt, the error goes small, never big.
- Discrete contracts are negligible at our size ($2 at 15¢ = 13 contracts = $1.95); fees (~1–3¢/contract) are already absorbed inside the 15¢ bar — no separate fee model needed yet.
- Soros concentration lesson, precisely stated: size up ONLY when the downside is modeled and bounded (government with finite reserves), never when the edge merely feels big. Our analog: clean-resolution markets only.
- Walters's quit rule (podcast via covers.com): "If I get to a point that I don't have that advantage, I'll quit." Our analog: if the learning loop shows realized edges ≤ 0 over 50+ settled trades, the desk stops trading and goes back to paper. Write that tripwire down now, while we're calm.

## 2026-09-24 ~11:00 UTC — YES-fade calibrated gate: correction complete
- The flat YES-bias rule is DEAD (study-hall replay: blanket fade −8.1¢/contract).
  Replaced by a calibrated gate: isotonic P(YES|quoted) on ECON_MACRO settled
  history, tilt only on ≥4¢ SHRUNK disagreement (shrinkage n/(n+20), min block n=10).
- CONVERGENCE TRAP found and fixed: settled crypto/sports/weather last_prices are
  converged (binary 0.01/0.99), not predictions. First backfill (15,262 pairs, global
  curve) was circular — caught before any shadow decision used it, replaced by
  macro-only fit (n=134). Crypto/sports/weather get NO curve (tilt 'no_curve'),
  never a cross-type fallback.
- Selftest 8/8. Live scan: 0 faded by gate. Open validation: T2.4 NO shows a
  three-way disagreement (market YES 41% / nowcast model ~5% / history 64%) —
  the Sep CPI print scores all three. Watch this one.

## 2026-09-24 ~12:00 CDT — STUDY HALL (TRACK A: real traders — Bill Benter, deep dive)

ONE TOPIC, done deep: Bill Benter — the computer horse bettor. Sources, honestly
labeled: (1) his own paper, William Benter, "Computer Based Horse Race
Handicapping and Wagering Systems: A Report" (1994, presented ORSA/TIMS Phoenix
Nov 1993) — read in full: intro, model development, the public-line combination
section, the complete wagering-strategy section (incl. Kelly), results, and notes,
via the datagolf.com PDF mirror. The middle Harville-formula tables were skimmed,
not studied. (2) Kit Chellel, "The Gambler Who Cracked the Horse-Racing Code,"
Bloomberg Businessweek, May 2018 — read via mirror (opening through the Woods
partnership, ~160 lines, plus search-result snippets for the Triple Trio hit).
Money figures ("close to a billion dollars," "$16 million" Triple Trio jackpot
Nov 2001, "$80,000 a year" blackjack era) are as printed — Benter's own account,
which Bloomberg says it corroborated where possible. Not independently verified
by me. No video/transcript involved; nothing here is a quote I didn't read.

Why Benter and not another trader: he is the only legendary bettor who
PUBLISHED his math. His game — a fundamental model betting against a public
line, sized by fractional Kelly — is structurally our game: our nowcast models
are his handicapping model, the Kalshi book is his tote board.

### Lesson 1: Never bet a raw model-vs-book disagreement. Run the second stage.
WHAT: Benter's central mechanism. Stage 1: fundamental model -> win
probabilities. Stage 2: combine them with the PUBLIC's implied probabilities in
a second logit regression, and bet only off the combined number. The public line
is "a sophisticated estimate" (paper) — it contains information your model
doesn't have (inside info, trainer intentions, the crowd's private signals).
WHY IT APPLIES: our T2.4 CPI entry did the opposite of Benter. Three estimators
said: book YES 41%, nowcast YES ~5%, shrunk empirical history YES ~64%. We bet
the nowcast at full weight against both the public line AND the base rate. That
is exactly the trade Benter's second stage exists to prevent.
TRY: shipped `benter_second_stage.py` — logit-space blend of model + public +
shrunk history, with the model's weight gated on PROVEN added information
(default 0: the tipster treatment). Worked T2.4 numbers through it: unratable
(model/public logit gap 2.58 > 1.5 bar), and the blend prices NO fair at ~47c
vs the 68c we paid — a ~21c overpay under Benter's framework.
AVOID: treating "the model disagrees with the book" as an edge. A disagreement
is a question, not a signal, until the model proves it adds information.
UNPROVEN FOR US: the 1.5-logit unratable bar and the 50/50/0 default weights
are starting values, not fitted. The nowcast may yet be proven right on Oct 14
— this rule is forward-looking; the open position stands and the learning loop
scores it.

### Lesson 2: The graduation exam for our shadow models now exists: Benter's delta test.
WHAT: Benter's profitability test for a model was never its standalone fit. It
was the GAIN in the combined model's pseudo-R^2 over the public-only fit:
delta = R^2(combined) - R^2(public). His fundamental model: 0.1396-0.1218 =
0.0178 — "though this value may appear small, it actually indicates that
significant profits could be made." His killer example: a 48-newspaper-tipster
model had a standalone R^2 of 0.1014, apparently EQUAL to his fundamental
model's 0.1016 — but in the second stage it added ~0 (0.1239 vs public 0.1237).
"When there is a difference between the public estimate and the tipster
estimate, then the public's estimate is superior." The second stage would have
saved that player from losing money.
WHY IT APPLIES: our NFL and soccer modules sit in shadow waiting for a
graduation protocol (Aronson's book was the placeholder). This is better: it
tests exactly what we need — does the model know something the book doesn't?
TRY: `benter_delta_test()` in the new module — IRLS logistic fits, McFadden
pseudo-R^2 (operationalization of his Bolton-Chapman stat, labeled as such),
materiality bar 0.005 (his two reference points: 0.0178 = real, 0.0002 =
tipster; the bar sits between them, judgment call), minimum 50 held-out
settled markets before the test can promote a model. Verified on synthetic
data: a model that knows the truth scores delta 0.029 (pass); a noisy-public
tipster scores 0.0023 (correctly binned as tipster_case).
AVOID: the naive `delta > 0` bar — in-sample fits almost always find a tiny
positive delta. That's noise fitting, not information. (Caught in self-test.)
UNPROVEN: the 0.005 bar and n=50 floor are priors. Revisit once real settled
fills exist.

### Lesson 3: "Correct the probabilities first, then calculate the advantage."
WHAT: paper's Note 1 — Benter explicitly rejects bolting a minimum-advantage
bar onto biased probabilities ("for exotic bets... the calculation of the
correct minimum advantage becomes exceedingly complex") and advocates fixing
the PROBABILITIES first, then betting the edge. Ziemba & Hausch's 10%-minimum
bar is cited as the crude alternative.
WHY IT APPLIES: our 15c bar is the crude alternative, and it should STAY the
crude alternative until our probabilities are corrected. Benter could bet "all
positive expectation bets" (paper, results section) ONLY because his
probabilities had survived the second stage. Ours haven't. The bar is
overstatement insurance (session-1 lesson), not a pricing model — don't let
anyone talk it down before calibration data exists.
TRY: no code change. Journal rule: the 15c bar may only be revisited after the
nowcast passes the delta test (Lesson 2), never before.
UNPROVEN: none — this is a process rule, cheap to keep.

### Lesson 4: Sizing corroboration from the survivor — and his losing season.
WHAT: Benter used "a conservative fractional Kelly betting strategy... 1/2 or
1/3" throughout five years. His three reasons for never betting full Kelly map
onto us exactly: (a) "if one overestimates the advantage by more than a factor
of two, Kelly betting will cause a negative rate of capital growth" and
"overestimating the advantage by a factor of two is easily done in practice";
(b) full Kelly downswings over 50% are "a common occurrence"; (c) pool-size
limits bind before wealth does ("as the bettor's wealth approaches the total
pool size, the dominant factor limiting bet size becomes the effect of the bet
on the dividend, not the bettor's wealth" — our analog: our taker entries move
thin Kalshi books). Results: ~470 races/year, 4 of 5 seasons profitable, the
losing season cost ~20% of starting capital, "a strong upward trend in rate of
return... as improvements were made to the handicapping model."
WHY IT APPLIES: independent corroboration of our half-Kelly + -$3/day stop
from a practitioner who ran it for five years at scale. His -20% season is the
honest base rate for "good process, bad year" — our stop would have cut that
season early, which is the point of the stop.
TRY: no change. Record the corroboration in the journal so a future losing
week doesn't trigger a sizing rethink.
AVOID: reading his success as permission to size up. He sized DOWN (1/2-1/3)
while winning ~$1B. The fraction is the discipline.

### Lesson 5 (Bloomberg): the ruin math that started it all.
WHAT: Benter's origin story is Thorp's Beat the Dealer (1962) -> blackjack
card counting -> Griffin Book blacklisting (~1984) -> Hong Kong with Alan
Woods. What stuck with him from the start was gambler's ruin: "if a player
with limited funds keeps betting against an opponent with unlimited funds...
he will eventually go broke, even if the game is fair." Hong Kong's take was
17% (later ~19% in his results section) — he had to clear the take on every
bet, and realistic max profit was 0.25-0.5% of per-race turnover.
WHY IT APPLIES: Kalshi's fee (0.07*P*(1-P), peaking at 50c) is our take, and
the 15c bar clears it by construction. His 0.25-0.5% of turnover ceiling is
the right mental model for our ceiling too: edges are thin, volume is the
game, and the take is forever.
Also noted (one line): his "golden age" warning — "computer handicappers may
become more numerous... the profits have gone, and will go, to those who are
'in action' first" — edges decay; ship models while they're fresh.

### Also noted (one line each)
- His model had ~120 factors after years of refinement; our econ edge is one
  nowcast with sigma 0.10pp measured over a single day. Factor-thin models get
  tipster weight (Lesson 1), not full weight. Earn the weight.
- The exotic-bet advantage principle ("the more exotic the bet, the higher the
  advantage") applied ONLY with corrected joint probabilities (he fixed
  Harville's bias first, gamma=0.81/delta=0.65 by MLE). Our combo module's
  min-of-legs conservatism is the right analog until we can model joints.
- Benter on volatile small-track odds: "the inaccuracy involved in using these
  volatile pre-post-time odds will decrease the effectiveness of the model" —
  direct warning for our thin-book entries; the quote we take at entry time is
  not the quote we think it is.

## NEXT BLOCK START HERE
TRACK B (book curriculum). Tier 1 #1 (Thorp 1997 Kelly paper) is DONE (session
1, 2026-09-24). Next in reading order: Tier 1 #2, Poundstone's Fortune's
Formula (2005) — the narrative companion to the Kelly math we already shipped;
free via Internet Archive lending / library (no legal free text; use the
lending copy or the free-alternative path in STUDY_CURRICULUM.md). If IA
lending is blocked, fall back to Tier 1 #4, Jaynes Probability Theory ch.1-2
(free PDF verified in the curriculum). Extract ONE chapter's lesson for the
desk; concrete output as usual.
Open threads for future blocks: (a) tune UNRATABLE_LOGIT_GAP and the 0.005
materiality bar once settled fills accumulate; (b) wire classify_market() into
the entry pipeline (currently standalone in benter_second_stage.py — the
yes-fade gate calls the blend once the nowcast passes the delta test);
(c) T2.4/T2.6/T2.7 CPI ladder settles Oct 14 — score the Benter adjudication
(blend said NO overpaid ~21c) against reality in the learning loop.
