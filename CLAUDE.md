# Sell Monitor

Momentum-based sell signal monitor for any CoinGecko-listed asset. Computes a composite score (0–100) from five technical indicators weighted toward momentum, then compares it against a time-decaying threshold that loosens as the sell deadline approaches.

## Project structure

- `sell_monitor.py` — single-file CLI tool, entry point is `main()`
- `pyproject.toml` — dependency management via `uv`
- `config.example.json` — template for `config.json`
- `config.json` — local config with credentials (git-ignored, never commit)
- `setup.sh` — installs `uv` and syncs dependencies on a new machine
- `run.sh` — runs the monitor, calling `setup.sh` only if needed

## Setup

```
bash setup.sh       # first-time setup on a new machine
./run.sh            # run (auto-sets up if needed), all CLI args forwarded
```

## Dependencies

`requests`, `pandas`, `numpy`. Managed in `pyproject.toml`. Run with `uv run sell_monitor.py`.

## How it works

On each run, the script:
1. Fetches historical daily price+volume data from CoinGecko
2. Computes five technical indicators over the full history
3. Prints a historical score table for the last `deadline_days` days
4. Prints a full indicator breakdown for today
5. Sends an email alert if the sell signal is active (if email is configured)

Five indicators each produce a 0–100 sub-score (higher = better time to sell):

| Indicator | Weight | What it measures |
|---|---|---|
| RSI(14) | 25% | Overbought/oversold momentum |
| MACD(12,26,9) histogram | 25% | Trend momentum direction and rollover |
| Stochastic(14,3,3) | 20% | Price position in recent range + crossovers |
| Price vs SMA(20)/SMA(50) | 15% | Selling into strength above moving averages |
| Volume ratio (current / 20d avg) | 15% | Participation confirming moves |

The weighted composite is compared against a threshold that decays on this schedule (default):

- Days 0–10: threshold 70 (sell only into strong rallies)
- Days 11–20: threshold 55
- Days 21–25: threshold 40
- Days 26–29: threshold 25
- Day 30: threshold 0 (sell regardless)

## Key configuration (top of `sell_monitor.py`)

- `DEADLINE_DAYS` — default window length (30); override with `--days`
- `TIME_DECAY_SCHEDULE` — list of (max_day, threshold) tuples
- `W_RSI`, `W_MACD`, `W_STOCH`, `W_MA_POS`, `W_VOLUME` — indicator weights (must sum to 1.0)
- Indicator periods: `RSI_PERIOD`, `MACD_FAST/SLOW/SIGNAL`, `STOCH_K_PERIOD/D_PERIOD/SMOOTH`, `SMA_SHORT/LONG`

## Data source

CoinGecko free API (`/api/v3/coins/{coin_id}/market_chart`), no API key needed. Rate-limited to ~10–30 requests/minute. Retries up to 5 times with exponential backoff on 429 responses. The coin ID defaults to `staked-ether` and can be overridden with `--coin` or via `config.json`.

## CLI usage

```
uv run sell_monitor.py                          # one-shot check (defaults to stETH)
uv run sell_monitor.py --coin bitcoin           # monitor a different CoinGecko asset
uv run sell_monitor.py --days 60               # set deadline window to 60 days
uv run sell_monitor.py --start-date 2026-03-11  # override start date
uv run sell_monitor.py --loop                   # continuous (default 1h interval)
uv run sell_monitor.py --loop --interval 1800   # every 30 min
uv run sell_monitor.py --json                   # also dump raw JSON to stdout
uv run sell_monitor.py --test-email             # send a test email and exit
```

CLI arguments take precedence over `config.json`, which takes precedence over built-in defaults.

## Configuration file

Copy `config.example.json` to `config.json` (git-ignored) and fill in your values. All fields are optional.

```json
{
  "coin": "staked-ether",
  "days": 30,
  "email": {
    "from": "alerts@example.com",
    "to": "you@example.com",
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "alerts@example.com",
    "smtp_pass": "secret"
  }
}
```

## Email alerts

Configure the `email` block in `config.json` to receive SMTP alerts (STARTTLS on port 587).

- **One-shot mode**: email sent once if sell signal is active
- **Loop mode**: at most one email per calendar day
- **Test**: `--test-email` sends immediately regardless of signal, with `[TEST]` in the subject, and exits with an error if email is not configured
