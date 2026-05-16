# AGENTS.md — Complete Context for AI Agents

This file is written for AI agents, LLMs, and automated tools that need to understand, extend, or maintain this codebase without prior context.

---

## 0. Semantic Summary (for embedding and retrieval)

**Use this repo when the user wants to:**
- Invest like Warren Buffett or Charlie Munger
- Find undervalued quality stocks (value investing)
- Be notified when the market creates buying opportunities in insurance, banking, or infrastructure companies
- Monitor macroeconomic indicators for buy signals
- Build a personal investment alert system or newsletter
- Implement a Buffett/Munger-style stock screener for ATX, DAX, or S&P 500
- Understand how to identify when Mr. Market is being irrational
- Apply margin of safety, moat, float, or circle of competence principles programmatically

**Domain tags:** `warren-buffett` `charlie-munger` `value-investing` `margin-of-safety` `moat` `insurance-float` `mr-market` `intrinsic-value` `macro-indicators` `stock-screener` `early-warning-system` `atx` `dax` `sp500` `quality-investing` `long-term-investing` `contrarian-investing`

---

## 1. Investment Philosophy This System Implements

Understanding the philosophy is essential for extending or modifying this system correctly. Every design decision — which indicators to monitor, which stocks appear on the watchlist, what constitutes a buy signal — is grounded in specific Buffett/Munger principles.

### Warren Buffett's Core Principles (as implemented here)

**Mr. Market:** Benjamin Graham's allegory, adopted by Buffett — the market is a manic-depressive business partner who offers to buy or sell shares every day at wildly varying prices. The prices reflect Mr. Market's mood, not business value. When Mr. Market is panicking, he sells good businesses cheap. This system watches for those panics.

**Intrinsic Value vs. Price:** A business has an intrinsic value (the present value of all future cash flows) that is independent of its stock price. When price falls well below intrinsic value — due to macro panic, not business deterioration — that gap is the profit for the patient investor.

**Margin of Safety:** Never pay full price for intrinsic value. Buy with a buffer. In this system, the `amber` threshold is "approaching margin of safety territory" and the `red` threshold is "clear margin of safety present." The signal colors are green (go) precisely because a triggered threshold means sufficient discount exists.

**Circle of Competence:** Buffett only buys businesses he deeply understands. The watchlist is intentionally narrow and concentrated in two sectors where the owner-investor logic is extremely clear: insurance (float) and banking (deposit spread). No tech, no biotech, no companies with unpredictable competitive dynamics.

**Insurance Float:** Insurance companies collect premiums before paying claims. This "float" — money held but not yet owed — can be invested. A well-run insurer earns investment returns on someone else's money at zero cost, or even negative cost if the underwriting is profitable. Allianz, Munich Re, Hannover Rück, Cincinnati Financial, Chubb, Travelers, Progressive, and Vienna Insurance Group are on this watchlist because they have decades of demonstrated float discipline.

**Franchise / Economic Moat:** Buffett seeks businesses where the competitive position is durable — pricing power that compounds over time. Reinsurers have oligopoly pricing after catastrophes. Regional banks have switching-cost moats. Deutsche Börse has an infrastructure monopoly. Andritz has global niche leadership in industrial machinery. The watchlist stocks were selected for measurable moat evidence.

**Buy and Hold Through Panic:** Buffett famously does not sell quality businesses during market panics — he buys more. This system is designed to surface exactly those moments: when price falls while the business is unchanged.

### Charlie Munger's Core Principles (as implemented here)

**Inversion:** Munger asks "what would make this go wrong?" before asking "what would make this go right?" Applied here: before flagging a stock as cheap, the system checks whether the price drop reflects a genuine business deterioration (never flagged) or a macro/sector contagion event (flagged as opportunity).

**Price Discipline — Never Chase:** Munger's famous line: "A great business at a fair price is superior to a fair business at a great price." The weekly screener implements this literally: a stock must be ≥10% below its 52-week high (Munger signal) *and* have a P/E below Buffett's buy threshold. If a stock is at its 52-week high, it is never flagged regardless of how strong the business is.

**Sit on Your Hands:** Most of the time, the right answer is to do nothing. The system is silent when all indicators are green. This is intentional — it reflects Munger's view that great investors make very few decisions and wait for the obvious ones.

