# QC Monitor

**You get an email and a Telegram message when quality stocks become cheap for the wrong reasons.**

Macro events — a banking panic, a tech selloff, an oil price spike — cause institutional investors to dump everything liquid, including high-quality insurance and banking companies that have nothing to do with the triggering event. This tool watches for those moments and tells you which specific stocks are affected.

> **🇩🇪 Bedienungsanleitung auf Deutsch → [ANLEITUNG.md](ANLEITUNG.md)** — wie du das Tool benutzt und was du beachten musst.
> The signal is calibrated on a 7-year backtest — see [backtest/report.md](backtest/report.md).

---

## What you receive

A daily morning message (email + Telegram) that looks like this:

```
🟢 KAUFSIGNAL - Markt-Monitor
16.05.2026, 08:00

🟡 US 10-Jahres-Staatsanleihe (Rendite)
   4,60% - Gelb ab 4,5%, Rot ab 5,5%
   US-Haushaltsstress — KGV-Multiples werden mechanisch gedrückt

   Günstig im S&P 500: Cincinnati Financial, Chubb, Travelers, ...
   Günstig im DAX: Allianz SE, Munich Re, Hannover Rück
   Günstig im ATX: Erste Group, Vienna Insurance Group

   → Aktuelle Nachrichten

⚪ VIX Angst-Index: 18,50 - Gelb ab 20, Rot ab 30
⚪ Nasdaq 100: -1,5% vom 52W-Hoch - Gelb ab -10%, Rot ab -20%
...

⚪ NORMAL = Kein Signal  🟡 BEOBACHTEN = Im Auge behalten  🟢 KAUFSIGNAL = Jetzt handeln
```

When everything is normal, you hear nothing. The tool is silent until something matters.

---

## The seven scenarios it watches

Each scenario has a documented history of creating unfair discounts on specific quality stocks:

| Signal | What happened | Why it creates a buying window |
|--------|--------------|-------------------------------|
| **VIX > 30** | Broad market panic | Institutions sell everything liquid. Insurance and banking stocks fall even if they have nothing to do with the panic. |
| **US Regional Banks -15% in 14 days** | Banking sector crisis | Conservatively-managed banks like U.S. Bancorp fall with the sector despite sound balance sheets. |
| **Nasdaq -20% from high** | Tech correction | Portfolio margin calls force selling across all sectors. Insurers have zero AI exposure but fall with NVIDIA. |
| **NVIDIA -35% from high** | AI sentiment collapse | Early warning of a Nasdaq correction. Broad forced selling typically follows. |
| **Brent > $130** | Iran war escalation | European equities sell off on recession fears. But Allianz and Munich Re are *reinsurers* — catastrophe events raise their pricing power for years. |
| **US 10Y yield > 5.5%** | Treasury market stress | Rising risk-free rates compress P/E multiples mechanically. Same earnings, lower price — a math effect, not a business deterioration. |
| **Category 3+ Hurricane** | Atlantic storm landfall | Maximum fear discount on insurers hits 2-3 days after landfall — exactly when the next 5 years of premium increases are becoming certain. |

---

## The stocks it watches

Selected for demonstrated franchise value, disciplined management, and long-term pricing power:

**S&P 500** — Chubb, Cincinnati Financial, Travelers, Progressive, Arch Capital, U.S. Bancorp, M&T Bank, Wells Fargo

**DAX** — Allianz SE, Munich Re, Hannover Rück, Deutsche Börse, DHL Group

**ATX** — Erste Group, Vienna Insurance Group, Andritz AG, EVN AG

---

## Weekly screener

Every Monday morning, a second report shows where **both** Buffett (P/E below buy threshold) and Munger (price 10%+ off its 52-week high) would agree to act. When both signals align, the business quality is right *and* the price discipline is right.

---

## The website

A public landing page explains the philosophy and lets people subscribe. A live status page is regenerated each morning alongside the email — it shows the current reading of every indicator, color-coded, with a timestamp.

---

## Setup

```bash
pip install yfinance requests
cp config/monitor_config.example.json config/monitor_config.json
# Add Gmail App Password + Telegram bot credentials to monitor_config.json
python scripts/market_monitor.py
```

Full setup instructions are in `config/monitor_config.example.json`. Windows Task Scheduler commands are at the bottom of each script.

---

## Disclaimer

Private, non-commercial market observation. Not investment advice. Not a licensed financial advisor (WAG 2018 / MiFID II). All investment decisions are your own responsibility.
