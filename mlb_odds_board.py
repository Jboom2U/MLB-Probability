"""
MLB Devigged Odds Board
========================
Pulls today's MLB Moneyline / Run Line / Total odds from Pinnacle (via The
Odds API), strips the sportsbook's built-in margin ("vig"), and writes a
clean self-contained HTML table of the resulting fair (devigged)
probabilities.

This is NOT a predictive model. It does not guess who wins - it just takes
the sharpest available market price and reports what it actually implies
once the house edge is removed.

Setup
-----
1. pip install -r requirements.txt   (only `requests` is needed, already
   listed there)
2. copy .env.example to .env and fill in ODDS_API_KEY (or export it in your
   shell instead - either works)
3. python mlb_odds_board.py

Credit usage
------------
The FIRST run (or any run with no local cache yet) pulls live from the Odds
API: ~3 credits (3 markets x 1 region), regardless of slate size. Every run
after that reuses the cached response and makes NO API call - free to
re-run as many times as you want to tweak the HTML/styling. Pass --refresh
to force a fresh pull when you actually want updated lines (odds moved,
new day, etc). Pass --sample to render from built-in fake data instead -
also free, useful for previewing changes with zero real games available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv(path: str) -> None:
    """Minimal .env loader (KEY=VALUE per line) - avoids a python-dotenv
    dependency just for this. Existing real env vars always win."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "UTC"))

SPORT = "baseball_mlb"
BOOKMAKER = "pinnacle"
MARKETS = "h2h,spreads,totals"
ODDS_API_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"

OUTPUT_HTML = os.path.join(SCRIPT_DIR, "mlb_odds_board.html")
CACHE_FILE = os.path.join(SCRIPT_DIR, "odds_cache.json")

MARKET_LABELS = {
    "h2h": "Moneyline",
    "spreads": "Run Line",
    "totals": "Total",
}


# ---------------------------------------------------------------------------
# Devig math
# ---------------------------------------------------------------------------

