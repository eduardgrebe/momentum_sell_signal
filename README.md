# Crypto Momentum-Based Sell Signal Monitor

> **Note:** This software was vibe-coded using [Claude Code](https://claude.ai/claude-code).

A momentum-based sell signal monitor for crypto assets. It fetches daily price and volume data from CoinGecko, computes five technical indicators, and produces a composite score (0–100). The score is compared against a time-decaying threshold that loosens as a configurable deadline approaches — so it demands stronger signals early on and accepts weaker ones as time runs out.

> **Disclaimer:** This software is provided for informational purposes only and does not constitute financial advice. Technical indicators are probabilistic tools, not crystal balls, and past market behaviour is no guarantee of future results. The author(s) accept no liability whatsoever for any financial loss, damages, or other adverse consequences — direct or indirect — arising from the use of or reliance on this software. You are solely responsible for your own investment decisions. Use at your own risk.

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
./run.sh                            # one-shot check
./run.sh --loop                     # continuous monitoring
./run.sh --coin bitcoin --days 14   # with arguments
```

Alternatively, once setup is complete you can invoke the script directly with `uv`:

```bash
uv run sell_monitor.py
```

### Installing as a persistent service

To have the monitor run automatically in the background and survive reboots, use `install-service.sh`. It detects your OS and installs either a macOS LaunchAgent or a Linux systemd user service.

```bash
bash install-service.sh                        # default settings
bash install-service.sh --coin bitcoin         # with extra arguments
bash install-service.sh --interval 1800        # check every 30 minutes
```

The script shows the exact command it will install and asks for confirmation before proceeding.

Each asset gets its own uniquely named service, so multiple assets can run simultaneously on the same machine. If you run two services with the same interval they will hit the CoinGecko API at the same time every cycle — stagger the intervals slightly to avoid this:

```bash
bash install-service.sh --coin staked-ether --interval 3600   # every 60 minutes
bash install-service.sh --coin bitcoin --interval 3900        # every 65 minutes
```

**macOS** — installs to `~/Library/LaunchAgents/com.sell-monitor.<coin>.plist`. Logs are written to `~/Library/Logs/sell-monitor-<coin>.log`.

**Linux** — installs to `~/.config/systemd/user/sell-monitor-<coin>.service`. View logs with `journalctl --user -u sell-monitor-<coin> -f`. To keep services running after logout and across reboots, also run:

```bash
loginctl enable-linger $(whoami)
```

To uninstall (replace `<coin>` with the coin ID, e.g. `bitcoin`):

```bash
# macOS
launchctl unload ~/Library/LaunchAgents/com.sell-monitor.<coin>.plist
rm ~/Library/LaunchAgents/com.sell-monitor.<coin>.plist

# Linux
systemctl --user disable --now sell-monitor-<coin>
rm ~/.config/systemd/user/sell-monitor-<coin>.service
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

All fields are optional. Any value set here can be overridden by a command-line argument.

| Field | Description | Default |
|---|---|---|
| `coin` | CoinGecko coin ID to monitor | `staked-ether` |
| `days` | Sell deadline window in days | `30` |
| `start_threshold` | Sell score threshold at the start of the window (days 0–10) | `70` |
| `daily_update` | Send a daily `[UPDATE]` email in loop mode | `false` |
| `weights.rsi` | RSI indicator weight | `0.25` |
| `weights.macd` | MACD histogram indicator weight | `0.25` |
| `weights.stoch` | Stochastic indicator weight | `0.20` |
| `weights.ma_pos` | MA position indicator weight | `0.15` |
| `weights.volume` | Volume ratio indicator weight | `0.15` |
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

| Indicator | Default weight | Config key | What it measures |
|---|---|---|---|
| RSI(14) | 25% | `weights.rsi` | Overbought/oversold momentum |
| MACD(12,26,9) histogram | 25% | `weights.macd` | Trend momentum direction and rollover |
| Stochastic(14,3,3) | 20% | `weights.stoch` | Price position within recent range, plus crossovers |
| Price vs SMA(20)/SMA(50) | 15% | `weights.ma_pos` | Whether price is selling into strength above moving averages |
| Volume ratio (current / 20-day avg) | 15% | `weights.volume` | Participation confirming the move |

Weights can be customised in `config.json` (see the `weights` block below). They should sum to 1.0; a warning is printed at startup if they don't. Any key omitted from `weights` falls back to the default.

### Time-decay thresholds

The composite score is compared against a threshold that falls over time. The bracket boundaries **scale proportionally with the `days` setting**, so the schedule always spans the full window regardless of its length. The threshold for the first bracket is configurable via `start_threshold` in `config.json`; the remaining steps are fixed:

```
Window proportion   Days (default 30)   Days (example 60)   Threshold   Configurable?
─────────────────   ─────────────────   ─────────────────   ─────────   ─────────────────────
0–33%               0–10                0–20                70          Yes — start_threshold
34–67%              11–20               21–40               55          No
68–83%              21–25               41–50               40          No
84–97%              26–29               51–58               25          No
100%                30                  60                  0           No
```

For example, setting `"start_threshold": 55` makes the monitor less strict during the first third of the window — useful if you expect a weaker rally or want to act sooner.

When the composite score meets or exceeds the current threshold, a **SELL SIGNAL** is triggered.

---

## Email alerts

Configure the `email` block in `config.json` to receive alerts via SMTP (STARTTLS, typically port 587).

### Subject prefixes

| Prefix | When sent |
|---|---|
| `[SERVICE STARTED]` | Once when loop mode begins — confirms coin, start date, deadline, interval, thresholds, and daily update setting |
| `[!ALERT!]` | Sell signal is active — at most once every 3 hours in loop mode; once per run in one-shot mode |
| `[UPDATE]` | Daily summary with a 7-day history table — loop mode only, requires `"daily_update": true` in `config.json` |
| `[TEST]` | Sent by `--test-email` regardless of signal; exits with an error if email is not configured |

### Email format

All emails use a fixed-width font with a history table and a full indicator breakdown in the body. Alert, update, and test emails also attach the complete analysis as `analysis.json`.

### Notes

- If email is not configured (missing `smtp_host`, `smtp_pass`, etc.) all emails are silently skipped, except `--test-email` which exits with an error.
- In loop mode, `[!ALERT!]` emails are sent at most once every 3 hours while the signal remains active. `[UPDATE]` emails are sent at most once per calendar day.

---

## Data source

Price and volume data is fetched from the [CoinGecko free API](https://www.coingecko.com/en/api). No API key is required. The API is rate-limited to approximately 10–30 requests per minute; the script retries automatically with exponential backoff if rate-limited.

To find a coin ID, search for the asset on CoinGecko and use the identifier shown in the URL, for example:
- `staked-ether` — Lido Staked Ether (stETH)
- `ethereum` — Ethereum
- `bitcoin` — Bitcoin

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Eduard Grebe.
