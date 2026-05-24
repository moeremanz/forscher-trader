# Market Screening

How Forscher screens the crypto market for tradeable setups.

## Environment First

Before looking at individual pairs, assess the macro environment:

### 1. Fear & Greed Index

```
Source: Alternative.me API or web scraping
Scale: 0 (Extreme Fear) → 100 (Extreme Greed)
```

| Range | Interpretation | Action |
|-------|---------------|--------|
| 0–25 | Extreme Fear | Reduce size, sit out if combined with high BTC.D |
| 25–45 | Fear | Cautious entries, smaller size |
| 45–55 | Neutral | Normal trading |
| 55–75 | Greed | Favourable, standard sizing |
| 75–100 | Extreme Greed | Watch for blow-off tops, consider taking profits |

### 2. BTC Dominance (BTC.D)

```
Source: CoinGecko, TradingView, or web search
```

| Range | Interpretation | Altcoin Impact |
|-------|---------------|----------------|
| < 54% | Alt season potential | Favourable for alts |
| 54–57% | Neutral | Mixed |
| > 57% | Alt-killer mode | Avoid alts, BTC only or sit out |

### 3. Macro Check

Quick scan:
- BTC price & 24h change
- Total market cap & 24h volume
- Top altcoin performance vs BTC

## Pair Screening

Screen Binance Futures pairs for candidates:

### Filters (priority order)
1. **Volume** — must be > $500M 24h for main focus, > $100M acceptable
2. **Momentum** — 24h change > 2% (either direction)
3. **Narrative** — does the pair have a story? (L1, DeFi, AI, meme, etc.)
4. **Volatility** — enough range to hit TP but not so much it hunts SL

### Screening Sources
- Binance Futures API: `GET /fapi/v1/ticker/24hr`
- CoinGlass: Weekly heatmap for macro levels (free tier limited, use sparingly)
- DexScreener: For on-chain pairs (not Binance-listed)

### What Gets Discarded
- Volume < $100M — not enough liquidity
- Pairs with no clear 4H structure
- Extreme outliers (500%+ pumps or -90% dumps)
- Stablecoin pairs (USDC/USDT etc.)

## Decision Matrix

| Environment | BTC.D | F&G | Action |
|------------|-------|-----|--------|
| Risk-on | <54% | >55 | Full screening, normal size |
| Cautious | 54–57% | 30–55 | Screen normally, half size |
| Risk-off | >57% | <30 | Minimal or no positions |

## Weekly CoinGlass Scan

Once per week (Monday), check CoinGlass heatmap:

- **3D/1W timeframe** — macro liquidity zones
- **Liquidation levels** — where stops cluster
- **Purpose:** Big-picture context, not entry timing

Free tier allows limited requests — use sparingly. Intraday levels read from standard charts.

---

*Last updated: 2026-05-24*