def american_to_prob(odds: float) -> float:
    """Convert American odds to raw (vig-included) implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def devig_multiplicative(probs: list[float]) -> list[float]:
    """Normalize implied probabilities so they sum to 1."""
    total = sum(probs)
    return [p / total for p in probs]


def devig_power(probs: list[float], tol: float = 1e-10, max_iter: int = 200) -> list[float]:
    """
    Solve for exponent k such that sum(p_i ** k) == 1, then return
    [p_i ** k for each p_i]. sum(p_i ** k) is strictly decreasing in k (for
    probabilities in (0, 1)), so a plain bisection finds the unique root -
    no scipy required.
    """
    def total_at(k: float) -> float:
        return sum(p ** k for p in probs)

    lo, hi = 0.0, 1.0
    # sum(p_i ** 1) == sum(probs), which is > 1 whenever there's vig, so the
    # root (where the sum hits exactly 1) sits above k=1. Expand hi until
    # total_at(hi) <= 1.
    while total_at(hi) > 1.0:
        hi *= 2
        if hi > 1e6:  # pathological input guard
            break

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        if total_at(mid) > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break

    k = (lo + hi) / 2
    return [p ** k for p in probs]


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_pinnacle_odds() -> list[dict]:
    if not ODDS_API_KEY:
        sys.exit(
            "ODDS_API_KEY is not set.\n"
            "Get a key at https://the-odds-api.com and run:\n"
            "  export ODDS_API_KEY=your-key-here"
        )

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",  # Pinnacle is grouped under 'eu', not 'us'
        "bookmakers": BOOKMAKER,
        "markets": MARKETS,
        "oddsFormat": "american",
    }

    resp = requests.get(ODDS_API_URL, params=params, timeout=30)

    remaining = resp.headers.get("x-requests-remaining")
    used = resp.headers.get("x-requests-used")
    if remaining is not None:
        print(f"Odds API credits used this run -> remaining: {remaining}, used so far this period: {used}")

    if resp.status_code != 200:
        sys.exit(f"Odds API request failed ({resp.status_code}): {resp.text}")

    return resp.json()


def get_events(force_refresh: bool) -> list[dict]:
    """
    Cache-aware wrapper around fetch_pinnacle_odds(). Reuses the last raw
    API response (odds_cache.json) unless force_refresh is set or no cache
    exists yet, so previewing HTML/styling changes never costs credits.
    """
    if not force_refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
        print(
            f"Using cached odds from {cache['fetched_at']} - no API call made. "
            "Run with --refresh to pull fresh lines."
        )
        return cache["events"]

    events = fetch_pinnacle_odds()
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now(LOCAL_TZ).isoformat(), "events": events}, f)
    return events


# Built-in fake data for --sample: same shape The Odds API returns, so it
# runs through build_board()/render_html() exactly like real events, with
# zero network calls and zero credits used.
SAMPLE_EVENTS = [
    {
        "commence_time": "2026-08-25T23:05:00Z",
        "home_team": "Boston Red Sox",
        "away_team": "New York Yankees",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Boston Red Sox", "price": -130},
                            {"name": "New York Yankees", "price": 120},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Boston Red Sox", "price": -105, "point": -1.5},
                            {"name": "New York Yankees", "price": -115, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 8.5},
                            {"name": "Under", "price": -110, "point": 8.5},
                        ],
                    },
                ],
            }
        ],
    },
    {
        "commence_time": "2026-08-26T00:10:00Z",
        "home_team": "Los Angeles Dodgers",
        "away_team": "San Francisco Giants",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Dodgers", "price": -165},
                            {"name": "San Francisco Giants", "price": 145},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Los Angeles Dodgers", "price": 110, "point": -1.5},
                            {"name": "San Francisco Giants", "price": -130, "point": 1.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -105, "point": 9.0},
                            {"name": "Under", "price": -115, "point": 9.0},
                        ],
                    },
                ],
            }
        ],
    },
]


# ---------------------------------------------------------------------------
# Assemble rows
# ---------------------------------------------------------------------------

def build_board(events: list[dict]) -> list[dict]:
    rows: list[dict] = []

    for event in events:
        home = event.get("home_team", "Home")
        away = event.get("away_team", "Away")
        commence = event.get("commence_time")
        local_time = "TBD"
        game_date = None
        if commence:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            local_time = dt.strftime("%a %I:%M %p %Z")
            game_date = dt.strftime("%Y-%m-%d")

        pinnacle = next(
            (bm for bm in event.get("bookmakers", []) if bm.get("key") == BOOKMAKER),
            None,
        )
        if pinnacle is None:
            continue  # Pinnacle hasn't posted this game yet

        for market in pinnacle.get("markets", []):
            key = market.get("key")
            outcomes = market.get("outcomes", [])
            if key not in MARKET_LABELS or len(outcomes) != 2:
                continue

            raw_probs = [american_to_prob(o["price"]) for o in outcomes]
            fair_multiplicative = devig_multiplicative(raw_probs)
            fair_power = devig_power(raw_probs)

            for outcome, raw_p, mult_p, power_p in zip(outcomes, raw_probs, fair_multiplicative, fair_power):
                point = outcome.get("point")
                team = outcome.get("name", "")  # team name, or "Over"/"Under" for totals
                selection = team
                if point is not None:
                    formatted_point = f"{point:+g}" if key == "spreads" else f"{point:g}"
                    selection = f"{selection} {formatted_point}"

                rows.append(
                    {
                        "game": f"{away} @ {home}",
                        "home_team": home,
                        "away_team": away,
                        "start": local_time,
                        "game_date": game_date,
                        "market": MARKET_LABELS[key],
                        "team": team,
                        "point": point,
                        "selection": selection,
                        "odds": outcome["price"],
                        "raw_pct": raw_p * 100,
                        "fair_multiplicative_pct": mult_p * 100,
                        "fair_power_pct": power_p * 100,
                    }
                )

    return rows


# ---------------------------------------------------------------------------
# High-confidence pick tracking
# ---------------------------------------------------------------------------

HISTORY_FILE = os.path.join(SCRIPT_DIR, "pick_history.json")

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def top_pick_for_game(game_rows: list[dict]) -> dict | None:
    """
    The single row - across ALL markets for one game - with the highest
    fair probability. This is "the" high-confidence pick for that game:
    used both for the on-page headline/star badge and for the tracked
    running record, so it's defined in exactly one place.
    """
    return max(game_rows, key=lambda r: r["fair_multiplicative_pct"], default=None)


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, sort_keys=True)


def record_todays_picks(rows: list[dict], history: dict) -> None:
    """
    Log today's high-confidence pick for each game into history, once.
    Idempotent per (date, game) - re-running --refresh mid-day (odds
    moved) must never overwrite a pick already locked in earlier that day.
    """
    games: dict[str, list[dict]] = {}
    for row in rows:
        games.setdefault(row["game"], []).append(row)

    for game, game_rows in games.items():
        pick = top_pick_for_game(game_rows)
        if pick is None or pick["game_date"] is None:
            continue

        day = history.setdefault(pick["game_date"], [])
        if any(entry["game"] == game for entry in day):
            continue  # already locked in earlier today

        day.append(
            {
                "game": pick["game"],
                "home_team": pick["home_team"],
                "away_team": pick["away_team"],
                "market": pick["market"],
                "selection": pick["selection"],
                "team": pick["team"],
                "point": pick["point"],
                "odds": pick["odds"],
                "fair_pct": round(pick["fair_multiplicative_pct"], 1),
                "result": "Pending",
            }
        )


def _fetch_final_scores(date: str) -> dict[tuple[str, str], tuple[int, int]]:
    """{(home_team, away_team): (home_score, away_score)} for Final games
    on `date`, from MLB's free public Stats API (no key, no credits)."""
    resp = requests.get(MLB_SCHEDULE_URL, params={"sportId": 1, "date": date}, timeout=30)
    if resp.status_code != 200:
        print(f"MLB Stats API request failed for {date} ({resp.status_code}) - leaving that day's picks Pending.")
        return {}

    scores: dict[tuple[str, str], tuple[int, int]] = {}
    for day in resp.json().get("dates", []):
        for game in day.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            home_name = home.get("team", {}).get("name")
            away_name = away.get("team", {}).get("name")
            if home_name is None or away_name is None:
                continue
            scores[(home_name, away_name)] = (home.get("score"), away.get("score"))
    return scores


