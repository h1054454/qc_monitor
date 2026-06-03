#!/usr/bin/env python3
"""
Market Early Warning Monitor
Checks daily indicators and sends email when approaching buy signal levels.

Setup (one time):
  1. pip install yfinance requests
  2. Edit monitor_config.json -add your Gmail App Password
  3. Schedule via Windows Task Scheduler (see instructions at bottom of this file)
"""

import email as stdlib_email
import imaplib
import json
import logging
import re
import smtplib
import ssl
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import xml.etree.ElementTree as ET

import requests
import yfinance as yf

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR             = Path(__file__).parent.parent        # QC_Monitor/
CFG_PATH             = BASE_DIR / "config" / "monitor_config.json"
LOG_PATH             = BASE_DIR / "logs"   / "monitor_log.txt"
CSV_PATH             = BASE_DIR / "data"   / "indicator_history.csv"
LEADING_CSV_PATH     = BASE_DIR / "data"   / "leading_history.csv"
SUBSCRIBERS_PATH     = BASE_DIR / "config" / "known_subscribers.json"
STATUS_PATH          = BASE_DIR / "docs"    / "status.html"
MARKET_ANALYSIS_DIR  = BASE_DIR.parent / "market-analysis"   # TOOLS/market-analysis/

CSV_COLUMNS = [
    "date",
    "vix", "vix_level",
    "kre_price", "kre_14d_pct", "kre_level",
    "qqq_price", "qqq_52w_pct", "qqq_level",
    "nvda_price", "nvda_52w_pct", "nvda_level",
    "brent", "brent_high_level", "brent_low_level",
    "us10y", "us10y_level",
    "move", "move_level",
    "periph_spread", "periph_level",
    "hurricane_max_winds", "hurricane_level",
    "overall_level", "alert_sent",
]

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ── Watchlist — loaded from config/watchlist.json ────────────────────────────
WATCHLIST_PATH = BASE_DIR / "config" / "watchlist.json"

def _load_watchlist():
    """Read watchlist.json and derive BUY_TARGETS, TICKER_NAMES, TICKER_YF, TICKER_INDEX."""
    if not WATCHLIST_PATH.exists():
        logging.warning(f"watchlist.json not found at {WATCHLIST_PATH} — watchlist empty")
        return {}, {}, {}, {}
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            data = json.load(f)
        stocks = data.get("stocks", {})
        buy_targets  = {t: {"name": s["name"], "curr": s["kgv_current"],
                             "amber": s["kgv_amber"], "red": s["kgv_red"]}
                        for t, s in stocks.items()}
        ticker_names = {t: s["name"]       for t, s in stocks.items()}
        ticker_yf    = {t: s["yf_symbol"]  for t, s in stocks.items()}
        ticker_index = {t: s["index"]      for t, s in stocks.items()}
        session = data.get("session", "unknown")
        logging.info(f"Watchlist loaded from {session}: {len(stocks)} stocks")
        return buy_targets, ticker_names, ticker_yf, ticker_index
    except Exception as exc:
        logging.warning(f"watchlist.json load failed: {exc} — watchlist empty")
        return {}, {}, {}, {}

BUY_TARGETS, TICKER_NAMES, TICKER_YF, TICKER_INDEX = _load_watchlist()

# Unit suffix appended to numeric values in compact display strings
INDICATOR_UNITS = {
    "VIX":        "",
    "KRE":        "%",
    "QQQ":        "%",
    "NVDA":       "%",
    "BRENT_HIGH": " $",
    "BRENT_LOW":  " $",
    "US10Y":      "%",
}

# ── Indicator definitions ─────────────────────────────────────────────────────
# Each entry: what triggers, what it means, which watchlist stocks get unfairly sold
INDICATORS = {
    "VIX": {
        "ticker": "^VIX",
        "label": "VIX Angst-Index",
        "check": "above",
        "amber": 20,
        "red": 30,
        "scenario": "Breite Marktpanik -unterschiedsloser Ausverkauf in allen Sektoren",
        "why_discount": (
            "Steigt der VIX, verkaufen institutionelle Investoren alles Liquide, um "
            "Liquidität zu schaffen oder Risiken zu reduzieren -auch qualitätsstarke "
            "Versicherungs- und Bankaktien, die nichts mit dem Auslöser der Panik zu tun haben. "
            "Erzwungener, unterschiedsloser Ausverkauf."
        ),
        "news_url": "https://news.google.com/search?q=VIX+Marktpanik+Börsenausverkauf&hl=de&gl=AT",
        "stocks": ["CB", "CINF", "TRV", "PGR", "ACGL", "USB", "MTB", "ALV", "MUV2", "HNR1", "VIG", "EBS", "ANDR", "EVN"],
    },
    "KRE": {
        "ticker": "KRE",
        "label": "US-Regionalbanken-ETF (14-Tage-Rückgang)",
        "check": "drop_14d",
        "amber": -10.0,
        "red": -15.0,
        "scenario": "US-Regionalbanken-Krise -Verluste bei Gewerbeimmobilien befürchtet",
        "why_discount": (
            "Fällt KRE stark, befürchtet der Markt die Zahlungsunfähigkeit von Regionalbanken. "
            "U.S. Bancorp und M&T Bank werden konservativ geführt mit geringer "
            "Gewerbeimmobilienexposition -sie fallen mit dem Sektor, obwohl sie fundamental "
            "nicht beeinträchtigt sind. Sektoransteckung, kein Fundamentalschaden."
        ),
        "news_url": "https://news.google.com/search?q=US+Regionalbanken+Krise+Gewerbeimmobilien&hl=de&gl=AT",
        "stocks": ["USB", "MTB", "WFC", "BAC", "EBS", "RBI"],
    },
    "QQQ": {
        "ticker": "QQQ",
        "label": "Nasdaq 100 ETF (Rückgang vom 52W-Hoch)",
        "check": "drop_52w",
        "amber": -10.0,
        "red": -20.0,
        "scenario": "KI/Tech-Korrektur -Zwangsverkäufe in allen Aktiensektoren",
        "why_discount": (
            "Eine Nasdaq-Korrektur zwingt Fondsmanager, liquide Positionen in allen Sektoren "
            "zu verkaufen. Versicherungs- und Bankaktien fallen mit Tech-Aktien, obwohl sie "
            "null KI-Exposure haben. Die Unternehmen sind unverändert; die Verkäufer sind verängstigt."
        ),
        "news_url": "https://news.google.com/search?q=Nasdaq+Korrektur+Tech+Ausverkauf&hl=de&gl=AT",
        "stocks": ["CB", "CINF", "TRV", "PGR", "USB", "MTB", "ALV", "MUV2", "VIG", "ANDR", "EVN"],
    },
    "NVDA": {
        "ticker": "NVDA",
        "label": "NVIDIA (KI-Blasenindikator, Rückgang vom 52W-Hoch)",
        "check": "drop_52w",
        "amber": -20.0,
        "red": -35.0,
        "scenario": "KI-Capex-Erwartungen brechen ein -Nasdaq-Ausverkauf droht",
        "why_discount": (
            "NVDA ist der Frühindikator für KI-Stimmung. Ein Rückgang von 35%+ signalisiert, "
            "dass der Markt die KI-Umsatz-Timeline nach unten revidiert und eine Nasdaq-Korrektur "
            "auslöst -mit breiten Zwangsverkäufen in allen Sektoren einschließlich Finanzwerte."
        ),
        "news_url": "https://news.google.com/search?q=NVIDIA+Kursrückgang+KI+Blase&hl=de&gl=AT",
        "stocks": ["CB", "CINF", "TRV", "PGR", "USB", "MTB", "ALV", "MUV2", "VIG", "ANDR", "EVN"],
    },
    "BRENT_HIGH": {
        "ticker": "BZ=F",
        "label": "Brent-Rohöl (Iran-Krieg-Eskalation)",
        "check": "above",
        "amber": 120,
        "red": 130,
        "scenario": "Iran-Krieg eskaliert -Europäische Rezession befürchtet",
        "why_discount": (
            "Öl über $130 signalisiert schwere Iran-Kriegseskalation. Europäische Aktien "
            "verkaufen sich breit aus Rezessionsangst. Allianz, Munich Re und Hannover Rück "
            "sind tatsächliche PROFITEURE -Katastrophenrückversicherungspreise steigen weiter. "
            "Ihre Kurse fallen dennoch kurzfristig mit der allgemeinen Marktpanik."
        ),
        "news_url": "https://news.google.com/search?q=Iran+Krieg+Ölpreis+Eskalation&hl=de&gl=AT",
        "stocks": ["ALV", "MUV2", "HNR1", "DB1", "VIG"],
    },
    "BRENT_LOW": {
        "ticker": "BZ=F",
        "label": "Brent-Rohöl (Iran-Konflikt-Deeskalation)",
        "check": "below",
        "amber": 80,
        "red": 70,
        "scenario": "Iran-Konflikt löst sich auf -Preismacht der Rückversicherer schwindet",
        "why_discount": (
            "Öl unter $70 deutet auf Deeskalation des Iran-Konflikts hin. Der "
            "Rückversicherungs-Preisrückenwind für Allianz, Munich Re und Hannover Rück "
            "wird nachlassen. Keine Krise, aber die Ergebnisprämie aus 2026 schwindet."
        ),
        "news_url": "https://news.google.com/search?q=Iran+Deeskalation+Ölpreis+Rückgang&hl=de&gl=AT",
        "stocks": ["ALV", "MUV2", "HNR1", "VIG"],
    },
    "US10Y": {
        "ticker": "^TNX",
        "label": "US 10-Jahres-Staatsanleihe (Rendite)",
        "check": "above",
        "amber": 4.5,
        "red": 5.5,
        "scenario": "US-Haushaltsstress -steigender risikofreier Zins drückt alle KGV-Multiples",
        "why_discount": (
            "Wenn US-Anleihen 4,5 % oder mehr abwerfen, verkaufen viele Investoren Aktien — "
            "nicht weil die Unternehmen schlechter werden, sondern weil Anleihen als sichere "
            "Alternative plötzlich attraktiv sind. Das trifft alle Aktien pauschal, auch "
            "Versicherungen und Banken, die mit dem Zinsanstieg operativ wenig zu tun haben. "
            "Dieselben Gewinne, günstigerer Preis — wegen eines externen Recheneffekts, "
            "nicht wegen eines fundamentalen Problems."
        ),
        "news_url": "https://news.google.com/search?q=US+Staatsanleihen+Rendite+Zinsanstieg&hl=de&gl=AT",
        "stocks": ["CINF", "CB", "TRV", "PGR", "USB", "MTB", "WFC", "ALV", "MUV2", "HNR1", "VIG", "EBS"],
    },
    "MOVE": {
        "ticker": "^MOVE",
        "label": "MOVE-Index (Anleihe-Volatilität)",
        "check": "above",
        # Calibrated 2026-06-01 against 2011/2018/2020 (backtest_move_periphery.py):
        # COVID peaked 164 (red), 2011 peaked 118 (amber), 2018 stayed ~68 (green,
        # correctly — it was equity not bond stress). MOVE is the bond-shock indicator.
        "amber": 100,
        "red": 140,
        "scenario": "Anleihemarkt-Stress -Frühwarnung für Fiskal-/Treasury-Schock",
        "why_discount": (
            "Der MOVE-Index ist der VIX für Anleihen: er misst die erwartete Schwankung "
            "von US-Staatsanleihen. Springt er hoch, ist der Anleihemarkt verunsichert — "
            "historisch der Frühindikator für einen Zins-/Haushaltsschock, der die Aktien-KGV "
            "pauschal komprimiert. Steigt oft, bevor der VIX reagiert. Erzwungener Ausverkauf "
            "folgt meist, wenn die Anleihevolatilität anhält."
        ),
        "news_url": "https://news.google.com/search?q=Anleihemarkt+Volatilität+Treasury+Stress&hl=de&gl=AT",
        "stocks": ["CINF", "CB", "TRV", "PGR", "USB", "MTB", "WFC", "ALV", "MUV2", "HNR1", "VIG", "EBS"],
    },
}

# ── Euro-periphery sovereign spread (ECB daily yield curve; not a yfinance ticker) ──
# All-euro-area-bonds 10Y minus AAA-only 10Y, in basis points. The broad periphery
# risk premium (Italy is the largest driver) — the leading indicator for every
# European sovereign-stress event. Daily, free, no key. NOTE: this composite measure
# runs NARROWER than the raw BTP-Bund spread quoted in the dashboard; thresholds below
# are recalibrated for it and are provisional until back-tested against 2011/2018.
PERIPHERY = {
    "label": "Euro-Peripherie-Spread (10J, alle Bonds − AAA)",
    # Calibrated 2026-06-01 against 2011/2018/2020 (backtest_move_periphery.py).
    # This composite (all-bonds minus AAA) runs much narrower than the raw BTP-Bund
    # spread: peaks were 2011=148bp, COVID=97bp, 2018-autumn=94bp, 2018-Feb=60bp.
    # amber 50 / red 100 makes 2011 clearly red (the EU-debt stress test, where it
    # went red 35d before the trough) and the milder episodes amber.
    "amber": 50,    # bp -European sovereign stress building
    "red":   100,   # bp -fear mode; DAX quality on sale
    "scenario": "Europäischer Staatsschuldenstress -DAX-Qualität wird breit ausverkauft",
    "why_discount": (
        "Jedes europäische Finanzstress-Ereignis der letzten 15 Jahre begann mit einem "
        "Ausweiten der Peripherie-Spreads (Italien vs. Deutschland). Wirkt Italien instabil, "
        "verkaufen Investoren europäische Aktien breit — auch Allianz, Munich Re, Hannover "
        "Rück und Deutsche Börse, die mit italienischen Staatsanleihen nichts zu tun haben, "
        "aber an derselben Börse mit denselben Investoren gehandelt werden."
    ),
    "news_url": "https://news.google.com/search?q=Italien+Anleihen+Spread+Europa+Staatsschulden&hl=de&gl=AT",
    "stocks": ["ALV", "MUV2", "HNR1", "DB1"],
    "ecb_url": "https://data-api.ecb.europa.eu/service/data/YC/",
    "ecb_aaa": "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
    "ecb_all": "B.U2.EUR.4F.G_N_C.SV_C_YM.SR_10Y",
}

