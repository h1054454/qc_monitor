#!/usr/bin/env python3
"""
QC Monitor — Backtest of the LEADING indicators (Vor-Indikatoren).

Calibrates the 4 reliably-historied leading indicators against the catalogued
crises in backtest/data/crash_events.csv:

    HYOAS    High-Yield credit spread (FRED BAMLH0A0HYM2, from 1996)
    KREXLF   Regional-banks-relative (KRE/XLF, 60d % vs avg; KRE from 2006)
    INFL5Y5Y 5y5y forward inflation (FRED T5YIFR, from 2003)
    STEEPEN  Bear-steepening (10Y-2Y, 21d change in bp; FRED T10Y2Y, from 1976)

UNLIKE the panic-indicator backtest (which measures buy-PAYOFF), a leading
indicator never triggers a buy. So we measure the three metrics that matter
for a leading indicator instead:

  1. LEAD-TO-TROUGH   — how many days before the market trough it first went red
  2. LEAD-VS-PANIC    — did it go red before its paired panic indicator (KRE / US10Y)
  3. FALSE-ALARM RATE — over the WHOLE history, how often it went red WITHOUT a
                        crisis following within 180 days (the critical weakness
                        of any leading indicator)

Plus a THRESHOLD SWEEP so we can pick rounded amber/red near the optimum.

Thresholds + metric definitions are imported from market_monitor.py
(mm.LEADING_INDICATORS) — single source of truth.

Run:    python scripts/backtest/backtest_leading.py
Output: backtest/data/leading_backtest_history.csv
        backtest/data/leading_backtest_summary.txt  + console
Data:   FRED keyless fredgraph.csv (HY-OAS, T5YIFR, T10Y2Y); yfinance (KRE, XLF).
"""
import sys
from pathlib import Path
from io import StringIO

sys.stdout.reconfigure(encoding="utf-8")   # Windows console is cp1252 by default

import numpy as np
import pandas as pd
import requests
import yfinance as yf

SCRIPTS_DIR = Path(__file__).resolve().parent.parent       # .../scripts
BASE_DIR    = SCRIPTS_DIR.parent                            # .../QC_Monitor
sys.path.insert(0, str(SCRIPTS_DIR))
import market_monitor as mm   # noqa: E402  -production thresholds, single source of truth

OUT_HIST = BASE_DIR / "backtest" / "data" / "leading_backtest_history.csv"
OUT_SUM  = BASE_DIR / "backtest" / "data" / "leading_backtest_summary.txt"
CRASHES  = BASE_DIR / "backtest" / "data" / "crash_events.csv"
PANIC    = BASE_DIR / "backtest" / "data" / "indicator_history_full.csv"
START    = "2003-01-01"          # T5YIFR inception ~2003; KRE ~2006 (HY-OAS/T10Y2Y go back further)
FALSE_ALARM_HORIZON = 180        # days: a red episode is a "hit" if a trough falls within this window

# Which panic indicator each leading indicator is supposed to lead (for LEAD-VS-PANIC).
PAIR = {"HYOAS": "kre_level", "KREXLF": "kre_level",
        "INFL5Y5Y": "us10y_level", "STEEPEN": "us10y_level"}


# ── Data fetch ────────────────────────────────────────────────────────────────
def fetch_fred_dated(series_id):
    """FRED keyless CSV → pd.Series(value, index=DatetimeIndex). Empty on failure."""
    last_exc = None
    for _ in range(2):
        try:
            # cosd/coed force the FULL history — without them fredgraph.csv
            # returns only a recent default window (~3 years).
            r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                             params={"id": series_id, "cosd": "1990-01-01",
                                     "coed": "2026-12-31"}, timeout=60)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text))
            df.columns = ["date", "value"]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.dropna().set_index("date")["value"].sort_index()
            s.name = series_id
            return s
        except Exception as exc:
            last_exc = exc
    print(f"  WARN: FRED fetch failed for {series_id}: {last_exc}")
    return pd.Series(dtype=float)


