#!/usr/bin/env python3
"""alpha_soccer.py — Kalshi soccer alpha module #5.

SHADOW MODE ONLY. This module NEVER places orders, never moves money, never
POSTs anything. It prices 1X2 (home/draw/away) soccer game markets, compares
its fair value to Kalshi's executable yes_ask, and logs shadow_candidates
when the edge clears 15c net of the taker fee.

Model: Dixon-Coles scoreline distribution.
  * Attack/defense strengths from rolling last-10-match goals for / against
    (home/away split). Intended to be xG-based; shot-level xG is NOT
    fetchable from this sandbox (Understat + FBref are Cloudflare-blocked
    for automated fetch, dataMB is JS-obfuscated) — goals are the honest
    substitute, and Dixon-Coles was originally fit on goals anyway.
  * ClubElo prior blended in (25%): Elo -> win prob via the standard
    1/(1+10^(-(dElo+HFA)/400)) mapping, draw from the league base rate.
  * Dixon-Coles rho is fit by log-likelihood grid search on the backtest set.

Data (all free):
  * football-data.co.uk CSVs — historical results incl. B365 closing odds
    (used as a market baseline in backtest), plus the weekly fixtures.csv
    for upcoming matches (same team naming, no matching needed).
  * clubelo.com — daily team Elo ratings (parsed from country pages).
    ClubElo's date-addressed fixture pages only list PAST matches, so
    fixtures come from FDC instead.
  * Kalshi public trade API — open soccer game markets per league series.

Kalshi soccer series (verified live 2026-09-24 — series exist, big-5 game
events only appear near matchdays):
  KXEPLGAME, KXLALIGAGAME, KXBUNDESLIGAGAME, KXSERIEAGAME, KXLIGUE1GAME,
  KXUCLGAME. National-team events (e.g. KXUEFANLGAME) are out of coverage.

Usage:
  python3 alpha_soccer.py            # run scan (needs caches; refresh first)
  python3 alpha_soccer.py --refresh  # rebuild results + Elo caches
  python3 alpha_soccer.py --backtest # walk-forward validation on 2024/25

Scope note (standing rule): sports markets are out of scope for live trading
unless Jeremiah authorizes a window. This module stays shadow until then.
"""
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.request
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shadow import shadow_candidate, shadow_run   # noqa: E402
from combo import fee_cents                        # noqa: E402

HF = os.path.join(HERE, 'hidden_files')
RESULTS_CACHE = os.path.join(HF, 'soccer_results.json')
ELO_CACHE = os.path.join(HF, 'soccer_elo.json')
os.makedirs(HF, exist_ok=True)

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'}
KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
ELO_W = 0.25          # ClubElo blend weight in final 1X2 probs
EDGE_BAR_C = 15.0     # net-of-fee bar, cents

LEAGUES = {
    'EPL':      {'fdc': 'E0',  'clubelo': 'ENG', 'kalshi': 'KXEPLGAME',
                 'espn': 'eng.1'},
    'LaLiga':   {'fdc': 'SP1', 'clubelo': 'ESP', 'kalshi': 'KXLALIGAGAME',
                 'espn': 'esp.1'},
    'Bundes':   {'fdc': 'D1',  'clubelo': 'GER', 'kalshi': 'KXBUNDESLIGAGAME',
                 'espn': 'ger.1'},
    'SerieA':   {'fdc': 'I1',  'clubelo': 'ITA', 'kalshi': 'KXSERIEAGAME',
                 'espn': 'ita.1'},
    'Ligue1':   {'fdc': 'F1',  'clubelo': 'FRA', 'kalshi': 'KXLIGUE1GAME',
                 'espn': 'fra.1'},
}