HURRICANE_MONTHS = {6, 7, 8, 9, 10, 11}
NOAA_ACTIVE_STORMS_URL = "https://www.nhc.noaa.gov/activestorms.xml"


# ── Vor-Indikatoren (leading stress indicators) ──────────────────────────────
# These measure stress BUILDING UP — the snowpack before the avalanche — not the
# avalanche itself. The panic indicators above (KRE, QQQ, MOVE …) are *coincident*:
# they fire once the market is already selling. These run *ahead* of that.
#
# DESIGN — "Aufmerksamkeit, nicht Handlung": they are PURELY INFORMATIONAL. They
# NEVER enter `alerts`, NEVER touch signal_level()/the >=3 KAUFSIGNAL, NEVER fire a
# notification on their own. The discount only exists once the *price* has fallen,
# so a leading indicator never tells you to buy — it tells you which scenario is
# heating up so you do the right homework early. They surface only in the weekly
# heartbeat + on the status page, and log to their own data/leading_history.csv.
#
# CALIBRATION (scripts/backtest/backtest_leading.py, metric = lead-time + false-alarm
# rate, NOT buy-payoff). Treat green/amber/red as "ruhig / erhöht / Stress-Aufbau", a
# direction, not a trigger.
#   • KREXLF — BACK-TESTED 2026-06-03 (yfinance 2006→26): -5/-10 confirmed. Red -10
#     catches GFC-2009, COVID, SVB-2023, 2025-tariff with 0 false alarms (sweep knee).
#   • HYOAS / INFL5Y5Y / STEEPEN / TERMPREM — STILL PROVISIONAL: need a re-run where
#     full FRED history is reachable (the dev sandbox only got a ~3y window / timeouts).
#   • BREADTH / DXYDIV — PROVISIONAL (not yet swept).
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

LEADING_INDICATORS = {
    "HYOAS": {
        "kind": "fred_level", "fred_id": "BAMLH0A0HYM2",
        "label": "High-Yield-Kreditspread (OAS)", "unit": " %", "decimals": 2,
        "amber": 4.5, "red": 6.0, "check": "above", "lane": "Kredit / Banken (CRE)",
        "explain": ("Risikoaufschlag für Ramsch-Anleihen. Steigt = der Kreditmarkt preist "
                    "Ausfälle ein — Vorlauf vor CRE-/Private-Credit-Stress, lange bevor der "
                    "Aktien-KRE absolut bricht."),
    },
    "KREXLF": {
        "kind": "ratio_below_avg", "num": "KRE", "den": "XLF", "window": 60,
        "label": "KRE/XLF (Regionalbanken relativ)", "unit": "%", "decimals": 1,
        # Back-tested 2026-06-03: -5/-10 confirmed (red -10 = 4/4 bank/broad crises, 0 false alarms).
        "amber": -5.0, "red": -10.0, "check": "below", "lane": "Kredit / Banken (CRE)",
        "explain": ("Regionalbanken gegen den breiten Finanzsektor. Fällt das Verhältnis = "
                    "sektorspezifischer CRE-Stress baut sich auf, bevor KRE absolut −15 % macht."),
    },
    "BREADTH": {
        "kind": "ratio_below_avg", "num": "RSP", "den": "SPY", "window": 60,
        "label": "Marktbreite (RSP/SPY, Equal vs Cap)", "unit": "%", "decimals": 1,
        "amber": -3.0, "red": -6.0, "check": "below", "lane": "KI / Konzentration",
        "explain": ("Gleichgewichteter gegen größengewichteten S&P 500. Fällt = die Rally "
                    "trägt nur noch die KI-Riesen — klassischer Spät-Blasen-Tell."),
    },
    "TERMPREM": {
        "kind": "fred_level", "fred_id": "THREEFYTP10",
        "label": "Term-Premium 10J (ACM-Modell)", "unit": " %", "decimals": 2,
        "amber": 0.5, "red": 1.0, "check": "above", "lane": "Fiskal / Zins",
        "explain": ("Risikoprämie für lange US-Laufzeiten. Steigt = der Anleihemarkt verlangt "
                    "einen Fiskal-Aufschlag — Vorlauf vor dem finalen Rendite-Ausbruch."),
    },
    "INFL5Y5Y": {
        "kind": "fred_level", "fred_id": "T5YIFR",
        "label": "5J/5J-Forward-Inflationserwartung", "unit": " %", "decimals": 2,
        "amber": 2.6, "red": 3.0, "check": "above", "lane": "Fiskal / Zins",
        "explain": ("Markterwartete Inflation in 5–10 Jahren. >3 % = Erwartungen entankern "
                    "(Fed-Glaubwürdigkeit) — der gefährliche Treiber steigender Langfristzinsen."),
    },
    "STEEPEN": {
        "kind": "fred_change", "fred_id": "T10Y2Y", "window": 21,
        "label": "Bear-Steepening (10J−2J, Δ 1 Monat)", "unit": " bp", "decimals": 0,
        "amber": 25, "red": 50, "check": "above", "lane": "Fiskal / Zins",
        "explain": ("Tempo der Kurven-Versteilung. Schnelle Versteilung am langen Ende = "
                    "Fiskal-Signatur (anders als eine wachstumsgetriebene Bewegung)."),
    },
    "DXYDIV": {
        "kind": "divergence_dxy", "dxy": "DX-Y.NYB", "yield_ticker": "^TNX", "window": 20,
        "label": "Dollar-Renditen-Divergenz (DXY ↓ & 10J ↑)", "lane": "Fiskal / Zins",
        "explain": ("Fällt der Dollar, WÄHREND die Renditen steigen, ist das ein Vertrauens- "
                    "(nicht Wachstums-)Signal — die Alarm-Signatur einer beginnenden Fiskalkrise."),
    },
}

# Only these leading indicators are back-tested enough to drive the "Vorwarnung"
# Telegram ping (a fresh crossing to red → one edge-triggered notification, clearly
# labelled "kein Kaufsignal"). The rest stay display-only (heartbeat + status page)
# until calibrated. Add a key here once backtest_leading.py validates its thresholds.
# (KREXLF back-tested 2026-06-03: -5/-10, 0 false alarms across the catalogued crises.)
CALIBRATED_LEADING = {"KREXLF"}


# ── Aggregate buy-signal logic (calibrated on the 7-year backtest) ────────────
# A KAUFSIGNAL means broad, indiscriminate selling — the moment quality stocks
# get dumped for the wrong reasons. The backtest showed a single red indicator is
# noise (and loses to the index); requiring >=3 panic indicators red at once lifted
# 12-month returns from +15% to +30%. brent_low (oil-deescalation) never counts
# toward a buy; an active major hurricane is a standalone buy signal by design.
#
# MOVE and PERIPHERY are deliberately NOT in this set yet: the >=3 rule was
# calibrated on these 6 keys, and adding un-backtested indicators would silently
# loosen the KAUFSIGNAL threshold. They run informationally (drive their own
# amber/red status + a single amber lifts the overall to BEOBACHTEN), but don't
# count toward the >=3 buy trigger until back-tested against 2011/2018/2020.
BROAD_PANIC_KEYS    = {"VIX", "KRE", "QQQ", "NVDA", "BRENT_HIGH", "US10Y"}
KAUFSIGNAL_MIN_REDS = 3


def signal_level(alerts):
    """Overall signal from the per-indicator alerts:
      'red'   (KAUFSIGNAL) -> >=3 broad-panic indicators red, or an active hurricane
      'amber' (BEOBACHTEN) -> anything else non-green
      'green' (NORMAL)     -> nothing elevated
    """
    broad_reds = sum(1 for a in alerts
                     if a["level"] == "red" and a.get("key") in BROAD_PANIC_KEYS)
    hurricane_red = any(a["level"] == "red" and a.get("key") == "HURRICANE" for a in alerts)
    if broad_reds >= KAUFSIGNAL_MIN_REDS or hurricane_red:
        return "red"
    return "amber" if alerts else "green"


# ── Data fetching ─────────────────────────────────────────────────────────────

def fetch_price_data():
    """Download 1 year of daily price history for all needed tickers."""
    tickers = list({ind["ticker"] for ind in INDICATORS.values()})
    log.info(f"Fetching data for: {tickers}")
    raw = yf.download(tickers, period="1y", auto_adjust=True, progress=False)
    # yf returns MultiIndex when multiple tickers; single ticker returns flat
    if isinstance(raw.columns, type(raw.columns)) and hasattr(raw.columns, "levels"):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]]
    return closes


def fetch_watchlist_prices():
    """Download 1 year of daily prices for all BUY_TARGETS watchlist stocks."""
    yf_tickers = list(TICKER_YF.values())
    log.info(f"Fetching watchlist prices for track record: {len(yf_tickers)} tickers")
    try:
        raw = yf.download(yf_tickers, period="1y", auto_adjust=True, progress=False)
        if hasattr(raw.columns, "levels"):
            return raw["Close"]
        return raw[["Close"]]
    except Exception as exc:
        log.warning(f"Watchlist price fetch failed (track record unavailable): {exc}")
        return None


def get_current_and_history(closes, ticker):
    """Return (current_value, series) for a ticker column."""
    col = ticker if ticker in closes.columns else None
    if col is None:
        log.warning(f"Ticker {ticker} not found in downloaded data")
        return None, None
    series = closes[col].dropna()
    if series.empty:
        return None, None
    return float(series.iloc[-1]), series


def fetch_periphery_spread():
    """Euro-periphery 10Y sovereign spread in basis points (ECB daily yield curve).

    All-euro-area-bonds 10Y minus AAA-only 10Y. Returns (spread_bp, all_pct, aaa_pct)
    or (None, None, None) on failure. Free, no key. Data lags ~1 trading day.
    """
    base = PERIPHERY["ecb_url"]

    def _last(key):
        r = requests.get(base + key,
                         params={"lastNObservations": 1, "format": "jsondata"},
                         headers={"Accept": "application/json"}, timeout=20)
        r.raise_for_status()
        j = r.json()
        obs = list(j["dataSets"][0]["series"].values())[0]["observations"]
        return float(list(obs.values())[0][0])

    try:
        all_y = _last(PERIPHERY["ecb_all"])
        aaa_y = _last(PERIPHERY["ecb_aaa"])
        spread_bp = round((all_y - aaa_y) * 100, 1)
        return spread_bp, round(all_y, 3), round(aaa_y, 3)
    except Exception as exc:
        log.warning(f"ECB periphery-spread fetch failed: {exc}")
        return None, None, None


def fetch_fred_series(series_id, n_obs=400):
    """Fetch a FRED series via the keyless CSV endpoint (no API key needed).
    Returns a list of float values oldest→newest, or [] on failure. Free, robust:
    any failure degrades to [] and the indicator shows 'keine Daten' — never crashes.
    FRED's CSV endpoint can be slow, so we allow a generous timeout + one retry."""
    last_exc = None
    for attempt in range(2):
        try:
            r = requests.get(FRED_CSV_URL, params={"id": series_id}, timeout=30)
            r.raise_for_status()
            out = []
            for line in r.text.splitlines()[1:]:        # skip header row
                parts = line.split(",")
                if len(parts) < 2:
                    continue
                v = parts[1].strip()
                if v in (".", ""):                       # FRED missing-value marker
                    continue
                try:
                    out.append(float(v))
                except ValueError:
                    continue
            return out[-n_obs:] if n_obs else out
        except Exception as exc:
            last_exc = exc
    log.warning(f"FRED fetch failed for {series_id}: {last_exc}")
    return []


def fetch_leading_prices():
    """yfinance closes for the ratio/divergence Vor-Indikatoren. 6 months is enough
    for a 60-day average. Returns a Close DataFrame or None on failure."""
    tickers = ["KRE", "XLF", "RSP", "SPY", "DX-Y.NYB", "^TNX"]
    try:
        raw = yf.download(tickers, period="6mo", auto_adjust=True, progress=False)
        return raw["Close"] if hasattr(raw.columns, "levels") else raw[["Close"]]
    except Exception as exc:
        log.warning(f"Leading-indicator price fetch failed: {exc}")
        return None


def _leading_level(value, amber, red, check):
    """green/amber/red for a leading indicator. Same machinery as the panic
    indicators, but here it means 'ruhig / erhöht / Stress-Aufbau' — a direction,
    not a buy trigger."""
    if check == "above":
        return "red" if value >= red else ("amber" if value >= amber else "green")
    return "red" if value <= red else ("amber" if value <= amber else "green")


