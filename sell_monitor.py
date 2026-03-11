#!/usr/bin/env python3
"""
stETH Momentum-Based Sell Signal Monitor
=========================================
Computes a composite momentum score from RSI, MACD, Stochastic, MA position,
and volume. Compares the score against a time-decaying threshold so that the
sell criteria loosen as the 30-day deadline approaches.

Usage:
    uv run sell_monitor.py                        # one-shot check
    uv run sell_monitor.py --loop                 # continuous monitoring
    uv run sell_monitor.py --loop --interval 1800 # every 30 min
    uv run sell_monitor.py --coin bitcoin --days 14

Configuration:
    Copy config.example.json to config.json and fill in your values.
    config.json supports: coin, days, and email (from/to/smtp_host/smtp_port/
    smtp_user/smtp_pass). CLI arguments override config.json values.

Disclaimer: This is NOT financial advice. Technical indicators are
probabilistic tools, not crystal balls. Use at your own risk.
"""

import argparse
import datetime as dt
import json
import os
import smtplib
import sys
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import numpy as np
import pandas as pd
import requests

# ──────────────────────────────────────────────────────────────────────
# Config file
# ──────────────────────────────────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    """Load config.json from the script directory, or return an empty dict."""
    if not os.path.exists(_CONFIG_PATH):
        return {}
    with open(_CONFIG_PATH) as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

# The date you START monitoring. Set via --start-date or defaults to today at runtime.
START_DATE: dt.date = None  # resolved in main()

# Hard deadline: must sell within 30 days of START_DATE
DEADLINE_DAYS = 30

# CoinGecko free API endpoint (no key needed, rate-limited to ~10-30 req/min)
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COIN_ID = "staked-ether"  # CoinGecko ID — override with --coin
VS_CURRENCY = "usd"

# Indicator parameters
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
STOCH_K_PERIOD = 14
STOCH_D_PERIOD = 3
STOCH_SMOOTH = 3
SMA_SHORT = 20
SMA_LONG = 50

# Weights (must sum to 1.0)
W_RSI = 0.25
W_MACD = 0.25
W_STOCH = 0.20
W_MA_POS = 0.15
W_VOLUME = 0.15

# Time-decay thresholds: (max_day, threshold)
# On day N (0-indexed from START_DATE), the sell threshold is the value
# from the first bracket whose max_day >= N.
TIME_DECAY_SCHEDULE = [
    (10, 70),   # days 0-10:  only sell into strong momentum
    (20, 55),   # days 11-20: moderately selective
    (25, 40),   # days 21-25: take reasonable opportunities
    (29, 25),   # days 26-29: sell on almost any uptick
    (30, 0),    # day 30:     sell regardless
]

# Warm-up rows needed before indicator values are valid
_INDICATOR_WARMUP = max(SMA_LONG, MACD_SLOW + MACD_SIGNAL, RSI_PERIOD, STOCH_K_PERIOD)

# Default fetch window; extended at runtime when --days exceeds 30
HISTORY_DAYS = _INDICATOR_WARMUP + DEADLINE_DAYS


# ──────────────────────────────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────────────────────────────

