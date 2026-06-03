# Plan: Tranche staggering (T1) + Signal→Playbook→target-price coupling (T2)

Source: `TODOS.md` T1/T2 (CEO review 2026-06-03, direction B). Design already locked,
so this plan ships with checklists for a one-shot build.

## Context
Make the KAUFSIGNAL alert enforce the backtest's #1 lesson (stagger, never all-in) and
close the gap between "signal fired" and "what exactly do I do" by surfacing the relevant
Krisen-Drehbuch + target prices at the moment of action. Both additions render **only on a
KAUFSIGNAL** (`signal_level(alerts) == "red"`, i.e. ≥3 panic reds), in German, in both the
Telegram message and the HTML email. No new state, no user input, no portfolio/dry-powder
data anywhere (status.html is public).

**Anti-goals:** no per-tranche state tracking (that's deferred T4); no live deep-links to the
private business-mentors playbooks (embed instead); do not change `signal_level()` / the ≥3
rule / thresholds; do not touch the leading-indicator or scenario-status layers.

## Commands Reference
| Task | Command (run from `TOOLS/QC_Monitor/`) |
|------|------|
| Syntax check | `python -m py_compile scripts/market_monitor.py` |
| Isolated render test (NO main, NO send) | `PYTHONIOENCODING=utf-8 python _test_alert.py` then `rm _test_alert.py` |
| JSON validity | `python -c "import json;json.load(open('config/watchlist.json',encoding='utf-8'))"` |

⚠️ Never run `python scripts/market_monitor.py` to test — it sends real email/Telegram. Test only via an isolated script that imports the module and calls the builders directly.

## File Inventory
| File | Change |
|------|--------|
| `scripts/market_monitor.py` | T1: store numeric drawdown in drop-indicator status dicts; new `tranche_guidance()` helper; render tranche block in `build_telegram_message` + `build_html` (red only). T2: `SCENARIO_DREHBUCH` map; `_load_watchlist` carries `target_price`; `buy_target_rows` gets a Zielpreis column; Telegram + HTML print scenario→Drehbuch + targets + Stand-date. |
| `config/watchlist.json` | T2: add optional `target_price` per stock (from the Drehbuch tranche tables); bump `last_updated` used as the target Stand-date. |

---

## Phase 1: T1 — Enforce tranche staggering (stateless-inferred) — *KAUFSIGNAL lays out the staged plan + infers the tranche from drawdown depth*

### Approach
`build_telegram_message(alerts, all_statuses)` has **no `closes`**, so the numeric drawdown
must travel on the status dicts. Today `evaluate()` computes `pct_change` for drop-type
indicators (`drop_52w`/`drop_14d`) but only writes it to `raw` (the CSV), not the status dict.

1. In `evaluate()`, add the numeric drawdown to the status dict for drop indicators:
   ```python
   status = { "key": key, "level": level, "label": ind["label"], ...
              "stocks": ind["stocks"] }
   if pct_change is not None:
       status["pct"] = round(pct_change, 1)   # negative = drawdown; for tranche depth
   ```

2. New pure helper. Depth proxy = the **deepest** drawdown among the *broad* drop indicators
   that are red (QQQ + KRE; NVDA excluded — single-stock volatile, would overstate depth):
   ```python
   TRANCHE_DEPTH_KEYS = {"QQQ", "KRE"}   # broad-market depth proxy (NVDA too volatile)

   def tranche_guidance(alerts):
       """Stateless tranche hint for a KAUFSIGNAL. Returns (n, label, line) or None.
       Infers depth from the deepest broad drop indicator; never tracks deployment."""
       depths = [a["pct"] for a in alerts
                 if a.get("key") in TRANCHE_DEPTH_KEYS and a["level"] == "red"
                 and a.get("pct") is not None]
       depth = min(depths) if depths else None          # most negative
       if depth is None:
           band, n = "Tranche 1", 1                      # red without a broad drop %: start small
       elif depth <= -35: band, n = "Tranche 3 / Reserve", 3
       elif depth <= -25: band, n = "Tranche 2", 2
       else:              band, n = "Tranche 1", 1        # -15%..-25%
       line = (f"Markt {('%.0f' % depth).replace('-', '−')} % vom Hoch → {band}-Territorium"
               if depth is not None else "Erste Tranche-Zone")
       return n, band, line
   ```

3. Render block (only when `signal_level(alerts) == "red"`). Telegram (plain, escaped):
   ```
   📉 Tranchen-Plan: {line}
      25 % bei −15 % · 25 % bei −25 % · 25 % bei −35 % · 25 % Reserve
      Gestaffelt, nie all-in — die tiefere Tranche zahlt am besten (Backtest 2008).
   ```
   HTML: same content as a bordered card placed before the "Aktuell günstig" section.

### Todo
- [ ] In `evaluate()` (`scripts/market_monitor.py`), add `status["pct"] = round(pct_change, 1)` for drop indicators (guard `pct_change is not None`).
- [ ] Add `TRANCHE_DEPTH_KEYS` + `tranche_guidance(alerts)` helper near `signal_level()` in `scripts/market_monitor.py`.
- [ ] In `build_telegram_message`, after the header block and before the per-indicator loop (or right after it), if `worst_level == "red"`, append the tranche block built from `tranche_guidance(alerts)`. Escape dynamic text; use only `−` via the `.replace('-', '−')` already in the helper (NB: `−` is allowed in Telegram/HTML body, just not the email *subject*).
- [ ] In `build_html`, if `worst == "red"`, build a tranche card (border-left `{header_color}`) and insert it before `{stocks_section}` in the body.
- [ ] Verify: `python -m py_compile scripts/market_monitor.py` clean.
- [ ] Verify: isolated test (below) shows the tranche block with the right band for a faked −27 % QQQ red KAUFSIGNAL, and shows **nothing** for a single-red BEOBACHTEN case.

---

## Phase 2: T2 — Signal→Playbook→target-price coupling (embedded) — *name the Drehbuch + show target prices at the moment of action*

### Approach
1. `config/watchlist.json`: add optional `target_price` (absolute, the −25 % Drehbuch target)
   per stock where a playbook target exists. Source values from the Drehbuch tranche tables:
   CINF ~118 $, CB ~234 $, ACGL ~67 $, TRV ~220 $, PGR ~145 $, USB ~41 $, MTB ~160 $,
   WFC ~58 $, ALV ~285 €, MUV2 ~340 €, VIG ~47 €. (HNR1/DB1/SAP/ANDR/EVN/EBS: omit — no
   playbook target; the field is optional and gracefully skipped.) The existing
   `last_updated` ("2026-05-30") is the Stand-date for these targets.
   ```json
   "CINF": { "name": "Cincinnati Financial", "index": "S&P 500", "yf_symbol": "CINF",
             "kgv_current": 9.00, "kgv_amber": 8.0, "kgv_red": 6.5, "target_price": 118 },
   ```

2. `_load_watchlist()`: carry `target_price` into `BUY_TARGETS` (use `.get`, default `None`).

3. `SCENARIO_DREHBUCH` map (indicator key → Drehbuch number + title), derived from the
   existing `SCENARIOS`/panic groupings:
   ```python
   SCENARIO_DREHBUCH = {
       "KRE": ("02", "CRE-Bankenkrise"),
       "QQQ": ("01", "KI-Blase"), "NVDA": ("01", "KI-Blase"),
       "US10Y": ("03", "US-Fiskal/Zins-Schock"), "MOVE": ("03", "US-Fiskal/Zins-Schock"),
       "BRENT_HIGH": ("04", "Nat-Cat-/Öl-Schock"), "HURRICANE": ("04", "Nat-Cat-/Öl-Schock"),
       # VIX = broad, no single Drehbuch
   }
   ```
   Build a deduped, ordered list of triggered scenarios from `alerts` keys.

4. Render (KAUFSIGNAL only):
   - Telegram: after the stock listing, add `📘 Betroffene Drehbücher: 01 KI-Blase, 02 CRE-Bankenkrise` and, in the per-index stock lines, append ` (Ziel ~118 $)` where a target exists.
   - HTML `buy_target_rows`: add a **Zielpreis** column (header + cell; show `—` when no target). Add a Stand-date note under the table: `Zielpreise Stand {watchlist last_updated} — am tatsächlichen KGV prüfen.`

### Todo
- [ ] Add `target_price` to the relevant stocks in `config/watchlist.json` (values above).
- [ ] Verify JSON: `python -c "import json;json.load(open('config/watchlist.json',encoding='utf-8'))"`.
- [ ] In `_load_watchlist()`, add `"target": s.get("target_price")` to the `BUY_TARGETS` dict comprehension.
- [ ] Add `SCENARIO_DREHBUCH` map + a small helper to derive triggered (number, title) pairs from `alerts`.
- [ ] `buy_target_rows`: add a Zielpreis `<th>` + `<td>` (`{b['target']:.0f} €/$` or `—`); thread currency by index if simple, else show plain number.
- [ ] `build_html`: add the "Zielpreise Stand … — am tatsächlichen KGV prüfen" note under the KGV table; add a "Betroffene Drehbücher: …" line.
- [ ] `build_telegram_message`: append target prices to the per-index stock lines + a "📘 Betroffene Drehbücher: …" line (KAUFSIGNAL only).
- [ ] Verify: `python -m py_compile scripts/market_monitor.py` clean.
- [ ] Verify: isolated test shows scenario→Drehbuch names + target prices + the Stand-date note; confirms no target rendered for a stock without `target_price`.

---

## Isolated verification script (create, run, delete — NEVER run main())
`_test_alert.py` at repo root:
```python
import sys, tempfile, pathlib
sys.stdout.reconfigure(encoding="utf-8")
import market_monitor as m
# Fake a KAUFSIGNAL: QQQ -27% red, NVDA -40% red, VIX red (≥3 → red)
def st(key,label,level,pct=None,stocks=None):
    d={"key":key,"level":level,"label":label,"compact":f"{key} test","current":"x",
       "threshold":"x","scenario":f"{key} szenario","why_discount":"...","news_url":"",
       "stocks":stocks or []}
    if pct is not None: d["pct"]=pct
    return d
alerts=[st("QQQ","Nasdaq 100","red",-27,["CINF","CB","ALV"]),
        st("NVDA","NVIDIA","red",-40,["CINF","CB"]),
        st("VIX","VIX","red",None,["CINF","CB","ALV","MUV2"])]
print("tranche_guidance:", m.tranche_guidance(alerts))   # expect Tranche 2 (-27%)
tg=m.build_telegram_message(alerts,alerts)
print("TG has Tranchen-Plan:", "Tranchen-Plan" in tg)
print("TG has Drehbuch:", "Drehbuch" in tg or "Drehbücher" in tg)
print("TG has target:", "Ziel" in tg)
# Single-red BEOBACHTEN must NOT show tranche block:
one=[st("US10Y","US 10J","amber",None,["CINF"])]
print("single-amber NO tranche:", "Tranchen-Plan" not in m.build_telegram_message(one,one))
print(tg)
```
Run: `PYTHONIOENCODING=utf-8 python _test_alert.py`, eyeball output, then `rm _test_alert.py`.

## Notes / risks
<!-- REVIEW: target_price values are the −25% Drehbuch targets dated 2026-05-30; they age. The Stand-date note is the mitigation. Refresh when the watchlist session updates. -->
<!-- REVIEW: BUY_TARGETS today is built only from watchlist.json; confirm every alert stock with a target is in watchlist.json (USB/MTB/WFC/VIG are; HNR1 has no target). -->
- Public repo: the plan + watchlist targets contain no secrets. No dry-powder/portfolio data anywhere (that's deferred T3).
- After build: commit in QC_Monitor (auto-hook commits locally; push is manual).
