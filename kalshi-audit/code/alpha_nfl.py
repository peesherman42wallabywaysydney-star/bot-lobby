#!/usr/bin/env python3
"""NFL win-probability alpha module for the Kalshi desk (SHADOW MODE ONLY).

Model: Elo (results) + net EPA/play (efficiency) -> expected margin -> win prob
via normal CDF -> fair moneyline cents. Compared against executable Kalshi
yes-ask from the KXNFLGAME series orderbook; edge >= 15c net of taker fee is
logged as a shadow candidate. NEVER places orders, NEVER moves money.

Data (all free):
  - nflverse play-by-play + schedules via nflreadpy (GitHub releases, no key),
    cached as parquet under hidden_files/nfl_cache/ so re-runs don't re-download.
  - ESPN hidden API (site.api.espn.com, no key) for current-week fixtures and
    injuries. Defensive parsing: any shape change degrades gracefully.

Intended cadence (weekly game -> weekly tool, NOT a 5-min-cycle tool):
  - Tue: model refresh (re-pull nflverse, rebuild ratings)      --refresh
  - Sun AM + Mon PM: injury re-check before kickoffs            --scan
  - Any day: print fixture table                                --fixtures
  - Validation (run once / after model changes)                 --backtest

Usage:
  ./alpha_nfl.py --backtest            # 2024+2025 no-lookahead backtest
  ./alpha_nfl.py --fixtures --week 4   # print this week's fixture table
  ./alpha_nfl.py --scan                 # map fixtures -> Kalshi markets, log shadow candidates
  ./alpha_nfl.py --refresh             # re-download nflverse cache

Model formulas (all documented in hidden_files/craft_sections/alpha_nfl.md):
  Elo: ELO0=1505, K=20, MOV multiplier = ln(|margin|+1) * 2.2/(2.2+0.001*|elo_diff|)
       (538 NFL formula), HFA=55 Elo in expectation.
  Season rollover: elo = 1505 + 0.75*(prev_end_elo - 1505).
  EPA: per-team net EPA/play (offense EPA/play minus defense EPA/play allowed),
       estimated as (sum_epa + REG_PLAYS*prior) / (plays + REG_PLAYS),
       REG_PLAYS=400 regression-to-mean plays, prior = 0.55*prev-season net EPA/play.
  Spread (home perspective):
       spread = W_ELO*(elo_diff/25) + W_EPA*(net_epa_diff*60) + HFA_PTS
                + rest_adj - qb_out_adj
       W_ELO=0.65, W_EPA=0.35, HFA_PTS=2.2, MARGIN_SD=13.5.
  Win prob: p = Phi(spread / MARGIN_SD).
  rest_adj = clip(rest_home - rest_away, -7, 7) * 0.35  (points per extra rest day)
  qb_out_adj = 4.0 if starting QB confirmed OUT/IR, else 0.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shadow import shadow_candidate, shadow_run  # noqa: E402
from combo import fee_cents  # noqa: E402  (read-only use; live paths untouched)

CACHE = os.path.join(HERE, 'hidden_files', 'nfl_cache')
os.makedirs(CACHE, exist_ok=True)
PY = os.path.join(HERE, '.venv-nfl', 'bin', 'python')

# ---------------------------------------------------------------- constants
ELO0 = 1505.0
K_ELO = 20.0
HFA_ELO = 55.0
PTS_PER_ELO = 25.0          # 25 Elo points ~= 1 point of spread
HFA_PTS = HFA_ELO / PTS_PER_ELO   # 2.2
W_ELO, W_EPA = 0.65, 0.35
PLAYS_PER_GAME = 60.0
MARGIN_SD = 13.5            # NFL margin-of-victory SD
REG_PLAYS = 400.0           # EPA regression-to-mean plays
PRIOR_PERSIST = 0.55        # preseason prior = 0.55 * prev-season net EPA/play
REST_PTS_PER_DAY = 0.35
QB_OUT_PTS = 4.0            # fixed spread penalty when starting QB OUT/IR
EDGE_BAR_C = 15.0           # net-of-fee edge bar (cents)
SERIES = 'KXNFLGAME'
KALSHI_BASE = 'https://api.elections.kalshi.com/trade-api/v2'

# ------------------------------------------------- team code normalization
# Canonical = ESPN/Kalshi 3-letter codes. nflverse uses LA (Rams) and JAX.
CANON_TEAMS = ['ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL',
               'DEN', 'DET', 'GB', 'HOU', 'IND', 'JAC', 'KC', 'LAC', 'LAR',
               'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT',
               'SEA', 'SF', 'TB', 'TEN', 'WAS']
NFLVERSE_TO_CANON = {'LA': 'LAR', 'JAX': 'JAC'}
ESPN_TO_CANON = {'JAX': 'JAC', 'WSH': 'WAS'}  # ESPN uses JAX + WSH (2025 rename)


def canon(code, source='nflverse'):
    c = (code or '').strip().upper()
    if source == 'nflverse':
        c = NFLVERSE_TO_CANON.get(c, c)
    elif source == 'espn':
        c = ESPN_TO_CANON.get(c, c)
    return c


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ---------------------------------------------------------------- data layer
def _need_venv():
    try:
        import polars  # noqa
        import nflreadpy  # noqa
        return False
    except ImportError:
        return True


def _pip():
    if _need_venv() and os.path.exists(PY):
        return PY
    return sys.executable


def cache_path(kind, season):
    return os.path.join(CACHE, f'{kind}_{season}.parquet')


def refresh_cache(seasons=(2023, 2024, 2025, 2026)):
    """Download nflverse schedules + pbp into the cache (idempotent)."""
    import subprocess
    code = (
        "import nflreadpy, os\n"
        f"cache={CACHE!r}\n"
        "os.makedirs(cache, exist_ok=True)\n"
        f"for yr in {list(seasons)}:\n"
        "  for kind, fn in (('schedules', nflreadpy.load_schedules),"
        "                   ('pbp', nflreadpy.load_pbp)):\n"
        "    p = f'{cache}/{kind}_{yr}.parquet'\n"
        "    if os.path.exists(p):\n"
        "      print('cached', kind, yr); continue\n"
        "    print('downloading', kind, yr, flush=True)\n"
        "    fn(seasons=[yr]).write_parquet(p)\n"
        "    print('wrote', p, flush=True)\n"
    )
    r = subprocess.run([_pip(), '-c', code], capture_output=True, text=True,
                       timeout=1800)
    print(r.stdout[-2000:])
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise RuntimeError('nflverse refresh failed')
    return True


def load_pl(kind, season):
    import polars as pl
    p = cache_path(kind, season)
    if not os.path.exists(p):
        refresh_cache((season,))
    return pl.read_parquet(p)

# ------------------------------------------------------------ ratings engine
class Ratings:
    """Season-scoped Elo + EPA state. No-lookahead by construction: games are
    fed in strict chronological order; predictions read state BEFORE the game
    is applied."""

    def __init__(self, prior_elo=None, prior_epa=None):
        self.elo = {t: (prior_elo.get(t, ELO0) if prior_elo else ELO0)
                    for t in CANON_TEAMS}
        self.prior_epa = dict(prior_epa) if prior_epa else {t: 0.0 for t in CANON_TEAMS}
        # current-season accumulators (offense and defense separately)
        self.off_epa = {t: 0.0 for t in CANON_TEAMS}
        self.off_plays = {t: 0.0 for t in CANON_TEAMS}
        self.def_epa = {t: 0.0 for t in CANON_TEAMS}   # EPA allowed
        self.def_plays = {t: 0.0 for t in CANON_TEAMS}
        self.last_game_date = {t: None for t in CANON_TEAMS}

    # -- Elo --
    @staticmethod
    def _mov_mult(margin, elo_diff):
        return math.log(max(1.0, abs(margin)) + 1.0) * (
            2.2 / (2.2 + 0.001 * abs(elo_diff)))

    def expected_home(self, home, away):
        return 1.0 / (1.0 + 10.0 ** (-((self.elo[home] - self.elo[away] + HFA_ELO) / 400.0)))

    def apply_game(self, home, away, hs, aws):
        """Update Elo + last-game dates AFTER a result is known."""
        exp = self.expected_home(home, away)
        actual = 1.0 if hs > aws else (0.0 if hs < aws else 0.5)
        mult = self._mov_mult(hs - aws, self.elo[home] - self.elo[away] + HFA_ELO)
        delta = K_ELO * mult * (actual - exp)
        self.elo[home] += delta
        self.elo[away] -= delta

    # -- EPA --
    def add_play(self, posteam, defteam, epa):
        self.off_epa[posteam] += epa
        self.off_plays[posteam] += 1.0
        self.def_epa[defteam] += epa
        self.def_plays[defteam] += 1.0

    def net_epa(self, team):
        """Net EPA/play with regression to the preseason prior (documented)."""
        prior = self.prior_epa.get(team, 0.0)
        off = (self.off_epa[team] + REG_PLAYS * prior) / (self.off_plays[team] + REG_PLAYS)
        dfn = (self.def_epa[team] + REG_PLAYS * (-prior)) / (self.def_plays[team] + REG_PLAYS)
        return off - dfn

    def final_net_epa(self):
        return {t: self.net_epa(t) for t in CANON_TEAMS}

    # -- model --
    def predict(self, home, away, rest_h=None, rest_a=None, qb_out_home=False,
                qb_out_away=False):
        """Return dict(spread, p_home, components). spread is home perspective."""
        elo_pts = (self.elo[home] - self.elo[away]) / PTS_PER_ELO
        epa_pts = (self.net_epa(home) - self.net_epa(away)) * PLAYS_PER_GAME
        spread = W_ELO * elo_pts + W_EPA * epa_pts + HFA_PTS
        rest_adj = 0.0
        if rest_h is not None and rest_a is not None:
            rest_adj = max(-7.0, min(7.0, rest_h - rest_a)) * REST_PTS_PER_DAY
            spread += rest_adj
        qb_adj = (QB_OUT_PTS if qb_out_away else 0.0) - (QB_OUT_PTS if qb_out_home else 0.0)
        spread += qb_adj
        p_home = norm_cdf(spread / MARGIN_SD)
        return {'spread': spread, 'p_home': p_home, 'elo_pts': elo_pts,
                'epa_pts': epa_pts, 'rest_adj': rest_adj, 'qb_adj': qb_adj,
                'fair_home_c': round(p_home * 100), 'fair_away_c': round((1 - p_home) * 100)}


def season_rollover(prev_ratings):
    """Preseason priors from the prior completed season (no lookahead:
    prev_ratings is final state of the previous season)."""
    prior_elo = {t: ELO0 + 0.75 * (prev_ratings.elo[t] - ELO0) for t in CANON_TEAMS}
    final_epa = prev_ratings.final_net_epa()
    prior_epa = {t: PRIOR_PERSIST * final_epa[t] for t in CANON_TEAMS}
    return Ratings(prior_elo=prior_elo, prior_epa=prior_epa)


def neutral_ratings():
    return Ratings()


# ------------------------------------------------- pbp -> EPA accumulators
def _truthy(col):
    """Boolean mask tolerant of float/int/bool flag columns."""
    import polars as pl
    return pl.col(col).fill_null(0).cast(pl.Boolean)


def feed_week_plays(ratings, season, week):
    """Add all qualifying plays from (season, week) into ratings. A play
    qualifies if: play_type in {pass, run}, not qb_kneel/spike, epa not null,
    posteam/defteam are valid NFL teams."""
    import polars as pl
    pbp = load_pl('pbp', season)
    wk = pbp.filter(
        (pl.col('week') == week)
        & (pl.col('play_type').is_in(['pass', 'run']))
        & (~_truthy('qb_kneel'))
        & (~_truthy('qb_spike'))
        & (pl.col('epa').is_not_null())
    )
    n = 0
    for row in wk.select(['posteam', 'defteam', 'epa']).iter_rows():
        pt, dt_, epa = row
        try:
            pt = canon(pt)
            dt_ = canon(dt_)
        except Exception:
            continue
        if pt not in CANON_TEAMS or dt_ not in CANON_TEAMS:
            continue
        ratings.add_play(pt, dt_, float(epa))
        n += 1
    return n


def reg_games(season):
    """Regular-season games in chronological order: (week, gameday, game_id,
    home, away, hs, aws, spread_line)."""
    import polars as pl
    s = load_pl('schedules', season)
    g = s.filter(pl.col('game_type') == 'REG').sort(['gameday', 'game_id'])
    out = []
    for r in g.iter_rows(named=True):
        home = canon(r['home_team'])
        away = canon(r['away_team'])
        if home not in CANON_TEAMS or away not in CANON_TEAMS:
            continue
        hs, aws = r['home_score'], r['away_score']
        if hs is None or aws is None:
            continue  # not yet played
        out.append({'week': int(r['week']), 'gameday': str(r['gameday']),
                    'game_id': str(r['game_id']), 'home': home, 'away': away,
                    'hs': int(hs), 'aws': int(aws),
                    'spread_line': r['spread_line']})
    return out

# ----------------------------------------------------------------- backtest
def _rest_days(season):
    """Map (team, week) -> days since that team's previous game."""
    import polars as pl
    from datetime import date as ddate
    s = load_pl('schedules', season)
    g = s.filter(pl.col('game_type') == 'REG').sort(['gameday', 'game_id'])
    last = {}
    rest = {}
    for r in g.iter_rows(named=True):
        gd = ddate.fromisoformat(str(r['gameday'])[:10])
        for tm in (canon(r['home_team']), canon(r['away_team'])):
            wk = int(r['week'])
            rest[(tm, wk)] = (gd - last[tm]).days if tm in last else 99
            last[tm] = gd
    return rest