def _grade_entry(entry: dict, home_score: int, away_score: int) -> str:
    is_home = entry["team"] == entry["home_team"]
    team_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score

    if entry["market"] == "Moneyline":
        return "W" if team_score > opp_score else "L"

    if entry["market"] == "Run Line":
        margin = (team_score - opp_score) + entry["point"]
        if margin > 0:
            return "W"
        if margin < 0:
            return "L"
        return "Push"

    if entry["market"] == "Total":
        combined = home_score + away_score
        over = entry["team"] == "Over"
        if combined == entry["point"]:
            return "Push"
        return "W" if (combined > entry["point"]) == over else "L"

    return "Pending"  # unrecognized market - leave ungraded rather than guess


def grade_pending_picks(history: dict) -> dict:
    """Grade any Pending entries from a date strictly before today (local)
    using free final scores from MLB's Stats API. One API call per distinct
    date that actually has something Pending; zero calls otherwise."""
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    for date, entries in history.items():
        if date >= today:
            continue
        if not any(e["result"] == "Pending" for e in entries):
            continue

        scores = _fetch_final_scores(date)
        for entry in entries:
            if entry["result"] != "Pending":
                continue
            final = scores.get((entry["home_team"], entry["away_team"]))
            if final is None or final[0] is None or final[1] is None:
                continue  # game not final yet, or a name mismatch - stay Pending
            entry["result"] = _grade_entry(entry, final[0], final[1])

    return history


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def format_odds(odds: float) -> str:
    return f"+{odds:g}" if odds > 0 else f"{odds:g}"