def evaluate_leading():
    """Evaluate the Vor-Indikatoren (leading stress). PURELY INFORMATIONAL — the
    returned statuses never enter `alerts`, never touch signal_level()/KAUFSIGNAL.
    Returns (leading_statuses, raw_leading) where raw_leading logs to leading_history.csv.
    Every indicator fails soft: a network/parse error yields level 'green' + 'keine Daten'."""
    statuses = []
    raw = {}
    lead_closes = fetch_leading_prices()

    def _series(t):
        cols = getattr(lead_closes, "columns", [])
        if lead_closes is None or t not in cols:
            return None
        s = lead_closes[t].dropna()
        return s if not s.empty else None

    for key, cfg in LEADING_INDICATORS.items():
        kind   = cfg["kind"]
        level  = "green"
        value  = None
        current = "—"
        compact = "keine Daten"
        try:
            if kind == "fred_level":
                hist = fetch_fred_series(cfg["fred_id"], n_obs=10)
                if hist:
                    value   = hist[-1]
                    level   = _leading_level(value, cfg["amber"], cfg["red"], cfg["check"])
                    current = f"{_de_num(value, cfg['decimals'])}{cfg['unit']}"
                    compact = (f"{current} — erhöht ab {_de_num(cfg['amber'], 1)}{cfg['unit']}, "
                               f"Stress ab {_de_num(cfg['red'], 1)}{cfg['unit']}")

            elif kind == "fred_change":
                w = cfg["window"]
                hist = fetch_fred_series(cfg["fred_id"], n_obs=w * 2)
                if len(hist) > w:
                    delta_bp = (hist[-1] - hist[-(w + 1)]) * 100   # % points → bp
                    value    = delta_bp
                    level    = _leading_level(delta_bp, cfg["amber"], cfg["red"], cfg["check"])
                    current  = f"{_de_num(delta_bp, 0)}{cfg['unit']} (1 Mt)"
                    compact  = (f"{current} — erhöht ab +{cfg['amber']}{cfg['unit']}, "
                                f"Stress ab +{cfg['red']}{cfg['unit']}")

            elif kind == "ratio_below_avg":
                num = _series(cfg["num"]); den = _series(cfg["den"])
                if num is not None and den is not None:
                    ratio = (num / den).dropna()
                    if len(ratio) > cfg["window"]:
                        cur = float(ratio.iloc[-1])
                        avg = float(ratio.iloc[-cfg["window"]:].mean())
                        pct = (cur / avg - 1) * 100 if avg else 0.0
                        value   = pct
                        level   = _leading_level(pct, cfg["amber"], cfg["red"], cfg["check"])
                        current = f"{_de_num(pct, 1)}% vs {cfg['window']}T-Schnitt"
                        compact = (f"{current} — erhöht unter {_de_num(cfg['amber'], 1)}%, "
                                   f"Stress unter {_de_num(cfg['red'], 1)}%")

            elif kind == "divergence_dxy":
                w = cfg["window"]
                dxy = _series(cfg["dxy"]); yld = _series(cfg["yield_ticker"])
                if (dxy is not None and yld is not None
                        and len(dxy) > w and len(yld) > w):
                    dxy_chg = (float(dxy.iloc[-1]) / float(dxy.iloc[-w]) - 1) * 100
                    yld_chg = float(yld.iloc[-1]) - float(yld.iloc[-w])   # % points
                    diverging = dxy_chg < 0 and yld_chg > 0
                    if diverging and dxy_chg <= -2 and yld_chg >= 0.3:
                        level = "red"
                    elif diverging:
                        level = "amber"
                    value   = round(dxy_chg, 2)
                    sign    = "+" if yld_chg >= 0 else ""
                    current = f"DXY {_de_num(dxy_chg, 1)}% / 10J {sign}{_de_num(yld_chg, 2)} pp (20T)"
                    compact = (f"{current} — erhöht: Dollar fällt & Rendite steigt; "
                               f"Stress: DXY −2 %+ & 10J +0,3 pp+")
        except Exception as exc:
            log.warning(f"Leading indicator {key} failed: {exc}")

        statuses.append({
            "key": key, "level": level, "label": cfg["label"],
            "lane": cfg["lane"], "explain": cfg.get("explain", ""),
            "current": current, "compact": compact,
        })
        raw[f"lead_{key.lower()}"]       = round(value, 3) if isinstance(value, float) else value
        raw[f"lead_{key.lower()}_level"] = level
        log.info(f"LEADING {key}: {current} → {level.upper()}")

    return statuses, raw


def check_atlantic_hurricanes():
    """Return list of active Atlantic tropical cyclones (name, type, wind_mph)."""
    if date.today().month not in HURRICANE_MONTHS:
        return []
    try:
        resp = requests.get(NOAA_ACTIVE_STORMS_URL, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"nhc": "https://www.nhc.noaa.gov"}
        storms = []
        for cyclone in root.findall("nhc:Cyclone", ns):
            wallet = cyclone.findtext("nhc:wallet", default="", namespaces=ns)
            # Atlantic storms have wallet AT1, AT2, AT3 …
            if not wallet.startswith("AT"):
                continue
            name  = cyclone.findtext("nhc:name",     default="Unknown", namespaces=ns)
            ctype = cyclone.findtext("nhc:type",     default="",        namespaces=ns)
            wind  = cyclone.findtext("nhc:wind",     default="0 mph",   namespaces=ns)
            head  = cyclone.findtext("nhc:headline", default="",        namespaces=ns)
            try:
                wind_mph = int(wind.split()[0])
            except (ValueError, IndexError):
                wind_mph = 0
            storms.append({"name": name, "type": ctype, "wind_mph": wind_mph, "headline": head})
        return storms
    except Exception as exc:
        log.warning(f"NOAA fetch failed: {exc}")
        return []


# ── Threshold evaluation ──────────────────────────────────────────────────────

_MONTHS_DE = ["Januar","Februar","März","April","Mai","Juni",
              "Juli","August","September","Oktober","November","Dezember"]
_DAYS_DE   = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"]

def _de_date():
    d = datetime.now()
    return f"{_DAYS_DE[d.weekday()]}, {d.day}. {_MONTHS_DE[d.month - 1]} {d.year}"


def _de_num(val, decimals=2):
    """Float → German decimal comma (e.g. 4.60 → '4,60')."""
    return f"{val:.{decimals}f}".replace(".", ",")


def _de_thr(val, unit=""):
    """Threshold value → German-formatted string with unit (1 decimal for floats)."""
    if isinstance(val, int):
        return f"{val}{unit}"
    return f"{_de_num(val, 1)}{unit}"


def _days_to_next_threshold(series, current, next_thr, direction):
    """Extrapolate linear trend from last 7 days; return days to next threshold or None."""
    if len(series) < 8:
        return None
    slope = (float(series.iloc[-1]) - float(series.iloc[-8])) / 7
    if direction == "above" and slope <= 0:
        return None
    if direction == "below" and slope >= 0:
        return None
    days = abs((next_thr - current) / slope)
    return round(days) if days <= 60 else None


_INDICATOR_LEVEL_COL = {
    "VIX":       "vix_level",
    "KRE":       "kre_level",
    "QQQ":       "qqq_level",
    "NVDA":      "nvda_level",
    "BRENT_HIGH":"brent_high_level",
    "BRENT_LOW": "brent_low_level",
    "US10Y":     "us10y_level",
    "HURRICANE": "hurricane_level",
}


def _consecutive_days(indicator_key: str) -> int:
    """Return how many consecutive days this indicator has been non-green in the CSV."""
    import csv as csv_mod
    col = _INDICATOR_LEVEL_COL.get(indicator_key)
    if not col or not CSV_PATH.exists():
        return 0
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv_mod.DictReader(f))
        if not rows:
            return 0
        # Deduplicate: keep last row per date
        by_date: dict = {}
        for r in rows:
            by_date[r["date"]] = r
        daily = list(by_date.values())
        count = 0
        for row in reversed(daily):
            if row.get(col, "green") != "green":
                count += 1
            else:
                break
        return count
    except Exception:
        return 0


def _build_intro(alerts: list, closes) -> str:
    """Build a dynamic German intro paragraph: yfinance duration + 7-day trend + proximity."""
    if not alerts:
        return ""

    def _yf_days_above(ticker, threshold, check):
        if closes is None or ticker not in closes.columns:
            return None
        try:
            series = closes[ticker].dropna()
            count = 0
            for val in reversed(series.values):
                crossed = (check == "above" and float(val) >= threshold) or \
                          (check == "below" and float(val) <= threshold)
                if crossed:
                    count += 1
                else:
                    break
            return count if count > 0 else None
        except Exception:
            return None

    def _seven_day_delta(ticker):
        if closes is None or ticker not in closes.columns:
            return None
        try:
            series = closes[ticker].dropna()
            if len(series) < 8:
                return None
            return float(series.iloc[-1]) - float(series.iloc[-8])
        except Exception:
            return None

    sentences = []
    for a in alerts:
        key   = a.get("key", "")
        label = a["label"]
        current_str = a.get("current", "")

        ind       = INDICATORS.get(key, {})
        ticker    = ind.get("ticker", "")
        check     = ind.get("check", "above")
        amber_thr = ind.get("amber")
        red_thr   = ind.get("red")
        unit_str  = INDICATOR_UNITS.get(key, "")

        # Duration: prefer yfinance series, fall back to CSV
        yf_days = _yf_days_above(ticker, amber_thr, check) if amber_thr is not None else None
        days    = yf_days if yf_days is not None else _consecutive_days(key)

        # 7-day trend sentence
        delta = _seven_day_delta(ticker)
        trend_sentence = ""
        if delta is not None and abs(delta) > 0.001:
            if key == "US10Y":
                bp = abs(round(delta * 100))
                direction = "Stieg" if delta > 0 else "Fiel"
                trend_sentence = f" {direction} in 7 Tagen um {bp} Basispunkte."
            elif key == "VIX":
                direction = "Stieg" if delta > 0 else "Fiel"
                trend_sentence = f" {direction} diese Woche um {_de_num(abs(delta), 1)} Punkte."
            elif check == "below":
                trend_sentence = f" Fiel weitere {_de_num(abs(delta), 1)}{unit_str} seit letzter Woche."
            else:
                direction = "Stieg" if delta > 0 else "Fiel"
                trend_sentence = f" {direction} in 7 Tagen um {_de_num(abs(delta), 1)}{unit_str}."

        # Proximity: distance to buy-signal threshold
        proximity = ""
        if red_thr is not None:
            proximity = f" — Kaufsignal ab {_de_thr(red_thr, unit_str)}"
        val_info = f"({current_str}{proximity})"

        if days <= 1:
            sentences.append(
                f"<strong>{label}</strong> hat heute die Warnschwelle überschritten "
                f"{val_info}.{trend_sentence}"
            )
        else:
            sentences.append(
                f"<strong>{label}</strong> befindet sich seit {days} Tagen im erhöhten "
                f"Bereich {val_info}.{trend_sentence}"
            )

    # Summary closing line
    total = len(INDICATORS) + 1  # +1 for hurricane
    inactive = total - len(alerts)
    if inactive > 0:
        if inactive == 1:
            closing = "1 weiterer Indikator unauffällig."
        elif inactive == total - 1:
            closing = "Alle anderen Indikatoren zeigen keine erhöhten Werte."
        else:
            closing = f"{inactive} weitere Indikatoren unauffällig."
    else:
        closing = "Alle überwachten Indikatoren sind aktiv."

    body = " ".join(sentences) + f" {closing}"
    return (
        f'<p style="font-size:14px;color:#374151;margin:0 0 20px;line-height:1.7">'
        f'{body}</p>'
    )


