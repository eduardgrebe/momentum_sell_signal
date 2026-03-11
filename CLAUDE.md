# Sell Monitor

Momentum-based sell signal monitor for any CoinGecko-listed asset. Computes a composite score (0–100) from five technical indicators weighted toward momentum, then compares it against a time-decaying threshold that loosens as the sell deadline approaches.

## Project structure

- `sell_monitor.py` — single-file CLI tool, entry point is `main()`
- `pyproject.toml` — dependency management via `uv`
- `config.example.json` — template for `config.json`
- `config.json` — local config with credentials (git-ignored, never commit)
- `setup.sh` — installs `uv` and syncs dependencies on a new machine
- `run.sh` — runs the monitor, calling `setup.sh` only if needed
- `install-service.sh` — installs the monitor as a persistent background service (macOS LaunchAgent or Linux systemd user service); supports multiple simultaneous instances for different assets via coin-specific service names

## Setup

```
bash setup.sh       # first-time setup on a new machine
./run.sh            # run (auto-sets up if needed), all CLI args forwarded
```

## Dependencies

`requests`, `pandas`, `numpy`. Managed in `pyproject.toml`. Run with `uv run sell_monitor.py`.

## How it works

In **loop mode**, on startup:
1. Sends a `[SERVICE STARTED]` confirmation email with key configuration parameters

On each check:
1. Fetches historical daily price+volume data from CoinGecko
2. Computes five technical indicators over the full history
3. Prints a historical score table for the last `deadline_days` days
4. Prints a full indicator breakdown for today
5. Sends a `[!ALERT!]` email if the sell signal is active (at most once every 3 hours)
6. Sends a `[UPDATE]` daily summary email if `daily_update` is enabled (once per calendar day)

Five indicators each produce a 0–100 sub-score (higher = better time to sell):

| Indicator | Default weight | Config key | What it measures |
|---|---|---|---|
| RSI(14) | 25% | `weights.rsi` | Overbought/oversold momentum |
| MACD(12,26,9) histogram | 25% | `weights.macd` | Trend momentum direction and rollover |
| Stochastic(14,3,3) | 20% | `weights.stoch` | Price position in recent range + crossovers |
| Price vs SMA(20)/SMA(50) | 15% | `weights.ma_pos` | Selling into strength above moving averages |
| Volume ratio (current / 20d avg) | 15% | `weights.volume` | Participation confirming moves |

Weights are configurable via the `weights` block in `config.json` (see Configuration file). They should sum to 1.0; a warning is printed at startup if they don't.

The weighted composite is compared against a time-decaying threshold. Bracket boundaries scale proportionally with `deadline_days`, so the schedule always spans the full window. The starting threshold is configurable via `start_threshold` in `config.json` (default 70); the intermediate thresholds are fixed:

| Window proportion | Days (default 30) | Default threshold | Meaning |
|---|---|---|---|
| 0–33% | 0–10 | 70 (`start_threshold`) | Sell only into strong rallies |
| 34–67% | 11–20 | 55 | Moderately selective |
| 68–83% | 21–25 | 40 | Take reasonable opportunities |
| 84–97% | 26–29 | 25 | Sell on almost any uptick |
| 100% | 30 | 0 | Sell regardless |

The full schedule can be changed by editing `TIME_DECAY_SCHEDULE` in the source.

## Key configuration (top of `sell_monitor.py`)

- `DEADLINE_DAYS` — default window length (30); override with `--days` or `config.json`
- `TIME_DECAY_SCHEDULE` — list of (max_day, threshold) tuples; first entry's threshold is overridden by `start_threshold`
- `W_RSI`, `W_MACD`, `W_STOCH`, `W_MA_POS`, `W_VOLUME` — indicator weight defaults (overridable via `weights` in `config.json`)
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
  "start_threshold": 70,
  "daily_update": false,
  "weights": {
    "rsi":    0.25,
    "macd":   0.25,
    "stoch":  0.20,
    "ma_pos": 0.15,
    "volume": 0.15
  },
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

| Field | Description | Default |
|---|---|---|
| `coin` | CoinGecko coin ID | `staked-ether` |
| `days` | Deadline window in days | `30` |
| `start_threshold` | Sell threshold for days 0–10 | `70` |
| `daily_update` | Send a daily `[UPDATE]` email in loop mode | `false` |
| `weights.rsi` | RSI indicator weight | `0.25` |
| `weights.macd` | MACD histogram indicator weight | `0.25` |
| `weights.stoch` | Stochastic indicator weight | `0.20` |
| `weights.ma_pos` | MA position indicator weight | `0.15` |
| `weights.volume` | Volume ratio indicator weight | `0.15` |
| `email.*` | SMTP credentials for alerts | — |

## Email alerts

Configure the `email` block in `config.json` to receive SMTP alerts (STARTTLS on port 587).

| Subject prefix | When sent |
|---|---|
| `[SERVICE STARTED]` | Once at startup in loop mode — confirms config, coin, interval, thresholds |
| `[!ALERT!]` | Sell signal active — at most once per calendar day in loop mode; once per run in one-shot mode |
| `[UPDATE]` | Daily update with 7-day history — loop mode only, if `daily_update: true` in config |
| `[TEST]` | `--test-email` flag — sends immediately regardless of signal; exits with error if email not configured |

All alert and update emails include an HTML body (fixed-width font, history table, indicator breakdown) and `analysis.json` as an attachment.

## License

MIT — see `LICENSE`. This software is provided as-is with no warranty. It is **not financial advice**; use at your own risk.