def backtest_season(season, prev_ratings):
    """No-lookahead walk of one regular season.

    Discipline (the whole credibility of this number):
      1. Ratings start from the PRIOR completed season's final state only.
      2. Games processed in strict chronological order (gameday, game_id).
      3. For each game: predict FIRST (reads state built from earlier games
         only), record, THEN apply the result + that week's plays.
      4. EPA for week w uses plays from weeks < w only; week-w plays are fed
         after all of week w's predictions are recorded.
      5. Baselines (50/50, Elo-only, pregame spread_line) use only pregame info.
    Returns list of per-game dicts."""
    games = reg_games(season)
    rest = _rest_days(season)
    r = season_rollover(prev_ratings)
    results = []
    cur_week = None
    pending = []  # games of current week awaiting play-feed + elo apply
    for g in games:
        if cur_week is None:
            cur_week = g['week']
        if g['week'] != cur_week:
            # week boundary: now safe to absorb the finished week's data
            feed_week_plays(r, season, cur_week)
            for pg in pending:
                r.apply_game(pg['home'], pg['away'], pg['hs'], pg['aws'])
                r.last_game_date[pg['home']] = pg['gameday']
                r.last_game_date[pg['away']] = pg['gameday']
            pending = []
            cur_week = g['week']
        pred = r.predict(g['home'], g['away'],
                         rest_h=rest.get((g['home'], g['week']), 7),
                         rest_a=rest.get((g['away'], g['week']), 7))
        # Elo-only baseline uses the SAME elo state (no EPA): replicate cheaply
        elo_pts = pred['elo_pts']
        p_elo = norm_cdf((W_ELO * 0 + elo_pts + HFA_PTS + pred['rest_adj']) / MARGIN_SD)
        line_p = None
        if g['spread_line'] is not None:
            # spread_line is HOME spread (positive => home favored); pregame line
            line_p = norm_cdf(float(g['spread_line']) / MARGIN_SD)
        actual = 1.0 if g['hs'] > g['aws'] else (0.5 if g['hs'] == g['aws'] else 0.0)
        results.append({'game_id': g['game_id'], 'week': g['week'],
                        'home': g['home'], 'away': g['away'],
                        'p': pred['p_home'], 'p_elo': p_elo, 'p_line': line_p,
                        'actual': actual, 'spread': pred['spread']})
        pending.append(g)
    # absorb final week (not needed for metrics, keeps state consistent)
    feed_week_plays(r, season, cur_week)
    for pg in pending:
        r.apply_game(pg['home'], pg['away'], pg['hs'], pg['aws'])
    return results, r


