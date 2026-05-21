#!/usr/bin/env python3
"""
QC Monitor — Phase 4 backtest: did buying the signal pay?

For each crash, finds the tool's first RED buy-signal (any panic indicator;
brent_low excluded), "buys" each labeled basket equal-weight, and measures
forward returns at +1/3/6/12 months. Compares the quality thesis basket against
the Mag 7, a broad control, the S&P index, and against buying at the exact
bottom (best-case timing).

Run: python scripts/backtest/payoff.py
"""
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE    = Path(__file__).resolve().parent.parent.parent
HIST    = BASE / "backtest" / "data" / "indicator_history_7y.csv"
EVENTS  = BASE / "backtest" / "data" / "crash_events.csv"
BASKETS = BASE / "backtest" / "baskets.json"

PANIC = ["vix_level", "kre_level", "qqq_level", "nvda_level", "brent_high_level", "us10y_level"]
HOR   = {"+1m": 21, "+3m": 63, "+6m": 126, "+12m": 252}
NAMES = {1: "COVID", 2: "2022 bear", 3: "2023 banks", 4: "Aug-24 VIX", 5: "2025 tariff"}


def fwd(series, when, horizons):
    s = series.dropna()
    pos = s.index.searchsorted(pd.Timestamp(when))
    if pos >= len(s):
        return {}
    p0 = float(s.iloc[pos])
    return {h: (float(s.iloc[pos + n]) / p0 - 1 if pos + n < len(s) else None)
            for h, n in horizons.items()}


def basket_fwd(closes, tickers, when):
    acc = {h: [] for h in HOR}
    for tk in tickers:
        if tk not in closes.columns:
            continue
        for h, v in fwd(closes[tk], when, HOR).items():
            if v is not None:
                acc[h].append(v)
    return {h: (sum(v) / len(v) if v else None) for h, v in acc.items()}


def avg_over(events_when, closes, tickers):
    per = {h: [] for h in HOR}
    for when in events_when:
        if when is None:
            continue
        for h, v in basket_fwd(closes, tickers, when).items():
            if v is not None:
                per[h].append(v)
    return {h: (sum(v) / len(v) if v else None) for h, v in per.items()}


def fmt(row):
    return "".join((f"{v * 100:+.1f}%" if v is not None else "—").rjust(8) for v in row.values())


def main():
    baskets = json.loads(BASKETS.read_text())
    hist = pd.read_csv(HIST, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    hist["panic_red"] = (hist[PANIC] == "red").any(axis=1)
    ev = pd.read_csv(EVENTS)
    ev["peak_date"] = pd.to_datetime(ev["peak_date"])
    ev["trough_date"] = pd.to_datetime(ev["trough_date"])

    all_tickers = sorted({t for b in baskets.values() if isinstance(b, dict) for t in b["tickers"]})
    closes = yf.download(all_tickers, start="2018-06-01", auto_adjust=True, progress=False)["Close"]

    entries, troughs = [], []
    print("Entry = first panic-red signal in each crash window:")
    for _, r in ev.iterrows():
        end = r["trough_date"] + pd.Timedelta(days=30)
        w = hist[(hist["date"] >= r["peak_date"]) & (hist["date"] <= end) & hist["panic_red"]]
        entry = w["date"].iloc[0] if len(w) else None
        entries.append(entry)
        troughs.append(r["trough_date"])
        tag = f"{entry.date()} ({(r['trough_date'] - entry).days:+d}d vs bottom)" if entry is not None else "no signal"
        print(f"  {NAMES.get(r['event_id'], r['event_id']):<12} {tag}")

    print("\nForward return after the RED signal — avg across the 5 crashes:\n")
    print(f"{'basket':<34}" + "".join(h.rjust(8) for h in HOR))
    for key in ["quality", "mag7", "broad", "benchmark"]:
        b = baskets[key]
        print(f"{b['label']:<34}{fmt(avg_over(entries, closes, b['tickers']))}")
    # best-case: quality bought at the exact bottom
    print(f"{'(quality, bought at the bottom)':<34}{fmt(avg_over(troughs, closes, baskets['quality']['tickers']))}")


if __name__ == "__main__":
    main()