# ClubElo page slugs are abbreviated (Bayern, Gladbach, Koeln ...).
# FDC-normalized name -> ClubElo slug-normalized name.
CLUB_SLUG_FIX = {
    'nottmforest': 'forest', 'mancity': 'mancity', 'manutd': 'manunited',
    'athbilbao': 'athleticclub', 'athmadrid': 'atletico',
    'espanol': 'espanyol',
    'bayernmunich': 'bayern', 'einfrankfurt': 'frankfurt',
    'fckoln': 'koeln', 'mgladbach': 'gladbach', 'schalke04': 'schalke',
    'werderbremen': 'werder', 'parma': 'parmacalcio1913',
}


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = s.lower()
    s = re.sub(r"['\.]", '', s)
    s = re.sub(r'\b(fc|cf|sc|ac|as|ss|us|rc|ud|cd|sd|ca|afc|cfc)\b', '', s)
    return re.sub(r'[^a-z0-9]', '', s)


def http_get(url, timeout=25, sleep=1.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    time.sleep(sleep)
    return data


# ---------------------------------------------------------------- data layer

def fetch_fdc_results(fdc_code, seasons=('2425', '2526', '2627')):
    """Historical results from football-data.co.uk free CSVs.
    Season codes: 2425 = 2024/25, 2526 = 2025/26 (both complete as of
    2026-09), 2627 = current 2026/27 season in progress."""
    out = []
    for s in seasons:
        url = f'https://www.football-data.co.uk/mmz4281/{s}/{fdc_code}.csv'
        try:
            raw = http_get(url, sleep=0.7).decode('utf-8-sig', 'ignore')
        except Exception as e:
            print(f'  !! {fdc_code}/{s}: {e}', file=sys.stderr)
            continue
        lines = [l for l in raw.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        head = lines[0].split(',')
        idx = {c: i for i, c in enumerate(head)}
        for line in lines[1:]:
            c = line.split(',')
            if len(c) <= max(idx.get('FTHG', 0), idx.get('FTAG', 0)):
                continue
            try:
                out.append({
                    'date': c[idx['Date']].strip(),
                    'home': c[idx['HomeTeam']].strip(),
                    'away': c[idx['AwayTeam']].strip(),
                    'hg': int(c[idx['FTHG']]), 'ag': int(c[idx['FTAG']]),
                    'b365h': float(c[idx['B365H']]) if c[idx.get('B365H', 0)] else None,
                    'b365d': float(c[idx['B365D']]) if c[idx.get('B365D', 0)] else None,
                    'b365a': float(c[idx['B365A']]) if c[idx.get('B365A', 0)] else None,
                })
            except (ValueError, IndexError, KeyError):
                continue
    return out


def parse_date(d):
    d = d.strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.date(*datetime.datetime.strptime(d, fmt).timetuple()[:3])
        except ValueError:
            pass
    return None


def refresh_results():
    """Rebuild the results cache: 2 seasons x 5 leagues."""
    cache = {'built': datetime.date.today().isoformat(), 'leagues': {}}
    for lg, cfg in LEAGUES.items():
        print(f'fetching {lg} ...', flush=True)
        rows = fetch_fdc_results(cfg['fdc'])
        rows = [r for r in rows if parse_date(r['date']) is not None]
        rows.sort(key=lambda r: parse_date(r['date']))
        cache['leagues'][lg] = rows
        print(f'  {lg}: {len(rows)} matches')
    with open(RESULTS_CACHE, 'w') as f:
        json.dump(cache, f)
    print('wrote', RESULTS_CACHE)
    return cache


def fetch_clubelo_elos():
    """Daily team Elo ratings from clubelo.com country pages.

    Country pages render accordions for every nation, so we keep only
    teams that appear in the league's own results-cache team set."""
    if os.path.exists(RESULTS_CACHE):
        known = {}
        rc = json.load(open(RESULTS_CACHE))
        for lg in LEAGUES:
            teams = set()
            for r in rc['leagues'].get(lg, []):
                teams.add(r['home']); teams.add(r['away'])
            known[lg] = teams
    else:
        known = {lg: set() for lg in LEAGUES}
    elos = {'date': datetime.date.today().isoformat(), 'teams': {}}
    for lg, cfg in LEAGUES.items():
        url = f'https://clubelo.com/{cfg["clubelo"]}'
        html = http_get(url, sleep=0.7).decode('utf-8', 'ignore')
        rows = re.findall(r'<tr>.*?</tr>', html, re.S)
        slugs = {}
        for r in rows:
            m = re.search(r'<a href="/([^"]+)"><span class="NonAst">', r)
            e = re.search(r'<td class="r">(\d{3,4})</td>', r)
            if m and e:
                slugs[norm(m.group(1))] = int(e.group(1))
        kept = 0
        for t in known[lg]:
            tn = norm(t)
            if tn in slugs:                       # exact
                elos['teams'][f'{lg}:{tn}'] = slugs[tn]
                kept += 1
            elif CLUB_SLUG_FIX.get(tn) in slugs:   # alias
                elos['teams'][f'{lg}:{tn}'] = slugs[CLUB_SLUG_FIX[tn]]
                kept += 1
            else:                                 # unique containment
                cands = [s for s in slugs if tn in s or s in tn]
                if len(cands) == 1:
                    elos['teams'][f'{lg}:{tn}'] = slugs[cands[0]]
                    kept += 1
        print(f'  {lg}: {kept}/{len(known[lg])} elos kept')
    with open(ELO_CACHE, 'w') as f:
        json.dump(elos, f)
    print('wrote', ELO_CACHE)
    return elos


FIXTURES_CACHE = os.path.join(HF, 'soccer_fixtures.json')

FDC_DIV = {'E0': 'EPL', 'SP1': 'LaLiga', 'D1': 'Bundes',
           'I1': 'SerieA', 'F1': 'Ligue1'}


def refresh_fixtures():
    """Upcoming fixtures from football-data.co.uk/fixtures.csv.

    Same team naming as the results cache (no name matching needed).
    The file is refreshed upstream roughly weekly; keep our copy fresh
    daily and treat an empty upcoming list as "no fixtures posted yet".
    """
    raw = http_get('https://www.football-data.co.uk/fixtures.csv',
                   sleep=0.5).decode('utf-8-sig', 'ignore')
    lines = [l for l in raw.splitlines() if l.strip()]
    head = lines[0].split(',')
    idx = {c: i for i, c in enumerate(head)}
    elos = load_elos() if os.path.exists(ELO_CACHE) else {'teams': {}}
    today = datetime.date.today()
    fixtures = {lg: [] for lg in LEAGUES}
    for line in lines[1:]:
        c = line.split(',')
        if c[idx['Div']] not in FDC_DIV:
            continue
        lg = FDC_DIV[c[idx['Div']]]
        d = parse_date(c[idx['Date']])
        if d is None or d < today:
            continue
        home, away = c[idx['HomeTeam']].strip(), c[idx['AwayTeam']].strip()
        fixtures[lg].append({
            'date': d.isoformat(), 'home': home, 'away': away,
            'elo_home': elos['teams'].get(f'{lg}:{norm(home)}'),
            'elo_away': elos['teams'].get(f'{lg}:{norm(away)}'),
            'b365h': float(c[idx['B365H']]) if c[idx['B365H']] else None,
            'b365d': float(c[idx['B365D']]) if c[idx['B365D']] else None,
            'b365a': float(c[idx['B365A']]) if c[idx['B365A']] else None,
        })
    out = {'fetched': today.isoformat(), 'fixtures': fixtures}
    with open(FIXTURES_CACHE, 'w') as f:
        json.dump(out, f)
    print('fixtures:', {k: len(v) for k, v in fixtures.items()})
    return out


def load_fixtures():
    with open(FIXTURES_CACHE) as f:
        return json.load(f)['fixtures']


def fetch_clubelo_fixtures(days_ahead=7):
    """DEPRECATED: ClubElo date pages only list past matches (no upcoming
    fixtures without login). Kept for reference; use refresh_fixtures()."""
    return {lg: [] for lg in LEAGUES}


_fdc_names = {}


def match_fdc_team(league, clubelo_name):
    """Map a ClubElo display name to the FDC team name used in the cache."""
    global _fdc_names
    if league not in _fdc_names:
        cache = load_results()
        teams = set()
        for r in cache['leagues'].get(league, []):
            teams.add(r['home'])
            teams.add(r['away'])
        _fdc_names[league] = teams
    cn = norm(clubelo_name)
    for t in _fdc_names[league]:
        if norm(t) == cn:
            return t
    for t in _fdc_names[league]:
        fix = CLUB_SLUG_FIX.get(norm(t))
        if fix and (fix == cn or fix in cn or cn in fix):
            return t
    cands = [t for t in _fdc_names[league]
             if norm(t) in cn or cn in norm(t)]
    return cands[0] if len(cands) == 1 else None


def load_results():
    with open(RESULTS_CACHE) as f:
        return json.load(f)


def load_elos():
    with open(ELO_CACHE) as f:
        return json.load(f)


# ------------------------------------------------------------------ model

def rolling_strengths(rows, as_of, team, venue, n=10):
    """(gf, ga, cnt): goals for/against per match over last n venue-split
    matches before as_of."""
    gf = ga = 0
    cnt = 0
    for r in reversed(rows):
        if parse_date(r['date']) >= as_of:
            continue
        if venue == 'home' and r['home'] == team:
            gf += r['hg']; ga += r['ag']; cnt += 1
        elif venue == 'away' and r['away'] == team:
            gf += r['ag']; ga += r['hg']; cnt += 1
        if cnt >= n:
            break
    if cnt == 0:
        return None
    return gf / cnt, ga / cnt, cnt


def league_avgs(rows, as_of):
    """League mean home/away goals per match before as_of."""
    hg = ag = n = 0
    for r in rows:
        if parse_date(r['date']) >= as_of:
            continue
        hg += r['hg']; ag += r['ag']; n += 1
    if n == 0:
        return 1.4, 1.1
    return hg / n, ag / n


PRIOR_W = 8.0  # shrinkage: matches-of-league-average blended into team rates


def _lambdas(hgf, hga, nh, agf, aga, na, avg_h, avg_a):
    """Dixon-Coles lambdas with shrinkage toward league averages.

    hgf/hga: home team's GF/GA per home game over nh games;
    agf/aga: away team's GF/GA per away game over na games.
    Small samples regress toward league mean (PRIOR_W matches of weight)."""
    rhgf = (hgf * nh + PRIOR_W * avg_h) / (nh + PRIOR_W)
    rhga = (hga * nh + PRIOR_W * avg_h) / (nh + PRIOR_W)
    ragf = (agf * na + PRIOR_W * avg_a) / (na + PRIOR_W)
    raga = (aga * na + PRIOR_W * avg_a) / (na + PRIOR_W)
    lam_h = max(avg_h * (rhgf / avg_h) * (raga / avg_a), 0.05)
    lam_a = max(avg_a * (ragf / avg_a) * (rhga / avg_h), 0.05)
    return lam_h, lam_a


def expected_goals(rows, home, away, as_of):
    """Dixon-Coles lambdas from rolling last-10 strengths (goals-based,
    venue-split, shrunk toward league averages)."""
    avg_h, avg_a = league_avgs(rows, as_of)
    hs = rolling_strengths(rows, as_of, home, 'home')
    as_ = rolling_strengths(rows, as_of, away, 'away')
    if hs is None or as_ is None:
        return None
    return _lambdas(hs[0], hs[1], hs[2], as_[0], as_[1], as_[2], avg_h, avg_a)


def dixon_coles(lam_h, lam_a, rho=-0.13, max_g=8):
    """Full scoreline distribution with the Dixon-Coles low-score correction."""
    from math import factorial, exp
    def pois(k, lam):
        return exp(-lam) * lam ** k / factorial(k)
    grid = {}
    for i in range(max_g + 1):
        for j in range(max_g + 1):
            p = pois(i, lam_h) * pois(j, lam_a)
            if i == 0 and j == 0:
                p *= 1 - lam_h * lam_a * rho
            elif i == 0 and j == 1:
                p *= 1 + lam_h * rho
            elif i == 1 and j == 0:
                p *= 1 + lam_a * rho
            elif i == 1 and j == 1:
                p *= 1 - rho
            grid[(i, j)] = p
    tot = sum(grid.values())
    ph = pd = pa = 0.0
    for (i, j), p in grid.items():
        p /= tot
        if i > j:
            ph += p
        elif i == j:
            pd += p
        else:
            pa += p
    return {'1': ph, 'X': pd, '2': pa}


def elo_probs(elo_home, elo_away, draw_base=0.25, hfa=80.0):
    """ClubElo prior: Elo -> home-win prob; draw from league base rate."""
    d = (elo_home or 1500) - (elo_away or 1500)
    ph = 1.0 / (1.0 + 10 ** (-(d + hfa) / 400.0))
    pd = draw_base
    pa = 1.0 - ph - pd
    if pa < 0.02:  # renormalize when Elo implies a blowout
        pa = 0.02
        s = ph + pd + pa
        ph, pd, pa = ph / s, pd / s, pa / s
    return {'1': ph, 'X': pd, '2': pa}


def fair_1x2(rows, fixture, as_of, rho=-0.13):
    """Blend goals-Dixon-Coles (75%) with ClubElo prior (25%)."""
    lam = expected_goals(rows, fixture['home'], fixture['away'], as_of)
    if lam is None:
        return None
    dc = dixon_coles(*lam, rho=rho)
    if fixture.get('elo_home') and fixture.get('elo_away'):
        ep = elo_probs(fixture['elo_home'], fixture['elo_away'])
        return {k: (1 - ELO_W) * dc[k] + ELO_W * ep[k] for k in dc}
    return dc

# ---------------------------------------------------------------- backtest

def fit_rho(lambdas, outcomes):
    """Grid-search the Dixon-Coles rho by log-likelihood.

    lambdas: list of (lam_h, lam_a); outcomes: '1'/'X'/'2' per match.
    Lambdas are computed once up front; rho only affects the DC step."""
    best, best_ll = -0.13, float('-inf')
    for rho in [round(x * 0.01, 2) for x in range(-25, 6)]:
        ll = 0.0
        for (lh, la), out in zip(lambdas, outcomes):
            p = dixon_coles(lh, la, rho=rho)
            ll += math.log(max(p[out], 1e-9))
        if ll > best_ll:
            best, best_ll = rho, ll
    return best


def brier(probs, outcome):
    return sum((probs[k] - (1.0 if k == outcome else 0.0)) ** 2 for k in probs)


def walkforward_lambdas(rows):
    """Chronological O(N) pass: per-match (lam_h, lam_a) + outcome.

    Team histories and league averages use only matches strictly before
    the current one — no lookahead. Same math as expected_goals()."""
    from collections import defaultdict, deque
    hist = defaultdict(lambda: {'home': deque(maxlen=20),
                                'away': deque(maxlen=20)})
    hg_t = ag_t = n_t = 0
    out = []
    for r in rows:
        h, a = r['home'], r['away']
        hh = list(hist[h]['home'])[-10:]
        ah = list(hist[a]['away'])[-10:]
        if hh and ah and n_t > 0:
            avg_h, avg_a = hg_t / n_t, ag_t / n_t
            nh, na = len(hh), len(ah)
            hgf = sum(x[0] for x in hh) / nh
            hga = sum(x[1] for x in hh) / nh
            agf = sum(x[0] for x in ah) / na
            aga = sum(x[1] for x in ah) / na
            lam_h, lam_a = _lambdas(hgf, hga, nh, agf, aga, na, avg_h, avg_a)
            res = '1' if r['hg'] > r['ag'] else ('X' if r['hg'] == r['ag'] else '2')
            out.append(((lam_h, lam_a), res, r))
        hist[h]['home'].append((r['hg'], r['ag']))
        hist[a]['away'].append((r['ag'], r['hg']))
        hg_t += r['hg']; ag_t += r['ag']; n_t += 1
    return out


def backtest(seasons=('2425', '2526'), rho=None):
    """Walk-forward over full completed seasons per league.

    Compares the goals-Dixon-Coles model against two baselines:
      * naive: constant home/draw/away rates
      * book:  B365 closing odds (vig-removed) — the market itself
    (ClubElo blend is structural and fitted live; backtest uses the
    goals component only, stated honestly.)
    """
    cache = load_results()
    data = []
    for lg, cfg in LEAGUES.items():
        rows = [r for r in cache['leagues'][lg]
                if _season_of(parse_date(r['date'])) in seasons]
        rows.sort(key=lambda r: parse_date(r['date']))
        data.extend(walkforward_lambdas(rows))
    if rho is None:
        print('fitting rho ...', flush=True)
        rho = fit_rho([d[0] for d in data], [d[1] for d in data])
        print(f'  fitted rho = {rho}')
    tot = {'1': 0, 'X': 0, '2': 0}
    for _, res, _ in data:
        tot[res] += 1
    n_all = sum(tot.values())
    naive = {k: tot[k] / n_all for k in tot}
    print(f'naive base rates: { {k: round(v,3) for k,v in naive.items()} }')

    stats = {'model': [], 'naive': [], 'book': []}
    cal = {}
    n = 0
    for (lh, la), res, r in data:
        if not (r['b365h'] and r['b365d'] and r['b365a']):
            continue
        p = dixon_coles(lh, la, rho=rho)
        stats['model'].append(brier(p, res))
        stats['naive'].append(brier(naive, res))
        inv = 1 / r['b365h'] + 1 / r['b365d'] + 1 / r['b365a']
        bp = {'1': 1 / r['b365h'] / inv, 'X': 1 / r['b365d'] / inv,
              '2': 1 / r['b365a'] / inv}
        stats['book'].append(brier(bp, res))
        b = int(p['1'] * 10) / 10
        w, c = cal.get(b, (0, 0))
        cal[b] = (w + (1 if res == '1' else 0), c + 1)
        n += 1
    print(f'\nBACKTEST seasons {"+".join("20"+s[:2]+"/20"+s[2:] for s in seasons)}: '
          f'N={n} matches')
    for k in ('model', 'naive', 'book'):
        print(f'  Brier {k:5s}: {sum(stats[k]) / len(stats[k]):.4f}')
    print('  calibration (model home-prob bucket -> realized home-win rate):')
    for b in sorted(cal):
        w, c = cal[b]
        if c >= 20:
            print(f'    {b:.1f}-{b+0.1:.1f}: {w/c:.2f}  (n={c})')
    return n


def _season_of(d):
    if d is None:
        return None
    return f'{d.year % 100:02d}{(d.year + 1) % 100:02d}' if d.month >= 7 \
        else f'{(d.year - 1) % 100:02d}{d.year % 100:02d}'


# ------------------------------------------------------------ market scan

def kalshi_events(series_ticker):
    try:
        data = http_get(f'{KALSHI}/events?series_ticker={series_ticker}'
                        f'&status=open&limit=200', sleep=0.4)
        return json.loads(data)['events']
    except Exception as e:
        print(f'  !! kalshi {series_ticker}: {e}', file=sys.stderr)
        return []


def kalshi_markets(event_ticker):
    try:
        data = http_get(f'{KALSHI}/markets?event_ticker={event_ticker}'
                        f'&status=open', sleep=0.3)
        return json.loads(data)['markets']
    except Exception as e:
        print(f'  !! markets {event_ticker}: {e}', file=sys.stderr)
        return []


def event_teams(event):
    """('Home', 'Away') from an event title like 'Arsenal vs Chelsea'."""
    t = event.get('title', '')
    if ' vs ' in t:
        h, a = t.split(' vs ', 1)
        return h.strip(), a.strip()
    return None


def _key(name):
    return CLUB_SLUG_FIX.get(norm(name), norm(name))


def match_fixture(fixture, home, away):
    """Match a Kalshi event to a model fixture by normalized team names."""
    kh, ka = norm(home), norm(away)
    fh, fa = _key(fixture['home']), _key(fixture['away'])
    return (fh == kh or fh in kh or kh in fh) and \
           (fa == ka or fa in ka or ka in fa)


def score_market(market, fair_yes):
    """Edge math for one YES leg. Returns (ask_c, edge_c, fee_c, net_c)."""
    ask = market.get('yes_ask_dollars')
    if ask is None:
        return None
    ask_c = int(round(float(ask) * 100))
    if ask_c <= 0 or ask_c >= 100:
        return None
    edge_c = (fair_yes - ask_c / 100.0) * 100.0
    fee_c = fee_cents(ask_c)
    return ask_c, edge_c, fee_c, edge_c - fee_c


def run_scan():
    rows_cache = load_results()
    fixtures = load_fixtures()
    today = datetime.date.today()
    table = []
    n_cand = 0
    for lg, cfg in LEAGUES.items():
        events = kalshi_events(cfg['kalshi'])
        if not events:
            print(f'{lg}: no open Kalshi game events')
            continue
        for ev in events:
            teams = event_teams(ev)
            if not teams:
                continue
            kh, ka = teams
            fx = None
            for f in fixtures.get(lg, []):
                hn, an = norm(f['home']), norm(f['away'])
                if (hn == norm(kh) or an == norm(ka)) or \
                   (hn in norm(kh) or norm(kh) in hn) and \
                   (an in norm(ka) or norm(ka) in an):
                    fx = f
                    break
            if fx is None:
                table.append((lg, kh, ka, 'no fixture map', '', '', ''))
                continue
            as_of = parse_date(fx['date'])
            fair = fair_1x2(rows_cache['leagues'][lg], fx, as_of)
            if fair is None:
                continue
            # map the 3 markets to 1/X/2 by ticker suffix
            for m in kalshi_markets(ev['event_ticker']):
                tkr = m['ticker']
                if tkr.endswith('-TIE'):
                    side, fy = 'X', fair['X']
                elif norm(kh).startswith(norm(tkr.rsplit('-', 1)[-1][:3])):
                    side, fy = '1', fair['1']
                else:
                    side, fy = '2', fair['2']
                sc = score_market(m, fy)
                if sc is None:
                    row = (lg, kh, ka, side, f'{fy:.2f}', 'no ask', '')
                else:
                    ask_c, edge_c, fee_c, net_c = sc
                    flag = 'EDGE' if net_c >= EDGE_BAR_C else ''
                    row = (lg, kh, ka, side, f'{fy:.2f}',
                           f'{ask_c}c', f'{net_c:+.1f}c {flag}'.strip())
                    if net_c >= EDGE_BAR_C:
                        n_cand += 1
                        shadow_candidate(
                            module='soccer', ticker=tkr, side='yes',
                            fair_yes=fy, price_cents=ask_c,
                            edge_c=edge_c, net_c=net_c,
                            note=(f'{kh} vs {ka} ({fx["date"]}): '
                                  f'model fair {fy:.2f} vs Kalshi ask {ask_c}c, '
                                  f'edge {edge_c:.1f}c, fee {fee_c}c, '
                                  f'net {net_c:.1f}c'))
                table.append(row)
    print(f'\n{"lg":8} {"home":22} {"away":22} {"leg":3} {"fair":5} {"book":7} net')
    for r in table:
        print(f'{r[0]:8} {r[1][:21]:22} {r[2][:21]:22} {r[3]:3} {r[4]:5} {r[5]:7} {r[6]}')
    shadow_run(module='soccer', n_candidates=n_cand,
               note=f'{len(table)} legs scored, {n_cand} cleared {EDGE_BAR_C}c')
    return n_cand


def main():
    if '--refresh' in sys.argv:
        refresh_results()
        fetch_clubelo_elos()
        refresh_fixtures()
        return 0
    if '--backtest' in sys.argv:
        backtest()
        return 0
    for p in (RESULTS_CACHE, ELO_CACHE):
        if not os.path.exists(p):
            print(f'missing cache {p} — run with --refresh first')
            return 2
    run_scan()
    return 0


if __name__ == '__main__':
    sys.exit(main())