def evaluate(closes):
    """
    Evaluate all indicators against thresholds.
    Returns (alerts, all_statuses, readings) where:
      - alerts: amber/red dicts for email detail and Telegram detail blocks
      - all_statuses: every indicator including green (for Telegram overview)
      - readings: flat dict of raw numeric values for CSV logging
    """
    alerts       = []
    all_statuses = []
    raw          = {}   # raw numeric values for CSV

    for key, ind in INDICATORS.items():
        ticker = ind["ticker"]
        current, series = get_current_and_history(closes, ticker)
        if current is None:
            log.warning(f"No data for {key} ({ticker}), skipping")
            continue

        check     = ind["check"]
        amber_thr = ind["amber"]
        red_thr   = ind["red"]
        pct_change = None
        unit = INDICATOR_UNITS.get(key, "")

        if check == "above":
            level = "red" if current >= red_thr else ("amber" if current >= amber_thr else "green")
            display_current   = f"{_de_num(current)}{unit}"
            display_threshold = f"Beobachten ab {_de_thr(amber_thr, unit)} | Kaufsignal ab {_de_thr(red_thr, unit)}"
            compact = (
                f"{_de_num(current)}{unit} - "
                f"Gelb ab {_de_thr(amber_thr, unit)}, Rot ab {_de_thr(red_thr, unit)}"
            )

        elif check == "below":
            level = "red" if current <= red_thr else ("amber" if current <= amber_thr else "green")
            display_current   = f"{_de_num(current)}{unit}"
            display_threshold = f"Beobachten unter {_de_thr(amber_thr, unit)} | Kaufsignal unter {_de_thr(red_thr, unit)}"
            compact = (
                f"{_de_num(current)}{unit} - "
                f"Gelb unter {_de_thr(amber_thr, unit)}, Rot unter {_de_thr(red_thr, unit)}"
            )

        elif check in ("drop_52w", "drop_14d"):
            if check == "drop_52w":
                reference    = float(series.max())
                ref_label_de = "vom 52W-Hoch"
                ref_period   = "52W-Hoch"
            else:
                lookback     = min(14, len(series) - 1)
                reference    = float(series.iloc[-(lookback + 1)])
                ref_label_de = "in 14 Tagen"
                ref_period   = "14-Tage-Hoch"
            pct_change = (current - reference) / reference * 100 if reference else 0.0
            level = "red" if pct_change <= red_thr else ("amber" if pct_change <= amber_thr else "green")
            display_current   = f"{_de_num(pct_change, 1)}% {ref_label_de} ({ref_period}: {_de_num(reference)} | Aktuell: {_de_num(current)})"
            display_threshold = f"Beobachten ab {_de_thr(amber_thr)}% | Kaufsignal ab {_de_thr(red_thr)}%"
            compact = (
                f"{_de_num(pct_change, 1)}% {ref_label_de} - "
                f"Gelb ab {_de_thr(amber_thr)}%, Rot ab {_de_thr(red_thr)}%"
            )

        else:
            level = "green"
            display_current = display_threshold = compact = "n/a"

        # ── Accumulate raw CSV values ────────────────────────────────────────
        if key == "VIX":
            raw["vix"] = round(current, 2);  raw["vix_level"] = level
        elif key == "KRE":
            raw["kre_price"] = round(current, 2)
            raw["kre_14d_pct"] = round(pct_change, 2) if pct_change is not None else None
            raw["kre_level"] = level
        elif key == "QQQ":
            raw["qqq_price"] = round(current, 2)
            raw["qqq_52w_pct"] = round(pct_change, 2) if pct_change is not None else None
            raw["qqq_level"] = level
        elif key == "NVDA":
            raw["nvda_price"] = round(current, 2)
            raw["nvda_52w_pct"] = round(pct_change, 2) if pct_change is not None else None
            raw["nvda_level"] = level
        elif key == "BRENT_HIGH":
            raw["brent"] = round(current, 2);  raw["brent_high_level"] = level
        elif key == "BRENT_LOW":
            raw["brent_low_level"] = level   # brent price already set by BRENT_HIGH
        elif key == "US10Y":
            raw["us10y"] = round(current, 2);  raw["us10y_level"] = level
        elif key == "MOVE":
            raw["move"] = round(current, 2);  raw["move_level"] = level

        status = {
            "key": key, "level": level, "label": ind["label"],
            "compact": compact,
            "current": display_current, "threshold": display_threshold,
            "scenario": ind["scenario"], "why_discount": ind["why_discount"],
            "news_url": ind.get("news_url", ""),
            "stocks": ind["stocks"],
        }
        all_statuses.append(status)
        # brent_low (oil-deescalation) is informational only — it stays on the
        # status page but never drives a notification (excluded from alerts).
        if level != "green" and key != "BRENT_LOW":
            alerts.append(status)
        log.info(f"{key}: {display_current} → {level.upper()}")

    # ── Hurricane check ──────────────────────────────────────────────────────
    storms = check_atlantic_hurricanes()
    strong = [s for s in storms if s["wind_mph"] >= 74] if storms else []
    hurr_stocks = ["CB", "CINF", "TRV", "PGR", "ACGL", "ALV", "MUV2", "HNR1"]
    hurr_why = (
        "Bedroht ein schwerer Hurrikan die US-Küste, fallen Versicherungsaktien um "
        "20–35% aufgrund erwarteter Schäden. Das Franchise ist NICHT beeinträchtigt -"
        "nach einem schweren Ereignis steigen die Prämien 3–5 Jahre lang. "
        "Der maximale Abschlag besteht 2–3 Tage nach dem Landfall, auf dem Höhepunkt der Unsicherheit."
    )
    if strong:
        hurr_level   = "red" if any(s["wind_mph"] >= 111 for s in strong) else "amber"
        max_winds    = max(s["wind_mph"] for s in strong)
        storm_str    = "; ".join(f"{s['name']} ({s['wind_mph']} mph)" for s in strong)
        hurr_compact = f"{storm_str} -Gelb: 74–110 mph, Rot: ≥111 mph"
        hurr_status  = {
            "key": "HURRICANE", "level": hurr_level,
            "label": "Atlantik-Hurrikan -Aktiver Sturm",
            "compact": hurr_compact,
            "current": storm_str,
            "threshold": "Gelb: 74–110 mph | Rot: ≥ 111 mph (Kat. 3+)",
            "scenario": "Aktiver Atlantik-Hurrikan -Ausverkauf im Versicherungssektor droht",
            "why_discount": hurr_why,
            "news_url": "https://www.nhc.noaa.gov/",
            "stocks": hurr_stocks,
        }
        all_statuses.append(hurr_status)
        alerts.append(hurr_status)
        raw["hurricane_max_winds"] = max_winds
        raw["hurricane_level"]     = hurr_level
    else:
        # Show during hurricane season so reader knows it was checked
        if date.today().month in HURRICANE_MONTHS:
            all_statuses.append({
                "key": "HURRICANE", "level": "green",
                "label": "Atlantik-Hurrikan",
                "compact": "Kein aktiver Sturm",
                "current": "-", "threshold": "-",
                "scenario": "", "why_discount": hurr_why,
                "news_url": "", "stocks": hurr_stocks,
            })
        raw["hurricane_max_winds"] = 0
        raw["hurricane_level"]     = "green"

    # ── Euro-periphery sovereign spread (ECB daily) ──────────────────────────
    spread_bp, all_y, aaa_y = fetch_periphery_spread()
    if spread_bp is not None:
        p_amber, p_red = PERIPHERY["amber"], PERIPHERY["red"]
        p_level = "red" if spread_bp >= p_red else ("amber" if spread_bp >= p_amber else "green")
        p_compact = (f"{_de_num(spread_bp, 1)} bp (alle {_de_num(all_y, 2)} % − AAA "
                     f"{_de_num(aaa_y, 2)} %) -Gelb ab {p_amber} bp, Rot ab {p_red} bp")
        p_status = {
            "key": "PERIPHERY", "level": p_level,
            "label": PERIPHERY["label"],
            "compact": p_compact,
            "current": f"{_de_num(spread_bp, 1)} bp",
            "threshold": f"Beobachten ab {p_amber} bp | Kaufsignal ab {p_red} bp",
            "scenario": PERIPHERY["scenario"],
            "why_discount": PERIPHERY["why_discount"],
            "news_url": PERIPHERY["news_url"],
            "stocks": PERIPHERY["stocks"],
        }
        all_statuses.append(p_status)
        if p_level != "green":
            alerts.append(p_status)
        raw["periph_spread"] = spread_bp
        raw["periph_level"]  = p_level
        log.info(f"PERIPHERY: {spread_bp} bp → {p_level.upper()}")
    else:
        raw["periph_spread"] = None
        raw["periph_level"]  = "green"   # unknown -don't fabricate stress

    raw["overall_level"] = signal_level(alerts)

    return alerts, all_statuses, raw


# ── CSV logger ────────────────────────────────────────────────────────────────

def read_last_overall_level():
    """Overall_level of the most recent CSV row — the last run's signal state.
    Used for edge-triggering (notify only when the signal level changes)."""
    import csv
    if not CSV_PATH.exists():
        return None
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        return rows[-1]["overall_level"] if rows else None
    except Exception:
        return None


def write_to_csv(raw, alert_sent: bool):
    """Append one row to indicator_history.csv. Creates file with header if new."""
    import csv
    raw["date"]       = date.today().isoformat()
    raw["alert_sent"] = alert_sent

    file_exists = CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(raw)
    log.info(f"CSV row written: {raw['date']} | overall={raw['overall_level']}")


def read_last_leading_levels():
    """Per-indicator level from the most recent leading_history.csv row, for
    edge-triggering the Vorwarnung (notify only on a fresh crossing to red).
    Returns {'lead_<key>_level': 'green'|'amber'|'red', ...} or {}."""
    import csv
    if not LEADING_CSV_PATH.exists():
        return {}
    try:
        with open(LEADING_CSV_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}
        return {k: v for k, v in rows[-1].items() if k.endswith("_level")}
    except Exception:
        return {}


