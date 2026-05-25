# Market Screening

How Forscher screens the crypto market for tradeable setups — using pure price geometry, not sentiment.

## Environment First

Before looking at individual pairs, assess the macro environment through three structural filters:

### 1. BTC Structure (The Anchor)

BTC is the tide. If BTC's 4H structure is broken, altcoin trades are swimming against the current.

**4H SMC on BTC/USDT:**
- **Trend UP** (HH/HL intact, 20EMA sloping up) → Full altcoin exposure
- **Range** (chop between key levels) → Reduced size, scalp-only
- **Trend DOWN** (LH/LL, 20EMA sloping down) → No altcoin longs, SHORT-only

**Key BTC levels** are tracked per session — these shift with structure breaks.

### 2. BTC Dominance (BTC.D)

BTC.D tells you where capital is flowing — into BTC (risk-off) or into alts (risk-on).

| BTC.D Movement | Capital Flow | Altcoin Impact |
|---------------|-------------|----------------|
| Rising | Into BTC | Alts underperform — reduce exposure |
| Falling | Into alts | Alt season conditions — full exposure |
| Flat | Equilibrium | Neutral — normal sizing |

**Source:** TradingView `BTC.D` ticker or CoinGecko API.

### 3. TOTAL2 (Altcoin Market Cap)

TOTAL2 = total crypto market cap **excluding BTC**. It's the purest measure of altcoin health.

| TOTAL2 Structure | Interpretation | Action |
|-----------------|----------------|--------|
| HH/HL on 1D/4H | Alt market expanding | Full exposure |
| Range | Consolidation | Normal trading |
| LH/LL on 1D/4H | Alt market contracting | Reduce to minimum or sit out |

**Source:** TradingView `TOTAL2` ticker.

---

## Exposure Matrix

Combine the three filters to determine position sizing:

| BTC 4H | BTC.D | TOTAL2 | Exposure | Max Size |
|--------|-------|--------|----------|----------|
| 🟢 UP | Falling | HH/HL | **Full** | 100% |
| 🟢 UP | Flat | HH/HL | **Full** | 100% |
| 🟢 UP | Rising | HH/HL | **Reduced** | 75% |
| 🟡 RANGE | Falling | HH/HL | **Reduced** | 50% |
| 🟡 RANGE | Flat/Rising | Range | **Light** | 25% |
| 🔴 DOWN | Any | LH/LL | **MINIMAL** | No new entries |
| 🔴 DOWN | Rising | LH/LL | **SIT OUT** | Close all |

---

## Pair Screening Funnel

Once macro environment is assessed, screen individual pairs through a volume-liquidity funnel:

### Stage 1: Volume Filter
- 24h volume > $100M (futures) — anything below is illiquid
- Volume ratio: current 4H volume vs 20-period average — must be ≥0.8×
- Spikes >3× avg without structure → suspect manipulation, skip

### Stage 2: Liquidity Filter
- Bid/Ask spread <0.05% on 1m orderbook
- Open Interest >$50M and stable (not dropping >10% in 24h)
- Funding rate between -0.05% and +0.05% (extreme funding invites reversals)

### Stage 3: Structure Filter
- 4H must have clear HH/HL (LONG) or LH/LL (SHORT)
- Price must be >50 candles away from any major S/R flip zone (avoid chop)
- At least one SMC signal: recent BOS/CHoCH, untouched OB, or swept liquidity

### Stage 4: 5-Pillar Gate
- Candidates that pass stages 1–3 go through the full L0 5-Pillar Gate
- Only pairs scoring ≥70% make it to execution

---

## Screening Cadence

| Session | Action |
|---------|--------|
| **Daily (08:00 WIB)** | Full macro assessment + funnel run |
| **Every 4H** | BTC structure update, scan for new BOS/CHoCH |
| **Every 1H** | Confirm zones, update OB/FVG invalidation |
| **Every 15m (live)** | Entry execution only — no new pair discovery at this TF |

---

## What We DON'T Use

- ❌ **Fear & Greed Index** — sentiment, not structure. The chart already prices in fear and greed.
- ❌ **News-based screening** — headlines are lagging indicators. Price leads, news follows.
- ❌ **Social sentiment / Twitter hype** — noise. If the setup isn't on the chart, it doesn't exist.
- ❌ **Fixed allocation models** — exposure scales with BTC structure, not a spreadsheet.

---

*Last updated: 2026-05-25*
