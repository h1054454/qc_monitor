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
BASE_DIR         = Path(__file__).parent.parent        # QC_Monitor/
CFG_PATH         = BASE_DIR / "config" / "monitor_config.json"
LOG_PATH         = BASE_DIR / "logs"   / "monitor_log.txt"
CSV_PATH         = BASE_DIR / "data"   / "indicator_history.csv"
SUBSCRIBERS_PATH = BASE_DIR / "config" / "known_subscribers.json"
STATUS_PATH      = BASE_DIR / "docs"    / "status.html"

CSV_COLUMNS = [
    "date",
    "vix", "vix_level",
    "kre_price", "kre_14d_pct", "kre_level",
    "qqq_price", "qqq_52w_pct", "qqq_level",
    "nvda_price", "nvda_52w_pct", "nvda_level",
    "brent", "brent_high_level", "brent_low_level",
    "us10y", "us10y_level",
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


# ── Buy-target P/E table ──────────────────────────────────────────────────────
BUY_TARGETS = {
    "ALV":  {"name": "Allianz SE",             "curr": 8.93,  "amber": 8.0,  "red": 6.5},
    "MUV2": {"name": "Munich Re",              "curr": 11.76, "amber": 10.0, "red": 8.5},
    "HNR1": {"name": "Hannover Rück",          "curr": 13.0,  "amber": 11.0, "red": 9.0},
    "CB":   {"name": "Chubb",                  "curr": 11.45, "amber": 10.0, "red": 8.0},
    "CINF": {"name": "Cincinnati Financial",   "curr": 9.52,  "amber": 8.5,  "red": 7.0},
    "TRV":  {"name": "Travelers",              "curr": 8.91,  "amber": 8.0,  "red": 6.5},
    "PGR":  {"name": "Progressive",            "curr": 10.15, "amber": 9.0,  "red": 7.5},
    "ACGL": {"name": "Arch Capital",           "curr": 7.21,  "amber": 6.5,  "red": 5.5},
    "DB1":  {"name": "Deutsche Börse",         "curr": 20.0,  "amber": 17.0, "red": 14.0},
    "USB":  {"name": "U.S. Bancorp",           "curr": 11.11, "amber": 10.0, "red": 8.0},
    "MTB":  {"name": "M&T Bank",               "curr": 11.47, "amber": 10.0, "red": 8.0},
    "WFC":  {"name": "Wells Fargo",            "curr": 11.33, "amber": 9.5,  "red": 8.0},
    "SAP":  {"name": "SAP SE",                 "curr": 22.0,  "amber": 18.0, "red": 15.0},
}

# ── Ticker → full company name (for readable alert messages) ─────────────────
TICKER_NAMES = {
    # S&P 500
    "CB":   "Chubb",
    "CINF": "Cincinnati Financial",
    "TRV":  "Travelers",
    "PGR":  "Progressive",
    "ACGL": "Arch Capital",
    "USB":  "U.S. Bancorp",
    "MTB":  "M&T Bank",
    "WFC":  "Wells Fargo",
    "BAC":  "Bank of America",
    # DAX
    "ALV":  "Allianz SE",
    "MUV2": "Munich Re",
    "HNR1": "Hannover Rück",
    "DB1":  "Deutsche Börse",
    "DHL":  "DHL Group",
    "RWE":  "RWE AG",
    "SAP":  "SAP SE",
    # ATX
    "EBS":  "Erste Group",
    "VIG":  "Vienna Insurance Group",
    "OMV":  "OMV AG",
    "RBI":  "Raiffeisen Bank",
    "ANDR": "Andritz AG",
    "EVN":  "EVN AG",
}

TICKER_INDEX = {
    # S&P 500
    "CB": "S&P 500", "CINF": "S&P 500", "TRV": "S&P 500", "PGR": "S&P 500",
    "ACGL": "S&P 500", "USB": "S&P 500", "MTB": "S&P 500", "WFC": "S&P 500", "BAC": "S&P 500",
    # DAX
    "ALV": "DAX", "MUV2": "DAX", "HNR1": "DAX", "DB1": "DAX", "DHL": "DAX", "RWE": "DAX",
    "SAP": "DAX",
    # ATX
    "EBS": "ATX", "VIG": "ATX", "OMV": "ATX", "RBI": "ATX", "ANDR": "ATX", "EVN": "ATX",
}

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
            "Jede Aktie wird relativ zum risikofreien Zins bewertet. Eine 10J-Rendite von 5,5%+ "
            "bedeutet: Eine Aktie, die bei KGV 15 fair war, ist nun nur bei KGV 10 fair -"
            "gleiche Gewinne, niedrigerer Preis. Qualitätsunternehmen werden aus einem rein "
            "mechanischen, nicht fundamentalen Grund günstig."
        ),
        "news_url": "https://news.google.com/search?q=US+Staatsanleihen+Rendite+Zinsanstieg&hl=de&gl=AT",
        "stocks": ["CINF", "CB", "TRV", "PGR", "USB", "MTB", "WFC", "ALV", "MUV2", "HNR1", "VIG", "EBS"],
    },
}