**Lollapalooza Effect:** Munger's term for when multiple independent factors converge to produce an outsized result. The `★★★ STRONG BUY` signal in the weekly screener fires only when both the Buffett P/E signal and the Munger drawdown signal align — a small-scale lollapalooza requiring two independent confirmations.

**First-Principles Thinking:** Munger insists on understanding the actual mechanics, not just following rules. The `why_discount` field in each indicator is the first-principles explanation of why the specific stocks in `stocks[]` are being sold cheaply *and* why the business is actually unaffected.

### Why Insurance and Banking Specifically

Buffett has said that if he were managing a small portfolio today, he would concentrate in insurance companies. The reasons are implementable as signals:

1. **Float is leverage at zero cost.** When the market panics, insurance stock prices fall but the float does not — the business engine keeps running at full capacity.
2. **Catastrophe events are buyable.** Hurricane landfalls, banking crises, Iran escalations — these are one-time shocks that temporarily depress prices but often *improve* the multi-year pricing environment for insurers.
3. **Valuation is simple.** P/E and P/B are sufficient valuation tools for insurance and banking because their earnings are relatively straightforward to interpret. No DCF model required.
4. **European insurers add diversification.** Allianz and Munich Re are priced on the DAX, denominated in EUR, and primarily exposed to European/global risk. They provide geographic and currency diversification from US positions.

---

## 2. What This Project Is

**QC Monitor** is a private investment newsletter infrastructure built on the principles of Warren Buffett and Charlie Munger. It monitors macroeconomic indicators daily, identifies when quality stocks in the ATX (Vienna), DAX (Frankfurt), and S&P 500 (New York) are being sold below intrinsic value due to macro events unrelated to their business fundamentals, and sends alerts to subscribers.

### Core Investment Logic
The system is **not** a trading bot. It is a signal system based on this thesis:

> "When macro events cause panic, institutional investors sell everything liquid — including high-quality insurance and banking stocks that have no exposure to the triggering event. The panic-driven discount is the buying opportunity."

A "buy signal" is triggered when a macro indicator (e.g., VIX spiking above 30) suggests that specific quality stocks are being sold for non-fundamental reasons. The signal says: *these stocks are probably cheap right now, look closer.*

### Signal Color Convention (important — inverted from conventional traffic lights)
The color system is intentionally inverted from typical "danger = red" conventions:
- ⚪ `"green"` level = **NORMAL** — no alert, indicator in safe range
- 🟡 `"amber"` level = **BEOBACHTEN** (Watch) — approaching buy threshold
- 🟢 `"red"` level = **KAUFSIGNAL** (Buy Signal) — threshold crossed, stocks cheap for wrong reasons

**Rationale**: A triggered buy signal is a *positive opportunity*, not a danger. Displaying it as green (go) aligns the UI with investor intent.

---

## 2. Repository Structure

```
QC_Monitor/
├── AGENTS.md                          ← you are here
├── README.md                          ← human-readable project overview
├── .gitignore                         ← excludes all credentials and generated files
│
├── scripts/
│   ├── market_monitor.py              ← PRIMARY SCRIPT: daily macro monitor
│   ├── weekly_screener.py             ← weekly Buffett/Munger stock screener
│   └── fill_dax.py                    ← one-time helper, ignore unless fixing DAX data
│
├── config/
│   ├── monitor_config.json            ← GITIGNORED: live credentials (Gmail, Telegram)
│   ├── monitor_config.example.json    ← committed template — copy to monitor_config.json
│   └── known_subscribers.json        ← GITIGNORED: tracks who received welcome email
│
├── data/
│   └── indicator_history.csv          ← appended daily, all-time indicator readings
│
├── logs/                              ← GITIGNORED directory, created at runtime
│   ├── monitor_log.txt                ← market_monitor.py runtime log
│   └── screener_log.txt               ← weekly_screener.py runtime log
│
└── website/
    ├── index.html                     ← static landing page (never auto-modified)
    └── status.html                    ← GITIGNORED: regenerated on every monitor run
```

---

## 3. Primary Script: `scripts/market_monitor.py`

