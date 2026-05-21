#!/usr/bin/env python3
"""
Weekly Stock Screener — ATX | DAX | S&P 500
Buffett & Munger Consensus Buy-Signal Detection

Runs weekly (Monday morning). Flags stocks where BOTH Buffett (valuation) and
Munger (price discipline) agree an entry makes sense:
  Buffett signal : live trailing P/E ≤ amber or red buy threshold
  Munger signal  : price ≥ 10% below its 52-week high (not chasing)

All readings logged to screener_history.csv for time-series analysis.
Sends a weekly email via Gmail — uses the same monitor_config.json.
If App Password is not yet configured, prints a console summary instead.

Setup:
  1. pip install yfinance
  2. Add Gmail App Password to monitor_config.json (shared with market_monitor.py)
  3. Schedule via Windows Task Scheduler (see bottom of this file)
"""

import csv
import json
import logging
import smtplib
import ssl
import time
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yfinance as yf

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent        # QC_Monitor/
CFG_PATH = BASE_DIR / "config" / "monitor_config.json"
LOG_PATH = BASE_DIR / "logs"   / "screener_log.txt"
CSV_PATH = BASE_DIR / "data"   / "screener_history.csv"

CSV_COLUMNS = [
    "date", "ticker", "name", "index",
    "price", "trailing_pe", "pe_amber", "pe_red", "pe_score",
    "high_52w", "drawdown_pct", "drawdown_score",
    "consensus", "div_yield_pct", "pb_ratio",
]

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ── Watchlist ─────────────────────────────────────────────────────────────────
# amber = P/E where Buffett starts accumulating
# red   = P/E where Buffett buys aggressively
# note  = why this stock is on the watchlist at all
WATCHLIST = {
    # ── ATX (Vienna Stock Exchange) ───────────────────────────────────────────
    "EBS.VI": {
        "name": "Erste Group Bank",       "index": "ATX",
        "amber": 4.5, "red": 3.5,
        "note": "CEE banking franchise; deposit float; conservative capital ratios",
    },
    "VIG.VI": {
        "name": "Vienna Insurance Group", "index": "ATX",
        "amber": 9.0, "red": 7.5,
        "note": "Insurance float; CEE dominance; 30-year underwriting track record",
    },
    "OMV.VI": {
        "name": "OMV AG",                 "index": "ATX",
        "amber": 6.5, "red": 5.0,
        "note": "Integrated energy; cyclical — watch only; limited Buffett franchise score",
    },
    "RBI.VI": {
        "name": "Raiffeisen Bank Int'l",  "index": "ATX",
        "amber": 4.0, "red": 3.0,
        "note": "CEE franchise; Russia exposure = quality discount; Buffett cautious",
    },
    "ANDR.VI": {
        "name": "Andritz AG",             "index": "ATX",
        "amber": 11.5, "red": 9.5,
        "note": "Capital goods; strong order book moat; pulp/hydro global leader",
    },
    "EVN.VI": {
        "name": "EVN AG",                 "index": "ATX",
        "amber": 10.5, "red": 8.5,
        "note": "Austrian regulated utility; predictable cash flow; infrastructure moat",
    },

    # ── DAX (Frankfurt) ───────────────────────────────────────────────────────
    "ALV.DE": {
        "name": "Allianz SE",             "index": "DAX",
        "amber": 8.0, "red": 6.5,
        "note": "Buffett & Munger DAX #1; global insurance float; asset management arm",
    },
    "MUV2.DE": {
        "name": "Munich Re",              "index": "DAX",
        "amber": 10.0, "red": 8.5,
        "note": "Munger's DAX #1; global reinsurance oligopoly; gold-standard underwriting",
    },
    "HNR1.DE": {
        "name": "Hannover Rück",          "index": "DAX",
        "amber": 11.0, "red": 9.0,
        "note": "Third global reinsurer; conservative capital; proven through cycles",
    },
    "DB1.DE": {
        "name": "Deutsche Börse",         "index": "DAX",
        "amber": 17.0, "red": 14.0,
        "note": "Exchange infrastructure monopoly; Iran War raises derivatives volumes",
    },
    "DHL.DE": {
        "name": "DHL Group",              "index": "DAX",
        "amber": 10.0, "red": 8.0,
        "note": "Global logistics network moat; Munger: infrastructure + switching costs",
    },
    "RWE.DE": {
        "name": "RWE AG",                 "index": "DAX",
        "amber": 6.5, "red": 5.0,
        "note": "European utility; energy transition capex risk; Munger: regulated returns",
    },

    # ── S&P 500 ───────────────────────────────────────────────────────────────
    "CINF": {
        "name": "Cincinnati Financial",   "index": "S&P500",
        "amber": 8.5, "red": 7.0,
        "note": "Buffett #1 insurance pick; 65-year dividend streak; agent loyalty moat",
    },
    "TRV": {
        "name": "Travelers",              "index": "S&P500",
        "amber": 8.0, "red": 6.5,
        "note": "Buffett-held; strict underwriting discipline; Berkshire-like culture",
    },
    "CB": {
        "name": "Chubb",                  "index": "S&P500",
        "amber": 10.0, "red": 8.0,
        "note": "Evan Greenberg; premium global franchise; catastrophe expertise",
    },
    "PGR": {
        "name": "Progressive",            "index": "S&P500",
        "amber": 9.0, "red": 7.5,
        "note": "Telematics flywheel moat; Munger: best data wins; unassailable lead",
    },
    "ACGL": {
        "name": "Arch Capital Group",     "index": "S&P500",
        "amber": 6.5, "red": 5.5,
        "note": "Counter-cyclical discipline; contracts in soft markets; 25-year proof",
    },
    "USB": {
        "name": "U.S. Bancorp",           "index": "S&P500",
        "amber": 10.0, "red": 8.0,
        "note": "Buffett's preferred bank; pure retail/commercial; no investment banking",
    },
    "MTB": {
        "name": "M&T Bank",               "index": "S&P500",
        "amber": 10.0, "red": 8.0,
        "note": "Conservative community bank DNA; Munger: aligned ownership culture",
    },
    "WFC": {
        "name": "Wells Fargo",            "index": "S&P500",
        "amber": 9.5, "red": 8.0,
        "note": "Asset cap removed early 2025; franchise recovery play; Buffett still holds",
    },
    "AFL": {
        "name": "Aflac Inc.",             "index": "S&P500",
        "amber": 9.0, "red": 7.5,
        "note": "Supplemental insurance niche; Japan franchise; float model; Buffett approved",
    },
    "WRB": {
        "name": "W.R. Berkley",           "index": "S&P500",
        "amber": 12.0, "red": 10.0,
        "note": "Decentralised underwriting; Munger: entrepreneurial culture preserved",
    },
    "CME": {
        "name": "CME Group",              "index": "S&P500",
        "amber": 20.0, "red": 17.0,
        "note": "Exchange oligopoly; volatility = revenue; Iran War raises futures volumes",
    },
    "ADP": {
        "name": "ADP",                    "index": "S&P500",
        "amber": 25.0, "red": 20.0,
        "note": "Munger: switching-cost franchise not tech; 40M employees on platform",
    },
    "BR": {
        "name": "Broadridge Financial",   "index": "S&P500",
        "amber": 27.0, "red": 22.0,
        "note": "Munger: market infrastructure; 98% client retention; Buffett would skip",
    },
}


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_pe(trailing_pe, amber, red):
    """Compare live P/E against Buffett buy thresholds."""
    if trailing_pe is None:
        return "n/a"
    if trailing_pe <= red:
        return "red_buy"
    if trailing_pe <= amber:
        return "amber_buy"
    if trailing_pe <= amber * 1.25:
        return "watch"
    return "fair"