def brier(rows, key):
    n = len(rows)
    return sum((r[key] - r['actual']) ** 2 for r in rows) / n


def run_backtest():
    """Full 2024 + 2025 validation. Prints N, Brier vs baselines, calibration
    buckets, and proxy-line edge>=15c frequency. Historical Kalshi prices do
    not exist publicly, so no simulated P&L vs Kalshi is possible — stated
    plainly in the output."""
    print('Building 2023 final state (priors for 2024 backtest)...')
    r23 = neutral_ratings()
    for g in reg_games(2023):
        r23.apply_game(g['home'], g['away'], g['hs'], g['aws'])
    for w in sorted({g['week'] for g in reg_games(2023)}):
        feed_week_plays(r23, 2023, w)
    for season in (2024, 2025):
        print(f'\n=== Backtesting {season} ===')
        rows, r_end = backtest_season(season, r23 if season == 2024 else r_end_prev)
        n = len(rows)
        b_model = brier(rows, 'p')
        b_elo = brier(rows, 'p_elo')
        b_5050 = 0.25
        lined = [r for r in rows if r['p_line'] is not None]
        b_line = (sum((r['p_line'] - r['actual']) ** 2 for r in lined) / len(lined)
                  if lined else float('nan'))
        print(f'N games: {n}')
        print(f'Brier  model      : {b_model:.4f}')
        print(f'Brier  Elo-only   : {b_elo:.4f}')
        print(f'Brier  50/50      : {b_5050:.4f}')
        print(f'Brier  line-implied (n={len(lined)}): {b_line:.4f}'
              if lined else 'Brier  line-implied : n/a (no spread_line)')
        # calibration buckets
        print('Calibration (model p_home buckets):')
        for lo, hi in [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]:
            b = [r for r in rows if lo <= r['p'] < hi or (hi == 1.0 and r['p'] == 1.0)]
            if b:
                hit = sum(r['actual'] for r in b) / len(b)
                print(f'  {lo:.0%}-{hi:.0%}: n={len(b):3d} hit={hit:.1%} (mid={(lo+hi)/2:.0%})')
        # proxy-line edge frequency: |model - line_implied| >= 15c
        big = [r for r in lined if abs(r['p'] - r['p_line']) >= 0.15]
        if big:
            hit = sum(1 for r in big if (r['p'] > r['p_line']) == (r['actual'] == 1.0)) / len(big)
            print(f'Proxy-line |edge|>=15c: {len(big)} games ({len(big)/len(lined):.1%}); '
                  f'model direction correct {hit:.1%}')
        print('Simulated Kalshi P&L: NOT POSSIBLE — no public historical KXNFLGAME '
              'prices exist; the proxy-line frequency above is the substitute.')
        r_end_prev = r_end
    print('\nDone. No-lookahead discipline documented in backtest_season docstring.')

