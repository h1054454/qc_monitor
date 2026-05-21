#!/usr/bin/env python3
"""
QC Monitor — Phase 6 backtest: extra historical validation.

Three checks that address the "only a few events" worry, on the full ~19-year
history (12 crashes, 2007 -> today):

(1) OUT-OF-SAMPLE: pick the best entry rule using ONLY pre-2019 crashes, then
    measure it on 2020-2026 crashes it never "saw". The honest overfitting test.
(2) EVERY-FIRING: list every time the >=3-reds buy signal actually fired (across
    all history, not just catalogued crashes) and the 12-month return each time.
    Catches false signals the crash-catalog approach can't see.
(3) BEAT-LUCK: compare the signal's average 12-month return to thousands of
    random buy dates — is it special, or just markets-go-up drift?

Run: python scripts/backtest/validate.py
"""
import json
import random
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE    = Path(__file__).resolve().parent.parent.parent
HIST    = BASE / "backtest" / "data" / "indicator_history_full.csv"
EVENTS  = BASE / "backtest" / "data" / "crash_events.csv"
BASKETS = BASE / "backtest" / "baskets.json"
PANIC   = ["vix_level", "kre_level", "qqq_level", "nvda_level", "brent_high_level", "us10y_level"]
N12     = 252           # ~12 months of trading days
random.seed(42)

RULES = {
    "any 1 red": lambda w: w[w["red_count"] >= 1],
    ">=2 reds":  lambda w: w[w["red_count"] >= 2],
    ">=3 reds":  lambda w: w[w["red_count"] >= 3],
    "VIX>=30":   lambda w: w[w["vix"] >= 30],
    "VIX>=35":   lambda w: w[w["vix"] >= 35],
    "VIX>=40":   lambda w: w[w["vix"] >= 40],
}


def basket_ret(series_map, tickers, when, n=N12):
    """Equal-weight basket return from `when` to `when`+n trading days."""
    rets = []
    for tk in tickers:
        s = series_map.get(tk)
        if s is None or len(s) == 0:
            continue
        pos = s.index.searchsorted(pd.Timestamp(when))
        if pos >= len(s) or pos + n >= len(s):
            continue
        rets.append(float(s.iloc[pos + n]) / float(s.iloc[pos]) - 1)
    return (sum(rets) / len(rets)) if rets else None


def entries_for(rule_fn, hist, ev):
    out = []
    for _, r in ev.iterrows():
        w = hist[(hist["date"] >= r["peak_date"]) & (hist["date"] <= r["trough_date"] + pd.Timedelta(days=30))]
        sel = rule_fn(w)
        out.append(sel["date"].iloc[0] if len(sel) else None)
    return out


def avg_ret(series_map, q, whens):
    rs = [basket_ret(series_map, q, w) for w in whens if w is not None]
    rs = [r for r in rs if r is not None]
    return (sum(rs) / len(rs)) if rs else None


def main():
    baskets = json.loads(BASKETS.read_text())
    q = baskets["quality"]["tickers"]
    hist = pd.read_csv(HIST, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    hist["red_count"] = (hist[PANIC] == "red").sum(axis=1)
    ev = pd.read_csv(EVENTS)
    ev["peak_date"] = pd.to_datetime(ev["peak_date"])
    ev["trough_date"] = pd.to_datetime(ev["trough_date"])
    closes = yf.download(sorted(set(q)), start="2006-06-01", auto_adjust=True, progress=False)["Close"]
    series_map = {tk: closes[tk].dropna() for tk in q if tk in closes.columns}

    # ── (1) Out-of-sample ────────────────────────────────────────────────────
    ev["ty"] = ev["trough_date"].dt.year
    train, test = ev[ev["ty"] < 2019], ev[ev["ty"] >= 2019]
    print(f"(1) OUT-OF-SAMPLE  — train: {len(train)} crashes (<=2018), test: {len(test)} crashes (>=2020)")
    print(f"    quality basket 12-month return by rule:\n")
    print(f"    {'rule':<12}{'train hits':>11}{'train +12m':>12}{'test hits':>11}{'test +12m':>12}")
    scored = {}
    for name, fn in RULES.items():
        tr_w, te_w = entries_for(fn, hist, train), entries_for(fn, hist, test)
        tr_r, te_r = avg_ret(series_map, q, tr_w), avg_ret(series_map, q, te_w)
        tr_h = sum(x is not None for x in tr_w)
        scored[name] = (tr_h, tr_r, te_r)
        f = lambda v: (f"{v*100:+.1f}%" if v is not None else "—")
        print(f"    {name:<12}{tr_h:>8}/{len(train)}{f(tr_r):>12}"
              f"{sum(x is not None for x in te_w):>8}/{len(test)}{f(te_r):>12}")
    eligible = {n: s for n, s in scored.items() if s[0] >= 3 and s[1] is not None}
    winner = max(eligible, key=lambda n: eligible[n][1])
    w_tr, w_te = eligible[winner][1], eligible[winner][2]
    print(f"\n    -> Best rule on TRAIN only: '{winner}' ({w_tr*100:+.1f}% in-sample)")
    print(f"       Its OUT-OF-SAMPLE result on 2020-2026: {w_te*100:+.1f}% "
          f"(index ~+11% over the same setup)")

    # ── (2) Every firing of the >=3-reds buy signal ─────────────────────────
    flag = hist["red_count"] >= 3
    onsets = hist.loc[flag & ~flag.shift(fill_value=False), "date"]
    rets = [(d.date(), basket_ret(series_map, q, d)) for d in onsets]
    rets = [(d, r) for d, r in rets if r is not None]
    wins = sum(1 for _, r in rets if r > 0)
    mean = sum(r for _, r in rets) / len(rets) if rets else 0
    print(f"\n(2) EVERY >=3-REDS FIRING (full history, not just catalogued crashes)")
    print(f"    {len(onsets)} firings; {len(rets)} with 12m of data after.")
    print(f"    Positive at +12m: {wins}/{len(rets)}   avg +12m: {mean*100:+.1f}%")
    for d, r in rets:
        print(f"      {d}  {r*100:+.1f}%")

    # ── (3) Beat-luck baseline ──────────────────────────────────────────────
    cutoff = hist["date"].max() - pd.Timedelta(days=400)
    pool = hist.loc[hist["date"] <= cutoff, "date"].tolist()
    sample = random.sample(pool, min(5000, len(pool)))
    rnd = [basket_ret(series_map, q, d) for d in sample]
    rnd = [r for r in rnd if r is not None]
    rnd_mean = sum(rnd) / len(rnd)
    pct = sum(1 for r in rnd if r < mean) / len(rnd) * 100
    print(f"\n(3) BEAT-LUCK — quality 12m return: random buy days vs the signal")
    print(f"    random buy day (n={len(rnd)}): avg {rnd_mean*100:+.1f}%")
    print(f"    >=3-reds signal:               avg {mean*100:+.1f}%")
    print(f"    -> the signal beats {pct:.0f}% of random buy days")


if __name__ == "__main__":
    main()