def score_drawdown(drawdown_pct):
    """
    Score how far the stock is below its 52-week high.
    Munger buys quality at a discount — he won't chase a stock near its high.
    drawdown_pct is negative (e.g. -18.5 means 18.5% below 52w high).
    """
    if drawdown_pct is None:
        return "fair"
    if drawdown_pct <= -20.0:
        return "compelling"    # >20% off high — Munger strongly interested
    if drawdown_pct <= -10.0:
        return "interesting"   # 10-20% off — Munger interested
    if drawdown_pct <= -5.0:
        return "watch"         # 5-10% off — getting there
    return "fair"              # <5% off — Munger would wait


def consensus_signal(pe_score, drawdown_score):
    """
    Both agree to buy = Buffett sees good valuation AND Munger sees a real discount.
    Strong buy = Buffett red_buy + Munger compelling/interesting.
    Buy        = Buffett amber_buy + Munger interesting/compelling.
    Watch      = one criterion met, the other approaching.
    """
    if pe_score == "red_buy" and drawdown_score in ("compelling", "interesting"):
        return "★★★ STRONG BUY"
    if pe_score == "amber_buy" and drawdown_score in ("compelling", "interesting"):
        return "★★ BUY"
    if pe_score == "red_buy" and drawdown_score == "watch":
        return "★★ BUY"
    if pe_score == "amber_buy" and drawdown_score == "watch":
        return "★ WATCH"
    if pe_score == "watch" and drawdown_score in ("compelling", "interesting"):
        return "★ WATCH"
    return "—"


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_screener_data():
    """
    Fetch price history (bulk — fast) and fundamentals (per-ticker — slower).
    Returns a list of result dicts, one per watchlist stock.
    """
    tickers = list(WATCHLIST.keys())
    log.info(f"Downloading 1-year price history for {len(tickers)} tickers")

    raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False)
    closes = raw["Close"] if hasattr(raw.columns, "levels") else raw[["Close"]]

    results = []
    for ticker, meta in WATCHLIST.items():
        record = {
            "date":           date.today().isoformat(),
            "ticker":         ticker,
            "name":           meta["name"],
            "index":          meta["index"],
            "note":           meta["note"],
            "pe_amber":       meta["amber"],
            "pe_red":         meta["red"],
            "price":          None,
            "trailing_pe":    None,
            "high_52w":       None,
            "drawdown_pct":   None,
            "div_yield_pct":  None,
            "pb_ratio":       None,
            "pe_score":       "n/a",
            "drawdown_score": "fair",
            "consensus":      "—",
        }

        # Price + 52-week high from bulk download
        col = ticker if ticker in closes.columns else None
        if col is not None:
            series = closes[col].dropna()
            if not series.empty:
                record["price"]    = round(float(series.iloc[-1]), 2)
                record["high_52w"] = round(float(series.max()), 2)
                if record["high_52w"]:
                    record["drawdown_pct"] = round(
                        (record["price"] - record["high_52w"]) / record["high_52w"] * 100, 1
                    )

        # Fundamentals from ticker.info — one retry on failure
        for attempt in range(2):
            try:
                info = yf.Ticker(ticker).info
                pe = info.get("trailingPE") or info.get("forwardPE")
                record["trailing_pe"]  = round(float(pe), 2) if pe else None
                dy = info.get("dividendYield")
                record["div_yield_pct"] = round(float(dy) * 100, 2) if dy else None
                pb = info.get("priceToBook")
                record["pb_ratio"]     = round(float(pb), 2) if pb else None
                break
            except Exception as exc:
                if attempt == 0:
                    time.sleep(2)
                else:
                    log.warning(f"{ticker}: info fetch failed — {exc}")

        record["pe_score"]       = score_pe(record["trailing_pe"], meta["amber"], meta["red"])
        record["drawdown_score"] = score_drawdown(record["drawdown_pct"])
        record["consensus"]      = consensus_signal(record["pe_score"], record["drawdown_score"])

        results.append(record)
        log.info(
            f"{ticker:8s}  P/E={record['trailing_pe']} ({record['pe_score']:10s})  "
            f"Drop={record['drawdown_pct']}% ({record['drawdown_score']:11s})  "
            f"→ {record['consensus']}"
        )

    return results


