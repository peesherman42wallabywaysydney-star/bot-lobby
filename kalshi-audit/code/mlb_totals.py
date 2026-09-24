#!/usr/bin/env python3
"""MLB full-game totals fair-value model (v1, 2026-09-24).

Shared by edge_scan.py §9 (scan) and auto_trade.py reverify_mlb (live re-verify).

Model: expected total runs from the pitching matchup, using the MLB Stats API
(free, keyless, no auth):
  * probable-pitcher season ERA (fallback: team ERA when TBD or IP < 20)
  * IP-weighted bullpen ERA from the daily roster hydrate (refresh_bullpen.py);
    fallback: team ERA if the cache is missing/stale
  * team runs/game vs league average as the offense proxy (wRC+ stand-in)
  * park run factors (RotoWire 2023-2025, from CRAFT.md); unlisted parks 1.00
Ladder SHAPE (sd) is calibrated from the market's own rungs via the
scan_ladder method from mlb_model.py — only the MEAN is ours.

Known gaps (documented, not hidden):
  * No xFIP / wRC+ (FanGraphs has no free API): ERA and runs/game are proxies.
  * September lineup effects (rest/call-ups) not modeled; PARK_BAND covers it.
  * Pregame only. Started/in-play/final games are skipped.
  * Regular-season math; playoff bullpen usage differs (documented caveat).

Kalshi ticker anatomy: KXMLBTOTAL-26SEP241235STLPIT[-<rungidx>]
  date 26SEP24, game time 12:35 ET, away STL @ home PIT (away first).
NOTE: Kalshi close_time on these is game_start + 72h, so the 10-min close gate
in auto_trade.py never binds for MLB — the game-start check here is the real
gate. Never trade after first pitch on a pregame model.
"""
import datetime
import json
import math
import os
import re
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))

PARK_BAND = 0.50      # runs; edges must survive this adverse mean shift
PROBABLE_MIN_IP = 20  # pitcher ERA needs this much season IP, else team ERA

# Park run factors (RotoWire 2023-2025, runs; 1.00 = neutral) — from CRAFT.md.
# Teams not listed default to 1.00 and keep the PARK_BAND uncertainty.
PARK = {'COL': 1.25, 'CIN': 1.06, 'MIN': 1.06, 'PHI': 1.02, 'DET': 1.02,
        'ATH': 1.04, 'NYY': 1.00, 'CHC': 1.00, 'KC': 1.02, 'SF': 0.93,
        'SD': 0.94, 'SEA': 0.95, 'TEX': 0.94, 'TB': 0.92, 'MIA': 0.95,
        'STL': 0.96, 'LAD': 1.00, 'BOS': 1.10}
BULLPEN_CACHE = os.path.join(HERE, 'hidden_files', 'mlb_bullpen.json')
BULLPEN_MAX_AGE_H = 30  # refresh daily via refresh_bullpen.py
PREGAME_CUTOFF_MIN = 10  # skip games starting within this many minutes

_CACHE = {}

# Verified 2026-09-24 from https://statsapi.mlb.com/api/v1/teams?sportId=1
MLB_ABBR = frozenset([
    'ATH', 'ATL', 'AZ', 'BAL', 'BOS', 'CHC', 'CIN', 'CLE', 'COL', 'CWS',
    'DET', 'HOU', 'KC', 'LAA', 'LAD', 'MIA', 'MIL', 'MIN', 'NYM', 'NYY',
    'PHI', 'PIT', 'SD', 'SEA', 'SF', 'STL', 'TB', 'TEX', 'TOR', 'WSH',
])

_MON = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
_ET = ZoneInfo('America/New_York')

_KALSHI = 'https://api.elections.kalshi.com/trade-api/v2'
_MLB = 'https://statsapi.mlb.com/api/v1'


class _Skip(Exception):
    """Expected skip (TBD probable, bad status, missing data) — not an error."""


def _get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


