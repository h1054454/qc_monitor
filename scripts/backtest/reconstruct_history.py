#!/usr/bin/env python3
"""
QC Monitor — Phase 1 backtest: reconstruct ~7 years of daily indicator history.

Pulls historical prices and recomputes each indicator's green/amber/red level
using the SAME thresholds + classification rules as scripts/market_monitor.py
(thresholds are imported, not re-typed). Then validates the reconstruction
against the live indicator_history.csv on overlapping dates, and writes the
multi-year history that Phases 2-4 will analyse.

Run:    python scripts/backtest/reconstruct_history.py
Output: backtest/data/indicator_history_7y.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ── Import production config (single source of truth for thresholds) ──────────
SCRIPTS_DIR = Path(__file__).resolve().parent.parent       # .../scripts
BASE_DIR    = SCRIPTS_DIR.parent                            # .../QC_Monitor
sys.path.insert(0, str(SCRIPTS_DIR))
import market_monitor as mm                                  # noqa: E402

START        = "2006-06-01"     # KRE inception (~2006-06-19) — earliest all indicators exist
REPORT_START = "2007-01-01"     # first date we keep (captures the 2007-09 GFC peak onward)
OUT_PATH     = BASE_DIR / "backtest" / "data" / "indicator_history_full.csv"
LIVE_CSV     = BASE_DIR / "data" / "indicator_history.csv"

LEVEL_COLS = ["vix_level", "kre_level", "qqq_level", "nvda_level",
              "brent_high_level", "brent_low_level", "us10y_level"]


def classify(series: pd.Series, check: str, amber, red):
    """Vectorized replica of market_monitor.evaluate() per-indicator logic.

    Returns (pct_series_or_None, level_series) aligned to series.index.
    """
    if check == "above":
        cond = [series >= red, series >= amber]
        return None, pd.Series(np.select(cond, ["red", "amber"], "green"), index=series.index)

    if check == "below":
        cond = [series <= red, series <= amber]
        return None, pd.Series(np.select(cond, ["red", "amber"], "green"), index=series.index)

    if check == "drop_52w":
        ref = series.rolling("365D", min_periods=1).max()   # trailing 52w high (= prod period="1y" max)
    elif check == "drop_14d":
        ref = series.shift(14)                               # 14 trading days back (= prod iloc[-15])
    else:
        return None, pd.Series("green", index=series.index)

    pct = (series - ref) / ref * 100.0
    cond = [pct <= red, pct <= amber]
    level = pd.Series(np.select(cond, ["red", "amber"], "green"), index=series.index)
    level[pct.isna()] = "green"
    return pct, level


def fetch(tickers):
    raw = yf.download(tickers, start=START, auto_adjust=True, progress=False)
    return raw["Close"] if hasattr(raw.columns, "levels") else raw[["Close"]]


def overall(row):
    vals = [row[c] for c in LEVEL_COLS]
    if "red" in vals:
        return "red"
    if "amber" in vals:
        return "amber"
    return "green"


def reconstruct():
    tickers = sorted({ind["ticker"] for ind in mm.INDICATORS.values()})
    closes = fetch(tickers)
    master = closes.index.sort_values()
    out = pd.DataFrame(index=master)

    for key, ind in mm.INDICATORS.items():
        tk = ind["ticker"]
        if tk not in closes.columns or closes[tk].dropna().empty:
            print(f"  WARN: no data for {tk} ({key}) — skipping")
            continue
        s = closes[tk].dropna()
        pct, level = classify(s, ind["check"], ind["amber"], ind["red"])
        val = s.reindex(master).ffill().round(2)
        lvl = level.reindex(master).ffill()
        pctm = pct.reindex(master).ffill().round(2) if pct is not None else None

        if key == "VIX":
            out["vix"] = val; out["vix_level"] = lvl
        elif key == "KRE":
            out["kre_price"] = val; out["kre_14d_pct"] = pctm; out["kre_level"] = lvl
        elif key == "QQQ":
            out["qqq_price"] = val; out["qqq_52w_pct"] = pctm; out["qqq_level"] = lvl
        elif key == "NVDA":
            out["nvda_price"] = val; out["nvda_52w_pct"] = pctm; out["nvda_level"] = lvl
        elif key == "BRENT_HIGH":
            out["brent"] = val; out["brent_high_level"] = lvl
        elif key == "BRENT_LOW":
            out["brent_low_level"] = lvl
        elif key == "US10Y":
            out["us10y"] = val; out["us10y_level"] = lvl

    out["hurricane_max_winds"] = 0
    out["hurricane_level"] = "green"               # not backtestable — see plan caveat
    out["overall_level"] = out.apply(overall, axis=1)
    out["alert_sent"] = out["overall_level"].ne("green")   # "would have alerted"

    out = out[out.index >= pd.Timestamp(REPORT_START)].dropna(subset=["vix_level"])
    out.insert(0, "date", out.index.strftime("%Y-%m-%d"))
    return out.reset_index(drop=True)[mm.CSV_COLUMNS]


def validate(recon):
    if not LIVE_CSV.exists():
        print("  (no live CSV to validate against)")
        return
    live = pd.read_csv(LIVE_CSV).drop_duplicates(subset="date", keep="last").set_index("date")
    rec = recon.set_index("date")
    common = [d for d in live.index if d in rec.index]
    if not common:
        print("  (no overlapping dates with live CSV)")
        return
    cols = LEVEL_COLS + ["overall_level"]
    mismatches = []
    for d in common:
        for c in cols:
            lv, rv = str(live.loc[d, c]), str(rec.loc[d, c])
            if lv != rv:
                mismatches.append(f"    {d} {c}: live={lv} recon={rv}")
    checks = len(common) * len(cols)
    print(f"  Validation: {checks - len(mismatches)}/{checks} level checks match "
          f"across {len(common)} overlapping day(s)")
    for m in mismatches[:15]:
        print(m)


def main():
    print("Reconstructing indicator history...")
    recon = reconstruct()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    recon.to_csv(OUT_PATH, index=False)

    print(f"\nRows: {len(recon)}  ({recon['date'].iloc[0]} -> {recon['date'].iloc[-1]})")
    print(f"^TNX (us10y) range: {recon['us10y'].min():.2f}% .. {recon['us10y'].max():.2f}%  "
          f"(sanity: should be ~0.5..5)")
    print("Non-green days per indicator (amber+red):")
    for c in LEVEL_COLS:
        n = int((recon[c] != "green").sum())
        r = int((recon[c] == "red").sum())
        print(f"  {c:<18} {n:>4} non-green  ({r} red)")
    print(f"  overall_level      {int((recon['overall_level'] != 'green').sum()):>4} non-green  "
          f"({int((recon['overall_level'] == 'red').sum())} red)")
    validate(recon)
    print(f"\nWrote {OUT_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
