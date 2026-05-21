# QC Monitor — Anleitung (einfach erklärt)

*Kurze Bedienungsanleitung auf Deutsch. Technische Details stehen in
`backtest/report.md`, die Produkt-Beschreibung in `README.md`.*

## Was macht das Tool?

Es beobachtet jeden Werktag früh ein paar Markt-Indikatoren (Angst, Zinsen, Öl,
Tech, Banken). Es meldet sich **nur dann**, wenn Qualitäts-Aktien (Versicherer,
Banken) wegen einer **breiten Panik** unfair billig werden — also ein guter
Moment zum **Kaufen** entstehen könnte.

## Wie läuft es?

Vollautomatisch über GitHub (in der Cloud), **Montag bis Freitag um ~08:00**.
Dein Laptop muss **nicht** an sein. Du musst nichts starten.

## Was bekommst du? Drei Zustände

| Zustand | Was es heißt | Was du tun sollst |
|---|---|---|
| **Stille** (keine Nachricht) | Alles normal | Nichts. Genießen. |
| 🟡 **BEOBACHTEN** | Ein Indikator ist auffällig | Nur zur Kenntnis nehmen, im Auge behalten |
| 🟢 **KAUFSIGNAL** | **Breiter Ausverkauf** (mind. 3 Indikatoren gleichzeitig rot) oder schwerer Hurrikan | Jetzt Qualitäts-Aktien prüfen und ggf. kaufen |

## Das Wichtigste: Du wirst nur bei **Änderung** benachrichtigt

Das Tool schickt **eine** Nachricht, wenn sich der Zustand **ändert** — nicht
jeden Tag aufs Neue.

- **Keine Nachricht = nichts Neues = alles in Ordnung.** Das ist Absicht (kein
  Spam mehr wie früher mit dem täglichen „Gelb"-Mail).
- Ein **KAUFSIGNAL** kommt **selten** — im Schnitt 1–2 Mal pro Jahr (in den
  letzten 7 Jahren nur ~3 Mal). Genau das ist gewollt: Qualität statt Lärm.

## Was du beachten musst

1. **Ein einzelner roter Indikator ist KEIN Kaufsignal.** Erst wenn **3 auf
   einmal** rot sind (= breite, unterschiedslose Panik), wird gehandelt. Das hat
   im 7-Jahres-Test den Unterschied gemacht (statt schlechter als der Index
   plötzlich +30 % auf 12 Monate).
2. **Das Signal feuert oft etwas VOR dem Tiefpunkt** (historisch im Schnitt
   einige Wochen früher). Deshalb: **gestaffelt kaufen** (z. B. in 2–3 Tranchen),
   nicht alles auf einmal — der Kurs kann nach dem Signal noch weiter fallen.
3. Es ist ein **Timing-Helfer**, kein Vorhersage-Orakel und **keine
   Anlageberatung**. Alle Entscheidungen triffst du selbst, auf eigenes Risiko.
4. Zwei Schwellen lösen praktisch nie aus (Brent > 130 $, US-Zins > 5,5 %) — das
   ist normal, sie sind absichtlich für Extremfälle reserviert.

## Aktuellen Stand jederzeit ansehen

Auf der **Status-Webseite** (wird jeden Morgen aktualisiert):
**https://h1054454.github.io/qc_monitor/status.html**

Dort siehst du alle Indikatoren farbig (grün/gelb/rot) mit Zeitstempel — auch
wenn keine Nachricht kam.

## Manuell testen / sofort laufen lassen

GitHub → Repository `qc_monitor` → Reiter **Actions** → „Market Monitor" →
Knopf **Run workflow**. Danach Status-Seite prüfen.
Hinweis: Eine **E-Mail/Telegram kommt nur, wenn sich der Zustand geändert hat** —
sonst läuft es still durch (das ist korrekt, kein Fehler).

## Die überwachten Schwellen (Kurzüberblick)

| Indikator | Gelb ab | Rot ab |
|---|---|---|
| VIX (Angst-Index) | 20 | 30 |
| Nasdaq 100 vom Hoch | −10 % | −20 % |
| NVIDIA vom Hoch | −20 % | −35 % |
| US-Regionalbanken (14 Tage) | −10 % | −15 % |
| US-Zins 10 Jahre | 4,5 % | 5,5 % (feuert quasi nie) |
| Brent-Öl (Krieg) | 120 $ | 130 $ (feuert quasi nie) |
| Hurrikan | Sturm 74+ mph | Kat. 3+ (eigenes Kaufsignal) |

**Rot allein reicht nicht — erst 3 rote zusammen ergeben ein KAUFSIGNAL.**

## Wo finde ich was?

- **Diese Anleitung:** `ANLEITUNG.md` (im Projekt-Ordner und auf GitHub)
- **Technische Auswertung (7-Jahres-Backtest):** `backtest/report.md`
- **Produkt-Beschreibung:** `README.md`