# ---------------- pure math (from mlb_model.py) ----------------
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def p_over(mean, sd, line):
    return 1 - norm_cdf((line - mean) / sd)


def norm_ppf(p):
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def implied_mean(ladder):
    """ladder: list of (rung, mid_prob). Linear interp of the 50% crossing."""
    pts = sorted((r, p) for r, p in ladder)
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if (y1 - 0.5) * (y2 - 0.5) <= 0 and y1 != y2:
            return x1 + (0.5 - y1) * (x2 - x1) / (y2 - y1)
    return None


def calibrate_sd(ladder, mean):
    """Fit normal sd from rungs priced 25%-75% (market's own shape)."""
    sigs = []
    for rung, p in ladder:
        if 0.25 <= p <= 0.75 and rung != mean:
            sd = (rung - mean) / norm_ppf(1 - p)
            if 1.0 < sd < 6.0:
                sigs.append(sd)
    if not sigs:
        return None
    return sum(sigs) / len(sigs)


def team_exp(opp_starter_era, starter_ip, pen_era, wrc, n_inn=9,
             starter_share_inn=5.2):
    """Expected runs for one team over n_inn innings (park=1.0, wx=1.0)."""
    opp_ra9 = (opp_starter_era * starter_share_inn
               + pen_era * (n_inn - starter_share_inn)) / n_inn
    return n_inn * opp_ra9 / 9.0 * (wrc / 100.0)


# ---------------- MLB Stats API ----------------
def _id_abbr():
    if 'id_abbr' not in _CACHE:
        d = _get(f'{_MLB}/teams?sportId=1')
        _CACHE['id_abbr'] = {t['id']: t['abbreviation'] for t in d['teams']}
    return _CACHE['id_abbr']


def _team_stats():
    """Returns ({team_id: {'era': f, 'rpg': f}}, league_rpg). Cached per run."""
    if 'team_stats' not in _CACHE:
        yr = _now().year
        p = _get(f'{_MLB}/teams/stats?season={yr}&stats=season&group=pitching&sportIds=1')
        h = _get(f'{_MLB}/teams/stats?season={yr}&stats=season&group=hitting&sportIds=1')
        out, tot_r, tot_g = {}, 0.0, 0.0
        for sp in p['stats'][0]['splits']:
            out[sp['team']['id']] = {'era': float(sp['stat']['era'])}
        for sp in h['stats'][0]['splits']:
            tid = sp['team']['id']
            r = float(sp['stat'].get('runs') or 0)
            g = float(sp['stat'].get('gamesPlayed') or 0) or 1.0
            out.setdefault(tid, {})['rpg'] = r / g
            tot_r += r
            tot_g += g
        _CACHE['team_stats'] = (out, tot_r / tot_g)
    return _CACHE['team_stats']


def _pitcher_era(pid, fallback):
    """Season ERA for a probable; fallback (team ERA) when TBD / thin sample."""
    if pid in _CACHE:
        return _CACHE[pid]
    v = fallback
    try:
        yr = _now().year
        d = _get(f'{_MLB}/people/{pid}/stats?stats=season&group=pitching&season={yr}')
        splits = d['stats'][0]['splits']
        if splits:
            st = splits[0]['stat']
            ip = float(st.get('inningsPitched') or 0)
            era = st.get('era')
            era = float(era) if era not in (None, '') else None
            if era is not None and ip >= PROBABLE_MIN_IP:
                v = era
    except Exception:
        v = fallback
    _CACHE[pid] = v
    return v


def _schedule(date_str):
    """date_str 'YYYY-MM-DD' -> list of game dicts. Cached per run."""
    key = f'sched:{date_str}'
    if key not in _CACHE:
        d = _get(f'{_MLB}/schedule?sportId=1&date={date_str}&hydrate=probablePitcher')
        games = []
        for dd in d.get('dates', []):
            games.extend(dd.get('games', []))
        _CACHE[key] = games
    return _CACHE[key]


