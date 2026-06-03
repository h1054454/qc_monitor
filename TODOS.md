# QC Monitor — TODOS

Outcome of a `/plan-ceo-review` (2026-06-03). Strategic direction chosen: **B — close the loop.**

## Strategic context (the *why*, so this survives without the conversation)

The 19-year backtest (`backtest/report.md`) says the edge is **modest** (+18.4% vs +12.7%
random at 12m) and **no signal saves you in a 2008-style meltdown.** So the tool's real job
is *not* alpha — it is **behavioural**: sit on your hands while green, require ≥3 confirmation
before acting, and stagger into fear.

The CEO review's core finding: the tool is **100% input-side** (signals in) and **0%
output-side** (Stefan's actual actions are never recorded). "Closing the loop" =
**signal → action → record → learn.** The two loop-ends (capital readiness *before*,
decision journal *after*) are deferred below (T3/T4). The two **alert-time reinforcements**
that sharpen the moment the signal fires (T1/T2) are next up.

Also surfaced (inversion / failure modes, not yet addressed): no capital-readiness gate
(best signal is worthless without dry powder), no enforced staggering, no watchlist
re-validation (a genuinely impaired name would still be flagged "cheap"), bus-factor 1
(target prices frozen at 29.05.; heartbeat proves the cron is alive, not the content fresh).

---

## Shipped 2026-06-03 (was: accepted scope P1)

### T1 — Enforce tranche staggering (stateless-inferred) — ✅ SHIPPED 2026-06-03
- **What:** On a KAUFSIGNAL, the alert lays out the staged tranche plan and infers which
  tranche is appropriate from the *current drawdown depth* — no per-tranche state tracked.
- **Why:** The backtest's #1 lesson — in a long meltdown the signal fires repeatedly and
  going all-in on the first red loses money for a year. Turn that prose warning into a
  visible, enforced behaviour at the moment of maximum fear.
- **Design (decided):** **Stateless.** Read current drawdown from the indicators (e.g.
  QQQ/S&P % from 52w-high), map to a tranche band (−15% → Tranche 1, −25% → T2, −35% → T3,
  deeper → reserve). Standing line: *"gestaffelt, nie all-in — die tiefere Tranche zahlt am
  besten (Backtest 2008)."* No input from Stefan (consistent with declining the journal in T4).
- **Edge cases:** fire only on KAUFSIGNAL (≥3 red), not a single-red BEOBACHTEN; when
  several scenarios are hot, key the band off the deepest drawdown; never imply Stefan has
  or hasn't already deployed (no state).
- **Files:** `scripts/market_monitor.py` — `build_telegram_message()` + `build_html()`
  (the KAUFSIGNAL alert path).
- **Effort:** human ~1 day / CC ~20 min. **Priority:** P1. **Depends on:** none.

### T2 — Signal → Playbook → target-price coupling (embedded) — ✅ SHIPPED 2026-06-03
- **What:** The KAUFSIGNAL alert names the relevant Krisen-Drehbuch scenario and shows the
  current target prices for the affected names.
- **Why:** Closes the gap between "signal fired" and "what *exactly* do I do." The playbook
  + target prices are the pre-committed plan; surface them at the moment of action.
- **Design (decided):** **Embedded, not live-linked.** The Drehbücher live in the *private*
  business-mentors repo and `status.html` is *public* → a working deep-link is impossible.
  So: add explicit `target_price` fields to `config/watchlist.json` (the `kgv_amber`/
  `kgv_red` thresholds already exist); add a scenario→Drehbuch-name map (reuse the existing
  `SCENARIOS` keys); the alert prints e.g. *"betroffenes Szenario: KI-Blase → Drehbuch 01;
  Zielpreise: CINF ~118 $, CB ~234 $ …"*.
- **Edge cases:** target prices age (currently 29.05.) → print with a Stand-date + *"am
  tatsächlichen KGV prüfen"*; keep **no** portfolio/dry-powder data in the public
  `status.html`.
- **Files:** `config/watchlist.json` (+ `target_price`), `scripts/market_monitor.py`
  (alert builders + scenario→Drehbuch map; `SCENARIOS` already exists).
- **Effort:** human ~half day / CC ~15 min. **Priority:** P1. **Depends on:** watchlist
  target prices being filled in.

---

## Deferred — the loop's two ends + 2 add-ons

### T3 — Capital-readiness / dry-powder gauge  (P2 · loop-end "before")
- **What:** Stefan records (locally, gitignored) the cash earmarked for deployment; the
  scenario map then shows *"if scenario X goes heiß, Tranche 1 = N €."*
- **Why:** The #1 inversion gap — the best KAUFSIGNAL is worthless without dry powder ready.
- **Design:** strictly **local/gitignored** (public repo — never commit a cash figure, never
  render it in `status.html`). A field in the local config + a line in the heartbeat.
- **Effort:** human ~half day / CC ~15 min. **Depends on:** none. *Deferred 2026-06-03 —
  Stefan opted out of input-bearing components for now.*

### T4 — Decision journal + retrospective  (P2 · loop-end "after" — the heart)
- **What:** Append-only log of what Stefan bought (date, ticker, price, which signal); after
  each cycle the tool shows *"signal said X, you did Y, outcome Z."*
- **Why:** Turns a one-way alert into a learning system that compounds judgement across
  cycles. This is the single highest-leverage piece for direction B — and the one most
  worth revisiting.
- **Design:** a journal CSV + a periodic retrospective view; needs light data-entry discipline.
- **Effort:** human ~1–2 days / CC ~30 min. **Depends on:** pairs naturally with T1 (the
  tranche state it deliberately omits could live here instead). *Deferred 2026-06-03.*

### T5 — Watchlist re-validation cadence  (P3)
- **What:** A scheduled Munger "permanent vs temporary" check: *"is any watchlist name
  actually impaired, not just cheap?"* (quarterly, or on each signal).
- **Why:** Prevents flagging a genuinely broken business (the Deutsche-Bank case) as a buy.
- **Design:** could ride the existing weekly screener as an extra prompt/section.
- **Effort:** human ~half day / CC ~15 min. **Priority:** P3.

### T6 — Scenario readiness checklist  (P3)
- **What:** When the live Krisen-Landkarte goes lauwarm/heiß, surface that scenario's
  homework checklist from the Drehbuch (CRE-Quoten prüfen, Zielpreise scharf, …).
- **Why:** Turns the playbook's "homework" into an active, timed checklist.
- **Design:** map each scenario → its checklist; surface on a temperature transition.
- **Effort:** human ~half day / CC ~15 min. **Priority:** P3.

---

## NOT in scope (considered, explicitly out)
- **Newsletter as a product** (audience/growth/monetisation) — different business, WAG/MiFID
  burden; the review framed QC_Monitor as a personal tool, so the existing subscriber
  machinery stays as-is (neither expanded nor removed).
- **More/sophisticated indicators** — the backtest says the edge is already modest;
  sophistication is not the bottleneck. Behaviour + capital readiness is.
