# Agent Forscher

```
██████████████████████████████████████████████████████████████████
█  _______ _______ ______ _______ ______ _______ _______ ______  █
█ |    ___|       |   __ \\     __|      |   |   |    ___|   __ \\ █
█ |    ___|   -   |      <__     |   ---|       |    ___|      < █
█ |___|   |_______|___|__|_______|______|___|___|_______|___|__| █
█                                                                █
██████████████████████████████████████████████████████████████████
```

**Not built to predict the market. Built to survive it.**

> *"The market speaks in structure. Learn the language, or stay silent."*
>
> *"Risk is defined before reward is pursued."*

---

## What is Forscher?

Forscher is an AI agent running on [Hermes](https://hermes-agent.nousresearch.com) — a personal AI agent framework. It operates as an autonomous crypto futures trader with a **pure price geometry** approach: no sentiment indicators, no news-based bias, no hype.

Every decision flows through the **5-Pillar L0 Gate** — a quantitative scoring engine built on structure, cycles, and supply/demand.

---

## 5-Pillar L0 Gate

| # | Pillar | Weight | Question | Tools |
|---|--------|--------|----------|-------|
| 1 | **Structure** | 20% | Is the trend valid? | HH/HL, 20EMA, BOS/CHoCH |
| 2 | **Elliott Wave** | 20% | Which wave are we in? | Impulse 1–5, ABC corrective |
| 3 | **Fibonacci** | 20% | At what price level? | 0.382/0.5/0.618 retrace, 1.272/1.618 ext |
| 4 | **Supply/Demand** | 20% | Are we in a safe zone? | Static + dynamic zones, S/R flip |
| 5 | **Gann Time Cycle** | 20% | When will momentum arrive? | Square of Nine, time clusters |

**Scoring:** ≥70% = LONG · 40–69% = WAIT · <40% = SHORT/AVOID

**Hard Rules:**
- Wave 5 = 0% for Pillar 2 (FOMO killer)
- Below supply zone = WAIT (Pillar 4 override)
- No Gann time cluster = Max 50% total score

---

---

## Philosophy

- **Pure price geometry.** No Fear & Greed. No sentiment aggregation. The chart is the only truth.
- **Structure over everything.** If 4H structure doesn't align, no trade — regardless of lower-TF signals.
- **SL at exchange or don't trade.** Manual stop-loss is fatal. Every position opens with `STOP_MARKET` + `TAKE_PROFIT_MARKET` as exchange algo orders.
- **Exposure scales with BTC structure.** When BTC breaks below key levels, reduce size. When BTC trends, full exposure. No fixed allocation.
- **Document everything.** Every loss becomes a permanent skill. Every backtest is a lesson, not a number.

---

## Repository Structure

```
forscher-trader/
├── README.md                        — This file
├── CHANGELOG.md                     — Evolution timeline
├── .env.example                     — Environment template (no secrets)
├── .gitignore                       — Secrets, caches, OS files
│
├── knowledge/                       — Trading methodologies
│   ├── trading-framework.md         — 5-Pillar L0 Gate full spec
│   ├── market-screening.md          — Volume/liquidity-based screening
│   ├── risk-management.md           — Non-negotiable risk rules
│   ├── gann-research.md             — Gann Time Cycle research (45+ sources)
│   └── 5-pillar-fundamental-analysis.md
│
├── skills/
│   └── catalog.md                   — All active Hermes trading skills
│
├── backtests/                       — Backtest scripts (V5 → V11)
│   └── backtest_v9.3.py             — Current production
│
├── scripts/
│   └── live_trader_v9.3g.py.retired  — V9.3g (retired, Binance testnet terminated)
│
├── challenges/
│   └── 01-testnet-2026-05-24.md     — Challenge #1 (🔴 TERMINATED)
│
└── tools/
    └── orcarouter.md                — LLM routing integration
```

---

*Built by Forscher, guided by moeremans.*
