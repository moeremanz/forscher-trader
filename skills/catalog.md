# Skills Catalog

Forscher's trading skills — reusable knowledge modules stored as Hermes skills.

## Active Trading Skills

### `forscher-trader-memory`
**Category:** trading  
**Purpose:** **L0 5-Pillar Gate** — the primary decision engine for every trade. Structure, Elliott Wave, Fibonacci, Supply/Demand, and Gann Time Cycle. Scoring matrix with hard rules (Wave 5 = 0%, below supply = WAIT, no time cluster = max 50%). Also serves as trading journal and postmortem system.

### `smart-money-concepts`
**Category:** trading  
**Purpose:** ICT Smart Money Concepts methodology — Order Blocks, Fair Value Gaps, Break of Structure, Change of Character, Liquidity zones, Sessions, Retracements. Mandatory for every trade analysis.

### `multi-timeframe-entry`
**Category:** trading  
**Purpose:** 4H structure → 1H confirmation → 15m execution framework. Defines the full pipeline from bias identification to precise entry timing.

### `time-based-exit-framework`
**Category:** trading  
**Purpose:** Exit rules adapted from `llm-trading-bot` — SL 1.5%, TP 3.0%, EARLYCUT 8h, TIMEPROFIT 24h. **Only for TF ≤ 30m** — destructive at ≥1H.

### `binance-futures-workflow`
**Category:** trading  
**Purpose:** End-to-end Binance Futures USDS-M trading workflow — screening, entry calculation, SL/TP as algo orders, position monitoring.

### `coinglass-weekly-swing-scanner`
**Category:** trading  
**Purpose:** Weekly CoinGlass liquidation heatmap analysis using 3D/1W timeframes. Big-picture macro scan, not intraday timing. Free tier conservation strategy.

### `timezone-awareness`
**Category:** trading  
**Purpose:** WIB (UTC+7) timezone context — session opens, kill zones, and date awareness for trade timing.

### `llm-trading-bot-analysis`
**Category:** trading  
**Purpose:** Analysis of `joshyattridge/llm-trading-bot` architecture — extracted time-based exit framework and validated across timeframes.

## Supporting Skills

### `market-environment` (forscher-market-environment)
**Category:** crypto  
**Purpose:** Market environment analysis — Fear & Greed, BTC dominance, total market cap — to determine exposure levels before screening.

### `binance` (binance-skills-hub)
**Category:** trading  
**Purpose:** Binance CLI operations — Spot, Futures USDS-M, and Coin-M endpoints.

---

*All skills stored in `~/.hermes/skills/`. Loaded on-demand when relevant to the task.*
