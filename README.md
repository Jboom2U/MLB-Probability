# MLB Probability Board

A lightweight daily tool that pulls today's MLB odds from **Pinnacle**
(the market widely regarded as the sharpest / closest to true probability),
strips the sportsbook's built-in margin (the "vig"), and writes a clean,
self-contained HTML table of the resulting **fair, devigged probabilities**
for each game's Moneyline, Run Line (spread), and Total (over/under).

This is **not** a predictive model. It doesn't guess who wins — it takes
the sharpest available market price and reports what it actually implies
once the house edge is removed.

## How it works

1. Fetches today's MLB games from [The Odds API](https://the-odds-api.com),
   filtered to the Pinnacle bookmaker and the `h2h` / `spreads` / `totals`
   markets.
2. Converts each American-odds price to a raw (vig-included) implied
   probability.
3. Devigs each 2-outcome market two ways:
   - **Multiplicative** — normalize so the pair sums to 100%.
   - **Power** — solve for exponent `k` so `p1^k + p2^k = 1`, via bisection
     (pure Python, no `scipy`).
4. Writes `mlb_odds_board.html` — one card per game, with a mini-table per
   market showing both fair-probability figures side by side, plus a
   headline naming whichever market/side has the single highest fair
   probability for that game.
5. Tracks that headline pick for every game in `pick_history.json`, and
   automatically grades yesterday's (and any other still-pending) picks
   using free final scores from MLB's own Stats API once they're final —
   see **Running Record** below.

## Setup

```bash
pip install -r requirements.txt
```

Set your Odds API key (get one free at https://the-odds-api.com) — either
copy `.env.example` to `.env` and fill it in, or export it in your shell:

```bash
export ODDS_API_KEY=your-key-here
# optional, defaults to UTC:
export LOCAL_TIMEZONE=America/New_York
```

(Windows PowerShell: `$env:ODDS_API_KEY="your-key-here"`)

Using a `.env` file is recommended on Windows since it lets the `.bat`
shortcuts below work without an open terminal.

## Daily use

Each day you want fresh odds, run:

```bash
python mlb_odds_board.py --refresh
```

(or double-click **`refresh_odds.bat`** on Windows). That's the whole daily
habit — it pulls live odds (~3 credits), grades yesterday's picks, updates
the Running Record, writes `mlb_odds_board.html`, **and opens it in your
browser automatically.** Pass `--no-open` to skip the auto-open (e.g. for
a scheduled/cron run on a machine with no display).

Plain `python mlb_odds_board.py` (no flags) also opens the browser, but
only pulls live if no cache exists yet — otherwise it just re-shows
whatever was last fetched, which is what you want for re-opening the page
later the same day without spending more credits.

## Credit usage — cached by default

The **first** run (or any run with no local cache yet) pulls live odds:
**~3 credits** (3 markets x 1 region), regardless of slate size. Every run
after that reuses the cached response (`odds_cache.json`) and makes **no
API call** — free to re-run as many times as you want while tweaking
styling or logic.

| Command | What it does | Costs credits? |
|---|---|---|
| `python mlb_odds_board.py` | Uses cache if present, else pulls live | Only if no cache yet |
| `python mlb_odds_board.py --refresh` | Forces a fresh pull (odds moved, new day) | Yes, ~3 |
| `python mlb_odds_board.py --sample` | Renders from built-in fake data | Never |

On Windows, double-click:
- **`refresh_odds.bat`** — pulls fresh live odds (the "refresh" button)
- **`preview_sample.bat`** — renders fake sample data, zero cost, good for
  previewing style changes

Both `.bat` files now auto-detect `python` vs. the `py` launcher and print
a clear error (staying open until you press a key) if neither is on PATH,
instead of silently doing nothing.

If double-clicking a `.bat` seems to do nothing, run it from PowerShell
instead so you can actually read any error: `.\refresh_odds.bat` (the
leading `.\` is required by PowerShell for anything in the current folder
— that's PowerShell's own safety default, not specific to this project).

The free tier's 500 credits/month covers well over a hundred `--refresh`
pulls, since normal re-runs between refreshes don't touch the API at all.

## Running Record

Each game's "Highest-Confidence Market" pick (one per game — whichever
market/side has the single highest fair probability) is logged to
`pick_history.json` the first time it's computed each day, and never
overwritten later that day even if you `--refresh` and the line moves.

The next time you run the script on a later day, it checks
[MLB's free public Stats API](https://statsapi.mlb.com) (no key required,
doesn't touch your Odds API credits) for final scores on any date with
still-`Pending` picks, and grades each one:

- **Moneyline** — win/loss on the final score.
- **Run Line** — covers if `(picked team's margin) + point > 0`.
- **Total** — Over/Under vs. combined runs; exact ties grade as `Push`.

A "Running Record" section at the bottom of `mlb_odds_board.html` shows
every graded pick with a date filter (dropdown: a single day, or "All
Time") and a live W-L(-Push) tally. `--sample` runs still show this
section (reading the real `pick_history.json`) — they just don't add fake
games to it. `pick_history.json` is committed to git, not gitignored, since
it's your actual track record, not disposable cache.

If a game's final score can't be matched (rare — usually a doubleheader or
a team-name mismatch), that entry just stays `Pending` rather than being
graded wrong.

## Notes

- Pinnacle is grouped under the `eu` region in The Odds API, not `us` —
  that's already handled in the script.
- If Pinnacle hasn't posted a game yet (early in the day) or the MLB slate
  is empty (off-day), the script says so and exits cleanly without writing
  a stale/empty file.
- Set `LOCAL_TIMEZONE` to your real zone (e.g. `America/New_York`) rather
  than leaving it at the UTC default — late night games otherwise get
  grouped into the *next* UTC calendar date in the Running Record, split
  away from the rest of that day's slate.