def render_history_section(history: dict) -> str:
    """
    Running record of daily high-confidence picks, with a client-side date
    filter (plain JS, no server - matches the rest of this page). The raw
    history is embedded as JSON; a small script builds the filter dropdown
    and table, and recomputes the W-L-Push tally whenever it changes.
    """
    if not history:
        return """
        <div class="card history-card">
          <h2>Running Record</h2>
          <p class="empty" style="padding: 20px 0;">No graded picks yet - check back after the first day's games finish.</p>
        </div>"""

    history_json = json.dumps(history)

    return f"""
    <div class="card history-card">
      <h2>Running Record &mdash; High-Confidence Picks</h2>
      <p class="start-time">One pick per game: whichever market/side had the single highest fair probability that day.</p>
      <div class="history-controls">
        <label for="history-filter">Show:</label>
        <select id="history-filter"></select>
        <span id="history-tally" class="history-tally"></span>
      </div>
      <table id="history-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Game</th>
            <th>Pick</th>
            <th>Fair %</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody id="history-body"></tbody>
      </table>
    </div>
    <script id="history-data" type="application/json">{history_json}</script>
    <script>
      (function() {{
        var history = JSON.parse(document.getElementById('history-data').textContent);
        var dates = Object.keys(history).sort().reverse();
        var select = document.getElementById('history-filter');
        var allOpt = document.createElement('option');
        allOpt.value = 'all';
        allOpt.textContent = 'All Time';
        select.appendChild(allOpt);
        dates.forEach(function(d) {{
          var opt = document.createElement('option');
          opt.value = d;
          opt.textContent = d;
          select.appendChild(opt);
        }});

        function resultClass(result) {{
          if (result === 'W') return 'result-w';
          if (result === 'L') return 'result-l';
          if (result === 'Push') return 'result-push';
          return 'result-pending';
        }}

        function render() {{
          var chosen = select.value;
          var body = document.getElementById('history-body');
          body.innerHTML = '';
          var w = 0, l = 0, push = 0, pending = 0;

          dates.forEach(function(d) {{
            if (chosen !== 'all' && chosen !== d) return;
            history[d].forEach(function(e) {{
              if (e.result === 'W') w++;
              else if (e.result === 'L') l++;
              else if (e.result === 'Push') push++;
              else pending++;

              var tr = document.createElement('tr');
              tr.innerHTML =
                '<td>' + d + '</td>' +
                '<td>' + e.game + '</td>' +
                '<td>' + e.market + ' — ' + e.selection + '</td>' +
                '<td>' + e.fair_pct.toFixed(1) + '%</td>' +
                '<td><span class="result-badge ' + resultClass(e.result) + '">' + e.result + '</span></td>';
              body.appendChild(tr);
            }});
          }});

          var tally = w + '-' + l;
          if (push) tally += ' (' + push + ' push)';
          if (pending) tally += ', ' + pending + ' pending';
          document.getElementById('history-tally').textContent = tally;
        }}

        select.addEventListener('change', render);
        render();
      }})();
    </script>"""


