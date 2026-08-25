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
        if commence:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
            local_time = dt.strftime("%a %I:%M %p %Z")

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
                selection = outcome.get("name", "")
                if point is not None:
                    formatted_point = f"{point:+g}" if key == "spreads" else f"{point:g}"
                    selection = f"{selection} {formatted_point}"

                rows.append(
                    {
                        "game": f"{away} @ {home}",
                        "start": local_time,
                        "market": MARKET_LABELS[key],
                        "selection": selection,
                        "odds": outcome["price"],
                        "raw_pct": raw_p * 100,
                        "fair_multiplicative_pct": mult_p * 100,
                        "fair_power_pct": power_p * 100,
                    }
                )

    return rows


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def format_odds(odds: float) -> str:
    return f"+{odds:g}" if odds > 0 else f"{odds:g}"


def render_html(rows: list[dict]) -> str:
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
        top_row = max(game_rows, key=lambda r: r["fair_multiplicative_pct"], default=None)

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
</style>
</head>
<body>
<div class="header">
  <h1>MLB Devigged Odds Board</h1>
  <p>Pinnacle lines, vig removed. Generated {generated_at}. Not a prediction &mdash; the market's own fair price.</p>
</div>
{''.join(game_cards) if game_cards else '<p class="empty">No Pinnacle MLB odds available right now.</p>'}
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

    html = render_html(rows)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    game_count = len({row["game"] for row in rows})
    print(f"Wrote {game_count} game(s) / {len(rows)} row(s) -> {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