# ── CSV logger ────────────────────────────────────────────────────────────────

def write_to_csv(results):
    """Append this week's readings — one row per stock."""
    file_exists = CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for r in results:
            writer.writerow(r)
    log.info(f"CSV: {len(results)} rows written for {date.today()}")


# ── Email builder ─────────────────────────────────────────────────────────────

CONSENSUS_COLOR = {
    "★★★ STRONG BUY": "#dc2626",
    "★★ BUY":         "#f59e0b",
    "★ WATCH":        "#3b82f6",
    "—":              "#e5e7eb",
}
CONSENSUS_BG = {
    "★★★ STRONG BUY": "#fee2e2",
    "★★ BUY":         "#fef3c7",
    "★ WATCH":        "#eff6ff",
    "—":              "#f9fafb",
}

TABLE_HEADER = """
<tr style="background:{hdr_color};color:white">
  <th style="padding:7px 10px;text-align:left">Ticker</th>
  <th style="padding:7px 10px;text-align:left">Unternehmen</th>
  <th style="padding:7px 10px;text-align:center">KGV</th>
  <th style="padding:7px 10px;text-align:center">Gelb-Ziel</th>
  <th style="padding:7px 10px;text-align:center">Rot-Ziel</th>
  <th style="padding:7px 10px;text-align:center">vs. 52W-Hoch</th>
  <th style="padding:7px 10px;text-align:center">Div.-Rendite</th>
  <th style="padding:7px 10px;text-align:center">KBV</th>
  <th style="padding:7px 10px;text-align:center">Signal</th>
</tr>"""