# ---------------- Kalshi ----------------
_ET_RE = re.compile(r'^KXMLBTOTAL-(\d{2})([A-Z]{3})(\d{2})(\d{4})([A-Z]+)$')


def parse_kalshi_event(event_ticker):
    """KXMLBTOTAL-26SEP241235STLPIT -> dict or None."""
    m = _ET_RE.match(event_ticker or '')
    if not m:
        return None
    yy, mon3, dd, hhmm, abbrs = m.groups()
    if mon3 not in _MON:
        return None
    pair = None
    for i in (2, 3):
        a1, a2 = abbrs[:i], abbrs[i:]
        if a1 in MLB_ABBR and a2 in MLB_ABBR:
            pair = (a1, a2)
            break
    if not pair:
        return None
    start_et = datetime.datetime(2000 + int(yy), _MON[mon3], int(dd),
                                 int(hhmm[:2]), int(hhmm[2:]),
                                 tzinfo=_ET)
    return {
        'event_ticker': event_ticker,
        'date_str': f'{2000 + int(yy):04d}-{_MON[mon3]:02d}-{int(dd):02d}',
        'start_utc': start_et.astimezone(datetime.timezone.utc),
        'away_abbr': pair[0],
        'home_abbr': pair[1],
    }


def get_event_nested(event_ticker):
    return _get(f'{_KALSHI}/events/{event_ticker}?with_nested_markets=true')['event']


def open_totals_events():
    d = _get(f'{_KALSHI}/events?series_ticker=KXMLBTOTAL&status=open&limit=50'
             f'&with_nested_markets=true')
    return d.get('events', [])


# ---------------- model ----------------
def model_mean(info):
    """(mean, 'ok') or (None, reason). All inputs fetched fresh."""
    try:
        return _model_mean_inner(info), 'ok'
    except _Skip as s:
        return None, str(s)
    except Exception as ex:
        return None, f'fetch failed: {type(ex).__name__}: {ex}'


def _bullpen_era(tid):
    """IP-weighted bullpen ERA from the daily cache; None if missing/stale."""
    try:
        with open(BULLPEN_CACHE) as f:
            c = json.load(f)
        age_h = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.datetime.fromisoformat(c['as_of'])).total_seconds() / 3600
        if age_h > BULLPEN_MAX_AGE_H:
            return None
        return float(c['pens'][str(tid)]['pen_era'])
    except Exception:
        return None


def _model_mean_inner(info):
    games = _schedule(info['date_str'])
    id_abbr = _id_abbr()
    game = None
    for g in games:
        ta = g['teams']['away']['team']
        th = g['teams']['home']['team']
        if (id_abbr.get(ta['id']) == info['away_abbr']
                and id_abbr.get(th['id']) == info['home_abbr']):
            try:
                gd = datetime.datetime.fromisoformat(
                    g['gameDate'].replace('Z', '+00:00'))
            except Exception:
                continue
            if abs((gd - info['start_utc']).total_seconds()) < 3 * 3600:
                game = g
                break
    if game is None:
        raise _Skip('no matching game on MLB schedule')
    st = game.get('status', {}).get('detailedState', '')
    if st not in ('Scheduled', 'Pre-Game'):
        raise _Skip(f'game status={st}')
    ap = game['teams']['away'].get('probablePitcher') or {}
    hp = game['teams']['home'].get('probablePitcher') or {}
    if not ap.get('id') or not hp.get('id'):
        raise _Skip('probable pitcher TBD')
    ts, lg_rpg = _team_stats()
    aid = game['teams']['away']['team']['id']
    hid = game['teams']['home']['team']['id']
    if aid not in ts or hid not in ts:
        raise _Skip('team stats missing')
    a_team_era = ts[aid]['era']
    h_team_era = ts[hid]['era']
    # Real bullpen ERA when the daily cache is fresh; else team-ERA fallback.
    a_pen = _bullpen_era(aid) or a_team_era
    h_pen = _bullpen_era(hid) or h_team_era
    a_era = _pitcher_era(ap['id'], a_team_era)
    h_era = _pitcher_era(hp['id'], h_team_era)
    park = PARK.get(info['home_abbr'], 1.00)

    def wrc(rpg):
        return max(80.0, min(120.0, 100.0 * rpg / lg_rpg))

    exp_a = team_exp(h_era, 5.2, h_pen, wrc(ts[aid]['rpg']))
    exp_h = team_exp(a_era, 5.2, a_pen, wrc(ts[hid]['rpg']))
    return (exp_a + exp_h) * park