def fetch_ohlc(coin_id: str = COIN_ID, days: int = HISTORY_DAYS) -> pd.DataFrame:
    """Fetch daily market data from CoinGecko and return a DataFrame."""
    # Use market_chart for price + volume (OHLC endpoint has limited granularity)
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": VS_CURRENCY, "days": days, "interval": "daily"}

    for attempt in range(5):
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            wait = 2 ** attempt * 10
            print(f"  Rate limited by CoinGecko, retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break
    else:
        resp.raise_for_status()
    data = resp.json()

    prices = data["prices"]          # [[timestamp_ms, price], ...]
    volumes = data["total_volumes"]  # [[timestamp_ms, volume], ...]

    df = pd.DataFrame(prices, columns=["ts", "close"])
    df["volume"] = [v[1] for v in volumes]
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.date
    df = df.drop(columns=["ts"]).set_index("date").sort_index()

    # CoinGecko daily data gives close prices; approximate high/low from
    # close using a rolling window matching the Stochastic look-back period.
    # For better precision you could use an OHLC source.
    df["high"] = df["close"].rolling(window=STOCH_K_PERIOD, min_periods=1).max()
    df["low"] = df["close"].rolling(window=STOCH_K_PERIOD, min_periods=1).min()

    return df


# ──────────────────────────────────────────────────────────────────────
# Technical indicator calculations
# ──────────────────────────────────────────────────────────────────────

def compute_rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_macd(series: pd.Series,
                 fast: int = MACD_FAST,
                 slow: int = MACD_SLOW,
                 signal: int = MACD_SIGNAL):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_stochastic(df: pd.DataFrame,
                       k_period: int = STOCH_K_PERIOD,
                       d_period: int = STOCH_D_PERIOD,
                       smooth: int = STOCH_SMOOTH):
    low_min = df["low"].rolling(window=k_period, min_periods=k_period).min()
    high_max = df["high"].rolling(window=k_period, min_periods=k_period).max()
    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    k = raw_k.rolling(window=smooth, min_periods=1).mean()
    d = k.rolling(window=d_period, min_periods=1).mean()
    return k, d


# ──────────────────────────────────────────────────────────────────────
# Scoring functions (each returns 0-100)
# ──────────────────────────────────────────────────────────────────────

def score_rsi(rsi_value: float) -> float:
    """Higher RSI = better time to sell (selling into strength)."""
    if rsi_value >= 75:
        return 100
    elif rsi_value >= 65:
        return 75 + 25 * (rsi_value - 65) / 10
    elif rsi_value >= 50:
        return 40 + 35 * (rsi_value - 50) / 15
    elif rsi_value >= 35:
        return 15 + 25 * (rsi_value - 35) / 15
    else:
        return max(0, 15 * rsi_value / 35)


def score_macd(histogram: float, prev_histogram: float) -> float:
    """
    Best sell: histogram positive but starting to decline (momentum fading).
    Worst: histogram deeply negative and falling (selling into weakness).
    """
    if histogram > 0 and prev_histogram > histogram:
        # Positive but declining — momentum rolling over, ideal sell window
        return 90
    elif histogram > 0:
        # Positive and rising — strong momentum, decent to sell into
        return 70
    elif histogram <= 0 and prev_histogram > histogram:
        # Negative and falling — momentum worsening
        return 20
    elif histogram <= 0 and prev_histogram <= histogram:
        # Negative but recovering
        return 40
    else:
        return 30


def score_stochastic(k: float, d: float, prev_k: float, prev_d: float) -> float:
    """Overbought with bearish crossover is the ideal sell signal."""
    score = 0.0
    # Position score (0-60 based on level)
    if k > 80:
        score += 60
    elif k > 60:
        score += 40
    elif k > 40:
        score += 25
    else:
        score += 10

    # Crossover bonus (0-40)
    if prev_k >= prev_d and k < d and k > 70:
        score += 40  # bearish crossover in overbought zone
    elif prev_k >= prev_d and k < d:
        score += 25  # bearish crossover but not overbought
    elif k > d:
        score += 15  # still bullish
    else:
        score += 5

    return min(100, score)


def score_ma_position(price: float, sma20: float, sma50: float) -> float:
    """Sell into strength: price above both MAs is ideal."""
    above_20 = price > sma20
    above_50 = price > sma50

    if above_20 and above_50:
        # How far above? Cap bonus at ~20% above MA
        pct_above = ((price / sma50) - 1) * 100
        return min(100, 60 + pct_above * 4)
    elif above_20:
        return 50
    elif above_50:
        return 40
    else:
        return 15


def score_volume(current_vol: float, avg_vol: float) -> float:
    """Higher-than-average volume on an up day is good for selling."""
    if avg_vol == 0:
        return 50
    ratio = current_vol / avg_vol
    if ratio >= 1.5:
        return 90
    elif ratio >= 1.0:
        return 60 + 30 * (ratio - 1.0) / 0.5
    elif ratio >= 0.5:
        return 30 + 30 * (ratio - 0.5) / 0.5
    else:
        return max(0, 30 * ratio / 0.5)


# ──────────────────────────────────────────────────────────────────────
# Composite score and decision
# ──────────────────────────────────────────────────────────────────────

def get_threshold(day_number: int,
                  deadline_days: int = DEADLINE_DAYS,
                  start_threshold: int = TIME_DECAY_SCHEDULE[0][1]) -> int:
    """Return the sell threshold for the given day (0-indexed from start).
    Bracket boundaries scale proportionally with deadline_days.
    start_threshold overrides the value for the first bracket."""
    scale = deadline_days / DEADLINE_DAYS
    first = True
    for max_day, threshold in TIME_DECAY_SCHEDULE:
        if day_number <= round(max_day * scale):
            return start_threshold if first else threshold
        first = False
    return 0  # past deadline: always sell


def enrich_indicators(df: pd.DataFrame) -> None:
    """Add all indicator columns to df in-place."""
    df["rsi"] = compute_rsi(df["close"])
    macd_line, signal_line, histogram = compute_macd(df["close"])
    df["macd"], df["macd_signal"], df["macd_hist"] = macd_line, signal_line, histogram
    df["stoch_k"], df["stoch_d"] = compute_stochastic(df)
    df["sma20"] = df["close"].rolling(window=SMA_SHORT).mean()
    df["sma50"] = df["close"].rolling(window=SMA_LONG).mean()
    df["vol_avg_20"] = df["volume"].rolling(window=20).mean()


def composite_score_at(df: pd.DataFrame, i: int) -> float:
    """Compute the composite sell score for row i (requires i >= 1)."""
    row, prev = df.iloc[i], df.iloc[i - 1]
    s_rsi = score_rsi(row["rsi"])
    s_macd = score_macd(row["macd_hist"], prev["macd_hist"])
    s_stoch = score_stochastic(row["stoch_k"], row["stoch_d"],
                               prev["stoch_k"], prev["stoch_d"])
    s_ma = score_ma_position(row["close"], row["sma20"], row["sma50"])
    s_vol = score_volume(row["volume"], row["vol_avg_20"])
    return (W_RSI * s_rsi + W_MACD * s_macd + W_STOCH * s_stoch
            + W_MA_POS * s_ma + W_VOLUME * s_vol)


def compute_history(df: pd.DataFrame, start_date: dt.date,
                    deadline_days: int,
                    start_threshold: int = TIME_DECAY_SCHEDULE[0][1]) -> list[dict]:
    """Return composite scores for the last deadline_days rows of an enriched df."""
    n = len(df)
    rows = []
    for i in range(max(1, n - deadline_days), n):
        row = df.iloc[i]
        date = df.index[i]
        day_num = (date - start_date).days
        threshold = get_threshold(max(0, min(day_num, deadline_days)), deadline_days, start_threshold)
        score = composite_score_at(df, i)
        rows.append({
            "date": str(date),
            "price_usd": round(row["close"], 2),
            "day_number": day_num,
            "composite_score": round(score, 1),
            "threshold": threshold,
            "sell_signal": bool(score >= threshold),
        })
    return rows


def print_history(history: list[dict]) -> None:
    """Print a compact table of historical composite scores."""
    print("\n  Historical scores:")
    print(f"  {'Date':<12} {'Price':>10}  {'Score':>6}  {'Thresh':>6}  Signal")
    print("  " + "-" * 52)
    for h in history:
        sig = "SELL" if h["sell_signal"] else "hold"
        print(f"  {h['date']:<12} ${h['price_usd']:>9,.2f}  "
              f"{h['composite_score']:>6.1f}  {h['threshold']:>6}  {sig}")


def analyse(df: pd.DataFrame, day_number: int, coin_id: str = COIN_ID,
            deadline_days: int = DEADLINE_DAYS,
            start_threshold: int = TIME_DECAY_SCHEDULE[0][1]) -> dict:
    """Compute today's full analysis from an already-enriched dataframe."""
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # Individual scores
    s_rsi = score_rsi(latest["rsi"])
    s_macd = score_macd(latest["macd_hist"], prev["macd_hist"])
    s_stoch = score_stochastic(
        latest["stoch_k"], latest["stoch_d"],
        prev["stoch_k"], prev["stoch_d"],
    )
    s_ma = score_ma_position(latest["close"], latest["sma20"], latest["sma50"])
    s_vol = score_volume(latest["volume"], latest["vol_avg_20"])

    composite = (
        W_RSI * s_rsi
        + W_MACD * s_macd
        + W_STOCH * s_stoch
        + W_MA_POS * s_ma
        + W_VOLUME * s_vol
    )

    threshold = get_threshold(day_number, deadline_days, start_threshold)
    sell_signal = bool(composite >= threshold)

    return {
        "coin_id": coin_id,
        "date": str(df.index[-1]),
        "price_usd": round(latest["close"], 2),
        "day_number": day_number,
        "deadline_days": deadline_days,
        "days_remaining": deadline_days - day_number,
        "threshold": threshold,
        "composite_score": round(composite, 1),
        "sell_signal": sell_signal,
        "indicators": {
            "rsi": {"value": round(latest["rsi"], 1), "score": round(s_rsi, 1)},
            "macd_histogram": {
                "value": round(latest["macd_hist"], 4),
                "prev": round(prev["macd_hist"], 4),
                "score": round(s_macd, 1),
            },
            "stochastic": {
                "k": round(latest["stoch_k"], 1),
                "d": round(latest["stoch_d"], 1),
                "score": round(s_stoch, 1),
            },
            "ma_position": {
                "price": round(latest["close"], 2),
                "sma20": round(latest["sma20"], 2) if pd.notna(latest["sma20"]) else None,
                "sma50": round(latest["sma50"], 2) if pd.notna(latest["sma50"]) else None,
                "score": round(s_ma, 1),
            },
            "volume": {
                "current": round(latest["volume"], 0),
                "avg_20d": round(latest["vol_avg_20"], 0) if pd.notna(latest["vol_avg_20"]) else None,
                "score": round(s_vol, 1),
            },
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Alerting
# ──────────────────────────────────────────────────────────────────────

def _build_email_html(analysis: dict, history_limit: Optional[int] = None) -> str:
    """Build an HTML email body with a monospace font, markdown history table,
    and today's indicator breakdown. history_limit trims the table to the most
    recent N rows (None = all rows)."""
    a = analysis
    history = a.get("history", [])
    if history_limit is not None:
        history = history[-history_limit:]
    ind = a["indicators"]
    signal_str = ">>> SELL SIGNAL <<<" if a["sell_signal"] else "hold"

    # History as a markdown table
    header = f"| {'Date':<12} | {'Price (USD)':>12} | {'Score':>6} | {'Thresh':>6} | Signal |"
    sep    = f"|{'-'*14}|{'-'*14}|{'-'*8}|{'-'*8}|{'-'*8}|"
    rows = [header, sep]
    for h in history:
        sig = "SELL" if h["sell_signal"] else "hold"
        rows.append(
            f"| {h['date']:<12} | ${h['price_usd']:>11,.2f} | "
            f"{h['composite_score']:>6.1f} | {h['threshold']:>6} | {sig:<6} |"
        )
    table = "\n".join(rows)

    # Today's breakdown
    breakdown = (
        f"## {a['coin_id']}  —  {a['date']}\n"
        f"Price: ${a['price_usd']:,.2f}    "
        f"Day {a['day_number']} of {a['deadline_days']}  ({a['days_remaining']} days remaining)\n"
        f"\n"
        f"  RSI(14):       {ind['rsi']['value']:>6.1f}    score {ind['rsi']['score']:>5.1f}  (weight 25%)\n"
        f"  MACD Hist:  {ind['macd_histogram']['value']:>10.4f}    score {ind['macd_histogram']['score']:>5.1f}  (weight 25%)\n"
        f"  Stoch %K/%D: {ind['stochastic']['k']:>5.1f}/{ind['stochastic']['d']:<5.1f}  score {ind['stochastic']['score']:>5.1f}  (weight 20%)\n"
        f"  MA Position:   SMA20={ind['ma_position']['sma20']}  SMA50={ind['ma_position']['sma50']}  score {ind['ma_position']['score']:>5.1f}  (weight 15%)\n"
        f"  Volume Ratio:                    score {ind['volume']['score']:>5.1f}  (weight 15%)\n"
        f"\n"
        f"  COMPOSITE SCORE:  {a['composite_score']:>5.1f}  /  threshold {a['threshold']}\n"
        f"  DECISION:  {signal_str}\n"
    )

    label = f"last {len(history)} days" if history_limit is None else f"last {len(history)} days"
    content = f"## Historical Scores ({label})\n\n{table}\n\n{'-'*60}\n\n{breakdown}"

    return (
        "<html><body style=\"font-family: monospace; font-size: 14px;\">"
        f"<pre>{content}</pre>"
        "</body></html>"
    )


def _smtp_send(subject: str, analysis: dict, email_cfg: dict,
               history_limit: Optional[int] = None) -> bool:
    """Build and send a multipart email with an HTML body and JSON attachment.
    Returns True on success, False if not configured."""
    email_from = email_cfg.get("from")
    email_to = email_cfg.get("to")
    smtp_host = email_cfg.get("smtp_host")
    smtp_port = int(email_cfg.get("smtp_port", 587))
    smtp_user = email_cfg.get("smtp_user", email_from)
    smtp_pass = email_cfg.get("smtp_pass")

    if not all([email_from, email_to, smtp_host, smtp_pass]):
        return False

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    msg.attach(MIMEText(_build_email_html(analysis, history_limit=history_limit), "html"))

    json_bytes = json.dumps(analysis, indent=2).encode()
    attachment = MIMEApplication(json_bytes, Name="analysis.json")
    attachment["Content-Disposition"] = 'attachment; filename="analysis.json"'
    msg.attach(attachment)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(email_from, [email_to], msg.as_string())
        print(f"  Email sent to {email_to}")
        return True
    except Exception as e:
        print(f"  Email failed: {e}", file=sys.stderr)
        return False


def send_email_alert(analysis: dict, email_cfg: dict):
    """Send a sell-signal alert email if email is configured."""
    subject = (
        f"[!ALERT!] {analysis['coin_id']} ${analysis['price_usd']} "
        f"— score {analysis['composite_score']}/{analysis['threshold']}"
    )
    _smtp_send(subject, analysis, email_cfg)


def send_daily_update_email(analysis: dict, email_cfg: dict):
    """Send a daily update email with a 7-day history table."""
    subject = (
        f"[UPDATE] {analysis['coin_id']} ${analysis['price_usd']} "
        f"— score {analysis['composite_score']}/{analysis['threshold']}"
    )
    _smtp_send(subject, analysis, email_cfg, history_limit=7)


def send_test_email(analysis: dict, email_cfg: dict):
    """Send a test email containing the current analysis including history."""
    subject = (
        f"[TEST] {analysis['coin_id']} ${analysis['price_usd']} "
        f"— score {analysis['composite_score']}/{analysis['threshold']}"
    )
    if not _smtp_send(subject, analysis, email_cfg):
        print("  Email not configured — check config.json.", file=sys.stderr)
        sys.exit(1)


def print_report(analysis: dict):
    """Pretty-print the analysis to stdout."""
    a = analysis
    sig = ">>> SELL SIGNAL <<<" if a["sell_signal"] else "    hold"
    print("=" * 60)
    print(f"  Sell Monitor [{a['coin_id']}] — {a['date']}")
    print(f"  Price: ${a['price_usd']:,.2f}")
    print(f"  Day {a['day_number']} of {a['deadline_days']}  "
          f"({a['days_remaining']} days remaining)")
    print("-" * 60)
    ind = a["indicators"]
    print(f"  RSI(14):        {ind['rsi']['value']:>6.1f}   "
          f"score {ind['rsi']['score']:>5.1f}  (weight {W_RSI:.0%})")
    print(f"  MACD Hist:      {ind['macd_histogram']['value']:>10.4f}   "
          f"score {ind['macd_histogram']['score']:>5.1f}  (weight {W_MACD:.0%})")
    print(f"  Stoch %K/%D:    {ind['stochastic']['k']:>5.1f}/{ind['stochastic']['d']:<5.1f} "
          f"score {ind['stochastic']['score']:>5.1f}  (weight {W_STOCH:.0%})")
    print(f"  MA Position:    SMA20={ind['ma_position']['sma20']}  SMA50={ind['ma_position']['sma50']}  "
          f"score {ind['ma_position']['score']:>5.1f}  (weight {W_MA_POS:.0%})")
    print(f"  Volume Ratio:   score {ind['volume']['score']:>5.1f}  (weight {W_VOLUME:.0%})")
    print("-" * 60)
    print(f"  COMPOSITE SCORE:  {a['composite_score']:>5.1f}  /  "
          f"threshold {a['threshold']}")
    print(f"  DECISION:  {sig}")
    print("=" * 60)


# ──────────────────────────────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────────────────────────────

def run_once(start_date: dt.date, coin_id: str = COIN_ID,
             deadline_days: int = DEADLINE_DAYS,
             start_threshold: int = TIME_DECAY_SCHEDULE[0][1]) -> dict:
    """Fetch data, compute indicators, print report, send alert if needed."""
    day_number = (dt.date.today() - start_date).days
    day_number = max(0, min(day_number, deadline_days))

    fetch_days = _INDICATOR_WARMUP + deadline_days
    print(f"\nFetching {fetch_days} days of {coin_id} data from CoinGecko "
          f"({_INDICATOR_WARMUP}d indicator warmup + {deadline_days}d window)...")
    df = fetch_ohlc(coin_id=coin_id, days=fetch_days)
    print(f"  Got {len(df)} data points, latest: {df.index[-1]}")

    enrich_indicators(df)
    history = compute_history(df, start_date, deadline_days, start_threshold)
    print_history(history)

    analysis = analyse(df, day_number, coin_id=coin_id, deadline_days=deadline_days,
                       start_threshold=start_threshold)
    analysis["history"] = history
    print_report(analysis)

    if analysis["sell_signal"]:
        print("\n  *** The composite score has breached the threshold. ***")
        print("  *** Consider executing your sell within the next 24h. ***\n")

    return analysis


def main():
    parser = argparse.ArgumentParser(description="stETH momentum sell-signal monitor")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously instead of one-shot")
    parser.add_argument("--interval", type=int, default=3600,
                        help="Seconds between checks in loop mode (default: 3600)")
    parser.add_argument("--coin", type=str, default=None,
                        help=f"CoinGecko coin ID to monitor (default: {COIN_ID})")
    parser.add_argument("--days", type=int, default=None,
                        help=f"Sell deadline window in days (default: {DEADLINE_DAYS})")
    parser.add_argument("--start-date", type=str, default=None,
                        help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true",
                        help="Also dump raw JSON to stdout")
    parser.add_argument("--test-email", action="store_true",
                        help="Fetch data, print report, and send a test email")
    args = parser.parse_args()

    cfg = load_config()
    email_cfg = cfg.get("email", {})
    daily_update = cfg.get("daily_update", False)

    # CLI > config.json > built-in defaults
    coin = args.coin or cfg.get("coin", COIN_ID)
    days = args.days or cfg.get("days", DEADLINE_DAYS)
    start_threshold = cfg.get("start_threshold", TIME_DECAY_SCHEDULE[0][1])

    start_date = (
        dt.date.fromisoformat(args.start_date) if args.start_date else dt.date.today()
    )
    if args.start_date:
        print(f"Start date overridden to {start_date}")

    if args.test_email:
        analysis = run_once(start_date, coin_id=coin, deadline_days=days,
                            start_threshold=start_threshold)
        send_test_email(analysis, email_cfg)
    elif not args.loop:
        print("Running in one-shot mode. Use --loop to keep the monitor active.")
        analysis = run_once(start_date, coin_id=coin, deadline_days=days,
                            start_threshold=start_threshold)
        if analysis["sell_signal"]:
            send_email_alert(analysis, email_cfg)
        if args.json:
            print("\n" + json.dumps(analysis, indent=2))
        print("\n(One-shot complete. Run with --loop for continuous monitoring.)")
    else:
        print(f"Starting continuous monitoring (interval: {args.interval}s)")
        print(f"Coin: {coin}")
        print(f"Deadline: {start_date + dt.timedelta(days=days)} ({days} days)")
        print("Press Ctrl+C to stop.\n")
        last_alert_date: Optional[dt.date] = None
        last_update_date: Optional[dt.date] = None
        try:
            while True:
                analysis = run_once(start_date, coin_id=coin, deadline_days=days,
                                    start_threshold=start_threshold)
                if args.json:
                    print("\n" + json.dumps(analysis, indent=2))
                today = dt.date.today()
                if analysis["sell_signal"]:
                    print("\nSell signal triggered! Continuing to monitor "
                          "in case you want to wait for an even better window.")
                    if last_alert_date != today:
                        send_email_alert(analysis, email_cfg)
                        last_alert_date = today
                if daily_update and last_update_date != today:
                    send_daily_update_email(analysis, email_cfg)
                    last_update_date = today
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped.")


if __name__ == "__main__":
    main()
