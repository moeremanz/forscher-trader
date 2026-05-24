# Forscher Trader

```
██████████████████████████████████████████████████████████████████
█  _______ _______ ______ _______ ______ _______ _______ ______  █
█ |    ___|       |   __ \     __|      |   |   |    ___|   __ \ █
█ |    ___|   -   |      <__     |   ---|       |    ___|      < █
█ |___|   |_______|___|__|_______|______|___|___|_______|___|__| █
█                                                                █
██████████████████████████████████████████████████████████████████
```

**Evolution of an AI trading agent** — from basic bot to a disciplined trading analyst with multi-timeframe SMC methodology, time-based exit frameworks, and systematic challenge execution.

## Who is Forscher?

Forscher is an AI agent running on [Hermes](https://hermes-agent.nousresearch.com) — a personal AI agent framework. Forscher specializes in:

- **Crypto futures trading** on Binance Testnet
- **Technical analysis** using Smart Money Concepts (SMC)
- **Multi-timeframe analysis** (4H → 1H → 15m)
- **Risk-first discipline** — always SL at exchange, no exceptions

## Philosophy

> "The market speaks in structure. Learn the language, or stay silent."

- Trade the structure, not the noise
- Time-based exits only where they help (≤15m), never where they hurt (≥1H)
- Market environment dictates exposure — fear means small or no position
- Document everything. Every loss is a skill.

## Capabilities

| Area | Tools & Methods |
|------|-----------------|
| **Market Screening** | Fear & Greed, BTC dominance, volume filtering across 200+ pairs |
| **Technical Analysis** | SMC (OB, FVG, BOS/CHoCH, Liquidity), multi-TF: 4H → 1H → 15m |
| **Risk Management** | SL/TP as exchange algo orders, exposure limits tied to environment |
| **CoinGlass** | Weekly heatmap (3D/1W for big picture), liquidation levels |
| **Time-Based Exits** | Framework from llm-trading-bot: SL 1.5%, TP 3%, EARLYCUT 8h, TIMEPROFIT 24h — only at TF ≤30m |
| **LLM Routing** | DeepSeek v4-pro (default), OrcaRouter (160+ models for heavy tasks) |

## Repository Structure

```
forscher-trader/
├── README.md
├── CHANGELOG.md                    — Evolution timeline
├── knowledge/                      — Trading knowledge & methodologies
│   ├── trading-framework.md
│   ├── risk-management.md
│   └── market-screening.md
├── skills/
│   └── catalog.md                  — All trading skills
├── challenges/
│   └── 01-testnet-2026-05-24.md    — Challenge logs
├── tools/
│   └── orcarouter.md               — Tool integrations
└── .env.example                    — Environment template (no secrets)
```

---

*Built by Forscher, guided by moeremans.*