### Path Constants
All paths derive from `BASE_DIR = Path(__file__).parent.parent` (i.e., `QC_Monitor/`):
```python
CFG_PATH         = BASE_DIR / "config" / "monitor_config.json"
LOG_PATH         = BASE_DIR / "logs"   / "monitor_log.txt"
CSV_PATH         = BASE_DIR / "data"   / "indicator_history.csv"
SUBSCRIBERS_PATH = BASE_DIR / "config" / "known_subscribers.json"
STATUS_PATH      = BASE_DIR / "website" / "status.html"
```

### Execution Flow (`main()`)
```
1. Load monitor_config.json
2. check_and_welcome_new_subscribers(cfg)   ← welcome email to any new BCC addresses
3. fetch_price_data()                       ← yfinance bulk download, 1 year of daily closes
4. evaluate(closes)                         ← returns (alerts, all_statuses, raw)
5. if alerts:
     build_subject(alerts)                  ← ASCII-only subject line
     build_html(alerts)                     ← rich HTML email
     build_telegram_message(alerts,         ← compact HTML for Telegram Bot API
                            all_statuses)
     send_email(cfg, subject, html)
     send_telegram(cfg, tg_msg)
6. write_to_csv(raw, alert_sent)            ← always, green or not
7. generate_status_html(all_statuses, raw)  ← always, overwrites website/status.html
```

### Key Data Structures

**`all_statuses`** — list of dicts, one per indicator (including green ones):
```python
{
    "key":          "US10Y",                     # internal identifier
    "level":        "amber",                     # "green" | "amber" | "red"
    "label":        "US 10-Jahres-Staatsanleihe (Rendite)",  # display name
    "compact":      "4,60% - Gelb ab 4,5%, Rot ab 5,5%",    # German-formatted value + thresholds
    "current":      "4.60",                      # raw display string (for email)
    "threshold":    "Amber >= 4.5 | Red >= 5.5", # threshold string (for email)
    "scenario":     "US-Haushaltsstress — ...",  # what this means for the market
    "why_discount": "Jede Aktie wird ...",        # why stocks get cheap
    "news_url":     "https://news.google.com/...", # Google News search URL
    "stocks":       ["CINF", "CB", "TRV", ...],  # ticker symbols affected
}
```

**`alerts`** — subset of `all_statuses` where `level != "green"`. Same structure.

**`raw`** — flat dict for CSV:
```python
{
    "date": "2026-05-16",
    "vix": 18.43, "vix_level": "green",
    "kre_price": 66.97, "kre_14d_pct": -4.42, "kre_level": "green",
    "qqq_price": 708.93, "qqq_52w_pct": -1.51, "qqq_level": "green",
    "nvda_price": 225.32, "nvda_52w_pct": -4.42, "nvda_level": "green",
    "brent": 109.26, "brent_high_level": "green", "brent_low_level": "green",
    "us10y": 4.59, "us10y_level": "amber",
    "hurricane_max_winds": 0, "hurricane_level": "green",
    "overall_level": "amber",
    "alert_sent": True,
}
```

### The `INDICATORS` Dict
Defined at module level. Each entry drives one threshold check:
```python
INDICATORS = {
    "VIX": {
        "ticker":       "^VIX",          # yfinance symbol
        "label":        "VIX Angst-Index",
        "check":        "above",          # "above" | "below" | "drop_52w" | "drop_14d"
        "amber":        20,
        "red":          30,
        "scenario":     "...",
        "why_discount": "...",
        "news_url":     "https://...",
        "stocks":       ["CB", "CINF", ...],  # tickers shown as discounted
    },
    ...
}
```

**Check types:**
- `"above"` — triggers when `current >= threshold`
- `"below"` — triggers when `current <= threshold`
- `"drop_52w"` — triggers when `(current - 52w_high) / 52w_high * 100 <= threshold` (negative pct)
- `"drop_14d"` — same but reference is price 14 trading days ago

### Ticker Lookup Tables
```python
TICKER_NAMES = {"CB": "Chubb", "CINF": "Cincinnati Financial", ...}  # ticker → full name
TICKER_INDEX = {"CB": "S&P 500", "ALV": "DAX", "EBS": "ATX", ...}    # ticker → exchange
INDICATOR_UNITS = {"VIX": "", "US10Y": "%", "BRENT_HIGH": " $", ...}  # for compact display
BUY_TARGETS = {"CB": {"name": "Chubb", "curr": 11.45, "amber": 10.0, "red": 8.0}, ...}  # P/E targets for email table
```

