#!/usr/bin/env python3
"""
QC Monitor — Phase 5 backtest: calibration.

(A) Tests alternative buy-signal entry rules against the Phase-4 payoff harness
    (quality basket forward returns), to find a trigger that buys closer to the
    bottom than "any one indicator red".
(B) Quantifies the noise reduction from dropping brent_low and edge-triggering.

Run: python scripts/backtest/calibrate.py
"""
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE    = Path(__file__).resolve().parent.parent.parent
HIST    = BASE / "backtest" / "data" / "indicator_history_full.csv"
EVENTS  = BASE / "backtest" / "data" / "crash_events.csv"
BASKETS = BASE / "backtest" / "baskets.json"

PANIC = ["vix_level", "kre_level", "qqq_level", "nvda_level", "brent_high_level", "us10y_level"]
HOR   = {"+1m": 21, "+3m": 63, "+6m": 126, "+12m": 252}


def fwd(series, when):
    s = series.dropna()
    pos = s.index.searchsorted(pd.Timestamp(when))
    if pos >= len(s):
        return {}
    p0 = float(s.iloc[pos])
    return {h: (float(s.iloc[pos + n]) / p0 - 1 if pos + n < len(s) else None) for h, n in HOR.items()}


def basket_avg(closes, tickers, whens):
    per = {h: [] for h in HOR}
    for when in whens:
        if when is None:
            continue
        acc = {h: [] for h in HOR}
        for tk in tickers:
            if tk in closes.columns:
                for h, v in fwd(closes[tk], when).items():
                    if v is not None:
                        acc[h].append(v)
        for h in HOR:
            if acc[h]:
                per[h].append(sum(acc[h]) / len(acc[h]))
    return {h: (sum(per[h]) / len(per[h]) if per[h] else None) for h in HOR}


def rrow(label, hits, lead, res):
    cells = "".join((f"{v * 100:+.1f}%" if v is not None else "—").rjust(8) for v in res.values())
    return f"{label:<22}{hits:>5}{lead:>6}{cells}"


def main():
    baskets = json.loads(BASKETS.read_text())
    q = baskets["quality"]["tickers"]
    hist = pd.read_csv(HIST, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    hist["red_count"] = (hist[PANIC] == "red").sum(axis=1)
    ev = pd.read_csv(EVENTS)
    ev["peak_date"] = pd.to_datetime(ev["peak_date"])
    ev["trough_date"] = pd.to_datetime(ev["trough_date"])
    closes = yf.download(sorted(set(q)), start="2006-06-01", auto_adjust=True, progress=False)["Close"]

    windows = []
    for _, r in ev.iterrows():
        w = hist[(hist["date"] >= r["peak_date"]) & (hist["date"] <= r["trough_date"] + pd.Timedelta(days=30))]
        windows.append((r["trough_date"], w))

    rules = {
        "current (any 1 red)": lambda w: w[w["red_count"] >= 1],
        ">=2 reds at once":    lambda w: w[w["red_count"] >= 2],
        ">=3 reds at once":    lambda w: w[w["red_count"] >= 3],
        "VIX >= 30":           lambda w: w[w["vix"] >= 30],
        "VIX >= 35":           lambda w: w[w["vix"] >= 35],
        "VIX >= 40":           lambda w: w[w["vix"] >= 40],
    }

    print("(A) Entry-rule calibration — quality basket fwd returns, avg over triggered crashes")
    print("    'lead' = avg days the entry preceded the bottom (lower = closer to capitulation)\n")
    print(f"{'rule':<22}{'hits':>5}{'lead':>6}" + "".join(h.rjust(8) for h in HOR))
    for name, fn in rules.items():
        whens, leads = [], []
        for trough, w in windows:
            sel = fn(w)
            if len(sel):
                d = sel["date"].iloc[0]
                whens.append(d)
                leads.append((trough - d).days)
            else:
                whens.append(None)
        lead = f"{int(sum(leads) / len(leads))}" if leads else "-"
        print(rrow(name, f"{sum(x is not None for x in whens)}/{len(windows)}", lead, basket_avg(closes, q, whens)))
    print(rrow("bought at the bottom", f"{len(windows)}/{len(windows)}", "0", basket_avg(closes, q, [t for t, _ in windows])))

    # (B) Noise
    cur = (hist["overall_level"] != "green").mean() * 100
    flag = hist[PANIC].isin(["amber", "red"]).any(axis=1)        # panic signals only (excl brent_low)
    rev = flag.mean() * 100
    episodes = int((flag & ~flag.shift(fill_value=False)).sum())
    yrs = len(hist) / 252
    print(f"\n(B) Noise reduction:")
    print(f"    current overall non-green:        {cur:.0f}% of days (incl. brent_low)")
    print(f"    panic-only aggregate (no brent_low): {rev:.0f}% of days")
    print(f"    edge-triggered: {episodes} distinct alert episodes in {yrs:.1f}y = ~{episodes / yrs:.0f}/year (vs ~daily today)")


if __name__ == "__main__":
    main()
