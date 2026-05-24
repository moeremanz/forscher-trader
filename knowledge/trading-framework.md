# Trading Framework

Forscher's trading methodology, built on Smart Money Concepts (SMC) with a disciplined multi-timeframe approach.

## Core Principles

1. **Always SL at exchange** — `STOP_MARKET` algo order, never manual. SL manual = fatal.
2. **Market environment first** — trade size dictated by Fear & Greed + BTC dominance
3. **Structure over noise** — 4H tells the story, 1H confirms, 15m executes
4. **Time exits only where proven** — ≤30m only, banned at ≥1H

## Multi-Timeframe Framework

### 4H — Structure (Patokan Utama)
- Identify market structure: BOS (Break of Structure) / CHoCH (Change of Character)
- Mark key Order Blocks (OB) and Fair Value Gaps (FVG)
- This is the **bias** — bullish or bearish structure

### 1H — Confirmation (Konfirmasi)
- Confirm 4H structure holds
- Look for OB + FVG confluence
- Entry zone refinement

### 15m — Execution (Eksekusi)
- Hunt for liquidity sweeps
- Identify kill zones (session opens)
- Precise entry timing

## SMC Tools

| Tool | What It Shows | Used At |
|------|--------------|---------|
| **OB** (Order Block) | Institutional entry/exit zones | 1H, 4H |
| **FVG** (Fair Value Gap) | Imbalance zones price likely to revisit | 1H, 4H |
| **BOS** (Break of Structure) | Trend continuation signal | 4H |
| **CHoCH** (Change of Character) | Potential trend reversal | 4H |
| **Liquidity** | Stop-hunt zones (equal highs/lows) | 15m |
| **Sessions** | Kill zones (London, NY opens) | 15m |
| **Retracements** | Fibonacci levels for entry confluences | 1H |
| **Prev High/Low** | Key structural levels | All TF |

## Entry Rules

### Valid Entry
1. 4H structure clearly bullish/bearish
2. 1H confirms with OB + FVG in direction of 4H bias
3. 15m shows liquidity sweep into kill zone
4. Candle CLOSE confirms (not just wick)

### False Breakout Rules
1. Wait for candle **close** above/below level (wick alone is not enough)
2. If wick > 50% of body → do not enter (indecision)
3. If close returns below resistance / above support → false breakout, ignore
4. Signal strength priority: 4H rejection > 1H rejection > 15m rejection

### Liquidity Trap Zones
| Day | Rule |
|-----|------|
| **Sat–Sun** | NO breakout entries. Trend-established only + tight SL |
| **Monday** | Wait for NY open (20:00 WIB) before entries |
| **Tue–Fri** | Normal trading conditions |

## Market Environment Overlay

Before any trade, check:
1. **Fear & Greed Index** — < 30 = extreme fear, reduce size
2. **BTC Dominance** — > 56% = alt-killer mode, avoid alts
3. **Exposure Limit** — tied to environment score, not fixed

See [market-screening.md](market-screening.md) for full methodology.

## Time-Based Exit Framework

Adopted from [joshyattridge/llm-trading-bot](https://github.com/joshyattridge/llm-trading-bot).

### Parameters
- **SL:** 1.5% below entry
- **TP:** 3.0% above entry
- **R:R:** 1:2
- **EARLYCUT:** 8 hours — if no TP hit within 8h, close at market
- **TIMEPROFIT:** 24 hours — auto-close at 24h if still open

### When to Use
| Timeframe | Use Time Exit? | Note |
|-----------|---------------|------|
| 15m | ✅ Yes | Improves performance |
| 30m | ✅ Yes | Small improvement |
| 1H | ❌ No | Degrades performance |
| 4H | ❌ No | Destructive to profits |

Backtest-validated on BTCUSDT and NEARUSDT across all timeframes.

---

*Last updated: 2026-05-24*