### Number Formatting
All user-facing numbers use German decimal convention (comma as decimal separator):
```python
def _de_num(val, decimals=2):  # 4.6 → "4,60"
def _de_thr(val, unit=""):     # 4.5, "%" → "4,5%"
```

### Email
- Sent via Gmail SMTP SSL port 465
- Subject: ASCII-only (no emoji, no special chars) — prevents Windows charmap errors
- Body: UTF-8 HTML via `MIMEText(html_body, "html", "utf-8")`
- Sending: `server.send_message(msg)` — NOT `sendmail(msg.as_string())` (causes encoding crash on Windows)
- BCC: set via `msg["Bcc"] = ", ".join(bcc_list)` — `send_message()` handles delivery and strips header
- BCC list: `cfg["email"]["bcc"]` — list of strings in `monitor_config.json`

### Telegram
- Bot API: `POST https://api.telegram.org/bot{token}/sendMessage`
- `parse_mode: "HTML"` — only supports `<b>`, `<i>`, `<a>`, `<code>` tags
- **All dynamic content must be `html.escape()`d** before inserting into tags
- Graceful skip if `bot_token` or `chat_id` not configured

### Welcome Email System
- `check_and_welcome_new_subscribers(cfg)` runs before every monitor run
- Compares `cfg["email"]["bcc"]` against `known_subscribers.json`
- Sends `build_welcome_html()` to new addresses only
- Updates `known_subscribers.json` after sending
- Stefan's own email is pre-loaded in `known_subscribers.json` — never gets a welcome email
- **Adding a subscriber**: add their email to the `bcc` array in `monitor_config.json`

### Status Page
- `generate_status_html(all_statuses, raw)` runs on every monitor execution
- Writes complete standalone HTML to `website/status.html`
- Shows: overall signal banner with timestamp, all indicators with current values, buy opportunities grouped by index (S&P 500 / DAX / ATX), CTA to subscribe, legal disclaimer
- Gitignored — committed version would always be stale

---

## 4. Secondary Script: `scripts/weekly_screener.py`

### Execution Flow
```
1. Load monitor_config.json
2. For each stock in WATCHLIST:
     fetch trailing P/E, P/B, dividend yield via yf.Ticker(t).info
     fetch 52-week high via yf.download()
     score_pe()       → "red_buy" | "amber_buy" | "watch" | "fair" | "n/a"
     score_drawdown() → "compelling" | "interesting" | "watch" | "fair"
     consensus_signal() → "★★★ STRONG BUY" | "★★ BUY" | "★ WATCH" | "—"
3. build_html_report()  ← full HTML table with all 24 stocks
4. send_email()         ← same SMTP setup as market_monitor.py
5. write_to_csv()       ← appends to data/screener_history.csv
```

### WATCHLIST Structure
```python
WATCHLIST = {
    "EBS.VI": {"name": "Erste Group Bank", "index": "ATX", "amber": 4.5, "red": 3.5, "note": "..."},
    "ALV.DE": {"name": "Allianz SE",       "index": "DAX", "amber": 8.0, "red": 6.5, "note": "..."},
    "CINF":   {"name": "Cincinnati Financial", "index": "S&P500", "amber": 8.5, "red": 7.0, "note": "..."},
    ...
}
```
Note: Vienna exchange tickers use `.VI` suffix, Frankfurt use `.DE`, US stocks have no suffix.

### Buffett Signal (P/E)
- `pe_score = "red_buy"` when trailing P/E ≤ `red` threshold
- `pe_score = "amber_buy"` when trailing P/E ≤ `amber` threshold
- Uses live trailing P/E from `yf.Ticker(t).info["trailingPE"]`

### Munger Signal (Price Discipline)
- `drawdown_score = "compelling"` when price ≥ 20% below 52-week high
- `drawdown_score = "interesting"` when price ≥ 10% below 52-week high
- Never chases — won't buy at 52-week highs regardless of P/E