def fetch_yf(ticker):
    d = yf.download(ticker, start=START, progress=False, auto_adjust=True)
    close = d["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    s = close.dropna()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = ticker
    return s


# ── Build each leading indicator's METRIC series (matches production logic) ────
def build_metrics():
    """Return dict key -> pd.Series of the production METRIC (the thing we threshold)."""
    metrics = {}

    # HYOAS — raw level
    hy = fetch_fred_dated("BAMLH0A0HYM2")
    if not hy.empty:
        metrics["HYOAS"] = hy

    # INFL5Y5Y — raw level
    infl = fetch_fred_dated("T5YIFR")
    if not infl.empty:
        metrics["INFL5Y5Y"] = infl

    # STEEPEN — 21-obs change of (10Y-2Y) in basis points
    t = fetch_fred_dated("T10Y2Y")
    if not t.empty:
        w = mm.LEADING_INDICATORS["STEEPEN"]["window"]
        metrics["STEEPEN"] = ((t - t.shift(w)) * 100).dropna().rename("STEEPEN")

    # KREXLF — (KRE/XLF) percent vs its own 60-trading-day average
    kre = fetch_yf("KRE"); xlf = fetch_yf("XLF")
    ratio = (kre / xlf).dropna()
    win = mm.LEADING_INDICATORS["KREXLF"]["window"]
    avg = ratio.rolling(win).mean()
    metrics["KREXLF"] = ((ratio / avg - 1) * 100).dropna().rename("KREXLF")

    return metrics


def classify(metric, amber, red, check):
    if check == "above":
        cond = [metric >= red, metric >= amber]
    else:  # below
        cond = [metric <= red, metric <= amber]
    return pd.Series(np.select(cond, ["red", "amber"], "green"), index=metric.index)


# ── Red-episode extraction (for false-alarm rate) ─────────────────────────────
def red_episodes(level, max_gap_days=10):
    """List of (start, end) timestamps for runs of red, merging gaps <= max_gap_days."""
    red_days = level[level == "red"].index
    if len(red_days) == 0:
        return []
    episodes, start, prev = [], red_days[0], red_days[0]
    for d in red_days[1:]:
        if (d - prev).days > max_gap_days:
            episodes.append((start, prev))
            start = d
        prev = d
    episodes.append((start, prev))
    return episodes


def main():
    crises = pd.read_csv(CRASHES, parse_dates=["peak_date", "trough_date"])
    panic = pd.read_csv(PANIC, parse_dates=["date"]).set_index("date") if PANIC.exists() else None

    print("Fetching leading-indicator history (FRED + yfinance)…")
    metrics = build_metrics()

    lines = []
    def emit(s=""):
        print(s); lines.append(s)

    # Persist the metric+level history for inspection
    hist = pd.DataFrame()
    for key, metric in metrics.items():
        cfg = mm.LEADING_INDICATORS[key]
        lvl = classify(metric, cfg["amber"], cfg["red"], cfg["check"])
        hist[key] = metric
        hist[f"{key}_level"] = lvl
    hist.sort_index().to_csv(OUT_HIST)
    emit(f"Wrote {OUT_HIST.relative_to(BASE_DIR)} ({len(hist)} rows)")

    emit("\n" + "=" * 74)
    emit("LEADING-INDICATOR BACKTEST — Vor-Indikatoren vs catalogued crises")
    emit("Thresholds (production, provisional): " + " · ".join(
        f"{k} {mm.LEADING_INDICATORS[k]['amber']}/{mm.LEADING_INDICATORS[k]['red']}"
        for k in metrics))
    emit("=" * 74)

    # ── Per-crisis lead time + lead-vs-panic ──────────────────────────────────
    for key, metric in metrics.items():
        cfg = mm.LEADING_INDICATORS[key]
        lvl = classify(metric, cfg["amber"], cfg["red"], cfg["check"])
        emit(f"\n### {key} — {cfg['label']}")
        emit(f"    metric range: {metric.min():.2f} .. {metric.max():.2f} "
             f"({metric.index.min().date()} → {metric.index.max().date()})")
        pair_col = PAIR.get(key)
        for _, c in crises.iterrows():
            peak, trough = c["peak_date"], c["trough_date"]
            win = lvl.loc[peak - pd.Timedelta(days=30): trough + pd.Timedelta(days=20)]
            if win.empty or metric.loc[:trough].empty:
                emit(f"  {c['label'][:22]:<22} (no data)"); continue
            first_red = win[win == "red"].index.min()
            mval = metric.loc[peak - pd.Timedelta(days=30): trough + pd.Timedelta(days=20)]
            extreme = mval.max() if cfg["check"] == "above" else mval.min()
            if pd.notna(first_red):
                lead = (trough - first_red).days
                tag = f"RED {first_red.date()} ({abs(lead)}d {'before' if lead >= 0 else 'after'} trough)"
                # lead vs paired panic indicator
                if panic is not None and pair_col in panic.columns:
                    pw = panic.loc[peak - pd.Timedelta(days=30): trough + pd.Timedelta(days=20), pair_col]
                    p_red = pw[pw == "red"].index.min()
                    if pd.notna(p_red):
                        d = (p_red - first_red).days
                        tag += f" | vs {pair_col.split('_')[0].upper()}: " + (
                            f"led {d}d" if d > 0 else (f"lagged {-d}d" if d < 0 else "same day"))
                    else:
                        tag += f" | {pair_col.split('_')[0].upper()} never red"
            else:
                tag = f"never red (extreme {extreme:.2f})"
            emit(f"  {c['label'][:22]:<22} {tag}")

    # ── False-alarm rate over the whole history ───────────────────────────────
    emit("\n" + "=" * 74)
    emit("FALSE-ALARM RATE (whole history) — red episode = hit if a crisis trough")
    emit(f"falls within {FALSE_ALARM_HORIZON}d after it starts, OR it starts inside a")
    emit("crisis peak→trough window; else it is a false alarm.")
    emit("=" * 74)
    troughs = crises["trough_date"].tolist()
    windows = list(zip(crises["peak_date"] - pd.Timedelta(days=30), crises["trough_date"]))
    for key, metric in metrics.items():
        cfg = mm.LEADING_INDICATORS[key]
        lvl = classify(metric, cfg["amber"], cfg["red"], cfg["check"])
        eps = red_episodes(lvl)
        tp = fp = 0
        for start, end in eps:
            hit = any(start <= tr <= start + pd.Timedelta(days=FALSE_ALARM_HORIZON) for tr in troughs) \
                  or any(w0 <= start <= w1 for w0, w1 in windows)
            tp += hit; fp += (not hit)
        n = len(eps)
        rate = (fp / n * 100) if n else 0
        emit(f"  {key:<9} {n:>2} red episodes | {tp} hit / {fp} false  → false-alarm {rate:.0f}%")

    # ── Threshold sweep ───────────────────────────────────────────────────────
    emit("\n" + "=" * 74)
    emit("THRESHOLD SWEEP — crises-caught vs false-alarm episodes per RED threshold")
    emit("(pick a rounded red threshold near the knee: catches the real crises,")
    emit(" few false alarms. amber is set looser for earlier 'attention'.)")
    emit("=" * 74)
    SWEEPS = {
        "HYOAS":    [4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0],
        "INFL5Y5Y": [2.4, 2.6, 2.8, 3.0, 3.2],
        "STEEPEN":  [20, 25, 30, 40, 50, 60],
        "KREXLF":   [-4, -5, -6, -8, -10, -12],
    }
    for key, metric in metrics.items():
        cfg = mm.LEADING_INDICATORS[key]
        emit(f"\n  {key} ({cfg['check']}):  red-threshold → crises-with-a-red / false-alarm episodes")
        relevant = crises
        for thr in SWEEPS.get(key, []):
            lvl = classify(metric, cfg["amber"], thr, cfg["check"])
            # crises caught: a red anywhere in [peak-30d, trough+20d]
            caught = 0
            for _, c in relevant.iterrows():
                w = lvl.loc[c["peak_date"] - pd.Timedelta(days=30): c["trough_date"] + pd.Timedelta(days=20)]
                caught += int((w == "red").any())
            eps = red_episodes(lvl)
            fa = sum(1 for s, e in eps
                     if not (any(s <= tr <= s + pd.Timedelta(days=FALSE_ALARM_HORIZON) for tr in troughs)
                             or any(w0 <= s <= w1 for w0, w1 in windows)))
            emit(f"    {thr:>6}  →  {caught:>2}/{len(relevant)} crises   |  {fa:>2} false alarms")

    emit("\n" + "=" * 74)
    emit("Reading: leading indicators warn EARLY and noisily. A good red threshold")
    emit("catches the relevant crises with an acceptable false-alarm count — it is")
    emit("NOT a buy trigger (they stay out of the >=3 KAUFSIGNAL by design).")
    emit("=" * 74)

    OUT_SUM.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nSummary written to {OUT_SUM.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
