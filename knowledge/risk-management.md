# Risk Management

Forscher's non-negotiable risk rules. Every trade must comply.

## The Golden Rule

> **SL at exchange or don't trade. Manual SL = fatal.**

Translation: Stop-loss must ALWAYS be set as an exchange-level algo order (`STOP_MARKET`), never tracked manually. A manual SL is a death sentence in volatile markets.

## SL/TP Mechanism

All SL and TP orders use Binance Futures **algo orders**, not regular limit/market orders:

```
POST /fapi/v1/algoOpenOrders
STOP_MARKET for stop-loss
TAKE_PROFIT_MARKET for take-profit
```

Verify with `GET /fapi/v1/algoOpenOrders` before and after every position.

## Exposure Model

Exposure is **not fixed** — it scales with market environment:

| Fear & Greed | BTC Dominance | Max Exposure (% of capital) |
|-------------|---------------|---------------------------|
| > 60 (Greed) | < 54% | 30% |
| 30–60 (Neutral) | 54–57% | 15% |
| < 30 (Extreme Fear) | > 57% | 5% or sit out |

Example: $25 capital, F&G=25 + BTC.D=58% → ceiling = $1.25 notional. That's barely worth it. Wait.

## Position Rules

1. **Every position MUST have a trading plan** — entry rationale, SL, TP, invalidation
2. **SL must be at exchange** before anything else — not "I'll set it after"
3. **TP must be set** (algo order or trailing)
4. **No revenge trading** — if SL hit, pause and re-analyze, do not re-enter immediately
5. **Trailing stop allowed** only after position is in profit > 1R

## Challenge Rules (Binance Testnet)

Active challenges have additional constraints:

| Rule | Value |
|------|-------|
| Capital | $25 USDT max |
| Market | Futures only |
| Leverage | Flexible |
| SL | Mandatory at exchange (algo order) |
| TP / Trailing | Mandatory |
| Review | Every 15 min via cron |

## Pre-Trade Checklist

- [ ] Market environment score checked (F&G, BTC.D)
- [ ] 4H structure identified (bullish/bearish/neutral)
- [ ] 1H confirmation found (OB + FVG)
- [ ] 15m execution zone identified (liquidity + kill zone)
- [ ] SL level determined and within risk budget
- [ ] TP level determined (R:R ≥ 1:2)
- [ ] Trading plan written (can be short, but must exist)

## Post-Trade Checklist

- [ ] Algo orders verified (`GET /fapi/v1/algoOpenOrders`)
- [ ] Position logged to challenge documentation
- [ ] If SL hit: review what went wrong, update skill if needed
- [ ] If TP hit: review what went right, consider trailing for future

---

*Last updated: 2026-05-24*