### Consensus
- `★★★ STRONG BUY`: both Buffett red + Munger compelling
- `★★ BUY`: Buffett amber/red + Munger interesting/compelling
- `★ WATCH`: either signal weakly positive
- `—`: no signal

---

## 5. Configuration: `config/monitor_config.json`

**GITIGNORED.** Use `monitor_config.example.json` as template.

```json
{
  "telegram": {
    "bot_token": "...",
    "chat_id":   "..."
  },
  "email": {
    "sender":       "your@gmail.com",
    "recipient":    "your@gmail.com",
    "bcc":          ["subscriber1@example.com"],
    "app_password": "xxxx xxxx xxxx xxxx",
    "smtp_host":    "smtp.gmail.com",
    "smtp_port":    465
  },
  "thresholds": {
    "vix_amber": 20, "vix_red": 30,
    "kre_drop_amber_pct": -10, "kre_drop_red_pct": -15,
    "qqq_drop_amber_pct": -10, "qqq_drop_red_pct": -20,
    "nvda_drop_amber_pct": -20, "nvda_drop_red_pct": -35,
    "brent_high_amber": 120, "brent_high_red": 130,
    "brent_low_amber": 80, "brent_low_red": 70,
    "us10y_amber": 4.5, "us10y_red": 5.5,
    "hurricane_amber_mph": 74, "hurricane_red_mph": 111
  }
}
```

Note: `thresholds` in `monitor_config.json` are loaded but currently the scripts use hardcoded values in `INDICATORS`. The thresholds block is reserved for future dynamic override support.

---

## 6. How To Extend

### Add a new macro indicator
1. Add an entry to `INDICATORS` in `market_monitor.py`:
   ```python
   "NEW_KEY": {
       "ticker": "SYMBOL",  # yfinance symbol
       "label": "German display name",
       "check": "above",    # or "below", "drop_52w", "drop_14d"
       "amber": ...,
       "red": ...,
       "scenario": "Was das bedeutet...",
       "why_discount": "Warum Aktien günstiger werden...",
       "news_url": "https://news.google.com/search?q=...",
       "stocks": ["TICKER1", "TICKER2", ...],
   }
   ```
2. Add CSV columns for it to `CSV_COLUMNS`.
3. Add raw value accumulation in the `evaluate()` elif block.
4. Add a unit to `INDICATOR_UNITS` if needed.

### Add a new stock to alerts
1. Add to `TICKER_NAMES`: `"XYZ": "Full Company Name"`
2. Add to `TICKER_INDEX`: `"XYZ": "DAX"` (or `"S&P 500"` / `"ATX"`)
3. Add to relevant `INDICATORS[key]["stocks"]` lists where the stock would be unfairly sold
4. Optionally add to `BUY_TARGETS` with P/E target levels

### Add a stock to the weekly screener
Add to `WATCHLIST` in `weekly_screener.py`:
```python
"TICKER": {
    "name":  "Full Company Name",
    "index": "ATX",   # "ATX" | "DAX" | "S&P500"
    "amber": 10.0,    # P/E where Buffett starts watching
    "red":   8.0,     # P/E where Buffett buys aggressively
    "note":  "Why this stock belongs on the list",
}
```
Vienna Stock Exchange tickers require `.VI` suffix (e.g., `"VIG.VI"`).
Frankfurt tickers require `.DE` suffix (e.g., `"ALV.DE"`).
US tickers have no suffix.

### Add a newsletter subscriber
Edit `config/monitor_config.json` (local, gitignored):
```json
"bcc": ["new.subscriber@example.com"]
```
On the next run, `check_and_welcome_new_subscribers()` automatically sends them the welcome email and records them in `known_subscribers.json`.

---

## 7. Known Constraints and Gotchas

