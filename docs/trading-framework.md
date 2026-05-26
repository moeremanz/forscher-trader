# Trading Framework

Forscher's trading methodology — a multi-pillar decision engine built on Smart Money Concepts (SMC), Elliott Wave, Fibonacci, Supply/Demand, and Gann Time Cycles.

## L0 Gate — 5-Pillar Decision Engine

The 5-pillar framework is the **primary gate** for every trade. All five pillars must be evaluated before any entry.

| # | Pillar | Question | Weight | Tools |
|---|--------|----------|--------|-------|
| 1 | **Structure** | Is the trend valid? | 20% | HH/HL, 20EMA, BOS/CHoCH |
| 2 | **Elliott Wave** | Which wave are we in? | 20% | Wave 1-5, ABC, impulse vs corrective |
| 3 | **Fibonacci** | At what price level? | 20% | Retracement 0.382/0.5/0.618, Extension 1.272/1.618 |
| 4 | **Supply/Demand** | Are we in a safe zone? | 20% | Static + dynamic zones, S/R flip |
| 5 | **Gann Time Cycle** | When will momentum arrive? | 20% | Square of Nine, time clusters, cardinal dates |

> *"Structure tells IF. Elliott tells WHERE in cycle. Fibonacci tells WHERE in price. S/D tells WHY. Gann tells WHEN."*

### Scoring Matrix

```
SCORE = P1(20) + P2(20) + P3(20) + P4(20) + P5(20)
MAX   = 100
```

| Score | Decision |
|-------|----------|
| ≥ 70% | **LONG** — Valid entry |
| 40-69% | **WAIT** — Insufficient confirmation |
| < 40% | **SHORT/AVOID** — Not tradeable |

### Hard Rules

1. **Wave 5 = 0% for Pillar 2** — NEVER enter on Wave 5. FOMO killer.
2. **Below supply zone = WAIT** — Even if 4 other pillars are bullish, Pillar 4 overrides.
3. **No Gann time cluster = Max 50% total score** — At least 1 cycle confluence required.

## Pilar 5: Gann Time Cycle

### Key Gann Numbers

```
144   ← Master cycle (days/weeks/months) — most powerful
90    ← Quarterly
45    ← Half-quarterly
180   ← Semi-annual
270   ← ¾ annual
360   ← Full annual
30    ← Monthly
7     ← Weekly
```

### Square of Nine

Input a significant price (swing high/low) into the Square of Nine spiral:
- **Support/Resistance levels** — horizontal price targets
- **Time projections** — which day price will reach a level
- **Key angles:** 45°, 90°, 135°, 180°, 225°, 270°, 315°, 360°

### Time Cluster Scoring

```
★★★★★  3+ cycles converge on the same date
★★★★   2 cycles converge
★★★    1 major cycle (144/90/360)
★★     Minor cycle only (30/45/7)
★      No cycle detected
```

### Ultimate Confluence

Wave 3 + 0.618 Fibonacci + Demand zone + Gann 144-day cycle + Square of Nine 180° angle = **★★★★★ setup**

### Gann References

- **Robert Miner** — Time/Price/Pattern: Gann + Elliott + Fibonacci (SacredTraders)
- **Bramesh** — Time cluster convergence analysis (brameshtechanalysis.com)
- **Patrick Mikula** — Trading the Square of Nine (PDF definitive guide)
- **Galarius/gann-square** — Python Square of Nine (GitHub)
- **JPMonty/Gann-time-series** — Python time node detection (GitHub)
- **monch1962/gann-swing** — Python Gann swing calculator (GitHub)
- **Ecency/NewsBTC** — Bitcoin 144-day/week cycle evidence

## Core Principles

1. **Always SL at exchange** — `STOP_MARKET` algo order, never manual. SL manual = fatal.
2. **Market environment first** — trade size dictated by Fear & Greed + BTC dominance
3. **Structure over noise** — 4H tells the story, 1H confirms, 15m executes
4. **Time exits only where proven** — ≤30m only, banned at ≥1H

## Multi-Timeframe Framework

### 4H — Structure (Main Anchor)
- Identify market structure: BOS (Break of Structure) / CHoCH (Change of Character)
- Mark key Order Blocks (OB) and Fair Value Gaps (FVG)
- This is the **bias** — bullish or bearish structure

### 1H — Confirmation
- Confirm 4H structure holds
- Look for OB + FVG confluence
- Entry zone refinement

### 15m — Execution
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

*Last updated: 2026-05-25*
