# Backtest-Notiz: Vor-Indikatoren kalibrieren

*Angelegt 2026-06-03. Kalibrierung der Vor-Indikatoren (leading layer) aus der Krisen-Drehbücher-Erweiterung.*

## Warum diese Notiz

Am 2026-06-03 kam eine **getrennte Vor-Indikatoren-Ebene** in `market_monitor.py` (`LEADING_INDICATORS` + `evaluate_leading()`). Sie laufen rein informativ (eigener Heartbeat-/Status-Block, eigene `data/leading_history.csv`) und zählen **nie** zur ≥3-Rot-Regel — der Discount entsteht erst beim Preisverfall, ein Vor-Indikator löst also nie einen Kauf aus.

Die Schwellen waren zunächst **provisorisch**. Diese Notiz hält fest, wie sie kalibriert werden — und was schon kalibriert ist.

## Der Backtest ist ein *anderer* als bei den Panik-Indikatoren

Die 6 Panik-Indikatoren wurden auf **Payoff** kalibriert („kaufe ich beim Signal, was ist der 12-Monats-Return?"). Vor-Indikatoren lösen keinen Kauf aus → andere Metrik. `scripts/backtest/backtest_leading.py` misst:

1. **Vorlauf zum Tief** — Tage zwischen Vor-Indikator-rot und dem Markttief je Krise.
2. **Vorlauf vs. Panik-Indikator** — ging er rot, *bevor* der zugehörige Panik-Indikator (KRE bzw. US-10J) rot wurde?
3. **Fehlalarmrate** — über die *ganze* Historie: Rot-Episoden, die *keiner* Krise vorausgingen (Treffer = ein Krisen-Tief innerhalb 180 T nach Episodenstart, oder Start im Krisenfenster).
4. **Schwellen-Sweep** — Krisen-getroffen vs. Fehlalarme je Rot-Schwelle, um eine **gerundete** Schwelle nahe am Knie zu wählen (nicht das exakte Optimum → Overfitting-Schutz, wie bei MOVE 100/140).

Getestet gegen die 12 Krisen aus `crash_events.csv` (2007–2025).

## Status — Lauf 2026-06-03

| Indikator | Quelle | Stand |
|-----------|--------|-------|
| **KREXLF** (KRE/XLF) | yfinance 2006→26 | ✅ **backtestet & validiert** |
| **HYOAS** (HY-OAS) | FRED `BAMLH0A0HYM2` | ⏳ offen — FRED im Dev-Sandbox nur ~3-J-Fenster |
| **INFL5Y5Y** (5J/5J) | FRED `T5YIFR` | ⏳ offen — FRED-Timeout im Dev-Sandbox |
| **STEEPEN** (10J−2J Δ) | FRED `T10Y2Y` | ⏳ offen — FRED-Timeout im Dev-Sandbox |
| **TERMPREM** (Term-Premium) | FRED `THREEFYTP10` | ⏳ offen + Serie ggf. eingestellt |
| **BREADTH** (RSP/SPY) | yfinance | ⏳ offen — noch nicht gesweept |
| **DXYDIV** (Dollar-Divergenz) | yfinance | ⏳ offen — Divergenz-Logik, kein einfacher Sweep |

### KREXLF — validiert (Schwellen −5 / −10 bestätigt)

Vorlauf zum Tief (rot −10): GFC-2009 **70 T** vorher, COVID 14 T, SVB-2023 **52 T**, 2025-Tarif 5 T.
Vorlauf vs. KRE: 2009 **+43 T** führend, 2025 +8 T führend; COVID −6 T, SVB −4 T (in den *schnellen* Crashs leicht nachlaufend — erwartbar, das Relativ-Maß ist der Vorlauf-Tell in *langsamem* bankenspezifischem Stress, nicht im Alles-Crash).
**Fehlalarme: 0** (5 Rot-Episoden, alle 5 vor einer Krise).
Sweep: rot −6 → 8/12 Krisen, aber 9 Fehlalarme; **rot −10 → 4/12, 0 Fehlalarme** (sauberes Knie). → −5/−10 bleibt.

## Noch offen

- [ ] **HYOAS / INFL5Y5Y / STEEPEN / TERMPREM** auf einer Umgebung mit **voll erreichbarem FRED** rücktesten. Der Dev-Sandbox bekam für `BAMLH0A0HYM2` nur ein ~3-Jahres-Fenster und für `T5YIFR`/`T10Y2Y` gar nichts (Read-Timeout). Re-Run-Befehl: `python scripts/backtest/backtest_leading.py`. Sauberster Weg: einmalig auf dem **GitHub-Actions-Runner** (der erreicht FRED ohnehin für die Produktion) oder lokal mit stabiler Verbindung. Erwartung: HY-OAS-Rot bei den 2008er (~20 %) und 2020er (~11 %) Spitzes klar getroffen; Schwelle 6,0 vs. Sweep prüfen.
- [ ] **TERMPREM** `THREEFYTP10` zuerst auf „noch gepflegt?" prüfen; falls eingestellt → ACM-Ersatz.
- [ ] **BREADTH / DXYDIV** sweepen (yfinance-Daten vorhanden, nur noch keine Schwellen-Auswertung).
- [ ] Ergebnis je Indikator in `backtest/report.md` (Addendum) nachtragen, sobald gerechnet.

## Vorwarnung-Freischaltung (CALIBRATED_LEADING)

Kalibrierung hat eine direkte Konsequenz: nur **backtestete** Indikatoren stehen in `CALIBRATED_LEADING` (in `market_monitor.py`) und dürfen die edge-getriggerte Telegram-**„Vorwarnung — kein Kaufsignal"** auslösen (beim ersten Übergang auf rot). Nicht-kalibrierte laufen nur als Anzeige (Heartbeat + Status-Seite). Aktuell freigeschaltet: **KREXLF**. Wenn `backtest_leading.py` (z. B. via Actions-Workflow `leading-backtest.yml`) die FRED-Vier validiert, deren Keys hier ergänzen.

## Wichtig

Auch nach Kalibrierung bleiben die Vor-Indikatoren in der **getrennten Ebene** — anders als bei MOVE/Peripherie ist die Aufnahme ins ≥3-Set **nicht** das Ziel. Der Backtest macht nur die *Schwellen* belastbar, liefert die erwartete Vorlaufzeit + Fehlalarmrate und schaltet die Vorwarnung frei. Die E-Mail bleibt der reine KAUFSIGNAL-Kanal.