def stock_row(r, bg="white"):
    c   = CONSENSUS_COLOR.get(r["consensus"], "#e5e7eb")
    pe  = f"{r['trailing_pe']:.1f}x" if r["trailing_pe"] else "—"
    pb  = f"{r['pb_ratio']:.1f}x"    if r["pb_ratio"]    else "—"
    dy  = f"{r['div_yield_pct']:.1f}%" if r["div_yield_pct"] else "—"
    dd  = f"{r['drawdown_pct']:+.1f}%" if r["drawdown_pct"] is not None else "—"
    sig = (
        f"<span style='font-weight:bold;color:{c}'>{r['consensus']}</span>"
        if r["consensus"] != "—" else "—"
    )
    return (
        f"<tr style='background:{bg}'>"
        f"<td style='padding:5px 10px;font-weight:bold'>{r['ticker']}</td>"
        f"<td style='padding:5px 10px'>{r['name']}</td>"
        f"<td style='padding:5px 10px;text-align:center'>{pe}</td>"
        f"<td style='padding:5px 10px;text-align:center;color:#b45309'>{r['pe_amber']:.1f}x</td>"
        f"<td style='padding:5px 10px;text-align:center;color:#dc2626;font-weight:bold'>{r['pe_red']:.1f}x</td>"
        f"<td style='padding:5px 10px;text-align:center'>{dd}</td>"
        f"<td style='padding:5px 10px;text-align:center'>{dy}</td>"
        f"<td style='padding:5px 10px;text-align:center'>{pb}</td>"
        f"<td style='padding:5px 10px;text-align:center'>{sig}</td>"
        f"</tr>"
    )


def buy_zone_section(results):
    strong = [r for r in results if r["consensus"] == "★★★ STRONG BUY"]
    buy    = [r for r in results if r["consensus"] == "★★ BUY"]
    watch  = [r for r in results if r["consensus"] == "★ WATCH"]

    if not strong and not buy and not watch:
        return """
        <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:16px;margin:20px 0">
          <strong style="color:#16a34a">Alle beobachteten Aktien über den Kaufschwellenwerten diese Woche.</strong><br>
          <span style="color:#374151;font-size:14px">
            Keine aktuellen Kaufsignale. Der Screener läuft weiter — du wirst benachrichtigt, wenn Signale erscheinen.
          </span>
        </div>"""

    def card(color, bg, title, rows_html):
        hdr = TABLE_HEADER.replace("{hdr_color}", color)
        return f"""
        <div style="background:{bg};border:2px solid {color};border-radius:8px;padding:16px;margin:16px 0">
          <div style="font-size:17px;font-weight:bold;color:{color};margin-bottom:12px">{title}</div>
          <table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead>{hdr}</thead><tbody>{rows_html}</tbody>
          </table>
        </div>"""

    out = ""
    if strong:
        rows = "".join(stock_row(r, bg="#fff5f5") for r in strong)
        n = len(strong)
        out += card("#dc2626", "#fee2e2",
                    f"STARKER KAUF - Beide stimmen stark zu ({n} Aktie{'n' if n > 1 else ''})", rows)
    if buy:
        rows = "".join(stock_row(r, bg="#fffbeb") for r in buy)
        n = len(buy)
        out += card("#f59e0b", "#fef3c7",
                    f"KAUF - Buffett und Munger stimmen zu ({n} Aktie{'n' if n > 1 else ''})", rows)
    if watch:
        rows = "".join(stock_row(r, bg="#eff6ff") for r in watch)
        n = len(watch)
        out += card("#3b82f6", "#eff6ff",
                    f"BEOBACHTEN - Wird interessant ({n} Aktie{'n' if n > 1 else ''})", rows)
    return out


def index_table(results, index_name):
    stocks = [r for r in results if r["index"] == index_name]
    if not stocks:
        return ""
    hdr = TABLE_HEADER.replace("{hdr_color}", "#1f2937")
    rows = "".join(stock_row(r, bg=CONSENSUS_BG.get(r["consensus"], "white")) for r in stocks)
    return f"""
    <h3 style="margin:28px 0 8px;color:#1f2937;border-bottom:2px solid #e5e7eb;padding-bottom:6px">
        {index_name}
    </h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>{hdr}</thead><tbody>{rows}</tbody>
    </table>"""


