#!/usr/bin/env python3
"""
QC Monitor — Backtest of the two NEW indicators: MOVE + Euro-periphery spread.

Tests whether MOVE (^MOVE) and the ECB periphery 10Y spread (all-bonds minus AAA)
would have gone RED near the bottom of the crises that matter for them — 2011
EU/US debt, 2018 Q4, COVID 2020 — using the SAME production thresholds imported
from market_monitor.py (single source of truth). Also measures the early-warning
lead vs the VIX.

Run:    python scripts/backtest/backtest_move_periphery.py
Output: backtest/data/move_periphery_history.csv  +  console/report summary
Data:   ^MOVE via yfinance (from 2010-01); ECB YC dataflow (AAA + all-bonds 10Y).
"""
import sys
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")   # Windows console is cp1252 by default

import pandas as pd
import requests
import yfinance as yf

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
BASE_DIR    = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
import market_monitor as mm   # noqa: E402  -production thresholds, single source of truth

OUT  = BASE_DIR / "backtest" / "data" / "move_periphery_history.csv"
HIST = BASE_DIR / "backtest" / "data" / "indicator_history_full.csv"   # for VIX comparison
START = "2010-01-01"

# Target crises (from crash_events.csv) — (label, peak, trough)
CRISES = [
    ("2011 EU/US debt", "2011-04-28", "2011-08-19"),
    ("2018 Q4 (Feb)",   "2018-01-26", "2018-02-08"),
    ("2018 Q4 selloff", "2018-09-20", "2018-12-24"),
    ("COVID",           "2020-02-19", "2020-03-23"),
]


def fetch_move():
    d = yf.download("^MOVE", start=START, progress=False, auto_adjust=True)
    close = d["Close"]
    if isinstance(close, pd.DataFrame):      # MultiIndex columns -> take the single column
        close = close.iloc[:, 0]
    s = close.dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = "move"
    return s


def fetch_ecb_series(key):
    base = "https://data-api.ecb.europa.eu/service/data/YC/"
    r = requests.get(base + key,
                     params={"startPeriod": START, "format": "jsondata"},
                     headers={"Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    j = r.json()
    obs  = list(j["dataSets"][0]["series"].values())[0]["observations"]
    dims = j["structure"]["dimensions"]["observation"][0]["values"]
    data = {dims[int(k)]["id"]: v[0] for k, v in obs.items()}
    s = pd.Series(data, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def classify_above(series, amber, red):
    out = pd.Series("green", index=series.index)
    out[series >= amber] = "amber"
    out[series >= red]   = "red"
    return out


def main():
    print("Fetching MOVE + ECB periphery history (2010→today)…")
    move = fetch_move()
    aaa  = fetch_ecb_series("B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y")
    allb = fetch_ecb_series("B.U2.EUR.4F.G_N_C.SV_C_YM.SR_10Y")
    periph_bp = ((allb - aaa) * 100).rename("periph_spread")

    # Thresholds straight from production
    move_amber, move_red = mm.INDICATORS["MOVE"]["amber"], mm.INDICATORS["MOVE"]["red"]
    p_amber, p_red       = mm.PERIPHERY["amber"], mm.PERIPHERY["red"]

    df = pd.DataFrame({"move": move}).join(periph_bp, how="outer").sort_index()
    df["move"]          = df["move"].ffill()
    df["periph_spread"] = df["periph_spread"].ffill()
    df["move_level"]   = classify_above(df["move"],          move_amber, move_red)
    df["periph_level"] = classify_above(df["periph_spread"], p_amber,    p_red)

    df.to_csv(OUT)
    print(f"Wrote {OUT} ({len(df)} rows, {df.index.min().date()}→{df.index.max().date()})")

    # VIX history for early-warning comparison
    vix = None
    if HIST.exists():
        h = pd.read_csv(HIST, parse_dates=["date"]).set_index("date")
        vix = h[["vix", "vix_level"]]

    lines = []
    def emit(s=""):
        print(s); lines.append(s)

    emit("\n" + "=" * 70)
    emit("BACKTEST — MOVE + Euro-periphery spread vs target crises")
    emit(f"Thresholds (production): MOVE amber {move_amber}/red {move_red} · "
         f"Periphery amber {p_amber}/red {p_red} bp")
    emit("=" * 70)

    for label, peak_s, trough_s in CRISES:
        peak, trough = pd.Timestamp(peak_s), pd.Timestamp(trough_s)
        win = df.loc[peak - pd.Timedelta(days=20): trough + pd.Timedelta(days=20)]
        emit(f"\n### {label}   (peak {peak.date()} → trough {trough.date()})")

        for name, col, lvl, unit in [
            ("MOVE",      "move",          "move_level",   ""),
            ("Periphery", "periph_spread", "periph_level", " bp"),
        ]:
            w = win[[col, lvl]].dropna()
            if w.empty:
                emit(f"  {name:<10} no data in window"); continue
            peak_val   = w[col].max()
            first_amber = w[w[lvl] != "green"].index.min()
            first_red   = w[w[lvl] == "red"].index.min()
            # value at/near the trough
            at_trough = w[col].asof(trough)
            msg = f"  {name:<10} peak {peak_val:6.1f}{unit} | at trough {at_trough:6.1f}{unit} | "
            if pd.notna(first_red):
                lead = (trough - first_red).days
                rel  = f"{abs(lead)}d {'BEFORE' if lead>0 else 'after'} trough"
                msg += f"first RED {first_red.date()} ({rel})"
            elif pd.notna(first_amber):
                lead = (trough - first_amber).days
                rel  = f"{abs(lead)}d {'before' if lead>0 else 'after'} trough"
                msg += f"only AMBER (first {first_amber.date()}, {rel}) — never red"
            else:
                msg += "stayed GREEN — no signal"
            emit(msg)

        # MOVE vs VIX early-warning lead
        if vix is not None:
            vwin = vix.loc[peak - pd.Timedelta(days=20): trough + pd.Timedelta(days=20)]
            v_red = vwin[vwin["vix_level"] == "red"].index.min()
            m_red = win[win["move_level"] == "red"].index.min()
            if pd.notna(v_red) and pd.notna(m_red):
                lead = (v_red - m_red).days
                emit(f"  → MOVE first red {m_red.date()} vs VIX first red {v_red.date()}: "
                     f"MOVE led by {lead}d" if lead > 0 else
                     f"  → MOVE first red {m_red.date()} vs VIX first red {v_red.date()}: "
                     f"VIX led by {-lead}d")
            elif pd.notna(v_red) and pd.isna(m_red):
                emit(f"  → VIX went red ({v_red.date()}) but MOVE did not — MOVE missed this one")

    emit("\n" + "=" * 70)
    emit("Reading: a useful buy-timer indicator goes RED at/just-before the trough.")
    emit("Red well BEFORE the trough = early but may be premature; AMBER-only or GREEN")
    emit("through a crisis = thresholds too loose for that indicator.")
    emit("=" * 70)

    rep = BASE_DIR / "backtest" / "data" / "move_periphery_backtest_summary.txt"
    rep.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary written to {rep}")


if __name__ == "__main__":
    main()
