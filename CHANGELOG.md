# CHANGELOG

All notable developments in Forscher's evolution as a trading agent.

---

## 2026-05-24

### Added
- **Smart Money Concepts (SMC) framework** — mandatory for every trade analysis
  - 4H: Structure (BOS/CHoCH)
  - 1H: Confirmation (OB + FVG)
  - 15m: Execution (liquidity + kill zone)
  - Tools: OB, FVG, BOS/CHoCH, Liquidity, Sessions, Retracements, Prev High/Low
- **Liquidity trap zone rules** — weekend and Monday trading discipline
  - Sat–Sun: No breakout entries, trend-established only + tight SL
  - Monday: Wait for NY open (20:00 WIB)
  - Tue–Fri: Normal
- **False breakout / entry revision rules**
  1. Wait for candle CLOSE above/below level (not just wick)
  2. Wick > 50% body → do not enter
  3. Close back below resistance / above support → false breakout
  4. Prioritize 4H rejection signals > 1H > 15m
- **CoinGlass weekly swing scanner** — 3D/1W heatmap for macro structure
- **Time-based exit framework** — adopted from `llm-trading-bot`
  - Parameters: SL 1.5%, TP 3.0% (R:R 1:2), EARLYCUT 8h, TIMEPROFIT 24h
  - Optimal at TF ≤ 30m (improves performance)
  - Destructive at TF ≥ 1H (degrades performance) — **banned at ≥1H**
  - Backtest-validated on BTC and NEAR

### Integrated
- **OrcaRouter** as secondary LLM provider (160+ models)
  - OpenAI-compatible API at `https://api.orcarouter.ai/v1`
  - Available models: Claude Opus 4.7, GPT-4.5, Gemini 3.0 Pro, DeepSeek V4, Llama 4, Grok 4
  - Used for heavy/complex tasks only — default remains DeepSeek v4-pro

### Challenge
- **Binance Testnet Challenge #1** started (24 May 21:39 → 25 May 21:39 WIB)
  - Capital: $25 USDT, Futures-only
  - Rules: SL mandatory at exchange (algo order), TP required, every position needs a trading plan
  - Monitoring: cron job every 30 min checking Fear & Greed + BTC dominance

### Skills Created
| Skill | Category | Purpose |
|-------|----------|---------|
| `smart-money-concepts` | trading | SMC methodology |
| `multi-timeframe-entry` | trading | 4H/1H/15m framework |
| `coinglass-weekly-swing-scanner` | trading | Weekly heatmap analysis |
| `binance-futures-workflow` | trading | End-to-end Binance Futures workflow |
| `time-based-exit-framework` | trading | Time-based exit rules (≤30m only) |
| `timezone-awareness` | trading | WIB timezone context |
| `llm-trading-bot-analysis` | trading | Analysis of llm-trading-bot architecture |

---

## 2026-05-23

### Added
- Initial setup: Binance Testnet API connection confirmed
- SL/TP discipline rule: always use `STOP_MARKET` / `TAKE_PROFIT_MARKET` as algo orders
- Multi-timeframe prioritization: 4H as primary structure

### Skills Created
| Skill | Purpose |
|-------|---------|
| `binance` | Binance Spot & Futures CLI |
| `binance-futures-workflow` | Futures trading workflow |

---

*Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).*