def build_html(results):
    today      = datetime.now().strftime("%A, %d %B %Y")
    buy_count  = sum(1 for r in results if r["consensus"] in ("★★★ STRONG BUY", "★★ BUY"))
    watch_count = sum(1 for r in results if r["consensus"] == "★ WATCH")

    if buy_count:
        hdr_color = "#dc2626" if any(r["consensus"] == "★★★ STRONG BUY" for r in results) else "#f59e0b"
        hdr_title = (
            f"{'STARKER KAUF' if hdr_color == '#dc2626' else 'KAUF'} - "
            f"{buy_count} Aktie{'n' if buy_count > 1 else ''} in der Kaufzone"
        )
    elif watch_count:
        hdr_color = "#3b82f6"
        hdr_title = f"BEOBACHTEN - {watch_count} Aktie{'n' if watch_count > 1 else ''} naehert sich dem Schwellenwert"
    else:
        hdr_color = "#16a34a"
        hdr_title = "ALLES GRUEN - Keine aktuellen Kaufsignale"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#1f2937">

  <div style="background:{hdr_color};color:white;border-radius:8px;padding:18px 22px;margin-bottom:24px">
    <div style="font-size:20px;font-weight:bold">{hdr_title}</div>
    <div style="font-size:14px;margin-top:4px;opacity:.9">
      Wochen-Screener — ATX | DAX | S&amp;P 500 &nbsp;|&nbsp; {today} &nbsp;|&nbsp; {len(results)} Aktien beobachtet
    </div>
  </div>

  <p style="font-size:14px;color:#374151;margin-bottom:4px">
    Aktien, bei denen <strong>beide</strong> — Buffett (Bewertung: KGV unter Kaufschwelle) und Munger
    (Preisdisziplin: Aktie deutlich unter 52-Wochen-Hoch) — einem Einstieg zustimmen würden.
    Konsens = gutes Unternehmen zu fairem bis günstigem Preis, das genügend zurückgekommen ist,
    sodass keiner der beiden das Gefühl hat, einem Kurs hinterherzulaufen.
  </p>

  {buy_zone_section(results)}

  <h2 style="margin:32px 0 8px;color:#1f2937">Vollständige Watchlist nach Index</h2>
  <p style="font-size:13px;color:#6b7280;margin:0 0 4px">
    Alle {len(results)} beobachteten Aktien — aktuelles KGV vs. Kaufziele und Abschlag vom 52-Wochen-Hoch.
  </p>
  {index_table(results, "ATX")}
  {index_table(results, "DAX")}
  {index_table(results, "S&P500")}

  <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:14px 16px;margin-top:24px;font-size:13px;color:#475569">
    <strong>So werden die Signale berechnet</strong><br>
    <strong>Buffett-Signal:</strong> Aktuelles KGV unter Gelb-Ziel = interessant; unter Rot-Ziel = starker Kauf.<br>
    <strong>Munger-Signal:</strong> Kurs mehr als 10% unter 52-Wochen-Hoch = interessant; mehr als 20% = überzeugend.<br>
    <strong>Beide stimmen zu (KAUF):</strong> Buffett Gelb/Rot + Munger interessant/überzeugend.<br>
    KGV-Schwellenwerte basieren auf der Tiefenanalyse vom 15.05.2026.
  </div>

  <div style="margin-top:28px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af">
    Erstellt von weekly_screener.py &nbsp;|&nbsp; {datetime.now().strftime('%H:%M')} &nbsp;|&nbsp;
    Zeitreihendaten gespeichert in screener_history.csv
  </div>

