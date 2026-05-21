#!/usr/bin/env python3
"""
QC Monitor — Phase 3 backtest: signal timing + false-alarm analysis.

Overlays the reconstructed daily indicator levels (Phase 1) on the crash
catalog (Phase 2) and answers:
  - For each crash, which indicators went RED, and how early/late was the first
    red signal vs the market bottom (the buy-the-dip timing question)?
  - How noisy are the indicators outside crashes (false-alarm rate)?

Only the panic/buy signals are analysed. brent_low (oil-deescalation) is excluded
- it is a different signal type, not a crash marker (see Phase 1). hurricane is
not backtestable.

Run: python scripts/backtest/signal_timing.py
"""
from pathlib import Path

import pandas as pd

BASE   = Path(__file__).resolve().parent.parent.parent
HIST   = BASE / "backtest" / "data" / "indicator_history_7y.csv"
EVENTS = BASE / "backtest" / "data" / "crash_events.csv"

IND = [("VIX", "vix_level"), ("KRE", "kre_level"), ("QQQ", "qqq_level"),
       ("NVDA", "nvda_level"), ("Brent", "brent_high_level"), ("US10Y", "us10y_level")]
NAMES = {1: "COVID", 2: "2022 bear", 3: "2023 banks", 4: "Aug-24 VIX", 5: "2025 tariff"}


def main():
    hist = pd.read_csv(HIST, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    ev = pd.read_csv(EVENTS)
    for c in ("peak_date", "trough_date"):
        ev[c] = pd.to_datetime(ev[c])
    ev["recovery_date"] = pd.to_datetime(ev["recovery_date"], errors="coerce")

    in_window = pd.Series(False, index=hist.index)
    rows = []
    for _, r in ev.iterrows():
        # Analysis window = the decline plus 30 days past the bottom (the buying
        # window). NOT to full recovery, which can be years later and would overlap
        # later crises (e.g. the 2023-banks recovery ran into the Aug-2024 spike).
        end = r["trough_date"] + pd.Timedelta(days=30)
        mask = (hist["date"] >= r["peak_date"]) & (hist["date"] <= end)
        in_window |= mask
        w = hist[mask]
        cells = {}
        for label, col in IND:
            red = w.loc[w[col] == "red", "date"]
            amb = w.loc[w[col].isin(["amber", "red"]), "date"]
            if len(red):
                cells[label] = ("red", (r["trough_date"] - red.iloc[0]).days)
            elif len(amb):
                cells[label] = ("amber", None)
            else:
                cells[label] = ("silent", None)
        rows.append((NAMES.get(r["event_id"], str(r["event_id"])), r["trough_date"], cells))

    # ── Timing matrix (cell = days first RED fired before the trough) ─────────
    print("Signal timing — cell = days first RED fired BEFORE the bottom "
          "(+early / -late, a=amber only, .=silent)\n")
    print(f"{'event':<13}" + "".join(f"{lbl:>7}" for lbl, _ in IND))
    for name, _, cells in rows:
        line = f"{name:<13}"
        for lbl, _ in IND:
            st, lead = cells[lbl]
            line += f"{(f'{lead:+d}' if st == 'red' else ('a' if st == 'amber' else '.')):>7}"
        print(line)

    # ── Per-indicator summary ────────────────────────────────────────────────
    print("\nPer-indicator hit rate across the 5 crashes:")
    for lbl, _ in IND:
        reds = [c[lbl][1] for _, _, c in rows if c[lbl][0] == "red"]
        amb  = sum(1 for _, _, c in rows if c[lbl][0] in ("red", "amber"))
        med  = (f"median {int(pd.Series(reds).median()):+d}d vs trough" if reds else "—")
        print(f"  {lbl:<6} red in {len(reds)}/5,  amber+ in {amb}/5   {med}")

    # ── False-alarm / noise ──────────────────────────────────────────────────
    print("\nFalse-alarm check — RED days inside vs outside the 5 crash windows:")
    for lbl, col in IND:
        rin  = int(((hist[col] == "red") & in_window).sum())
        rout = int(((hist[col] == "red") & ~in_window).sum())
        prec = f"{rin / (rin + rout) * 100:.0f}%" if (rin + rout) else "n/a"
        print(f"  {lbl:<6} {rin:>4} in-crash  {rout:>4} outside   ({prec} of red days were real)")
    o_in  = int(((hist["overall_level"] != "green") & in_window).sum())
    o_out = int(((hist["overall_level"] != "green") & ~in_window).sum())
    print(f"\n  OVERALL non-green: {o_in} in-crash, {o_out} outside "
          f"({o_in + o_out} of {len(hist)} days = {(o_in + o_out) / len(hist) * 100:.0f}% of all days alerting)")


if __name__ == "__main__":
    main()
