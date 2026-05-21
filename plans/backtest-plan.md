# QC Monitor — Historical Backtest Plan

**Goal:** Pull ~7 years of historical data and test whether the QC Monitor's
indicators would have (a) fired at the right *time* around each market crash, and
(b) whether buying the watchlist stocks on those signals would have paid off.

**Status:** Planned — not yet built. Standalone analysis; does **not** touch the
live monitor (`scripts/market_monitor.py`).

---

## Reframing (what "success" means)

This tool is **not a crash predictor** — it's a *buy-the-panic timer*. Its signals
(VIX>30, Nasdaq −20%, KRE −15%/14d, Brent>$130) are **coincident or lagging**
markers of a selloff already underway, used to buy quality names that get dumped
unfairly. The only forward-looking signal is **NVDA −35%** ("early warning of a
Nasdaq correction").

So the backtest measures **timing relative to the bottom**, not prediction lead,
and **forward returns after the signal**, not forecast accuracy.

## Locked scope decisions

| Decision | Choice |
|---|---|
| Success metric | **Both** — signal timing *and* buy-the-dip payoff |
| Time window | **~7 years (back to ~2019)** — includes the Mar-2020 COVID crash |
| Thresholds | **Evaluate current as-is, then suggest** recalibrated (with overfit caveat) |

## Events expected in the window

- **Feb–Mar 2020 — COVID crash** (VIX hit 82, S&P −34%) — the extreme stress test.
- **2022 bear market** (S&P ≈ −25%, Fed hikes) — marquee test for the **US10Y** signal.
- **Mar 2023 — regional-bank crisis** (SVB/Signature/First Republic; KRE ≈ −35%) —
  textbook test for the **KRE −15%/14d** signal and the "good banks dumped with bad
  ones" thesis.
- **Aug 2024 — VIX spike** (carry-trade unwind, VIX intraday ~65) — the **VIX>30** test.
- **Any 2025 volatility** — let the drawdown rule surface it rather than assume.

---

## Data sources (yfinance)

- Indicators: `^VIX`, `^TNX` (US 10Y), `QQQ`, `NVDA`, `KRE`, `BZ=F` (Brent)
- Crash ground truth + benchmark: `^GSPC` (S&P 500)
- Watchlist forward returns: reuse `TICKER_YF` map from `market_monitor.py`
  (Allianz `ALV.DE`, Munich Re `MUV2.DE`, Chubb `CB`, Cincinnati `CINF`,
  Travelers `TRV`, Progressive `PGR`, Arch `ACGL`, US Bancorp `USB`, M&T `MTB`,
  Wells Fargo `WFC`, Erste, VIG, etc.)

---

## Phases

### Phase 1 — Data pull + indicator reconstruction
- Download ~7y daily history for all tickers above.
- Recompute each day's green/amber/red using the **exact threshold logic from
  `market_monitor.py`** (import/refactor the per-indicator checks so backtest ==
  production — avoid re-implementing thresholds by hand).
- Output: `backtest/data/indicator_history_7y.csv` (same schema as the live
  `data/indicator_history.csv`).
- **Validation gate:** the reconstructed values for the days we already have in
  the live `indicator_history.csv` (May 2026+) must match. Cross-check before
  trusting the history.

### Phase 2 — Crash ground truth
- Define a "crash" by rule: `^GSPC` drawdown from trailing peak crossing **−10%**
  (correction) and **−20%** (bear). Cluster into events with peak / trough /
  recovery dates.
- Output: dated event table.

### Phase 3 — Signal timing
- Per event: first amber date and first red date for each indicator within a
  window around the peak/trough.
- Metrics: hit rate (did any indicator go red during the event?), lead/lag vs
  **peak** and vs **trough** (how early/late was the buy signal relative to the
  bottom), misses (crashes with no signal), and **false alarms** (amber/red
  episodes with no ≥10% drawdown following) → "alert days per year."

### Phase 4 — Buy-the-dip payoff
- On each first-**red** signal date, "buy" an equal-weight watchlist basket.
- Forward returns at **+21 / +63 / +126 / +252** trading days.
- Benchmarks: same-date `^GSPC` buy, and buying at the actual trough (best case,
  to show how much timing was left on the table).
- Aggregate: average forward return after red signals vs unconditional baseline.

### Phase 5 — Calibration + report
- Report current-threshold performance (timing + payoff).
- Then sweep thresholds (e.g. VIX 25/30/35; US10Y 4.5/5.0/5.5; KRE −10/−15/−20)
  and show sensitivity tables.
- **Overfit caveat stated loudly:** ~4–5 events is anecdote, not statistics.
  "Best" thresholds here are hypotheses to watch forward, not a tuned strategy.

---

## Deliverables

- `scripts/backtest/run_backtest.py` — pulls data, reconstructs indicators, runs
  Phases 2–4.
- `backtest/data/indicator_history_7y.csv` — reconstructed daily history.
- `backtest/report.md` — per-event scorecards, false-alarm summary, payoff
  tables, calibration sensitivity, caveats.
- (Stretch) simple PNG charts via matplotlib.

## Caveats (carried into the report)

1. **~4–5 events ≠ statistics.** Calibration and sanity check, not proof.
2. **Hurricane signal not backtestable** — the live script reads only *active*
   NOAA storms; historical landfalls need a different dataset (HURDAT2). Excluded.
3. **Watchlist look-ahead** — today's stock list was partly chosen with hindsight,
   so payoff numbers are mildly optimistic.
4. **Brent `BZ=F`** is a continuous front-month future with roll quirks.
5. **European tickers** (`.DE`/`.VI`) have currency and trading-holiday alignment
   differences vs US data.