</body>
</html>"""


def build_subject(results):
    strong = sum(1 for r in results if r["consensus"] == "★★★ STRONG BUY")
    buy    = sum(1 for r in results if r["consensus"] == "★★ BUY")
    watch  = sum(1 for r in results if r["consensus"] == "★ WATCH")
    if strong:
        names = ", ".join(r["ticker"] for r in results if r["consensus"] == "★★★ STRONG BUY")
        return f"[Wochen-Screener] STARKER KAUF - {names}"
    if buy:
        names = ", ".join(r["ticker"] for r in results if r["consensus"] == "★★ BUY")
        return f"[Wochen-Screener] KAUF - {names}"
    if watch:
        return f"[Wochen-Screener] Beobachten - {watch} Aktie{'n' if watch > 1 else ''} naeher sich Schwelle"
    return f"[Wochen-Screener] Alles gruen - {date.today()}"


# ── Email sending ─────────────────────────────────────────────────────────────

def send_email(cfg, subject, html_body):
    sender    = cfg["email"]["sender"]
    recipient = cfg["email"]["recipient"]
    bcc_list  = cfg["email"].get("bcc", [])
    password  = cfg["email"]["app_password"]
    host      = cfg["email"].get("smtp_host", "smtp.gmail.com")
    port      = cfg["email"].get("smtp_port", 465)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx) as server:
        server.login(sender, password)
        server.send_message(msg)
    log.info(f"Email sent to {1 + len(bcc_list)} recipient(s): {subject}")


# ── Console summary (when email not configured) ───────────────────────────────

def print_console_summary(results):
    strong = [r for r in results if r["consensus"] == "★★★ STRONG BUY"]
    buy    = [r for r in results if r["consensus"] == "★★ BUY"]
    watch  = [r for r in results if r["consensus"] == "★ WATCH"]

    print(f"\n{'='*65}")
    print(f"  Wochen-Screener -- {date.today()}")
    print(f"{'='*65}")
    for label, stocks in [("[ROT] STARKER KAUF", strong), ("[GELB] KAUF", buy), ("[BLAU] BEOBACHTEN", watch)]:
        if stocks:
            print(f"\n  {label} ({len(stocks)}):")
            for r in stocks:
                pe  = f"KGV={r['trailing_pe']}" if r["trailing_pe"] else "KGV=n/a"
                dd  = f"Abschlag={r['drawdown_pct']}%" if r["drawdown_pct"] is not None else "Abschlag=n/a"
                print(f"     {r['ticker']:8s}  {r['name']:<30s}  {pe:14s}  {dd}")
    if not strong and not buy and not watch:
        print("\n  Alles gruen -- keine aktuellen Kaufsignale.")
    print(f"\n  Daten gespeichert in: {CSV_PATH}")
    print(f"{'='*65}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Weekly screener run started ===")

    cfg = None
    email_enabled = False
    if CFG_PATH.exists():
        with open(CFG_PATH) as f:
            cfg = json.load(f)
        if cfg["email"]["app_password"] != "YOUR_GMAIL_APP_PASSWORD_HERE":
            email_enabled = True
        else:
            print("Gmail App Password not yet configured — printing to console only.")
    else:
        print(f"Config not found ({CFG_PATH}) — printing to console only.")

    try:
        results = fetch_screener_data()
    except Exception as exc:
        log.error(f"Screener run failed: {exc}")
        print(f"Error: {exc}")
        return

    write_to_csv(results)

    subject = build_subject(results)
    html    = build_html(results)

    if email_enabled:
        try:
            send_email(cfg, subject, html)
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] Email sent: {subject}")
        except Exception as exc:
            log.error(f"Email failed: {exc}")
            print(f"Email error: {exc}")
            print_console_summary(results)
    else:
        print_console_summary(results)

    log.info("=== Weekly screener run complete ===")


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONAL LOCAL SCHEDULING (Windows Task Scheduler) — run once in PowerShell as Admin
# Production runs in the cloud via .github/workflows/weekly-screener.yml (Mondays).
# ══════════════════════════════════════════════════════════════════════════════
#
# Replace <YOUR_PYTHON_PATH> with:  (Get-Command python).Source
#
#   $action  = New-ScheduledTaskAction `
#                  -Execute "<YOUR_PYTHON_PATH>" `
#                  -Argument "C:\Users\User\Projects\business-mentors\TOOLS\QC_Monitor\scripts\weekly_screener.py" `
#                  -WorkingDirectory "C:\Users\User\Projects\business-mentors\TOOLS\QC_Monitor"
#
#   $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00AM"
#
#   $settings = New-ScheduledTaskSettingsSet `
#                   -StartWhenAvailable `
#                   -RunOnlyIfNetworkAvailable
#
#   Register-ScheduledTask `
#       -TaskName "WeeklyStockScreener" `
#       -Action $action `
#       -Trigger $trigger `
#       -Settings $settings `
#       -RunLevel Highest
#
# To test immediately:  python weekly_screener.py
# To view logs:         notepad screener_log.txt
# ══════════════════════════════════════════════════════════════════════════════