def write_leading_csv(raw_leading):
    """Append one row to leading_history.csv (separate from the panic-indicator CSV
    so adding/removing a Vor-Indikator never disturbs the back-tested main history)."""
    import csv
    if not raw_leading:
        return
    row  = {"date": date.today().isoformat(), **raw_leading}
    cols = ["date"] + sorted(raw_leading.keys())
    exists = LEADING_CSV_PATH.exists()
    with open(LEADING_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    log.info(f"Leading CSV row written: {row['date']}")


# ── Email builder ─────────────────────────────────────────────────────────────


def _build_voice(alerts: list) -> str:
    """Return a natural German opening sentence based on the current alert state."""
    n_red   = sum(1 for a in alerts if a["level"] == "red")
    n_amber = sum(1 for a in alerts if a["level"] == "amber")

    if n_red > 0:
        text = (
            "Heute liegt eine klare Kaufgelegenheit vor: der Markt verkauft "
            "Qualität aus Gründen, die nichts mit dem Unternehmenswert zu tun haben."
        )
    elif n_amber >= 3:
        text = (
            "Mehrere Indikatoren blinken gleichzeitig auf — das ist selten "
            "und verdient volle Aufmerksamkeit."
        )
    elif n_amber == 2:
        text = (
            "Zwei Indikatoren signalisieren gleichzeitig makroökonomischen Druck "
            "— die Wahrscheinlichkeit unfairer Kursrückgänge steigt."
        )
    else:
        text = (
            "Ein Indikator hat die Aufmerksamkeitsschwelle überschritten — noch kein "
            "Handlungsbedarf, aber der Markt sendet ein erstes Warnsignal."
        )

    return (
        f'<p style="font-size:15px;color:#111827;font-style:italic;margin:0 0 16px;'
        f'line-height:1.7;border-left:3px solid #d1d5db;padding-left:14px">'
        f'{text}</p>'
    )


def _build_track_record(watchlist, closes=None) -> str:
    """Build Track Record using real yfinance market data to find true signal start dates."""
    if watchlist is None or closes is None:
        return ""

    rows_html = ""
    for key, ind in INDICATORS.items():
        ticker    = ind["ticker"]
        check     = ind["check"]
        amber_thr = ind["amber"]

        if ticker not in closes.columns:
            continue

        series = closes[ticker].dropna()
        if series.empty:
            continue

        current_val  = float(series.iloc[-1])
        is_triggered = (check == "above" and current_val >= amber_thr) or \
                       (check == "below" and current_val <= amber_thr)
        if not is_triggered:
            continue

        # Walk backwards to find the real start of this elevated run
        count = 0
        for val in reversed(series.values):
            crossed = (check == "above" and float(val) >= amber_thr) or \
                      (check == "below" and float(val) <= amber_thr)
            if crossed:
                count += 1
            else:
                break

        if count == 0:
            continue

        start_idx  = len(series) - count
        start_date = series.index[start_idx]
        start_str  = start_date.strftime("%d.%m.%Y") if hasattr(start_date, "strftime") else str(start_date)[:10]

        label  = ind["label"].split("(")[0].strip()
        stocks = ind.get("stocks", [])

        stock_cells = []
        for display_ticker in sorted(stocks)[:4]:
            yf_ticker = TICKER_YF.get(display_ticker)
            if not yf_ticker or yf_ticker not in watchlist.columns:
                continue
            wl = watchlist[yf_ticker].dropna()
            if wl.empty:
                continue
            idx = wl.index.searchsorted(start_date)
            if idx >= len(wl):
                continue
            start_price = float(wl.iloc[idx])
            today_price = float(wl.iloc[-1])
            if start_price == 0:
                continue
            ret   = (today_price - start_price) / start_price * 100
            color = "#15803d" if ret >= 0 else "#dc2626"
            sign  = "+" if ret >= 0 else ""
            stock_cells.append(
                f'<span style="color:{color};font-weight:600">'
                f'{display_ticker} {sign}{ret:.1f}%</span>'
            )

        stocks_html = " &nbsp; ".join(stock_cells) if stock_cells else "—"

        rows_html += (
            f'<tr style="border-bottom:1px solid #e5e7eb">'
            f'<td style="padding:8px 12px;font-size:13px;color:#374151;white-space:nowrap">{label}</td>'
            f'<td style="padding:8px 12px;font-size:13px;color:#6b7280;white-space:nowrap">{start_str}</td>'
            f'<td style="padding:8px 12px;font-size:13px">{stocks_html}</td>'
            f'</tr>'
        )

    if not rows_html:
        return ""

    return (
        f'<div style="background:#fff;border-radius:8px;border-left:5px solid #6366f1;'
        f'box-shadow:0 1px 4px rgba(0,0,0,.07);margin-bottom:16px">'
        f'<div style="padding:14px 18px;border-bottom:1px solid #f3f4f6">'
        f'<span style="font-size:13px;font-weight:700;color:#374151;'
        f'text-transform:uppercase;letter-spacing:.07em">Track Record</span>'
        f'</div>'
        f'<div style="overflow-x:auto">'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px">'
        f'<thead><tr style="background:#f8fafc">'
        f'<th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;'
        f'font-size:12px;text-transform:uppercase">Signal</th>'
        f'<th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;'
        f'font-size:12px;text-transform:uppercase">Seit</th>'
        f'<th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;'
        f'font-size:12px;text-transform:uppercase">Watchlist seit Signal</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div></div>'
    )

LEVEL_COLOR  = {"amber": "#f59e0b", "red": "#16a34a"}   # green = buy signal
LEVEL_LABEL  = {"amber": "BEOBACHTEN", "red": "KAUFSIGNAL"}
STOCK_COLORS = {"amber": "#fef3c7", "red": "#dcfce7"}   # light green for buy

def buy_target_rows(stock_tickers):
    rows = ""
    for t in stock_tickers:
        if t not in BUY_TARGETS:
            continue
        b = BUY_TARGETS[t]
        rows += (
            f"<tr>"
            f"<td style='padding:4px 10px;font-weight:bold'>{t}</td>"
            f"<td style='padding:4px 10px'>{b['name']}</td>"
            f"<td style='padding:4px 10px;text-align:center'>{b['curr']:.2f}x</td>"
            f"<td style='padding:4px 10px;text-align:center;color:#b45309'>{b['amber']:.1f}x</td>"
            f"<td style='padding:4px 10px;text-align:center;color:#15803d;font-weight:bold'>{b['red']:.1f}x</td>"
            f"</tr>"
        )
    return rows


def build_html(alerts, closes, watchlist):
    today        = _de_date()
    time_str     = datetime.now().strftime("%H:%M")
    worst        = signal_level(alerts)
    header_color = LEVEL_COLOR[worst]
    header_label = LEVEL_LABEL[worst]

    # ── Compact indicator cards (no stocks) + collect all active stocks ──────────
    indicator_cards = ""
    all_active_stocks: list = []
    seen_stocks: set = set()

    for a in alerts:
        c = LEVEL_COLOR[a["level"]]

        # Collect stocks for the aggregated section (preserving order, deduped)
        for t in a.get("stocks", []):
            if t not in seen_stocks:
                all_active_stocks.append(t)
                seen_stocks.add(t)

        # Vorausschau: trend extrapolation to next threshold (amber cards only)
        vorausschau_html = ""
        if a["level"] == "amber" and closes is not None:
            try:
                v_ind    = INDICATORS.get(a.get("key", ""), {})
                v_ticker = v_ind.get("ticker", "")
                v_check  = v_ind.get("check", "above")
                v_red    = v_ind.get("red")
                if v_ticker and v_red is not None and v_ticker in closes.columns:
                    v_series  = closes[v_ticker].dropna()
                    v_current = float(v_series.iloc[-1])
                    days_to_red = _days_to_next_threshold(v_series, v_current, v_red, v_check)
                    if days_to_red is not None:
                        vorausschau_html = (
                            f'<div style="font-size:13px;color:#6b7280;margin-top:12px;'
                            f'padding:8px 12px;background:#f8fafc;border-radius:4px">'
                            f'Bei aktuellem Trend: Kaufsignal in ca. {days_to_red} '
                            f'Tag{"en" if days_to_red != 1 else ""}.'
                            f'</div>'
                        )
            except Exception:
                pass

        news_url  = a.get("news_url", "")
        news_html = (
            f'<div style="margin-top:10px"><a href="{news_url}" '
            f'style="color:#0284c7;font-size:13px">→ Aktuelle Nachrichten</a></div>'
        ) if news_url else ""

        indicator_cards += f"""
        <div style="background:#fff;border-radius:8px;margin:0 0 12px;
                    border-left:5px solid {c};box-shadow:0 1px 4px rgba(0,0,0,.07)">
          <div style="padding:14px 18px;border-bottom:1px solid #f3f4f6">
            <span style="display:inline-block;background:{c};color:#fff;
                         font-size:11px;font-weight:700;letter-spacing:.07em;
                         text-transform:uppercase;padding:3px 10px;border-radius:20px">
              {LEVEL_LABEL[a['level']]}
            </span>
            <span style="font-size:16px;font-weight:700;color:#111827;margin-left:10px">
              {a['label']}
            </span>
          </div>
          <div class="card-pad" style="padding:16px 18px">

            <table style="margin-bottom:14px;font-size:13px">
              <tr>
                <td style="padding:3px 14px 3px 0;color:#9ca3af;white-space:nowrap">Aktueller Wert</td>
                <td style="padding:3px 0;font-weight:700;color:#111827">{a['current']}</td>
              </tr>
              <tr>
                <td style="padding:3px 14px 3px 0;color:#9ca3af;white-space:nowrap">Schwellenwerte</td>
                <td style="padding:3px 0;color:#374151">{a['threshold']}</td>
              </tr>
            </table>

            <div style="background:#f8fafc;border-left:4px solid {c};
                        padding:10px 14px;margin-bottom:14px;font-size:14px;
                        color:#374151;line-height:1.6;border-radius:0 4px 4px 0">
              {a['scenario']}
            </div>

            <div style="font-size:13px;color:#374151;line-height:1.7">
              <strong>Warum jetzt günstiger — ohne fundamentalen Grund:</strong><br>
              {a['why_discount']}
            </div>

            {news_html}
            {vorausschau_html}

          </div>
        </div>
        """

    # ── Aggregated "Aktuell günstig" section (all stocks from all active signals) ─
    stocks_section = ""
    if all_active_stocks:
        worst_c  = LEVEL_COLOR[worst]
        worst_bg = STOCK_COLORS[worst]
        agg_rows = buy_target_rows(all_active_stocks)

        by_index: dict = {}
        for t in all_active_stocks:
            idx_name = TICKER_INDEX.get(t, "Sonstige")
            by_index.setdefault(idx_name, []).append(TICKER_NAMES.get(t, t))
        stock_lines = ""
        for idx_name in ["S&P 500", "DAX", "ATX"]:
            names = by_index.get(idx_name, [])
            if names:
                stock_lines += (
                    f'<div style="margin-bottom:4px">'
                    f'<span style="color:#6b7280;font-size:11px;text-transform:uppercase;'
                    f'letter-spacing:.05em;font-weight:700">{idx_name}</span><br>'
                    f'{", ".join(names)}'
                    f'</div>'
                )

        stocks_section = f"""
        <div style="background:#fff;border-radius:8px;margin:0 0 16px;
                    border-left:5px solid {worst_c};box-shadow:0 1px 4px rgba(0,0,0,.07)">
          <div style="padding:14px 18px;border-bottom:1px solid #f3f4f6">
            <span style="font-size:13px;font-weight:700;color:#374151;
                         text-transform:uppercase;letter-spacing:.07em">Aktuell günstig</span>
          </div>
          <div class="card-pad" style="padding:16px 18px">
            <div style="font-size:13px;color:#374151;margin-bottom:14px;line-height:2">
              {stock_lines}
            </div>
            <div class="kgv-wrap" style="overflow-x:auto">
              <table style="width:100%;border-collapse:collapse;font-size:13px;
                            background:{worst_bg};border-radius:6px;overflow:hidden">
                <thead>
                  <tr style="background:{worst_c};color:white">
                    <th style="padding:8px 10px;text-align:left;font-weight:600">Ticker</th>
                    <th style="padding:8px 10px;text-align:left;font-weight:600">Unternehmen</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Aktuelles KGV</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Beobachten</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Kaufsignal</th>
                  </tr>
                </thead>
                <tbody>{agg_rows}</tbody>
              </table>
            </div>
          </div>
        </div>
        """

    manual_check = """
    <div style="background:#fff;border-radius:8px;border-left:5px solid #e5e7eb;
                box-shadow:0 1px 4px rgba(0,0,0,.07);padding:16px 18px;margin-top:8px">
      <div style="font-size:13px;font-weight:700;color:#374151;text-transform:uppercase;
                  letter-spacing:.05em;margin-bottom:8px">Weiterer Indikator auf dem Radar</div>
      <p style="font-size:13px;color:#374151;margin:0 0 8px;line-height:1.7">
        Der <strong>BTP-Bund-Spread</strong> misst die Risikoprämie für italienische
        Staatsanleihen gegenüber deutschen Bundesanleihen. Steigt er über 200 Basispunkte,
        signalisiert das erhöhten Stress im Euroraum — DAX-Aktien werden dann oft pauschal
        abgestraft, unabhängig von ihrer Qualität.
      </p>
      <p style="font-size:13px;color:#6b7280;margin:0">
        Aktuell: Keine erhöhte Risikoprämie. &nbsp;
        <a href="https://tradingeconomics.com/italy/government-bond-yield"
           style="color:#0284c7">→ Aktueller Stand</a>
      </p>
    </div>
    """

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ margin:0; padding:0; background:#f3f4f6; font-family:Arial,sans-serif; color:#1f2937; }}
    .wrapper {{ max-width:640px; margin:0 auto; background:#f3f4f6; padding:0 0 32px; }}
    .kgv-wrap {{ overflow-x:auto; }}
    @media (max-width:600px) {{
      .card-pad {{ padding:14px !important; }}
      .header-title {{ font-size:16px !important; }}
      td, th {{ font-size:12px !important; padding:5px 6px !important; }}
    }}
  </style>
</head>
<body>
<div class="wrapper">

  <!-- Header (table layout for Outlook compatibility) -->
  <div style="background:#111827;padding:18px 24px;border-radius:0 0 0 0">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr>
        <td style="font-size:12px;font-weight:700;letter-spacing:.12em;color:#9ca3af;
                   text-transform:uppercase">MARKT-MONITOR</td>
        <td align="right" style="font-size:12px;color:#6b7280">{today} &nbsp;·&nbsp; {time_str} Uhr</td>
      </tr>
    </table>
    <div style="margin-top:10px">
      <span style="display:inline-block;background:{header_color};color:#fff;
                   font-size:11px;font-weight:700;padding:4px 14px;border-radius:20px;
                   letter-spacing:.06em;text-transform:uppercase">
        {header_label}
      </span>
    </div>
  </div>

  <!-- Voice + Intro -->
  <div style="padding:20px 20px 4px">
    {_build_voice(alerts)}
    {_build_intro(alerts, closes)}
  </div>

  <!-- Track Record -->
  <div style="padding:0 20px">
    {_build_track_record(watchlist, closes)}
  </div>

  <!-- Indicator cards (compact, no stocks) -->
  <div style="padding:0 20px">
    {indicator_cards}
  </div>

  <!-- Aggregated stocks watchlist -->
  <div style="padding:0 20px">
    {stocks_section}
  </div>

  <!-- Manual check -->
  <div style="padding:0 20px">
    {manual_check}
  </div>

  <!-- Footer -->
  <div style="padding:24px 20px 0;border-top:1px solid #e5e7eb;margin:24px 20px 0;
              font-size:12px;color:#9ca3af;line-height:1.9">
    Markt-Monitor &nbsp;·&nbsp; stefan.steinberger16@gmail.com<br>
    <a href="mailto:stefan.steinberger16@gmail.com?subject=ABMELDEN"
       style="color:#9ca3af;text-decoration:underline">Vom Newsletter abmelden</a>
  </div>

</div>
</body>
</html>"""
    return html


def build_subject(alerts):
    worst = "KAUFSIGNAL" if signal_level(alerts) == "red" else "BEOBACHTEN"
    labels = [a["label"].split("(")[0].strip() for a in alerts]
    summary = ", ".join(labels[:2]) + (" + mehr" if len(labels) > 2 else "")
    return f"[Markt-Monitor] {worst} - {summary}"


# ── Telegram alert ───────────────────────────────────────────────────────────

def build_telegram_message(alerts, all_statuses):
    """Compact phone-friendly alert -Telegram supports only basic HTML tags."""
    import html as html_lib

    worst_level = signal_level(alerts)
    header_icon = {
        "red":   "🟢 KAUFSIGNAL",
        "amber": "🟡 BEOBACHTEN",
        "green": "⚪ ALLES NORMAL",
    }[worst_level]

    lines = [
        f"{header_icon} - <b>Markt-Monitor</b>",
        f"<b>{datetime.now().strftime('%d.%m.%Y, %H:%M')}</b>",
        "",
    ]

    # ── Buy signal / Watch: full detail blocks ────────────────────────────────
    for a in alerts:
        icon     = "🟢" if a["level"] == "red" else "🟡"
        label    = html_lib.escape(a["label"])
        compact  = html_lib.escape(a.get("compact", ""))
        scenario = html_lib.escape(a["scenario"])
        news_url = a.get("news_url", "")

        lines.append(f"{icon} <b>{label}</b>")
        lines.append(f"   {compact}")
        lines.append(f"   <i>{scenario}</i>")

        # Group affected stocks by index
        by_index: dict = {}
        for t in a.get("stocks", []):
            idx = TICKER_INDEX.get(t, "Sonstige")
            by_index.setdefault(idx, []).append(TICKER_NAMES.get(t, t))

        for idx_name in ["S&P 500", "DAX", "ATX"]:
            names_list = by_index.get(idx_name, [])
            names_str  = html_lib.escape(", ".join(names_list)) if names_list else "-"
            lines.append(f"   Günstig im {html_lib.escape(idx_name)}: {names_str}")

        if news_url:
            lines.append(f'   <a href="{html_lib.escape(news_url)}">→ Aktuelle Nachrichten</a>')
        lines.append("")

    # ── Normal indicators: compact single lines ───────────────────────────────
    normal = [s for s in all_statuses if s["level"] == "green"]
    if normal:
        for s in normal:
            label   = html_lib.escape(s["label"])
            compact = html_lib.escape(s.get("compact", ""))
            lines.append(f"⚪ {label}: {compact}")
        lines.append("")

    # ── Legend ────────────────────────────────────────────────────────────────
    lines.append("⚪ NORMAL = Kein Signal  🟡 BEOBACHTEN = Im Auge behalten  🟢 KAUFSIGNAL = Jetzt handeln")
    lines.append("📧 Vollständiger Bericht in deiner Inbox.")

    return "\n".join(lines)


# Heartbeat per-indicator display: (raw-value key, short label, unit, decimals).
# Order = how they appear in the weekly message. Thresholds are pulled live from
# INDICATORS / PERIPHERY so this never drifts from the production config.
_HEARTBEAT_ROWS = [
    ("VIX",        "vix",           "VIX (Angst-Index)",          "",     1),
    ("KRE",        "kre_14d_pct",   "KRE (US-Regionalbanken)",    "%",    1),
    ("QQQ",        "qqq_52w_pct",   "QQQ (Nasdaq/Tech)",          "%",    1),
    ("NVDA",       "nvda_52w_pct",  "NVDA (KI-Stimmung)",         "%",    1),
    ("BRENT_HIGH", "brent",         "Brent (Ölpreis)",            " $",   1),
    ("US10Y",      "us10y",         "US-10J (US-Zins)",           "%",    2),
    ("MOVE",       "move",          "MOVE (Anleihe-Volatilität)", "",     0),
    ("PERIPHERY",  "periph_spread", "Peripherie (EU-Staatsanl.)", " bp",  0),
]

# One-line plain-language explainer per indicator: what it measures → what a RED
# reading means → which watchlist names get cheap. Shown under each line when
# heartbeat_explanations is on (default). Turn off once the eight are familiar.
_HEARTBEAT_EXPLAIN = {
    "VIX":        "Marktangst. Rot = Panik-Ausverkauf, Qualität fällt pauschal mit.",
    "KRE":        "US-Regionalbanken. Rot = Bankenangst → USB, M&T fallen mit dem Sektor.",
    "QQQ":        "Tech-Index. Rot = Tech-Korrektur, reißt auch Nicht-Tech mit nach unten.",
    "NVDA":       "KI-Frühindikator. Rot = KI-Stimmung kippt → breiter Tech-Ausverkauf.",
    "BRENT_HIGH": "Ölpreis/Iran. Rot (>130$) = Eskalation → EU-Aktien fallen breit.",
    "US10Y":      "US-Zins. Rot (>5,5%) = höhere Zinsen drücken alle Aktien-Bewertungen.",
    "MOVE":       "„VIX für Anleihen\". Rot = Anleihe-Schock, Vorbote für Zins-/Fiskal-Stress.",
    "PERIPHERY":  "EU-Schuldenstress (Italien). Rot = Allianz, Munich Re, Dt. Börse auf Sale.",
}

_LEVEL_ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}


def _next_threshold_text(key, level):
    """Text for the NEXT threshold: green -> show amber, amber -> show red, red -> done."""
    if key == "PERIPHERY":
        amber, red, check, unit = PERIPHERY["amber"], PERIPHERY["red"], "above", " bp"
    else:
        ind = INDICATORS.get(key)
        if not ind:
            return ""
        amber, red, check, unit = ind["amber"], ind["red"], ind["check"], INDICATOR_UNITS.get(key, "")
    if level == "green":
        word, val = "Gelb", amber
    elif level == "amber":
        word, val = "Rot", red
    else:
        return "bereits ROT"
    prep = "unter" if check == "below" else "ab"
    return f"→ {word} {prep} {_de_thr(val, unit)}"


def build_heartbeat_message(all_statuses, raw, explanations=True, leading=None):
    """Weekly 'still alive' ping for quiet days.

    Edge-triggered alerts mean silence on unchanged days — which is ambiguous:
    all-quiet, or the job is broken? This weekly Telegram message removes that
    ambiguity. If it stops arriving, something is broken (Action, yfinance, or an
    expired secret). One per indicator, with the next threshold to watch, plus a
    standing reminder of why we do this. With explanations=True (default) each
    indicator gets a one-line plain-language explainer; turn off via config once
    the eight are familiar.
    """
    overall = raw.get("overall_level", "green")
    overall_txt = {
        "red":   "🔴 KAUFSIGNAL — jetzt handeln",
        "amber": "🟡 BEOBACHTEN — genau hinsehen",
        "green": "🟢 ALLES GRÜN — nichts zu tun",
    }.get(overall, "🟢 ALLES GRÜN — nichts zu tun")

    level_by_key = {s["key"]: s["level"] for s in all_statuses}

    lines = [
        "💚 <b>QC-Monitor läuft</b> — wöchentlicher Statuscheck",
        f"<b>{_de_date()}, {datetime.now():%H:%M}</b>",
        "",
        f"Gesamtampel: <b>{overall_txt}</b>",
        "",
    ]

    for key, rawkey, label, unit, dec in _HEARTBEAT_ROWS:
        val = raw.get(rawkey)
        if val is None:
            lines.append(f"⚪ <b>{label}</b>: keine Daten")
            continue
        level = level_by_key.get(key, "green")
        icon  = _LEVEL_ICON.get(level, "🟢")
        nxt   = _next_threshold_text(key, level)
        lines.append(f"{icon} <b>{label}</b> {_de_num(val, dec)}{unit} {nxt}")
        if explanations and key in _HEARTBEAT_EXPLAIN:
            lines.append(f"   <i>{_HEARTBEAT_EXPLAIN[key]}</i>")

    # ── Vor-Indikatoren (Stress-Aufbau) — informational, NOT a buy trigger ─────
    if leading:
        lines += [
            "",
            "📡 <b>Vor-Indikatoren</b> (Stress-Aufbau — zählen NICHT zum Kaufsignal, "
            "zeigen nur, welches Szenario sich aufheizt):",
        ]
        for s in leading:
            icon = _LEVEL_ICON.get(s["level"], "🟢")
            lines.append(f"{icon} <b>{s['label']}</b>: {s.get('current', '—')}")
            if explanations and s.get("explain"):
                lines.append(f"   <i>{s['explain']}</i>")

    lines += [
        "",
        "🎯 <b>Warum das hier läuft:</b> Wir warten geduldig auf die seltenen Momente, "
        "in denen der Markt Qualität aus Angst zu billig verkauft — und kaufen dann in "
        "Tranchen. Meistens ist nichts zu tun (grün). Diese Indikatoren zeigen früh, "
        "wann sich ein Discount-Fenster nähert.",
        "",
        "<i>Kommt automatisch jeden Montag. Bleibt die Nachricht aus, ist etwas kaputt.</i>",
    ]
    return "\n".join(lines)


def build_leading_warning_message(newly_red):
    """Telegram 'Vorwarnung' — fires when a CALIBRATED leading indicator first crosses
    to red. Deliberately NOT a KAUFSIGNAL: clearly labelled, separate wording, says
    'prepare the homework', not 'buy'. The discount only exists once the price falls."""
    import html as html_lib
    lines = [
        "📡 <b>VORWARNUNG — kein Kaufsignal</b>",
        f"<b>{_de_date()}, {datetime.now():%H:%M}</b>",
        "",
        "Ein backtesteter <b>Vor-Indikator</b> ist auf <b>Stress-Aufbau (rot)</b> gesprungen. "
        "Das ist <b>kein</b> Kaufsignal — der Discount entsteht erst, wenn der <i>Preis</i> fällt. "
        "Es heißt: jetzt die Hausaufgabe für das betroffene Szenario vorbereiten.",
        "",
    ]
    for s in newly_red:
        lines.append(f"🔴 <b>{html_lib.escape(s['label'])}</b> "
                     f"<i>({html_lib.escape(s.get('lane', ''))})</i>")
        lines.append(f"   {html_lib.escape(s.get('current', ''))}")
        if s.get("explain"):
            lines.append(f"   <i>{html_lib.escape(s['explain'])}</i>")
        lines.append("")
    lines += [
        "<b>Was tun:</b> Zielpreise der betroffenen Watchlist-Namen scharfstellen, "
        "Kapital-/CRE-Quoten prüfen. <b>Nicht kaufen</b>, bis der Preis-Trigger "
        "(KRE / QQQ / US-10J …) fällt und das echte KAUFSIGNAL (≥3 rot) kommt.",
        "",
        "<i>Vor-Indikatoren zählen nie zum ≥3-Kaufsignal — sie warnen nur früher.</i>",
    ]
    return "\n".join(lines)


def send_telegram(cfg, message):
    """Send message via Telegram bot. Returns True on success, False if not configured."""
    tg      = cfg.get("telegram", {})
    token   = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        return False
    if not chat_id or chat_id == "YOUR_TELEGRAM_CHAT_ID_HERE":
        return False
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
    resp.raise_for_status()
    return True


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
        server.send_message(msg)   # send_message includes Bcc recipients, then strips the header
    log.info(f"Email sent to {1 + len(bcc_list)} recipient(s): {subject}")


# ── Welcome email ─────────────────────────────────────────────────────────────

def build_welcome_html():
    today = datetime.now().strftime("%d.%m.%Y")
    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Arial,sans-serif;max-width:680px;margin:0 auto;padding:24px;color:#1f2937">

      <div style="background:#16a34a;color:white;border-radius:8px;padding:20px 24px;margin-bottom:28px">
        <div style="font-size:22px;font-weight:bold">Herzlich willkommen!</div>
        <div style="font-size:14px;margin-top:6px;opacity:.9">Markt-Monitor - {today}</div>
      </div>

      <p style="font-size:15px;line-height:1.7;margin-bottom:20px">
        ich freue mich, dich dabei zu haben! Ich teile diesen täglichen Markt-Monitor,
        weil ich selbst nach einem klaren System investieren will - nach den Prinzipien von
        <strong>Warren Buffett und Charlie Munger</strong>. Die Kernidee ist einfach:
      </p>

      <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:14px 18px;margin:20px 0;font-size:15px;font-style:italic;line-height:1.6">
        Qualitätsunternehmen kaufen, wenn der Markt aus Panik verkauft - nicht wegen
        fundamentaler Probleme der Unternehmen, sondern wegen Angst, Zwangsverkäufen
        oder makroökonomischen Ereignissen, die das Geschäftsmodell gar nicht berühren.
      </div>

      <h2 style="font-size:17px;color:#111827;margin-top:28px">Wie das System funktioniert</h2>
      <p style="font-size:14px;line-height:1.7;color:#374151">
        Täglich laufen 7 Makro-Indikatoren im Hintergrund. Wenn einer davon einen Schwellenwert
        erreicht, bedeutet das: Bestimmte Qualitätsaktien werden gerade aus Gründen günstig, die
        nichts mit ihrem Geschäftsmodell zu tun haben.
      </p>

      <h2 style="font-size:17px;color:#111827;margin-top:28px">Die 7 Indikatoren</h2>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr style="background:#f9fafb">
          <td style="padding:10px 12px;font-weight:bold;border-bottom:1px solid #e5e7eb">VIX - Angst-Index</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151">
            Bei breiter Marktpanik fallen alle Aktien - auch Versicherungen und Banken,
            die nichts mit dem Auslöser zu tun haben. Unterschiedsloser Zwangsverkauf.
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;font-weight:bold;border-bottom:1px solid #e5e7eb">US-Regionalbanken (KRE)</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151">
            Eine Krise im US-Bankensektor zieht konservativ geführte Häuser wie U.S. Bancorp
            oder Erste Group mit runter - obwohl deren Fundamentaldaten intakt sind.
          </td>
        </tr>
        <tr style="background:#f9fafb">
          <td style="padding:10px 12px;font-weight:bold;border-bottom:1px solid #e5e7eb">Nasdaq / NVIDIA</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151">
            Tech-Korrekturen erzwingen Verkäufe in allen Sektoren. Versicherungen und Banken
            fallen mit, obwohl sie null KI-Exposure haben.
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;font-weight:bold;border-bottom:1px solid #e5e7eb">Brent-Öl (hoch/niedrig)</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151">
            Ölpreis-Extremwerte signalisieren Iran-Kriseneskalation oder -entspannung.
            Rückversicherer wie Allianz und Munich Re werden kurzfristig verkauft,
            sind aber langfristig Nutzniesser steigender Katastrophenprämien.
          </td>
        </tr>
        <tr style="background:#f9fafb">
          <td style="padding:10px 12px;font-weight:bold;border-bottom:1px solid #e5e7eb">US 10J-Rendite</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151">
            Steigende Zinsen drücken KGV-Multiples mechanisch nach unten. Gleiche Gewinne,
            niedrigerer fairer Preis - ein rein rechnerischer, kein fundamentaler Effekt.
          </td>
        </tr>
        <tr>
          <td style="padding:10px 12px;font-weight:bold">Atlantik-Hurrikan</td>
          <td style="padding:10px 12px;color:#374151">
            Nach einem schweren Hurrikan fallen Versicherungsaktien 20-35% wegen erwarteter
            Schäden. Der maximale Kursabschlag ist 2-3 Tage nach dem Landfall - genau dann,
            wenn die Prämien für die nächsten Jahre steigen werden.
          </td>
        </tr>
      </table>

      <h2 style="font-size:17px;color:#111827;margin-top:28px">Die Watchlist</h2>
      <p style="font-size:14px;line-height:1.7;color:#374151">
        Ausgewählte Versicherungen, Banken und Infrastrukturunternehmen aus drei Märkten -
        Unternehmen mit nachgewiesenem Franchise, diszipliniertem Management und langfristiger
        Preismacht:
      </p>
      <div style="font-size:13px;color:#374151;line-height:1.8">
        <strong>S&amp;P 500:</strong> Chubb, Cincinnati Financial, Travelers, Progressive, Arch Capital, U.S. Bancorp, M&amp;T Bank, Wells Fargo<br>
        <strong>DAX:</strong> Allianz SE, Munich Re, Hannover Rück, Deutsche Börse, DHL Group<br>
        <strong>ATX:</strong> Erste Group, Vienna Insurance Group, Andritz AG, EVN AG
      </div>

      <h2 style="font-size:17px;color:#111827;margin-top:28px">Was bedeuten die Signale?</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px">
        <tr>
          <td style="padding:10px 12px;font-size:20px">⚪</td>
          <td style="padding:10px 12px;font-weight:bold">NORMAL</td>
          <td style="padding:10px 12px;color:#374151">Kein Signal - du bekommst keine Mail. Alles im Normbereich.</td>
        </tr>
        <tr style="background:#fef3c7">
          <td style="padding:10px 12px;font-size:20px">🟡</td>
          <td style="padding:10px 12px;font-weight:bold">BEOBACHTEN</td>
          <td style="padding:10px 12px;color:#374151">Ein Indikator nähert sich dem Kaufbereich. Noch nicht handeln, aber im Auge behalten.</td>
        </tr>
        <tr style="background:#dcfce7">
          <td style="padding:10px 12px;font-size:20px">🟢</td>
          <td style="padding:10px 12px;font-weight:bold">KAUFSIGNAL</td>
          <td style="padding:10px 12px;color:#374151">Kaufschwelle erreicht. Zeit, genauer hinzuschauen - diese Aktien werden gerade aus den falschen Gründen günstig.</td>
        </tr>
      </table>

      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:14px 18px;margin-top:28px;font-size:12px;color:#6b7280;line-height:1.6">
        <strong style="color:#374151">Rechtlicher Hinweis</strong><br><br>
        Dieser Newsletter ist eine <strong>private, unentgeltliche Marktbeobachtung</strong> und stellt
        ausdrücklich <strong>keine Anlageberatung, Vermögensverwaltung oder Anlageempfehlung</strong>
        im Sinne des Wertpapieraufsichtsgesetzes 2018 (WAG 2018) oder der EU-Richtlinie MiFID II dar.
        Der Autor ist kein konzessionierter Anlageberater oder Wertpapierdienstleister.<br><br>
        Die enthaltenen Informationen dienen ausschließlich der allgemeinen Information und Bildung.
        Sie ersetzen keine individuelle, auf die persönliche Situation abgestimmte Beratung durch einen
        zugelassenen Finanzberater. <strong>Jede Investitionsentscheidung triffst du eigenverantwortlich.</strong><br><br>
        Kapitalanlagen sind mit Risiken verbunden. Es kann zum teilweisen oder vollständigen Verlust
        des eingesetzten Kapitals kommen. Vergangene Wertentwicklungen sind kein verlässlicher Indikator
        für zukünftige Ergebnisse. Alle Inhalte wurden nach bestem Wissen und Gewissen erstellt;
        für die Richtigkeit, Vollständigkeit und Aktualität der Informationen wird keine Haftung übernommen.
      </div>

      <p style="font-size:15px;line-height:1.7;margin-top:24px">
        Ich freue mich auf den gemeinsamen Austausch!<br><br>
        Liebe Grüße,<br>
        <strong>Stefan</strong>
      </p>

      <div style="margin-top:28px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af">
        Du erhältst diese Mail, weil du zum Markt-Monitor-Verteiler hinzugefügt wurdest.
        Schreib mir einfach zurück, falls du dich austragen möchtest.
      </div>

    </body>
    </html>
    """


def check_and_welcome_new_subscribers(cfg):
    """Send a welcome email to any BCC address not yet in known_subscribers.json."""
    import json as _json

    bcc_list = cfg["email"].get("bcc", [])
    if not bcc_list:
        return

    # Load known subscribers
    if SUBSCRIBERS_PATH.exists():
        with open(SUBSCRIBERS_PATH, encoding="utf-8") as f:
            data = _json.load(f)
    else:
        data = {"welcomed": [cfg["email"]["sender"], cfg["email"]["recipient"]]}

    welcomed = set(data.get("welcomed", []))
    new_addresses = [addr for addr in bcc_list if addr not in welcomed]

    if not new_addresses:
        return

    html = build_welcome_html()
    sender    = cfg["email"]["sender"]
    password  = cfg["email"]["app_password"]
    host      = cfg["email"].get("smtp_host", "smtp.gmail.com")
    port      = cfg["email"].get("smtp_port", 465)

    ctx = ssl.create_default_context()
    for address in new_addresses:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Willkommen beim Markt-Monitor"
            msg["From"]    = sender
            msg["To"]      = address
            msg.attach(MIMEText(html, "html", "utf-8"))

            with smtplib.SMTP_SSL(host, port, context=ctx) as server:
                server.login(sender, password)
                server.send_message(msg)

            welcomed.add(address)
            log.info(f"Welcome email sent to {address}")
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] Welcome email sent to {address}")
        except Exception as exc:
            log.warning(f"Welcome email failed for {address}: {exc}")
            print(f"Welcome email error for {address}: {exc}")

    # Persist updated list
    data["welcomed"] = sorted(welcomed)
    with open(SUBSCRIBERS_PATH, "w", encoding="utf-8") as f:
        _json.dump(data, f, indent=2, ensure_ascii=False)


# ── Status page generator ─────────────────────────────────────────────────────

def generate_status_html(all_statuses, raw, leading=None):
    """Rewrite website/status.html with today's indicator readings. Called on every run."""
    import html as _h

    overall  = raw.get("overall_level", "green")
    now_str  = datetime.now().strftime("%d. %B %Y, %H:%M")

    BANNER_ICON  = {"green": "⚪", "amber": "🟡", "red": "🟢"}
    BANNER_LABEL = {"green": "ALLES NORMAL", "amber": "BEOBACHTEN", "red": "KAUFSIGNAL"}
    BANNER_COLOR = {"green": "#374151", "amber": "#92400e", "red": "#166534"}
    BANNER_BG    = {"green": "#f3f4f6", "amber": "#fef9c3", "red": "#dcfce7"}

    ROW_ICON   = {"green": "⚪", "amber": "🟡", "red": "🟢"}
    ROW_BG     = {"green": "#f9fafb", "amber": "#fef9c3", "red": "#dcfce7"}
    ROW_BORDER = {"green": "#e5e7eb", "amber": "#fde68a", "red": "#86efac"}

    b_icon  = BANNER_ICON[overall]
    b_label = BANNER_LABEL[overall]
    b_bg    = BANNER_BG[overall]
    b_color = BANNER_COLOR[overall]

    # ── Indicator rows ────────────────────────────────────────────────────────
    indicator_rows = ""
    for s in all_statuses:
        lvl     = s["level"]
        icon    = ROW_ICON.get(lvl, "⚪")
        bg      = ROW_BG.get(lvl, "#f9fafb")
        border  = ROW_BORDER.get(lvl, "#e5e7eb")
        label   = _h.escape(s["label"])
        compact = _h.escape(s.get("compact", ""))
        indicator_rows += (
            f'<div style="display:flex;align-items:center;gap:16px;padding:14px 20px;'
            f'background:{bg};border-bottom:1px solid {border}">'
            f'<div style="font-size:22px;min-width:28px;text-align:center">{icon}</div>'
            f'<div style="flex:1">'
            f'<div style="font-weight:600;font-size:14px;color:#111827">{label}</div>'
            f'<div style="font-size:13px;color:#4b5563;font-family:monospace;margin-top:2px">{compact}</div>'
            f'</div></div>\n'
        )

    # ── Vor-Indikatoren (Stress-Aufbau) — separate, informational section ──────
    # These are leading indicators: they show stress BUILDING, not the panic itself.
    # They never drive the banner / KAUFSIGNAL — purely "which scenario is heating up".
    leading_section = ""
    if leading:
        lead_rows = ""
        for s in leading:
            lvl     = s["level"]
            l_icon  = ROW_ICON.get(lvl, "⚪")
            l_bg    = ROW_BG.get(lvl, "#f9fafb")
            l_bord  = ROW_BORDER.get(lvl, "#e5e7eb")
            l_label = _h.escape(s["label"])
            l_lane  = _h.escape(s.get("lane", ""))
            l_cur   = _h.escape(s.get("current", "—"))
            l_expl  = _h.escape(s.get("explain", ""))
            lead_rows += (
                f'<div style="padding:14px 20px;background:{l_bg};border-bottom:1px solid {l_bord}">'
                f'<div style="display:flex;align-items:center;gap:16px">'
                f'<div style="font-size:22px;min-width:28px;text-align:center">{l_icon}</div>'
                f'<div style="flex:1">'
                f'<div style="font-weight:600;font-size:14px;color:#111827">{l_label} '
                f'<span style="font-weight:400;font-size:11px;color:#9ca3af">· {l_lane}</span></div>'
                f'<div style="font-size:13px;color:#4b5563;font-family:monospace;margin-top:2px">{l_cur}</div>'
                f'</div></div>'
                f'<div style="font-size:12px;color:#6b7280;margin-top:6px;padding-left:44px">{l_expl}</div>'
                f'</div>\n'
            )
        leading_section = (
            '<section style="padding:0 0 48px">'
            '<div style="max-width:780px;margin:0 auto;padding:0 24px">'
            '<h2 style="font-size:22px;font-weight:800;color:#111827;margin-bottom:8px">'
            'Vor-Indikatoren <span style="font-size:14px;font-weight:600;color:#9ca3af">(Stress-Aufbau)</span></h2>'
            '<p style="font-size:15px;color:#6b7280;margin-bottom:24px">'
            'Diese Kennzahlen zeigen, ob sich <em>unter der Oberfläche</em> Stress aufbaut — '
            'früher als die Panik-Indikatoren oben. Sie sind <strong>kein Kaufsignal</strong>, '
            'sondern zeigen, welches Krisen-Szenario sich aufheizt. Schwellen sind vorläufig.</p>'
            '<div style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">'
            f'{lead_rows}'
            '</div></div></section>'
        )

    # ── Buy opportunities (only when alerts exist) ────────────────────────────
    alerts = [s for s in all_statuses if s["level"] != "green"]
    buy_section = ""
    if alerts:
        cards = ""
        for a in alerts:
            lvl        = a["level"]
            icon       = ROW_ICON.get(lvl, "🟡")
            bg         = ROW_BG.get(lvl, "#fef9c3")
            border     = ROW_BORDER.get(lvl, "#fde68a")
            a_label    = _h.escape(a["label"])
            a_compact  = _h.escape(a.get("compact", ""))
            a_scenario = _h.escape(a.get("scenario", ""))
            news_url   = a.get("news_url", "")

            by_index: dict = {}
            for t in a.get("stocks", []):
                idx = TICKER_INDEX.get(t, "Sonstige")
                by_index.setdefault(idx, []).append(TICKER_NAMES.get(t, t))

            stock_lines = "".join(
                f'<div style="margin-bottom:4px"><strong>{_h.escape(idx_name)}:</strong> '
                f'{_h.escape(", ".join(names))}</div>'
                for idx_name in ["S&P 500", "DAX", "ATX"]
                if (names := by_index.get(idx_name, []))
            )
            news_link = (
                f'<div style="margin-top:10px">'
                f'<a href="{_h.escape(news_url)}" style="color:#16a34a;font-size:13px">'
                f'→ Aktuelle Nachrichten</a></div>'
                if news_url else ""
            )
            cards += (
                f'<div style="border:1px solid {border};border-radius:10px;overflow:hidden;margin-bottom:16px">'
                f'<div style="background:{bg};padding:14px 18px;border-bottom:1px solid {border}">'
                f'<div style="font-weight:700;font-size:15px">{icon} {a_label}</div>'
                f'<div style="font-size:13px;color:#4b5563;margin-top:4px;font-family:monospace">{a_compact}</div>'
                f'</div>'
                f'<div style="padding:14px 18px;background:white">'
                f'<div style="font-size:13px;color:#374151;font-style:italic;margin-bottom:12px">{a_scenario}</div>'
                f'<div style="font-size:13px;color:#374151">{stock_lines}</div>'
                f'{news_link}</div></div>\n'
            )
        buy_section = (
            '<section style="padding:48px 0;background:white">'
            '<div style="max-width:780px;margin:0 auto;padding:0 24px">'
            '<h2 style="font-size:22px;font-weight:800;color:#111827;margin-bottom:8px">Jetzt günstig</h2>'
            '<p style="font-size:15px;color:#6b7280;margin-bottom:24px">'
            'Diese Aktien werden aus makroökonomischen Gründen günstiger - '
            'nicht wegen fundamentaler Probleme.</p>'
            f'{cards}'
            '</div></section>'
        )

    # ── Full page ─────────────────────────────────────────────────────────────
    page = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Aktueller Stand - Markt-Monitor</title>
  <meta name="description" content="Tagesaktueller Stand aller Marktindikatoren. Zuletzt aktualisiert: {now_str}.">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; color: #1f2937; background: #f9fafb; }}
    a {{ color: #16a34a; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>

<nav style="background:white;border-bottom:1px solid #e5e7eb;padding:16px 0">
  <div style="max-width:780px;margin:0 auto;padding:0 24px;display:flex;align-items:center;justify-content:space-between">
    <a href="index.html" style="font-size:14px;color:#6b7280">← Zur Übersicht</a>
    <div style="font-weight:700;font-size:16px;color:#16a34a">🟢 <span style="color:#1f2937">Markt-Monitor</span></div>
  </div>
</nav>

<div style="background:{b_bg};border-bottom:1px solid #e5e7eb;padding:40px 0;text-align:center">
  <div style="max-width:780px;margin:0 auto;padding:0 24px">
    <div style="font-size:52px;margin-bottom:12px">{b_icon}</div>
    <div style="font-size:30px;font-weight:800;color:{b_color};margin-bottom:10px">{b_label}</div>
    <div style="font-size:14px;color:#6b7280">Zuletzt aktualisiert: {now_str}</div>
    <div style="font-size:13px;color:#9ca3af;margin-top:4px">Automatische Aktualisierung täglich</div>
  </div>
</div>

<section style="padding:48px 0">
  <div style="max-width:780px;margin:0 auto;padding:0 24px">
    <h2 style="font-size:22px;font-weight:800;color:#111827;margin-bottom:8px">Alle Indikatoren</h2>
    <p style="font-size:15px;color:#6b7280;margin-bottom:24px">Stand: {now_str}</p>
    <div style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">
      {indicator_rows}
    </div>
  </div>
</section>

{leading_section}

{buy_section}

<div style="background:#111827;color:white;text-align:center;padding:56px 24px">
  <div style="font-size:22px;font-weight:800;margin-bottom:10px">Alerts direkt ins Postfach</div>
  <p style="font-size:15px;color:#9ca3af;max-width:480px;margin:0 auto 28px;line-height:1.6">
    Kostenloser privater Newsletter. E-Mail und Telegram-Nachricht,
    sobald ein Indikator eine Kaufschwelle erreicht.
  </p>
  <a href="index.html#signup"
     style="display:inline-block;background:#16a34a;color:white;padding:13px 32px;border-radius:8px;font-weight:600;font-size:15px">
    Jetzt abonnieren →
  </a>
</div>

<div style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:32px 0">
  <div style="max-width:780px;margin:0 auto;padding:0 24px">
    <p style="font-size:12px;color:#9ca3af;line-height:1.7">
      <strong style="color:#6b7280">Rechtlicher Hinweis:</strong>
      Diese Seite ist eine private, unentgeltliche Marktbeobachtung und stellt ausdrücklich keine Anlageberatung,
      Vermögensverwaltung oder Anlageempfehlung im Sinne des WAG 2018 oder der EU-Richtlinie MiFID II dar.
      Der Betreiber ist kein konzessionierter Anlageberater. Kapitalanlagen sind mit Risiken verbunden,
      einschließlich des vollständigen Kapitalverlusts. Vergangene Wertentwicklungen sind kein verlässlicher
      Indikator für künftige Ergebnisse. Jede Investitionsentscheidung liegt in der alleinigen Verantwortung
      des Lesers.
    </p>
  </div>
</div>

<footer style="background:#111827;color:#6b7280;text-align:center;padding:20px;font-size:13px">
  Markt-Monitor &nbsp;·&nbsp;
  <a href="mailto:stefan.steinberger16@gmail.com" style="color:#6b7280">stefan.steinberger16@gmail.com</a>
  &nbsp;·&nbsp;
  <a href="index.html" style="color:#6b7280">Hauptseite</a>
</footer>

</body>
</html>"""

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(page, encoding="utf-8")
    log.info(f"status.html updated: {now_str}")
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] status.html updated")


# ── Auto-subscriber ingestion via IMAP ───────────────────────────────────────

def save_cfg(cfg):
    """Write updated config back to disk (persists new BCC entries)."""
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def check_new_subscribers_via_imap(cfg):
    """
    Poll Gmail for Formspree signup notifications, add new addresses to BCC.
    Looks for unread emails with subject containing 'Markt-Monitor Anmeldung'.
    Returns list of newly added email addresses.
    """
    email_cfg = cfg["email"]
    excluded = {email_cfg["sender"].lower(), "noreply@formspree.io"}

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_cfg["sender"], email_cfg["app_password"])
        mail.select("INBOX")

        _, ids = mail.search(None, '(UNSEEN SUBJECT "Markt-Monitor Anmeldung")')
        if not ids[0]:
            mail.close()
            mail.logout()
            return []

        new_emails = []
        for msg_id in ids[0].split():
            _, data = mail.fetch(msg_id, "(RFC822)")
            msg = stdlib_email.message_from_bytes(data[0][1])

            # Extract plain-text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

            # Find subscriber email — any address in body that isn't ours or Formspree's
            found = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", body)
            subscriber = next((e.lower() for e in found if e.lower() not in excluded), None)

            if subscriber and subscriber not in [b.lower() for b in cfg["email"]["bcc"]]:
                cfg["email"]["bcc"].append(subscriber)
                new_emails.append(subscriber)
                log.info(f"New subscriber from form: {subscriber}")

            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close()
        mail.logout()
        return new_emails

    except Exception as exc:
        log.warning(f"IMAP subscriber check skipped: {exc}")
        return []


def check_unsubscribe_requests_via_imap(cfg):
    """
    Poll Gmail for emails with subject 'ABMELDEN' sent by current BCC subscribers.
    Removes matching addresses from BCC. Returns list of removed addresses.
    """
    email_cfg    = cfg["email"]
    sender_email = email_cfg["sender"].lower()
    bcc_lower    = {b.lower(): b for b in email_cfg.get("bcc", [])}

    if not bcc_lower:
        return []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_cfg["sender"], email_cfg["app_password"])
        mail.select("INBOX")

        _, ids = mail.search(None, '(UNSEEN SUBJECT "ABMELDEN")')
        if not ids[0]:
            mail.close()
            mail.logout()
            return []

        removed = []
        for msg_id in ids[0].split():
            _, data = mail.fetch(msg_id, "(RFC822)")
            msg = stdlib_email.message_from_bytes(data[0][1])

            from_raw  = msg.get("From", "")
            found     = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", from_raw)
            requester = next((e.lower() for e in found if e.lower() != sender_email), None)

            if requester and requester in bcc_lower:
                original = bcc_lower[requester]
                cfg["email"]["bcc"] = [b for b in cfg["email"]["bcc"]
                                       if b.lower() != requester]
                removed.append(original)
                log.info(f"Unsubscribed: {original}")
                print(f"[{datetime.now():%Y-%m-%d %H:%M}] Unsubscribed: {original}")

            mail.store(msg_id, "+FLAGS", "\\Seen")

        mail.close()
        mail.logout()
        return removed

    except Exception as exc:
        log.warning(f"IMAP unsubscribe check skipped: {exc}")
        return []


# ── Analysis-session staleness check ─────────────────────────────────────────

def check_watchlist_staleness(cfg):
    """
    Scan TOOLS/market-analysis/ for session folders newer than watchlist.json.
    Sends a one-time Telegram reminder per new session; tracks via cfg.
    """
    import re
    from datetime import date as date_cls

    if not MARKET_ANALYSIS_DIR.exists():
        return

    date_re = re.compile(r"^(\d{4}-\d{2}-\d{2})")
    session_dates = []
    for item in MARKET_ANALYSIS_DIR.iterdir():
        if item.is_dir():
            m = date_re.match(item.name)
            if m:
                try:
                    session_dates.append(date_cls.fromisoformat(m.group(1)))
                except ValueError:
                    pass

    if not session_dates:
        return

    latest_session = max(session_dates)

    # What date is the watchlist currently based on?
    watchlist_date = None
    if WATCHLIST_PATH.exists():
        try:
            with open(WATCHLIST_PATH, encoding="utf-8") as f:
                wl = json.load(f)
            lu = wl.get("last_updated", "")
            if lu:
                watchlist_date = date_cls.fromisoformat(lu)
        except Exception:
            pass

    if watchlist_date and latest_session <= watchlist_date:
        return  # Watchlist is up to date

    # Already sent reminder for this exact session date?
    last_reminded = cfg.get("last_watchlist_reminder_session", "")
    if last_reminded == latest_session.isoformat():
        return

    # Send Telegram reminder
    session_str   = latest_session.strftime("%d.%m.%Y")
    watchlist_str = watchlist_date.strftime("%d.%m.%Y") if watchlist_date else "noch nie"
    msg = (
        f"📋 <b>Watchlist-Erinnerung</b>\n\n"
        f"Neue Analyse-Session gefunden: <b>{session_str}</b>\n"
        f"Watchlist zuletzt aktualisiert: {watchlist_str}\n\n"
        f"<b>Was zu tun ist:</b>\n"
        f"1. Analyse-Session in <code>market-analysis/{latest_session} Session/</code> reviewen\n"
        f"2. <code>config/watchlist.json</code> mit neuen Aktien + KGV-Schwellenwerten updaten\n"
        f"3. <code>last_updated</code> und <code>session</code> Felder in watchlist.json setzen\n"
        f"4. Commit + Push → QC Monitor liest die neue Liste morgen früh automatisch"
    )
    send_telegram(cfg, msg)

    # Remember we reminded about this session
    cfg["last_watchlist_reminder_session"] = latest_session.isoformat()
    save_cfg(cfg)
    log.info(f"Watchlist staleness reminder sent for session {latest_session}")
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Watchlist reminder sent: new session {latest_session}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Monitor run started ===")

    # Load config
    if not CFG_PATH.exists():
        print(f"Config not found: {CFG_PATH}\nRun once to create it, then add your Gmail App Password.")
        log.error("Config file missing")
        return

    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)

    if cfg["email"]["app_password"] == "YOUR_GMAIL_APP_PASSWORD_HERE":
        print("Please add your Gmail App Password to monitor_config.json")
        log.error("Gmail App Password not configured")
        return

    # Check if a newer analysis session exists than the current watchlist
    check_watchlist_staleness(cfg)

    # Pull new subscribers from Formspree notification emails in Gmail
    new_from_form = check_new_subscribers_via_imap(cfg)
    if new_from_form:
        save_cfg(cfg)
        log.info(f"Added {len(new_from_form)} new subscriber(s) from web form")

    # Process unsubscribe requests (subject: ABMELDEN)
    removed = check_unsubscribe_requests_via_imap(cfg)
    if removed:
        save_cfg(cfg)
        log.info(f"Removed {len(removed)} subscriber(s): {removed}")

    # Welcome any new BCC subscribers before the regular run
    check_and_welcome_new_subscribers(cfg)

    # Fetch + evaluate
    try:
        closes = fetch_price_data()
    except Exception as exc:
        log.error(f"Data fetch failed: {exc}")
        return

    watchlist = fetch_watchlist_prices()

    alerts, all_statuses, raw = evaluate(closes)

    # Vor-Indikatoren (Stress-Aufbau): leading, informational only. Computed
    # separately so they can NEVER affect alerts / overall_level / KAUFSIGNAL.
    prev_leading = read_last_leading_levels()   # read BEFORE we append today's row
    try:
        leading, raw_leading = evaluate_leading()
    except Exception as exc:
        log.warning(f"Leading-indicator evaluation failed (non-fatal): {exc}")
        leading, raw_leading = [], {}

    # Edge-triggered: notify only when the signal level CHANGES vs the last run
    # (the previous state is read from the CSV). This stops the daily repeat-pings
    # when nothing has changed — silence means "no change", which is the design.
    current_signal = raw["overall_level"]
    last_signal    = read_last_overall_level()

    alert_sent = False
    if alerts and current_signal != last_signal:
        subject = build_subject(alerts)
        html    = build_html(alerts, closes, watchlist)
        tg_msg  = build_telegram_message(alerts, all_statuses)

        # Email (rich HTML report)
        try:
            send_email(cfg, subject, html)
            alert_sent = True
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] Email sent: {subject}")
        except Exception as exc:
            log.error(f"Email failed: {exc}")
            print(f"Email error: {exc}")

        # Telegram (concise phone alert)
        try:
            if send_telegram(cfg, tg_msg):
                alert_sent = True
                log.info("Telegram alert sent")
                print(f"[{datetime.now():%Y-%m-%d %H:%M}] Telegram alert sent")
            else:
                log.info("Telegram not configured -skipped")
        except Exception as exc:
            log.warning(f"Telegram failed: {exc}")
            print(f"Telegram error (non-fatal): {exc}")
    elif alerts:
        log.info(f"Signal unchanged ({current_signal}) since last run -no notification (edge-triggered)")
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] Signal unchanged ({current_signal}). No notification.")
    else:
        log.info("All indicators green -no alerts sent")
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] All green. No alerts.")

    # ── Vor-Indikator-Vorwarnung ──────────────────────────────────────────────
    # Edge-triggered, Telegram-only, CALIBRATED indicators only. Fires when a
    # back-tested leading indicator FIRST crosses to red (vs the last run). It is
    # NOT a KAUFSIGNAL and is fully independent of the alert logic above — it never
    # touches overall_level / the ≥3 rule. The discount only exists once the price
    # falls, so this says "prepare the homework", not "buy".
    newly_red = [s for s in leading
                 if s["key"] in CALIBRATED_LEADING and s["level"] == "red"
                 and prev_leading.get(f"lead_{s['key'].lower()}_level") != "red"]
    if newly_red:
        try:
            if send_telegram(cfg, build_leading_warning_message(newly_red)):
                log.info(f"Vorwarnung sent: {[s['key'] for s in newly_red]}")
                print(f"[{datetime.now():%Y-%m-%d %H:%M}] Vorwarnung sent "
                      f"({', '.join(s['key'] for s in newly_red)})")
        except Exception as exc:
            log.warning(f"Vorwarnung failed (non-fatal): {exc}")

    # ── Weekly heartbeat ──────────────────────────────────────────────────────
    # Prove the monitor is alive on quiet days. Only when no alert already went
    # out (a real alert is itself proof of life) and only on the configured
    # weekday (default Monday = 0). Telegram only — one low-friction ping.
    hb_enabled = cfg.get("heartbeat_enabled", True)
    hb_weekday = cfg.get("heartbeat_weekday", 0)        # 0 = Monday
    hb_explain = cfg.get("heartbeat_explanations", True)  # per-indicator explainers
    if hb_enabled and not alert_sent and datetime.now().weekday() == hb_weekday:
        try:
            if send_telegram(cfg, build_heartbeat_message(all_statuses, raw, hb_explain, leading)):
                log.info("Heartbeat sent")
                print(f"[{datetime.now():%Y-%m-%d %H:%M}] Heartbeat sent")
            else:
                log.info("Heartbeat skipped -Telegram not configured")
        except Exception as exc:
            log.warning(f"Heartbeat failed: {exc}")
            print(f"Heartbeat error (non-fatal): {exc}")

    write_to_csv(raw, alert_sent)
    write_leading_csv(raw_leading)
    generate_status_html(all_statuses, raw, leading)


if __name__ == "__main__":
    main()


# ══════════════════════════════════════════════════════════════════════════════
# WINDOWS TASK SCHEDULER SETUP (run once, in PowerShell as Administrator)
# ══════════════════════════════════════════════════════════════════════════════
#
# Replace <YOUR_PYTHON_PATH> with the result of: (Get-Command python).Source
# Replace <SCRIPT_PATH> with the full path to this file
#
#   $action  = New-ScheduledTaskAction `
#                  -Execute "<YOUR_PYTHON_PATH>" `
#                  -Argument "<SCRIPT_PATH>" `
#                  -WorkingDirectory "<SCRIPT_FOLDER>"
#
#   $trigger = New-ScheduledTaskTrigger -Daily -At "08:00AM"
#
#   $settings = New-ScheduledTaskSettingsSet `
#                   -StartWhenAvailable `
#                   -RunOnlyIfNetworkAvailable
#
#   Register-ScheduledTask `
#       -TaskName "MarketMonitor" `
#       -Action $action `
#       -Trigger $trigger `
#       -Settings $settings `
#       -RunLevel Highest
#
# To test immediately:  python market_monitor.py
# To view logs:         notepad monitor_log.txt
# ══════════════════════════════════════════════════════════════════════════════