def _ladder_mids(markets):
    """-> list of (rung, bid_c, ask_c, ticker) for active Over rungs."""
    out = []
    for mk in markets:
        if mk.get('status') != 'active':
            continue
        tm = re.search(r'Over ([\d.]+)', mk.get('title', ''))
        if not tm:
            continue
        try:
            b = float(mk.get('yes_bid_dollars') or 0)
            a = float(mk.get('yes_ask_dollars') or 0)
        except (TypeError, ValueError):
            continue
        if not (0 < a < 1):
            continue
        out.append((float(tm.group(1)), b * 100, a * 100, mk.get('ticker', '')))
    return out


def scan_event(event, flag_bar=0.15):
    """Scan one KXMLBTOTAL event -> list of FLAG strings (research only).

    FLAG-ONLY, never EDGE: live testing 2026-09-24 (v1 and v1.1) shows the
    model mean disagrees with the market by ~0.7 runs on average (bidirectional;
    market spreads are 1c = efficient). v1.1 closed the two fixable gaps — real
    IP-weighted bullpen ERA (daily roster hydrate) and verified park factors
    (RotoWire 2023-2025) — but the market still prices game-specific info the
    model lacks (lineup cards, weather, September rest/call-up effects; no free
    API). The market is better informed than this model, so disagreements are
    logged for research, not traded. Promote to EDGE only after lineup/weather
    inputs land and the disagreement is measured gone.
    """
    flags = []
    info = parse_kalshi_event(event.get('event_ticker', ''))
    if not info:
        return flags
    if (info['start_utc'] - _now()).total_seconds() < PREGAME_CUTOFF_MIN * 60:
        return flags
    if info['home_abbr'] == 'COL':
        return flags  # Coors exceeds the park-uncertainty band
    mean, _reason = model_mean(info)
    if mean is None:
        return flags
    ladder = _ladder_mids(event.get('markets', []))
    if len(ladder) < 5:
        return flags
    mids = [(r, (b + a) / 200) for r, b, a, _ in ladder]
    mkt_mean = implied_mean(mids)
    sd = calibrate_sd(mids, mkt_mean) if mkt_mean is not None else None
    if mkt_mean is None or sd is None:
        return flags
    for rung, b, a, tk in ladder:
        if abs(rung - mkt_mean) > 2.0:
            continue  # only liquid rungs near the line
        f_yes_adv = p_over(mean - PARK_BAND, sd, rung)  # adverse for OVER
        if f_yes_adv - a / 100 >= flag_bar:
            flags.append(
                f'MLB-TOTAL {tk} OVER: model {mean:.1f} vs mkt {mkt_mean:.1f} '
                f'runs, ask {a:.0f}c vs adverse fair {f_yes_adv:.0%}')
            continue
        f_no_adv = p_over(mean + PARK_BAND, sd, rung)  # adverse for UNDER
        if b / 100 >= 0.10 and b / 100 - f_no_adv >= flag_bar:
            flags.append(
                f'MLB-TOTAL {tk} UNDER: model {mean:.1f} vs mkt {mkt_mean:.1f} '
                f'runs, bid {b:.0f}c vs adverse fair {f_no_adv:.0%}')
    return flags


def scan_all():
    """Scan every open KXMLBTOTAL event -> FLAG strings (research only)."""
    flags = []
    try:
        events = open_totals_events()
    except Exception:
        return flags
    for e in events:
        try:
            flags.extend(scan_event(e))
        except Exception:
            continue
    return flags
