# stETH Sell Monitor

Momentum-based sell signal monitor for stETH. Computes a composite score (0–100) from five technical indicators weighted toward momentum, then compares it against a time-decaying threshold that loosens as a 30-day sell deadline approaches.

## Project structure

- `sell_monitor.py` — single-file CLI tool, entry point is `main()`
- `pyproject.toml` — dependency management via `uv`

## Dependencies

`requests`, `pandas`, `numpy`. Managed in `pyproject.toml`. Run with `uv run sell_monitor.py`.

## How it works

Five indicators each produce a 0–100 sub-score (higher = better time to sell):

| Indicator | Weight | What it measures |
|---|---|---|
| RSI(14) | 25% | Overbought/oversold momentum |
| MACD(12,26,9) histogram | 25% | Trend momentum direction and rollover |
| Stochastic(14,3,3) | 20% | Price position in recent range + crossovers |
| Price vs SMA(20)/SMA(50) | 15% | Selling into strength above moving averages |
| Volume ratio (current / 20d avg) | 15% | Participation confirming moves |

The weighted composite is compared against a threshold that decays on this schedule:

- Days 0–10: threshold 70 (sell only into strong rallies)
- Days 11–20: threshold 55
- Days 21–25: threshold 40
- Days 26–29: threshold 25
- Day 30: threshold 0 (sell regardless)

## Key configuration (top of `sell_monitor.py`)

- `START_DATE` — when the 30-day window begins (defaults to today)
- `DEADLINE_DAYS` — window length (default 30)
- `TIME_DECAY_SCHEDULE` — list of (max_day, threshold) tuples
- `W_RSI`, `W_MACD`, `W_STOCH`, `W_MA_POS`, `W_VOLUME` — indicator weights (must sum to 1.0)
- Indicator periods: `RSI_PERIOD`, `MACD_FAST/SLOW/SIGNAL`, `STOCH_K_PERIOD/D_PERIOD/SMOOTH`, `SMA_SHORT/LONG`

## Data source

CoinGecko free API (`/api/v3/coins/{coin_id}/market_chart`), no API key needed. Rate-limited to ~10–30 requests/minute. The coin ID defaults to `staked-ether` and can be overridden with `--coin` (use the CoinGecko coin ID, e.g. `bitcoin`, `ethereum`, `staked-ether`).

## CLI usage

```
uv run sell_monitor.py                          # one-shot check (defaults to stETH)
uv run sell_monitor.py --coin bitcoin           # monitor a different CoinGecko asset
uv run sell_monitor.py --loop                   # continuous (default 1h interval)
uv run sell_monitor.py --loop --interval 1800   # every 30 min
uv run sell_monitor.py --json                   # also dump raw JSON
uv run sell_monitor.py --start-date 2026-03-11  # override start date
uv run sell_monitor.py --days 60                # extend deadline to 60 days
```

## Email alerts

Set these environment variables to receive SMTP email alerts on sell signals:

`ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
