# CHANGELOG

All notable developments in Forscher's evolution as a trading agent.

---

## 2026-05-25

### Changed
- **Philosophy shift: Pure Price Geometry** — removed all sentiment-based indicators
  - Replaced Fear & Greed with BTC 4H structure + BTC.D + TOTAL2 for macro assessment
  - `knowledge/market-screening.md` — completely rewritten with volume/liquidity funnel
  - `knowledge/risk-management.md` — exposure model now scales with structure, not sentiment
  - `README.md` — rewritten to reflect pure price geometry approach
  - `skills/catalog.md` — `market-environment` (F&G-based) marked DEPRECATED
- **Backtests cleanup** — archived pre-Wide25 versions (V5-V7) and early experiments to `backtests/archive/`

### Added
- `scripts/live_trader_v9.3g.py` — V9.3g production live trader tracked in repo
- Exposure Matrix in `market-screening.md` — combined BTC 4H + BTC.D + TOTAL2 filter
- "What We DON'T Use" section — explicit rejection of sentiment, news, and fixed allocation

### Updated
- `challenges/01-testnet-2026-05-24.md` — marked as Completed ✅

### Added
- **L0 5-Pillar Gate** — primary trade decision engine replacing ad-hoc analysis
  1. **Structure** (20%) — HH/HL, 20EMA, BOS/CHoCH — "Is the trend valid?"
  2. **Elliott Wave** (20%) — Wave 1-5, ABC, impulse vs corrective — "Which wave?"
  3. **Fibonacci** (20%) — Retracement + Extension + Confluence — "What price level?"
  4. **Supply/Demand** (20%) — Static + dynamic zones, S/R flip — "Are we safe?"
  5. **Gann Time Cycle** (20%) — Square of Nine, time clusters, cardinal dates — "When?"
- **Gann Time Cycle research** — comprehensive study of WD Gann's cyclical theory
  - 8 key Gann numbers: 144, 90, 45, 180, 270, 360, 30, 7
  - Square of Nine for price-to-time projections
  - Key angles: 45°, 90°, 135°, 180°, 225°, 270°, 315°, 360°
  - Time cluster scoring: ★ to ★★★★★
  - Research document: `knowledge/gann-research.md` (45+ sources)
- **Scoring matrix** — quantitative decision framework
  - ≥ 70% = LONG, 40-69% = WAIT, < 40% = SHORT/AVOID
- **3 new hard rules:**
  1. Wave 5 = 0% for Pillar 2 (FOMO killer)
  2. Below supply zone = WAIT (Pillar 4 override)
  3. No Gann time cluster = Max 50% total score

### Skills Updated
- **`forscher-trader-memory`** — upgraded from 4-pillar to 5-pillar L0 Gate
  - New pillar: Gann Time Cycle with Square of Nine + time cluster methodology
  - Scoring weights rebalanced: 30/25/25/20 → 20/20/20/20/20
  - Threshold raised: ≥65% → ≥70% (higher bar with 5 pillars)

### Knowledge Base
- `knowledge/trading-framework.md` — rewritten with full 5-pillar L0 Gate
- `knowledge/gann-research.md` — 45+ sources cataloging Gann theory implementations
- `skills/catalog.md` — added `forscher-trader-memory` as primary skill

### Challenge
- **Binance Testnet Challenge #1** completed (24–25 May 2026)
  - Permanent rules extracted: SL/TP must be exchange algo orders, no manual SL

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