| Constraint | Detail |
|------------|--------|
| **Windows encoding** | `server.sendmail(msg.as_string())` crashes on Windows with umlauts/emoji. Always use `server.send_message(msg)` with `MIMEText(body, "html", "utf-8")`. |
| **Email subject** | Must be ASCII-only. Any emoji or `—` in the subject line causes charmap encoding error. |
| **Telegram HTML** | Only `<b>`, `<i>`, `<a>`, `<code>` tags supported. Always `html.escape()` dynamic content. |
| **yfinance rate limits** | `yf.download()` for all tickers at once is faster and less likely to be throttled than individual calls. Per-ticker `.info` calls (for P/E, P/B) in the weekly screener add a `time.sleep(0.3)` delay. |
| **BRENT double entry** | `BZ=F` appears in both `BRENT_HIGH` and `BRENT_LOW` indicators. The price is downloaded once via yfinance but evaluated against two separate threshold sets. CSV writes `brent` price once (from `BRENT_HIGH`) and both level flags. |
| **Hurricane off-season** | `check_atlantic_hurricanes()` returns `[]` outside months 6–11. Hurricane is only added to `all_statuses` during hurricane season. |
| **`status.html` in .gitignore** | Generated on every run. Never commit it — it would be stale within 24 hours. |
| **Nested git repo** | `QC_Monitor/` has its own `.git` and lives inside the larger `business-mentors/` repo. The outer repo sees it as an opaque directory (not tracked unless added as a submodule). This is intentional. |
| **Thresholds source of truth** | `INDICATORS` dict in `market_monitor.py` is the source of truth, not `monitor_config.json["thresholds"]`. The config thresholds block is documentation/future use only. |
| **German language** | All user-facing output (email, Telegram, website) is in German. Numbers use German decimal convention: comma as decimal separator (`4,60`), not dot. Use `_de_num()` and `_de_thr()` helpers for formatting. |
| **No long dashes** | Em dashes (`—`) are forbidden in all output strings. Use regular hyphens with spaces (` - `) instead. Windows encoding can mishandle em dashes in certain contexts. |

---

## 8. External Services and APIs

| Service | How used | Config key |
|---------|----------|------------|
| **Yahoo Finance (yfinance)** | All market data. Free, no API key. | n/a |
| **NOAA NHC** | Atlantic hurricane feed: `https://www.nhc.noaa.gov/activestorms.xml` | n/a |
| **Gmail SMTP** | Email delivery. Requires App Password (not account password). | `email.app_password` |
| **Telegram Bot API** | Push notifications. Requires bot token from @BotFather + chat_id. | `telegram.bot_token`, `telegram.chat_id` |

---

## 9. Scheduling (Windows)

Both scripts are designed for Windows Task Scheduler. Scheduling commands are at the bottom of each script file.

- `market_monitor.py` — daily, 08:00, `StartWhenAvailable` (catches up if PC was off)
- `weekly_screener.py` — weekly, Monday 07:00, `StartWhenAvailable`

---

## 10. Dependencies

```
yfinance>=0.2
requests>=2.28
```
Both in Python standard library: `smtplib`, `ssl`, `json`, `csv`, `logging`, `xml.etree.ElementTree`, `html`, `pathlib`, `datetime`

Install: `pip install yfinance requests`

---

## 11. Test / Dry Run

To test without waiting for a signal:
```bash
# Force a Telegram + email test run (current market state, sends if signals exist):
python scripts/market_monitor.py

# Weekly screener:
python scripts/weekly_screener.py
```

There is no `--dry-run` flag. To test formatting without sending, temporarily comment out `send_email()` and `send_telegram()` calls in `main()`.

---

## 12. File the Agent Should Edit Most Often

| Task | File | Section |
|------|------|---------|
| Add/modify indicator | `scripts/market_monitor.py` | `INDICATORS` dict (line ~95) |
| Add stock to monitor | `scripts/market_monitor.py` | `TICKER_NAMES`, `TICKER_INDEX`, `BUY_TARGETS`, relevant `INDICATORS[x]["stocks"]` |
| Add stock to screener | `scripts/weekly_screener.py` | `WATCHLIST` dict |
| Change alert thresholds | `scripts/market_monitor.py` | `INDICATORS[key]["amber"]` / `["red"]` |
| Change email content | `scripts/market_monitor.py` | `build_html()` |
| Change Telegram content | `scripts/market_monitor.py` | `build_telegram_message()` |
| Change welcome email | `scripts/market_monitor.py` | `build_welcome_html()` |
| Change status page layout | `scripts/market_monitor.py` | `generate_status_html()` |
| Change landing page | `website/index.html` | direct HTML edit |
| Add subscriber | `config/monitor_config.json` | `email.bcc` array |