HURRICANE_MONTHS = {6, 7, 8, 9, 10, 11}
NOAA_ACTIVE_STORMS_URL = "https://www.nhc.noaa.gov/activestorms.xml"


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


def _build_intro(alerts: list) -> str:
    """Build a dynamic German intro paragraph: duration + proximity to next threshold."""
    if not alerts:
        return ""

    sentences = []
    for a in alerts:
        key   = a.get("key", "")
        days  = _consecutive_days(key)
        label = a["label"]
        current_str = a.get("current", "")

        # Proximity: distance to buy-signal threshold
        ind = INDICATORS.get(key, {})
        red_thr  = ind.get("red")
        unit_str = INDICATOR_UNITS.get(key, "")
        proximity = ""
        if red_thr is not None:
            proximity = f" — Kaufsignal ab {_de_thr(red_thr, unit_str)}"

        val_info = f"({current_str}{proximity})"

        if days <= 1:
            sentences.append(
                f"<strong>{label}</strong> hat heute die Warnschwelle überschritten {val_info}."
            )
        else:
            sentences.append(
                f"<strong>{label}</strong> befindet sich seit {days} Tagen im erhöhten Bereich {val_info}."
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

        status = {
            "key": key, "level": level, "label": ind["label"],
            "compact": compact,
            "current": display_current, "threshold": display_threshold,
            "scenario": ind["scenario"], "why_discount": ind["why_discount"],
            "news_url": ind.get("news_url", ""),
            "stocks": ind["stocks"],
        }
        all_statuses.append(status)
        if level != "green":
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

    all_levels = [a["level"] for a in alerts]
    raw["overall_level"] = "red" if "red" in all_levels else ("amber" if "amber" in all_levels else "green")

    return alerts, all_statuses, raw


# ── CSV logger ────────────────────────────────────────────────────────────────

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


# ── Email builder ─────────────────────────────────────────────────────────────

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


def build_html(alerts):
    today        = _de_date()
    time_str     = datetime.now().strftime("%H:%M")
    worst        = "red" if any(a["level"] == "red" for a in alerts) else "amber"
    header_color = LEVEL_COLOR[worst]
    header_label = LEVEL_LABEL[worst]

    cards = ""
    for a in alerts:
        c    = LEVEL_COLOR[a["level"]]
        bg   = STOCK_COLORS[a["level"]]
        rows = buy_target_rows(a["stocks"])

        by_index: dict = {}
        for t in a.get("stocks", []):
            idx = TICKER_INDEX.get(t, "Sonstige")
            by_index.setdefault(idx, []).append(TICKER_NAMES.get(t, t))
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
        news_url = a.get("news_url", "")

        cards += f"""
        <div style="background:#fff;border-radius:8px;margin:0 0 16px;
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

            <div style="font-size:13px;color:#374151;margin-bottom:14px;line-height:1.7">
              <strong>Warum jetzt günstiger — ohne fundamentalen Grund:</strong><br>
              {a['why_discount']}
            </div>

            <div style="font-size:13px;color:#374151;margin-bottom:14px">
              <strong>Aktuell günstig:</strong>
              <div style="margin-top:8px;line-height:2">{stock_lines}</div>
              {"" if not news_url else
               f'<div style="margin-top:8px"><a href="{news_url}" '
               f'style="color:#0284c7;font-size:13px">→ Aktuelle Nachrichten</a></div>'}
            </div>

            <div class="kgv-wrap" style="overflow-x:auto">
              <table style="width:100%;border-collapse:collapse;font-size:13px;
                            background:{bg};border-radius:6px;overflow:hidden">
                <thead>
                  <tr style="background:{c};color:white">
                    <th style="padding:8px 10px;text-align:left;font-weight:600">Ticker</th>
                    <th style="padding:8px 10px;text-align:left;font-weight:600">Unternehmen</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Aktuelles KGV</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Beobachten</th>
                    <th style="padding:8px 10px;text-align:center;font-weight:600">Kaufsignal</th>
                  </tr>
                </thead>
                <tbody>{rows}</tbody>
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

  <!-- Header -->
  <div style="background:#111827;padding:18px 24px;border-radius:0 0 0 0">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <div style="font-size:12px;font-weight:700;letter-spacing:.12em;color:#9ca3af;
                  text-transform:uppercase">Markt-Monitor</div>
      <div style="font-size:12px;color:#6b7280">{today} &nbsp;·&nbsp; {time_str} Uhr</div>
    </div>
    <div class="header-title" style="margin-top:10px;font-size:22px;font-weight:800;
         color:white;letter-spacing:-.01em">{header_label}</div>
    <div style="margin-top:4px">
      <span style="display:inline-block;background:{header_color};color:#fff;
                   font-size:11px;font-weight:700;padding:3px 12px;border-radius:20px;
                   letter-spacing:.06em;text-transform:uppercase">
        {header_label}
      </span>
    </div>
  </div>

  <!-- Intro -->
  <div style="padding:20px 20px 4px">
    {_build_intro(alerts)}
  </div>

  <!-- Cards -->
  <div style="padding:0 20px">
    {cards}
  </div>

  <!-- Manual check -->
  <div style="padding:0 20px">
    {manual_check}
  </div>

  <!-- Footer -->
  <div style="padding:24px 20px 0;border-top:1px solid #e5e7eb;margin:24px 20px 0;
              font-size:12px;color:#9ca3af;line-height:1.9">
    Markt-Monitor &nbsp;·&nbsp; stefan.steinberger16@gmail.com<br>
    Zum Abmelden einfach auf diese E-Mail antworten.
  </div>

</div>
</body>
</html>"""
    return html


def build_subject(alerts):
    worst = "KAUFSIGNAL" if any(a["level"] == "red" for a in alerts) else "BEOBACHTEN"
    labels = [a["label"].split("(")[0].strip() for a in alerts]
    summary = ", ".join(labels[:2]) + (" + mehr" if len(labels) > 2 else "")
    return f"[Markt-Monitor] {worst} - {summary}"


# ── Telegram alert ───────────────────────────────────────────────────────────

def build_telegram_message(alerts, all_statuses):
    """Compact phone-friendly alert -Telegram supports only basic HTML tags."""
    import html as html_lib

    worst_level = (
        "red"   if any(a["level"] == "red"   for a in alerts) else
        "amber" if alerts else
        "green"
    )
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

def generate_status_html(all_statuses, raw):
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Monitor run started ===")

    # Load config
    if not CFG_PATH.exists():
        print(f"Config not found: {CFG_PATH}\nRun once to create it, then add your Gmail App Password.")
        log.error("Config file missing")
        return

    with open(CFG_PATH) as f:
        cfg = json.load(f)

    if cfg["email"]["app_password"] == "YOUR_GMAIL_APP_PASSWORD_HERE":
        print("Please add your Gmail App Password to monitor_config.json")
        log.error("Gmail App Password not configured")
        return

    # Pull new subscribers from Formspree notification emails in Gmail
    new_from_form = check_new_subscribers_via_imap(cfg)
    if new_from_form:
        save_cfg(cfg)
        log.info(f"Added {len(new_from_form)} new subscriber(s) from web form")

    # Welcome any new BCC subscribers before the regular run
    check_and_welcome_new_subscribers(cfg)

    # Fetch + evaluate
    try:
        closes = fetch_price_data()
    except Exception as exc:
        log.error(f"Data fetch failed: {exc}")
        return

    alerts, all_statuses, raw = evaluate(closes)

    # Always write to CSV -every run, green or not
    alert_sent = False
    if alerts:
        subject = build_subject(alerts)
        html    = build_html(alerts)
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
    else:
        log.info("All indicators green -no alerts sent")
        print(f"[{datetime.now():%Y-%m-%d %H:%M}] All green. No alerts.")

    write_to_csv(raw, alert_sent)
    generate_status_html(all_statuses, raw)


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
