#!/usr/bin/env python3
"""
QC Monitor — Phase 2 backtest: detect crash events (ground truth).

Builds the dated event catalog the timing/payoff phases test against:
  - BROAD market crashes: S&P 500 (^GSPC) drawdown >= 10% from a trailing peak.
  - SECTOR-only crises that the broad market shrugged off: KRE (banks) or QQQ
    (tech) drawdown >= 15% whose window does NOT overlap a broad event. This is
    what catches the Mar-2023 regional-bank crisis (only ~ -8% on the S&P).

Each event = peak -> trough -> recovery (price regains the prior peak).
Output: backtest/data/crash_events.csv

Run: python scripts/backtest/detect_crashes.py
"""
from pathlib import Path

import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent.parent.parent     # .../QC_Monitor
OUT_PATH = BASE_DIR / "backtest" / "data" / "crash_events.csv"
START    = "2018-06-01"
REPORT_START = pd.Timestamp("2019-01-01")


def detect_drawdowns(close: pd.Series, min_depth: float, peak_window=None):
    """Return drawdown episodes (peak->trough->recovery) at least `min_depth` deep.

    min_depth is negative, e.g. -0.10. Recovery = first day the price regains the
    pre-decline peak value.
      peak_window=None -> drawdown from the all-time running peak. Clean for broad
                          bears (one big episode each).
      peak_window=N    -> drawdown from a trailing N-day high. Catches fast local
                          sector crises (e.g. Mar-2023 banks) even while the sector
                          is still below its all-time high.
    """
    close = close.dropna()
    peak = close.cummax() if peak_window is None else close.rolling(peak_window, min_periods=1).max()
    dd = close / peak - 1.0
    uw = dd < -1e-6
    seg = (uw != uw.shift(fill_value=False)).cumsum()
    events = []
    for sid in pd.unique(seg[uw]):
        sub = dd[(seg == sid) & uw]
        depth = float(sub.min())
        if depth > min_depth:           # not deep enough
            continue
        start = sub.index[0]
        trough = sub.idxmin()
        window = close.loc[:start] if peak_window is None else close.loc[:start].tail(peak_window)
        peak_date = window.idxmax()
        peak_val = close.loc[peak_date]
        post = close.loc[trough:]
        regained = post[post >= peak_val]
        ongoing = regained.empty
        recovery = None if ongoing else regained.index[0]
        events.append({
            "peak_date": peak_date,
            "trough_date": trough,
            "recovery_date": recovery,
            "depth_pct": round(depth * 100, 1),
            "peak_to_trough_td": close.loc[peak_date:trough].shape[0] - 1,
            "ongoing": ongoing,
        })
    return events


def detect_sharp_declines(close: pd.Series, ret_window=21, threshold=-0.15, gap_td=21):
    """Detect sharp panic-style declines via a rolling `ret_window`-day return.

    Robust to the all-time-high problem: isolates a fast crash (e.g. SVB Mar-2023)
    even when the asset has been grinding below its peak for over a year. Trigger
    days (return <= threshold) are clustered into one event when within `gap_td`
    trading days of each other. Best suited to sectors, which is what we use it for.
    """
    close = close.dropna()
    ret = close.pct_change(ret_window)
    trig = list(ret[ret <= threshold].index)
    if not trig:
        return []
    loc = close.index.get_loc
    clusters, cur = [], [trig[0]]
    for d in trig[1:]:
        if loc(d) - loc(cur[-1]) <= gap_td:
            cur.append(d)
        else:
            clusters.append(cur); cur = [d]
    clusters.append(cur)

    events = []
    for cl in clusters:
        i0 = max(0, loc(cl[0]) - ret_window)
        i1 = min(len(close) - 1, loc(cl[-1]) + 10)
        trough = close.iloc[i0:i1 + 1].idxmin()
        j0 = max(0, loc(trough) - 90)
        peak_date = close.iloc[j0:loc(trough) + 1].idxmax()
        peak_val = close.loc[peak_date]
        post = close.loc[trough:]
        regained = post[post >= peak_val]
        ongoing = regained.empty
        events.append({
            "peak_date": peak_date,
            "trough_date": trough,
            "recovery_date": None if ongoing else regained.index[0],
            "depth_pct": round(float(close.loc[trough] / peak_val - 1) * 100, 1),
            "peak_to_trough_td": loc(trough) - loc(peak_date),
            "ongoing": ongoing,
        })
    return events


def overlaps(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def merge_overlapping(events):
    """Collapse events whose peak->trough windows overlap into one (same crisis),
    keeping the deepest leg's trough/depth/recovery and the earliest peak."""
    merged = []
    for e in sorted(events, key=lambda x: x["peak_date"]):
        hit = next((m for m in merged if overlaps(e["peak_date"], e["trough_date"],
                                                   m["peak_date"], m["trough_date"])), None)
        if hit is None:
            merged.append(dict(e))
            continue
        if e["depth_pct"] < hit["depth_pct"]:        # deeper -> adopt its trough/depth/recovery
            hit.update(trough_date=e["trough_date"], depth_pct=e["depth_pct"],
                       recovery_date=e["recovery_date"], ongoing=e["ongoing"],
                       peak_to_trough_td=e["peak_to_trough_td"])
        hit["peak_date"] = min(hit["peak_date"], e["peak_date"])
    return merged


def main():
    data = yf.download(["^GSPC", "KRE", "QQQ"], start=START,
                       auto_adjust=True, progress=False)["Close"]

    broad = detect_drawdowns(data["^GSPC"], -0.10)
    for e in broad:
        e["source"] = "broad (S&P 500)"
        e["classification"] = "bear" if e["depth_pct"] <= -20 else "correction"

    sector = []
    for tk, lbl in [("KRE", "sector (banks)"), ("QQQ", "sector (tech)")]:
        for e in detect_sharp_declines(data[tk], ret_window=21, threshold=-0.15):
            # Keep only if its DECLINE (peak->trough) doesn't overlap a broad event's
            # decline. A sector crisis during a broad recovery (e.g. Mar-2023 banks,
            # while the S&P was still grinding back to its 2022 peak) stays separate.
            if any(overlaps(e["peak_date"], e["trough_date"],
                            b["peak_date"], b["trough_date"]) for b in broad):
                continue
            e["source"] = lbl
            e["classification"] = "sector"
            sector.append(e)

    sector = merge_overlapping(sector)
    events = broad + sector
    df = pd.DataFrame(events)
    df = df[df["trough_date"] >= REPORT_START].sort_values("peak_date").reset_index(drop=True)
    df.insert(0, "event_id", range(1, len(df) + 1))

    # Tidy date formatting for output
    out = df.copy()
    for c in ["peak_date", "trough_date", "recovery_date"]:
        out[c] = out[c].apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "ongoing")
    cols = ["event_id", "source", "classification", "peak_date", "trough_date",
            "recovery_date", "depth_pct", "peak_to_trough_td", "ongoing"]
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out[cols].to_csv(OUT_PATH, index=False)

    print(f"Detected {len(out)} crash events (2019 -> today):\n")
    print(f"{'#':>2}  {'source':<16} {'class':<11} {'peak':<11} {'trough':<11} "
          f"{'recovery':<11} {'depth':>6}  td")
    for _, r in out.iterrows():
        print(f"{r.event_id:>2}  {r.source:<16} {r.classification:<11} {r.peak_date:<11} "
              f"{r.trough_date:<11} {r.recovery_date:<11} {r.depth_pct:>5}%  {r.peak_to_trough_td}")
    print(f"\nWrote {OUT_PATH.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    main()
