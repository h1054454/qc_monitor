# Backtest-TODO: MOVE + Euro-Peripherie-Spread kalibrieren

*Angelegt 2026-06-01. Offener Punkt aus der Indikator-Erweiterung (Commit `8185ae4`).*

## Warum diese Notiz

Am 2026-06-01 wurden zwei neue Makro-Indikatoren in `market_monitor.py` ergänzt:

- **MOVE** (`^MOVE` via yfinance) — Anleihe-Volatilität, „VIX für Bonds". Schwellen: amber 110, red 150.
- **Euro-Peripherie-Spread** (ECB-Tageszinskurve, alle-Euro-Bonds-10J − AAA-10J, in bp).
  Schwellen: **amber 70, red 120 — PROVISORISCH**, weil dieses Maß enger läuft als der
  rohe BTP-Bund-Spread, der im Dashboard genannt ist (amber 150–200, red 300).

Beide laufen aktuell **informativ**: sie treiben ihre eigene Gelb/Rot-Ampel (und ein einzelnes
Gelb hebt die Gesamtampel auf BEOBACHTEN), sind aber **bewusst NICHT in `BROAD_PANIC_KEYS`** —
sie zählen also noch **nicht** zur backtest-kalibrierten ≥3-KAUFSIGNAL-Regel. Grund: die ≥3-Regel
wurde auf den ursprünglichen 6 Indikatoren kalibriert; un-rückgetestete Indikatoren dazuzunehmen
würde die Kaufsignal-Schwelle still lockern.

## Was zu tun ist

Diese beiden gegen die schon katalogisierten Krisen rücktesten — **2011 EU/US-Schuldenkrise
(#4), 2018 Q4 (#6/#7), COVID 2020 (#8)** — und beantworten:

1. **Schwellen-Kalibrierung:** Bei welchen Werten gingen MOVE / Peripherie in diesen Krisen
   tatsächlich auf rot? Sind amber/red richtig gesetzt, oder zu eng/zu weit? (v.a. die
   provisorischen Peripherie-Schwellen 70/120 gegen 2011 prüfen — damals der Härtetest.)
2. **Timing:** Gingen sie **nahe am Tief** rot (nützlich) oder zu früh/zu spät? Wie bei den
   anderen 6 (siehe `backtest/report.md`, Phase 3 „signal_timing").
3. **Frühwarn-Mehrwert:** Bewegte sich MOVE **vor** dem VIX? Bewegte sich der Peripherie-Spread
   **vor** dem breiten Selloff? (Das ist die eigentliche These hinter beiden.)
4. **Aufnahme-Entscheidung:** Erst nach bestandenem Rücktest entscheiden, ob MOVE / Peripherie
   in `BROAD_PANIC_KEYS` aufgenommen werden — und ob `KAUFSIGNAL_MIN_REDS` angepasst werden muss
   (mehr Kandidaten ⇒ evtl. Schwelle anheben, damit die kalibrierte Trefferquote erhalten bleibt).

## Datenverfügbarkeit (Risiko)

- **Bestehende Grundlage:** `backtest/data/indicator_history_full.csv` (2007–2026, 4880 Tage,
  6 Indikatoren) + `backtest/data/crash_events.csv` (12 Ereignisse). Methodik:
  `scripts/backtest/reconstruct_history.py` (importiert die Produktions-Thresholds).
- **MOVE:** `^MOVE` via yfinance reicht evtl. **nicht** bis 2011 zurück — Verfügbarkeit prüfen;
  ggf. FRED-Reihe (`^MOVE`-Ersatz) oder ICE-Daten nötig.
- **Peripherie-Spread:** ECB-Tageszinskurve (`YC`-Dataflow) reicht historisch weit zurück —
  AAA- und All-Bonds-10J sollten 2011 abdecken. Über dieselbe API wie in `fetch_periphery_spread()`.

## Vorgehen (an die bestehende Phasen-Struktur anlehnen)

1. Historische MOVE- + Peripherie-Reihen ziehen, mit den Produktions-Schwellen klassifizieren
   (Muster: `reconstruct_history.py` → `classify()`), in `indicator_history_full.csv` ergänzen
   oder eine Parallel-CSV.
2. Pro Krise (#4/#6/#7/#8) das Rot-Timing relativ zum Tief auswerten (Muster: `signal_timing.py`).
3. Frühwarn-Vorlauf vs. VIX / breitem Selloff messen.
4. Ergebnis in `backtest/report.md` ergänzen; Schwellen + `BROAD_PANIC_KEYS`-Entscheidung
   dokumentieren.

## Status — erledigt 2026-06-01 (Backtest gerechnet)
- [x] Datenverfügbarkeit MOVE — `^MOVE` via yfinance ab 2010-01 (4043 Tage). Reicht für alle 3 Krisen.
- [x] Peripherie-Historie über ECB gezogen — `YC`-Dataflow ab 2010-01, täglich.
- [x] Rücktest 2011 / 2018 / 2020 gerechnet — `scripts/backtest/backtest_move_periphery.py`.
- [x] Schwellen kalibriert: **MOVE amber 100/red 140**, **Peripherie amber 50/red 100 bp**
      (vorher provisorisch 110/150 bzw. 70/120 — waren zu unempfindlich).
- [x] Entscheidung: **vorerst NICHT** in `BROAD_PANIC_KEYS`. Stichprobe (3 Krisen) zu klein,
      MOVE ist nur Bestätiger (führt den VIX nicht), COVID-Peripherie knapp unter rot.
      Peripherie ist der stärkere Kandidat (2011 sauber rot, 44d früh) — bei mehr Evidenz
      neu bewerten. Ergebnis ausführlich in `backtest/report.md` (Addendum 2026-06-01).

## Noch offen (für später, optional)
- [ ] Peripherie ggf. in `BROAD_PANIC_KEYS` aufnehmen, wenn weitere EU-Krisen sie bestätigen
      (dann `KAUFSIGNAL_MIN_REDS` prüfen — mehr Kandidaten ⇒ evtl. Schwelle anheben).
- [ ] Roher BTP-Bund-Spread (IT 10J − DE 10J) als Alternative zum engeren Composite, falls
      eine tagesaktuelle italienische 10J-Quelle gefunden wird.