# -------------------------------------------------------------------- ESPN
ESPN_BASE = 'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl'
ESPN_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')


def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': ESPN_UA,
                                               'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def espn_scoreboard(week=None, season=2026):
    """Current-week fixtures from ESPN. Returns list of
    {away, home, date(ISO), week}. Defensive: returns [] on any shape change."""
    try:
        url = f'{ESPN_BASE}/scoreboard?dates={season}&seasontype=2'
        if week:
            url += f'&week={week}'
        d = _http_json(url)
        out = []
        for ev in d.get('events', []):
            try:
                comps = ev['competitions'][0]['competitors']
                away = home = None
                for c in comps:
                    abbr = canon(c['team']['abbreviation'], source='espn')
                    if c.get('homeAway') == 'home':
                        home = abbr
                    else:
                        away = abbr
                if not home or not away:
                    continue
                out.append({'away': away, 'home': home,
                            'date': ev.get('date', '')[:10],
                            'week': ev.get('week', {}).get('number'),
                            'name': ev.get('name', '')})
            except Exception:
                continue
        return out
    except Exception as e:
        print(f'ESPN scoreboard failed: {e}')
        return []


def espn_qb_out():
    """Teams whose starting QB is OUT/IR per ESPN injuries.

    Method: ESPN injuries endpoint -> for each team, collect QBs with status
    in {Out, IR}. Starter check: team's most-attempted passer in 2026 pbp
    (falls back to any listed QB when pbp unavailable). Documented, simple.
    Returns set of canonical team codes. Empty set on any failure."""
    out_teams = set()
    try:
        d = _http_json(f'{ESPN_BASE}/injuries')
        injuries = d.get('injuries', d if isinstance(d, list) else [])
    except Exception as e:
        print(f'ESPN injuries unavailable ({e}); skipping QB adjustment')
        return out_teams
    try:
        import polars as pl
        pbp = load_pl('pbp', 2026)
        att = (pbp.filter(_truthy('qb_dropback'))
                  .group_by('posteam').agg(pl.len().alias('n')))
        starter = {canon(r['posteam']): True for r in
                   att.sort('n', descending=True).iter_rows(named=True)}
        # map team -> top passer name
        pn = (pbp.filter(_truthy('qb_dropback') &
                         pl.col('passer_player_name').is_not_null())
                 .group_by(['posteam', 'passer_player_name']).agg(pl.len().alias('n'))
                 .sort('n', descending=True))
        top_passer = {}
        for r in pn.iter_rows(named=True):
            t = canon(r['posteam'])
            if t not in top_passer:
                top_passer[t] = (r['passer_player_name'] or '').lower()
    except Exception:
        top_passer = {}
    try:
        teams = injuries if isinstance(injuries, list) else injuries.get('teams', [])
        for t in teams:
            for inj in t.get('injuries', []):
                try:
                    athlete = inj.get('athlete', {})
                    # team abbr lives on the athlete record, not the team entry
                    abbr = canon(athlete.get('team', {}).get('abbreviation', ''),
                                 source='espn')
                    pos = (athlete.get('position', {}).get('abbreviation', '') or '').upper()
                    status = (inj.get('status', '') or '').upper()
                    name = (athlete.get('displayName', '') or '').lower()
                except Exception:
                    continue
                if abbr not in CANON_TEAMS:
                    continue
                if pos == 'QB' and any(s in status for s in ('OUT', 'IR', 'INJURED RESERVE')):
                    if not top_passer or top_passer.get(abbr, '') in name or name in top_passer.get(abbr, ''):
                        out_teams.add(abbr)
                    elif abbr not in top_passer:
                        out_teams.add(abbr)  # no pbp fallback: trust ESPN listing
    except Exception as e:
        print(f'ESPN injury parse degraded ({e}); partial QB-out set: {sorted(out_teams)}')
    return out_teams