def render_html(rows: list[dict], history: dict) -> str:
    games: dict[str, list[dict]] = {}
    for row in rows:
        games.setdefault(f"{row['game']}|{row['start']}", []).append(row)

    game_cards = []
    for game_key, game_rows in games.items():
        game, start = game_key.split("|")

        markets: dict[str, list[dict]] = {}
        for row in game_rows:
            markets.setdefault(row["market"], []).append(row)

        # Which single row - across ALL markets for this game - has the
        # highest fair probability. That's the game's clear leader: no
        # averaging or edge-distance math, just the highest Fair % wins.
        top_row = top_pick_for_game(game_rows)

        market_tables = []
        for market_name, market_rows in markets.items():
            # Highlight whichever side of THIS market the fair (devigged)
            # probability favors - a per-market call (moneyline favorite,
            # run-line favorite, and O/U favorite can all point different
            # directions), separate from the game-wide leader above.
            favorite = max(market_rows, key=lambda r: r["fair_multiplicative_pct"], default=None)
            is_top_market = market_name == top_row["market"]

            body_rows = "".join(
                f"""
                <tr class="{'pick' if r is favorite else ''}">
                  <td>{r['selection']}{' <span class="badge">Most Likely</span>' if r is favorite else ''}</td>
                  <td>{format_odds(r['odds'])}</td>
                  <td>{r['raw_pct']:.1f}%</td>
                  <td class="fair">{r['fair_multiplicative_pct']:.1f}%</td>
                  <td class="fair">{r['fair_power_pct']:.1f}%</td>
                </tr>"""
                for r in market_rows
            )
            market_tables.append(
                f"""
                <h3>{market_name}{' <span class="star">⭐ Highest Confidence</span>' if is_top_market else ''}</h3>
                <table>
                  <thead>
                    <tr>
                      <th>Selection</th>
                      <th>Odds</th>
                      <th>Raw Implied</th>
                      <th>Fair (Multiplicative)</th>
                      <th>Fair (Power)</th>
                    </tr>
                  </thead>
                  <tbody>{body_rows}
                  </tbody>
                </table>"""
            )

        headline = (
            f"""<div class="headline">
              \U0001f3af Highest-Confidence Market: <strong>{top_row['market']} — {top_row['selection']}</strong> ({top_row['fair_multiplicative_pct']:.1f}% fair)
            </div>"""
            if top_row
            else ""
        )

        game_cards.append(
            f"""
            <div class="card">
              <h2>{game}</h2>
              <p class="start-time">{start}</p>
              {headline}
              {''.join(market_tables)}
            </div>"""
        )

    generated_at = datetime.now(LOCAL_TZ).strftime("%a %b %d, %Y - %I:%M %p %Z")
    history_section = render_history_section(history)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MLB Devigged Odds Board</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #0f1115; color: #e6e8eb; padding: 24px; }}
  .header {{ text-align: center; margin-bottom: 30px; }}
  .header h1 {{ margin-bottom: 4px; }}
  .header p {{ color: #9aa0a6; font-size: 13px; }}
  .card {{ background: #1a1d24; border: 1px solid #2a2e37; border-radius: 10px; padding: 20px; max-width: 820px; margin: 0 auto 24px auto; }}
  .card h2 {{ margin: 0 0 2px 0; font-size: 19px; }}
  .start-time {{ color: #9aa0a6; font-size: 13px; margin: 0 0 14px 0; }}
  .headline {{ background: rgba(111, 209, 138, 0.12); border: 1px solid rgba(111, 209, 138, 0.35); border-radius: 8px; padding: 10px 14px; font-size: 14px; margin: 4px 0 4px 0; }}
  .headline strong {{ color: #6fd18a; }}
  h3 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.04em; color: #9aa0a6; margin: 18px 0 6px 0; }}
  h3 .star {{ text-transform: none; letter-spacing: normal; color: #6fd18a; font-size: 11px; margin-left: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2e37; }}
  th {{ color: #9aa0a6; font-weight: 600; font-size: 12px; text-transform: uppercase; }}
  td.fair {{ color: #6fd18a; font-weight: 600; }}
  tr.pick {{ background: rgba(111, 209, 138, 0.08); }}
  tr.pick td:first-child {{ font-weight: 600; }}
  .badge {{ display: inline-block; background: #6fd18a; color: #0f1115; font-size: 10px; font-weight: 700; letter-spacing: 0.02em; text-transform: uppercase; padding: 2px 6px; border-radius: 4px; margin-left: 6px; vertical-align: middle; }}
  .empty {{ text-align: center; color: #9aa0a6; padding: 60px 0; }}
  .history-card {{ max-width: 900px; }}
  .history-controls {{ display: flex; align-items: center; gap: 10px; margin: 10px 0 16px 0; font-size: 13px; color: #9aa0a6; }}
  .history-controls select {{ background: #0f1115; color: #e6e8eb; border: 1px solid #2a2e37; border-radius: 6px; padding: 4px 8px; font-size: 13px; }}
  .history-tally {{ font-weight: 700; color: #e6e8eb; font-size: 15px; margin-left: 4px; }}
  .result-badge {{ display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
  .result-w {{ background: rgba(111, 209, 138, 0.18); color: #6fd18a; }}
  .result-l {{ background: rgba(224, 108, 117, 0.18); color: #e06c75; }}
  .result-push {{ background: rgba(154, 160, 166, 0.18); color: #9aa0a6; }}
  .result-pending {{ background: rgba(224, 178, 96, 0.18); color: #e0b260; }}
</style>
</head>
<body>
<div class="header">
  <h1>MLB Devigged Odds Board</h1>
  <p>Pinnacle lines, vig removed. Generated {generated_at}. Not a prediction &mdash; the market's own fair price.</p>
</div>
{''.join(game_cards) if game_cards else '<p class="empty">No Pinnacle MLB odds available right now.</p>'}
{history_section}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MLB devigged odds board")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh pull from the Odds API even if a cache exists (~3 credits).",
    )
    group.add_argument(
        "--sample",
        action="store_true",
        help="Render from built-in fake data - no network call, no credits used.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.sample:
        print("Using built-in sample data - no API call, no credits used.")
        events = SAMPLE_EVENTS
    else:
        events = get_events(force_refresh=args.refresh)

    if not events:
        print("No MLB games found for today's slate. Nothing to write.")
        return

    rows = build_board(events)
    if not rows:
        print("Games were returned but Pinnacle hasn't posted odds for any of them yet.")
        return

    history = load_history()
    if not args.sample:
        record_todays_picks(rows, history)
        history = grade_pending_picks(history)
        save_history(history)

    html = render_html(rows, history)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    game_count = len({row["game"] for row in rows})
    print(f"Wrote {game_count} game(s) / {len(rows)} row(s) -> {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
