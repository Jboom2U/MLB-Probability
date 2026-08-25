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
2. export ODDS_API_KEY=your-key-from-the-odds-api.com
   (optional) export LOCAL_TIMEZONE=America/New_York   # defaults to UTC
3. python mlb_odds_board.py

Each run costs ~3 Odds API credits (3 markets x 1 region), regardless of how
many games are on the slate that day.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "UTC"))

SPORT = "baseball_mlb"
BOOKMAKER = "pinnacle"
MARKETS = "h2h,spreads,totals"
ODDS_API_URL = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"

OUTPUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mlb_odds_board.html")

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

        market_tables = []
        for market_name, market_rows in markets.items():
            body_rows = "".join(
                f"""
                <tr>
                  <td>{r['selection']}</td>
                  <td>{format_odds(r['odds'])}</td>
                  <td>{r['raw_pct']:.1f}%</td>
                  <td class="fair">{r['fair_multiplicative_pct']:.1f}%</td>
                  <td class="fair">{r['fair_power_pct']:.1f}%</td>
                </tr>"""
                for r in market_rows
            )
            market_tables.append(
                f"""
                <h3>{market_name}</h3>
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

        game_cards.append(
            f"""
            <div class="card">
              <h2>{game}</h2>
              <p class="start-time">{start}</p>
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
  h3 {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.04em; color: #9aa0a6; margin: 18px 0 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2e37; }}
  th {{ color: #9aa0a6; font-weight: 600; font-size: 12px; text-transform: uppercase; }}
  td.fair {{ color: #6fd18a; font-weight: 600; }}
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

def main() -> None:
    events = fetch_pinnacle_odds()

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