# ------------------------------------------------------------------ Kalshi
def kalshi_get(path):
    req = urllib.request.Request(KALSHI_BASE + path, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def verify_series():
    """Confirm the NFL game series ticker live (never trust a guess)."""
    d = kalshi_get(f'/series/{SERIES}')
    title = d['series'].get('title')
    print(f'Series {SERIES} verified live: "{title}"')
    return title


def kalshi_open_games():
    """All open KXNFLGAME markets, grouped by game segment."""
    mkts, cursor = [], None
    while True:
        p = f'/markets?series_ticker={SERIES}&status=open&limit=1000'
        if cursor:
            p += f'&cursor={cursor}'
        d = kalshi_get(p)
        mkts += d['markets']
        cursor = d.get('cursor')
        if not cursor:
            break
    games = {}
    seg_re = re.compile(r'^KXNFLGAME-(\d{2}[A-Z]{3}\d{2})([A-Z]{4,6})-([A-Z]{2,3})$')
    for m in mkts:
        mt = seg_re.match(m['ticker'])
        if not mt:
            continue
        datestr, pair, side = mt.groups()
        # split the team pair at the position where both halves are valid codes
        # (greedy regex mis-splits 2+3 letter combos like NEBUF -> NEB|UF)
        away = home = None
        for i in (2, 3):
            a, h = pair[:i], pair[i:]
            if a in CANON_TEAMS and h in CANON_TEAMS:
                away, home = a, h
                break
        if not away or side not in (away, home):
            continue  # unparseable -> skip (never guess)
        key = (datestr, away, home)
        games.setdefault(key, {})[side] = m['ticker']
    return games


def kalshi_yes_ask(ticker):
    """Executable yes ask in cents from the public orderbook.

    orderbook_fp: yes_dollars = standing yes BIDS, no_dollars = standing no BIDS.
    Executable yes ask = 1 - best no bid. Returns None when no book."""
    try:
        ob = kalshi_get(f'/markets/{ticker}/orderbook?depth=10')['orderbook_fp']
        no_bids = [float(p) for p, _ in ob.get('no_dollars', [])]
        if not no_bids:
            return None
        return int(round((1.0 - max(no_bids)) * 100))
    except Exception:
        return None


def parse_seg_date(datestr):
    # '26SEP27' -> date(2026,9,27)
    mon = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
    return dt.date(2000 + int(datestr[:2]), mon[datestr[2:5]], int(datestr[5:7]))


def map_fixture_to_markets(fixture, games):
    """Map one fixture {away, home, date} to Kalshi game tickers.

    Matches on unordered team pair + date within 1 day. Returns
    {side_team: ticker} or None when ambiguous (0 or >1 matches -> SKIP)."""
    fdate = dt.date.fromisoformat(fixture['date'][:10])
    pair = {fixture['away'], fixture['home']}
    hits = []
    for (datestr, away, home), sides in games.items():
        if {away, home} != pair:
            continue
        try:
            if abs((parse_seg_date(datestr) - fdate).days) <= 1:
                hits.append(sides)
        except Exception:
            continue
    if len(hits) != 1:
        return None  # ambiguous or missing -> skip
    return hits[0]


# ------------------------------------------------------------- scan / table
def build_current_ratings():
    """Ratings from completed 2023-2025 + 2026-to-date (no lookahead issues
    for forecasting: only finished games are in the cache)."""
    r = neutral_ratings()
    for season in (2023, 2024, 2025):
        games = reg_games(season)
        for g in games:
            r.apply_game(g['home'], g['away'], g['hs'], g['aws'])
        for w in sorted({g['week'] for g in games}):
            feed_week_plays(r, season, w)
    # 2026 to date: apply only finished games
    games26 = [g for g in reg_games(2026)]
    r26 = season_rollover(r)
    for g in games26:
        r26.apply_game(g['home'], g['away'], g['hs'], g['aws'])
    weeks26 = sorted({g['week'] for g in games26})
    for w in weeks26:
        feed_week_plays(r26, 2026, w)
    # current week = max finished week + 1
    cur_week = (max(weeks26) + 1) if weeks26 else 1
    rest = _rest_days(2026)
    return r26, cur_week, rest


def run_scan(week=None, log=True):
    """Weekly scan: fixtures -> model -> Kalshi book -> shadow candidates."""
    verify_series()
    ratings, cur_week, rest = build_current_ratings()
    week = week or cur_week
    fixtures = espn_scoreboard(week=week)
    if not fixtures:
        print('No fixtures from ESPN; aborting scan.')
        shadow_run(module='nfl', n_candidates=0, note='no fixtures')
        return 0
    qb_out = espn_qb_out()
    if qb_out:
        print('QB OUT/IR adjustment (-4.0 spread pts):', sorted(qb_out))
    games = kalshi_open_games()
    print(f'{len(fixtures)} fixtures (week {week}), {len(games)} Kalshi games open')
    print(f'{"AWAY":>4} @ {"HOME":<4}  date        fairA fairH  KX-A ask  KX-H ask  edgeA  edgeH')
    n_cand = 0
    for f in fixtures:
        sides = map_fixture_to_markets(f, games)
        pred = ratings.predict(
            f['home'], f['away'],
            rest_h=rest.get((f['home'], week), 7),
            rest_a=rest.get((f['away'], week), 7),
            qb_out_home=f['home'] in qb_out, qb_out_away=f['away'] in qb_out)
        fa, fh = pred['fair_away_c'], pred['fair_home_c']
        ask_a = ask_h = None
        if sides:
            if f['away'] in sides:
                ask_a = kalshi_yes_ask(sides[f['away']])
            if f['home'] in sides:
                ask_h = kalshi_yes_ask(sides[f['home']])
        edge_a = edge_h = None
        row_extra = {}
        for label, fair, ask, team in (('A', fa, ask_a, f['away']),
                                      ('H', fh, ask_h, f['home'])):
            if ask is None:
                continue
            edge = fair - ask
            fee = fee_cents(ask)
            net = edge - fee
            if label == 'A':
                edge_a = edge
            else:
                edge_h = edge
            if net >= EDGE_BAR_C and log:
                ticker = sides[team]
                shadow_candidate(module='nfl', ticker=ticker, side='yes',
                                 fair_yes=fair / 100.0, price_cents=ask,
                                 edge_c=edge, net_c=net,
                                 note=f'fair {fair}c vs KX ask {ask}c '
                                      f'(fee {fee}c); {f["away"]}@{f["home"]} '
                                      f'model spread {pred["spread"]:+.1f}')
                n_cand += 1
                row_extra[label] = '*'
        flag_a = row_extra.get('A', '')
        flag_h = row_extra.get('H', '')
        print(f'{f["away"]:>4} @ {f["home"]:<4}  {f["date"]}  {fa:>3}c {fh:>3}c  '
              f'{str(ask_a)+"c" if ask_a else "  --":>7} {str(ask_h)+"c" if ask_h else "  --":>7}  '
              f'{str(edge_a)+"c"+flag_a if edge_a is not None else " --":>6} '
              f'{str(edge_h)+"c"+flag_h if edge_h is not None else " --":>6}  '
              f'spread {pred["spread"]:+.1f}' + ('' if sides else '  [no KX map]'))
    shadow_run(module='nfl', n_candidates=n_cand,
               note=f'week {week} scan: {len(fixtures)} fixtures, {n_cand} shadow candidates')
    print(f'\n{n_cand} shadow candidates logged (SHADOW ONLY — no orders placed).')
    return 0


def run_fixtures(week=None):
    ratings, cur_week, rest = build_current_ratings()
    week = week or cur_week
    fixtures = espn_scoreboard(week=week)
    qb_out = espn_qb_out()
    print(f'NFL week {week} fixture table (model fair values)')
    print(f'{"AWAY":>4} @ {"HOME":<4}  date        spread   p(home)  fairA  fairH')
    for f in fixtures:
        pred = ratings.predict(
            f['home'], f['away'],
            rest_h=rest.get((f['home'], week), 7),
            rest_a=rest.get((f['away'], week), 7),
            qb_out_home=f['home'] in qb_out, qb_out_away=f['away'] in qb_out)
        q = ' [QB-OUT]' if (f['home'] in qb_out or f['away'] in qb_out) else ''
        print(f'{f["away"]:>4} @ {f["home"]:<4}  {f["date"]}  {pred["spread"]:+6.1f}  '
              f'{pred["p_home"]:.1%}   {pred["fair_away_c"]:>3}c  {pred["fair_home_c"]:>3}c{q}')
    return 0


def main():
    ap = argparse.ArgumentParser(description='NFL win-probability alpha (SHADOW ONLY)')
    ap.add_argument('--backtest', action='store_true')
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--scan', action='store_true')
    ap.add_argument('--fixtures', action='store_true')
    ap.add_argument('--week', type=int, default=None)
    args = ap.parse_args()
    if args.refresh:
        refresh_cache()
        return 0
    if args.backtest:
        run_backtest()
        return 0
    if args.scan:
        return run_scan(week=args.week)
    if args.fixtures:
        return run_fixtures(week=args.week)
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
