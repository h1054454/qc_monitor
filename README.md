# QC Monitor — Macro Early Warning System for Value Investors

A daily macro indicator monitor and weekly stock screener built on the investment principles of **Warren Buffett and Charlie Munger**. Monitors ATX, DAX, and S&P 500 quality stocks and sends alerts when macro events create unfair discounts unrelated to business fundamentals.

## What This Tool Does

### Daily Monitor (`scripts/market_monitor.py`)
Runs every morning. Checks 7 macro indicators against Buffett/Munger buy-signal thresholds. Sends alerts via **Email (HTML)** and **Telegram** when a threshold is crossed. Also regenerates `website/status.html` with the current market snapshot.

**Signal logic (inverted from conventional danger colors):**
- ⚪ **NORMAL** — all indicators in range, no email sent
- 🟡 **BEOBACHTEN** — approaching buy threshold, watch closely
- 🟢 **KAUFSIGNAL** — buy threshold reached: quality stocks are getting cheap for the wrong reasons

### Weekly Screener (`scripts/weekly_screener.py`)
Runs every Monday. Fetches live P/E ratios and 52-week drawdowns for a curated 24-stock watchlist. Flags stocks where **both** Buffett (P/E below threshold) and Munger (≥10% off 52-week high) would agree to buy. Logs results to CSV for time-series analysis.

### Newsletter Website (`website/index.html` + `website/status.html`)
- `index.html` — static landing page explaining the philosophy, indicators, and watchlist. Signup via mailto.
- `status.html` — regenerated daily with live indicator values, current signal levels, and grouped stock recommendations.

---

## The 7 Macro Indicators

| Indicator | Trigger | Why it creates unfair discounts |
|-----------|---------|--------------------------------|
| **VIX** | > 20 / > 30 | Broad panic causes indiscriminate selling of quality insurance + banking stocks |
| **KRE (US Regional Banks ETF)** | -10% / -15% in 14 days | Regional bank crisis drags conservative banks (USB, MTB) down with the sector |
| **QQQ (Nasdaq 100)** | -10% / -20% from 52W high | Tech correction forces portfolio liquidations across all sectors |
| **NVDA** | -20% / -35% from 52W high | AI sentiment collapse signals Nasdaq correction with broad forced selling |
| **Brent Oil (high)** | > $120 / > $130 | Iran war escalation sells down European stocks — but reinsurers are actually beneficiaries |
| **Brent Oil (low)** | < $80 / < $70 | Iran de-escalation reduces reinsurer pricing tailwind |
| **US 10Y Treasury Yield** | > 4.5% / > 5.5% | Rising risk-free rate mechanically compresses P/E multiples across all equities |
| **Atlantic Hurricane** | Cat 1+ / Cat 3+ | Hurricane landfall creates 2-3 day window of maximum fear discount on insurers |

---

## Watchlist

**S&P 500:** Chubb, Cincinnati Financial, Travelers, Progressive, Arch Capital, U.S. Bancorp, M&T Bank, Wells Fargo, Bank of America

**DAX:** Allianz SE, Munich Re, Hannover Rück, Deutsche Börse, DHL Group, RWE AG

**ATX:** Erste Group, Vienna Insurance Group, OMV AG, Raiffeisen Bank, Andritz AG, EVN AG

---

## Folder Structure

```
QC_Monitor/
  scripts/
    market_monitor.py       # Daily macro monitor — email + Telegram + status.html
    weekly_screener.py      # Weekly Buffett/Munger consensus screener
    fill_dax.py             # One-time helper for DAX data enrichment
  config/
    monitor_config.json     # GITIGNORED — credentials (Gmail, Telegram, thresholds)
    monitor_config.example.json  # Template — copy to monitor_config.json and fill in
    known_subscribers.json  # GITIGNORED — list of addresses that received welcome email
  data/
    indicator_history.csv   # Time-series of all daily indicator readings
    screener_history.csv    # Time-series of weekly screener results (auto-created)
  logs/
    monitor_log.txt         # GITIGNORED — runtime log
    screener_log.txt        # GITIGNORED — runtime log
  website/
    index.html              # Static landing page + newsletter signup
    status.html             # GITIGNORED — auto-generated daily market snapshot
```

---

## Setup

### 1. Install dependencies
```bash
pip install yfinance requests
```

### 2. Configure credentials
```bash
cp config/monitor_config.example.json config/monitor_config.json
# Edit monitor_config.json — add Gmail App Password and Telegram bot credentials
```

**Gmail App Password:** myaccount.google.com → Security → 2-Step Verification → App Passwords

**Telegram Bot:**
1. Message `@BotFather` → `/newbot` → copy token
2. Send your bot any message
3. Get your `chat_id`: `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 3. Run manually
```bash
python scripts/market_monitor.py   # daily monitor
python scripts/weekly_screener.py  # weekly screener
```

### 4. Schedule (Windows Task Scheduler)
See the PowerShell commands at the bottom of each script file.

### 5. Newsletter distribution
Add subscriber email addresses to the `bcc` array in `monitor_config.json`.
New addresses automatically receive a personalized welcome email on the next run.

---

## Newsletter Welcome Email
Automatically sent once to each new subscriber added to the `bcc` list.
Contains: investment philosophy, all 7 indicators explained, watchlist, signal legend, legal disclaimer.

---

## Legal
Private, non-commercial market observation. Not investment advice. Not a licensed financial advisor. See full disclaimer in `website/index.html`.

---

## Tech Stack
- Python 3.x
- `yfinance` — market data (prices, P/E, P/B, dividend yield)
- `requests` — NOAA hurricane feed, Telegram Bot API
- Gmail SMTP SSL (port 465) — HTML email delivery
- Static HTML — no backend, no framework, deployable to GitHub Pages

## Keywords
`value-investing` `buffett` `munger` `market-monitor` `stock-screener` `macro-indicators` `vix` `early-warning` `atx` `dax` `sp500` `telegram-bot` `gmail` `newsletter` `python`
