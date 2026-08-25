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
   market showing both fair-probability figures side by side.

## Setup

```bash
pip install -r requirements.txt
```

Set your Odds API key (get one free at https://the-odds-api.com):

```bash
export ODDS_API_KEY=your-key-here
# optional, defaults to UTC:
export LOCAL_TIMEZONE=America/New_York
```

(Windows PowerShell: `$env:ODDS_API_KEY="your-key-here"`)

## Run

```bash
python mlb_odds_board.py
```

Open the generated `mlb_odds_board.html` in any browser.

## Cost

Each run costs **~3 Odds API credits** (3 markets x 1 region), regardless
of how many games are on the slate — the free tier's 500 credits/month
covers well over a hundred daily runs.

## Notes

- Pinnacle is grouped under the `eu` region in The Odds API, not `us` —
  that's already handled in the script.
- If Pinnacle hasn't posted a game yet (early in the day) or the MLB slate
  is empty (off-day), the script says so and exits cleanly without writing
  a stale/empty file.
