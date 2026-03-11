# Sell Monitor

A momentum-based sell signal monitor for crypto assets. It fetches daily price and volume data from CoinGecko, computes five technical indicators, and produces a composite score (0–100). The score is compared against a time-decaying threshold that loosens as a configurable deadline approaches — so it demands stronger signals early on and accepts weaker ones as time runs out.

> **Disclaimer:** This is not financial advice. Technical indicators are probabilistic tools, not crystal balls. Use at your own risk.

---

## Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (installed automatically by `setup.sh` if missing)
- Internet access to the [CoinGecko free API](https://www.coingecko.com/en/api) (no API key required)

---

## Quick start

### On a new machine

```bash
bash setup.sh
```

This installs `uv` to `~/.local/bin` if it is not already available, then installs all Python dependencies into a local virtual environment.

### Running the monitor

The easiest way to run is via `run.sh`, which automatically runs `setup.sh` if setup has not been done yet:

```bash
./run.sh
```

All command-line arguments are forwarded:

```bash
./run.sh --coin bitcoin --days 14 --loop
```

Alternatively, once setup is complete you can invoke the script directly with `uv`:

```bash
uv run sell_monitor.py
```

---

## Configuration

### config.json

Copy `config.example.json` to `config.json` and fill in your values. This file is git-ignored so credentials will not be committed.

```bash
cp config.example.json config.json
```

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

All fields are optional. Any value set here can be overridden by a command-line argument.

| Field | Description | Default |
|---|---|---|
| `coin` | CoinGecko coin ID to monitor | `staked-ether` |
| `days` | Sell deadline window in days | `30` |
| `email.from` | Sender address | — |
| `email.to` | Recipient address | — |
| `email.smtp_host` | SMTP server hostname | — |
| `email.smtp_port` | SMTP port (STARTTLS) | `587` |
| `email.smtp_user` | SMTP username (defaults to `from`) | — |
| `email.smtp_pass` | SMTP password | — |

### Priority order

**CLI argument > config.json > built-in default**

---

## Command-line arguments

```
uv run sell_monitor.py [OPTIONS]
```

| Argument | Description |
|---|---|
| `--coin ID` | CoinGecko coin ID to monitor (e.g. `bitcoin`, `ethereum`, `staked-ether`) |
| `--days N` | Sell deadline window in days (default: 30) |
| `--start-date YYYY-MM-DD` | Override the start date of the deadline window (default: today) |
| `--loop` | Run continuously, checking on a fixed interval |
| `--interval N` | Seconds between checks in loop mode (default: 3600) |
| `--json` | Also print the full analysis as JSON to stdout |
| `--test-email` | Fetch data, print the report, send a test email, then exit |

### Examples

```bash
# One-shot check with default settings (stETH, 30-day window starting today)
uv run sell_monitor.py

# Monitor Bitcoin with a 14-day window
uv run sell_monitor.py --coin bitcoin --days 14

# Start a 30-day window from a specific date
uv run sell_monitor.py --start-date 2026-03-01

# Run continuously, checking every 30 minutes
uv run sell_monitor.py --loop --interval 1800

# One-shot check with full JSON output
uv run sell_monitor.py --json

# Verify your email configuration
uv run sell_monitor.py --test-email
```

---

## How the score works

On each run the script prints a historical score table covering the last `days` days, followed by a detailed breakdown for today.

### Indicators

Five indicators each produce a sub-score from 0 to 100, where a higher score means it is a better time to sell:

| Indicator | Weight | What it measures |
|---|---|---|
| RSI(14) | 25% | Overbought/oversold momentum |
| MACD(12,26,9) histogram | 25% | Trend momentum direction and rollover |
| Stochastic(14,3,3) | 20% | Price position within recent range, plus crossovers |
| Price vs SMA(20)/SMA(50) | 15% | Whether price is selling into strength above moving averages |
| Volume ratio (current / 20-day avg) | 15% | Participation confirming the move |

### Time-decay thresholds

The composite score is compared against a threshold that falls over time:

| Days elapsed | Threshold | Meaning |
|---|---|---|
| 0–10 | 70 | Sell only into strong momentum |
| 11–20 | 55 | Moderately selective |
| 21–25 | 40 | Take reasonable opportunities |
| 26–29 | 25 | Sell on almost any uptick |
| 30 | 0 | Sell regardless |

When the composite score meets or exceeds the threshold, a **SELL SIGNAL** is triggered.

---

## Email alerts

Configure the `email` block in `config.json` to receive alerts via SMTP (STARTTLS, typically port 587).

- **One-shot mode:** one email is sent if the sell signal is active.
- **Loop mode:** at most one email is sent per calendar day, even if the signal stays active across multiple checks.
- **Test:** run with `--test-email` to send a test email immediately, regardless of the current signal. The subject is prefixed with `[TEST]`. The command exits with an error if email is not configured.

---

## Data source

Price and volume data is fetched from the [CoinGecko free API](https://www.coingecko.com/en/api). No API key is required. The API is rate-limited to approximately 10–30 requests per minute; the script retries automatically with exponential backoff if rate-limited.

To find a coin ID, search for the asset on CoinGecko and use the identifier shown in the URL, for example:
- `staked-ether` — Lido Staked Ether (stETH)
- `ethereum` — Ethereum
- `bitcoin` — Bitcoin
