#!/usr/bin/env python3
"""
Forscher V9 — MULTI-TF SNIPER
==============================
4H: Structure → real S/R zones (3+ touches), trend direction
1H: Confirmation → price at zone, RSI alignment, volume surge
15m: Execution → reversal candle, RSI crossing, tight entry trigger

Target: WR ≥ 57% | 10+ altcoins | Dec 2025 – May 2026
"""
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════
SYMBOLS = [
    'ETH/USDT', 'SOL/USDT', 'NEAR/USDT', 'DOGE/USDT',
    'ONDO/USDT', 'LINK/USDT', 'AVAX/USDT', 'MATIC/USDT',
    'ARB/USDT', 'OP/USDT', 'INJ/USDT', 'TIA/USDT', 'SUI/USDT',
    'RUNE/USDT',
]

SINCE = '2025-12-01T00:00:00Z'
UNTIL = '2026-05-25T00:00:00Z'

# SL/TP as percentage of entry
SLTP_CONFIGS = [
    # Tight scalper
    ('Tight 1:1.5',   0.008, 0.012),
    ('Tight 1:2',     0.008, 0.016),
    # Mid
    ('Mid 1:1.5',     0.012, 0.018),
    ('Mid 1:2',       0.012, 0.024),
    # Wide
    ('Wide 1:1.5',    0.015, 0.0225),
    ('Wide 1:2',      0.015, 0.030),
]

# ── 4H STRUCTURE ──
SWING_LOOKBACK_4H = 30       # ~5 days of 4H candles
ZONE_TOUCH_MIN = 3            # minimum touches for a valid zone
ZONE_BAND_PCT = 0.015         # 1.5% band for zone clustering
TREND_EMA_FAST_4H = 20
TREND_EMA_SLOW_4H = 50

# ── 1H CONFIRMATION ──
RSI_PERIOD_1H = 14
RSI_LONG_MIN_1H = 30          # RSI above 30 = recovering from oversold
RSI_LONG_MAX_1H = 55          # RSI below 55 = not overbought yet
RSI_SHORT_MAX_1H = 70         # RSI below 70 = cooling from overbought
RSI_SHORT_MIN_1H = 45         # RSI above 45 = not oversold yet
VOLUME_THRESHOLD_1H = 1.15     # volume > 1.15x average
ZONE_PROXIMITY_1H = 0.008     # price within 0.8% of 4H zone

# ── 15m EXECUTION ──
RSI_PERIOD_15M = 7
RSI_CROSS_LONG = 35            # RSI crossing above 35
RSI_CROSS_SHORT = 65           # RSI crossing below 65
DIVERGENCE_LOOKBACK = 15       # candles for divergence check


# ═══════════════════════════════════════════════
# DATA FETCH
# ═══════════════════════════════════════════════
def fetch_ohlcv(symbol, timeframe, limit=1000):
    """Fetch complete OHLCV data"""
    exchange = ccxt.binance({'enableRateLimit': True})
    all_candles = []
    since_ms = exchange.parse8601(SINCE)

    while since_ms < exchange.parse8601(UNTIL):
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since_ms, limit)
            if not candles:
                break
            all_candles.extend(candles)
            since_ms = candles[-1][0] + 1
        except Exception as e:
            print(f"  ⚠️  {symbol} {timeframe}: {e}")
            break

    df = pd.DataFrame(all_candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    df.drop_duplicates(inplace=True)
    return df


# ═══════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════
def add_rsi(df, period=14):
    """Add RSI to dataframe"""
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


def add_emas(df, fast=20, slow=50):
    """Add EMAs"""
    df['ema_fast'] = df['close'].ewm(span=fast).mean()
    df['ema_slow'] = df['close'].ewm(span=slow).mean()
    df['trend_bull'] = df['ema_fast'] > df['ema_slow']
    df['trend_bear'] = df['ema_fast'] < df['ema_slow']
    return df


def add_swing_points(df, lookback=30):
    """Detect swing highs and lows"""
    df['swing_high'] = df['high'].rolling(lookback).max()
    df['swing_low'] = df['low'].rolling(lookback).min()
    return df


def add_volume_avg(df, period=20):
    """Add volume average and ratio"""
    df['vol_avg'] = df['volume'].rolling(period).mean()
    df['vol_ratio'] = df['volume'] / df['vol_avg']
    return df


def add_candle_patterns(df):
    """Add candle pattern detection"""
    df['body'] = df['close'] - df['open']
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    df['candle_range'] = df['high'] - df['low']

    # Patterns
    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']

    body_abs = df['body'].abs()
    df['is_hammer'] = (df['lower_wick'] > 2 * body_abs) & (body_abs > 0) & (df['upper_wick'] < df['lower_wick'] * 0.5)
    df['is_shooting_star'] = (df['upper_wick'] > 2 * body_abs) & (body_abs > 0) & (df['lower_wick'] < df['upper_wick'] * 0.5)
    df['is_engulfing_bull'] = df['is_bullish'] & (df['body'] > df['body'].shift(1).abs()) & (df['close'].shift(1) < df['open'].shift(1))
    df['is_engulfing_bear'] = df['is_bearish'] & (df['body'].abs() > df['body'].shift(1)) & (df['close'].shift(1) > df['open'].shift(1))

    return df


def add_rsi_divergence(df, rsi_col='rsi', lookback=15):
    """Detect RSI divergence: price lower low, RSI higher low (bullish) and vice versa"""
    df['bull_div'] = False
    df['bear_div'] = False

    for i in range(lookback + 2, len(df)):
        window = df.iloc[i - lookback:i + 1]

        # Find last two swing lows in price
        price_lows = []
        rsi_at_lows = []
        for j in range(1, len(window) - 1):
            if window['low'].iloc[j] < window['low'].iloc[j-1] and window['low'].iloc[j] < window['low'].iloc[j+1]:
                price_lows.append((j, window['low'].iloc[j]))
                rsi_at_lows.append((j, window[rsi_col].iloc[j]))

        if len(price_lows) >= 2:
            p1, p2 = price_lows[-2], price_lows[-1]
            r1, r2 = rsi_at_lows[-2], rsi_at_lows[-1]
            # Bullish divergence: price lower low, RSI higher low
            if p2[1] < p1[1] and r2[1] > r1[1]:
                df.iloc[i, df.columns.get_loc('bull_div')] = True

        # Find last two swing highs
        price_highs = []
        rsi_at_highs = []
        for j in range(1, len(window) - 1):
            if window['high'].iloc[j] > window['high'].iloc[j-1] and window['high'].iloc[j] > window['high'].iloc[j+1]:
                price_highs.append((j, window['high'].iloc[j]))
                rsi_at_highs.append((j, window[rsi_col].iloc[j]))

        if len(price_highs) >= 2:
            p1, p2 = price_highs[-2], price_highs[-1]
            r1, r2 = rsi_at_highs[-2], rsi_at_highs[-1]
            # Bearish divergence: price higher high, RSI lower high
            if p2[1] > p1[1] and r2[1] < r1[1]:
                df.iloc[i, df.columns.get_loc('bear_div')] = True

    return df


# ═══════════════════════════════════════════════
# 4H: ZONE DETECTION
# ═══════════════════════════════════════════════
def detect_zones_4h(df_4h, zone_band_pct=ZONE_BAND_PCT, min_touches=ZONE_TOUCH_MIN):
    """
    Find support and resistance zones from 4H data.
    A zone is a price band where price has reversed multiple times.
    """
    # Collect all swing highs and lows
    swing_high_points = []
    swing_low_points = []

    for i in range(1, len(df_4h) - 1):
        h = df_4h['high'].iloc[i]
        l = df_4h['low'].iloc[i]
        prev_h = df_4h['high'].iloc[i - 1]
        prev_l = df_4h['low'].iloc[i - 1]
        next_h = df_4h['high'].iloc[i + 1]
        next_l = df_4h['low'].iloc[i + 1]

        # Swing high: higher than both neighbors
        if h > prev_h and h > next_h:
            swing_high_points.append(h)
        # Swing low: lower than both neighbors
        if l < prev_l and l < next_l:
            swing_low_points.append(l)

    # Cluster nearby points into zones
    def cluster_levels(points):
        if not points:
            return []

        points = sorted(points)
        zones = []
        current_zone = [points[0]]

        for p in points[1:]:
            if (p - current_zone[-1]) / current_zone[-1] < zone_band_pct:
                current_zone.append(p)
            else:
                if len(current_zone) >= min_touches:
                    zones.append({
                        'price': np.mean(current_zone),
                        'top': max(current_zone),
                        'bottom': min(current_zone),
                        'touches': len(current_zone),
                        'type': 'zone'
                    })
                current_zone = [p]

        # Don't forget the last cluster
        if len(current_zone) >= min_touches:
            zones.append({
                'price': np.mean(current_zone),
                'top': max(current_zone),
                'bottom': min(current_zone),
                'touches': len(current_zone),
                'type': 'zone'
            })

        return zones

    support_zones = cluster_levels(swing_low_points)
    resistance_zones = cluster_levels(swing_high_points)

    return support_zones, resistance_zones


def price_near_zone(price, zones, proximity_pct=ZONE_PROXIMITY_1H):
    """Check if price is near any zone"""
    for zone in zones:
        if abs(price - zone['price']) / price < proximity_pct:
            return zone
    return None


# ═══════════════════════════════════════════════
# ENTRY DETECTION
# ═══════════════════════════════════════════════
def align_timeframes(df_4h, df_1h, df_15m, support_zones, resistance_zones):
    """
    Detect entries using multi-TF alignment:
    4H: trend direction + zone
    1H: price at zone + RSI alignment + volume
    15m: trigger candle + RSI crossing + divergence
    """
    signals = []

    # Get 4H trend
    trend_bull_4h = df_4h['trend_bull'].iloc[-1]
    trend_bear_4h = df_4h['trend_bear'].iloc[-1]

    for i in range(3, len(df_15m)):
        ts_15m = df_15m.index[i]
        price_15m = df_15m['close'].iloc[i]

        # ── Find corresponding 1H candle ──
        # 1H candle that covers this 15m timestamp
        mask_1h = df_1h.index <= ts_15m
        if not mask_1h.any():
            continue
        idx_1h = mask_1h.sum() - 1
        if idx_1h < 2:
            continue

        row_1h = df_1h.iloc[idx_1h]
        price_1h = row_1h['close']

        # ── 1H CONFIRMATION CHECKS ──
        # Check if near 4H zone
        near_support = price_near_zone(price_1h, support_zones)
        near_resistance = price_near_zone(price_1h, resistance_zones)

        if near_support is None and near_resistance is None:
            continue

        vol_ok = row_1h['vol_ratio'] > VOLUME_THRESHOLD_1H if not pd.isna(row_1h['vol_ratio']) else False

        # ── 15m EXECUTION CHECKS ──
        row_15m = df_15m.iloc[i]
        rsi_15m = row_15m['rsi']
        rsi_15m_prev = df_15m['rsi'].iloc[i - 1] if i > 0 else rsi_15m

        rsi_crossing_up = (rsi_15m_prev < RSI_CROSS_LONG and rsi_15m >= RSI_CROSS_LONG)
        rsi_crossing_down = (rsi_15m_prev > RSI_CROSS_SHORT and rsi_15m <= RSI_CROSS_SHORT)

        # ── LONG ENTRY ──
        if near_support and trend_bull_4h:
            # 1H confirmation
            rsi_1h = row_1h['rsi']
            rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_LONG_MIN_1H and rsi_1h <= RSI_LONG_MAX_1H)

            # 1H candle bullish or has lower wick (rejection at support)
            candle_1h_ok = row_1h['is_bullish'] or row_1h['is_hammer']

            # 15m trigger
            trigger_15m = (row_15m['is_bullish'] or row_15m['is_hammer'] or row_15m['is_engulfing_bull'])
            rsi_15m_ok = rsi_15m < 60  # not already overbought
            div_ok = row_15m['bull_div']  # bonus: bullish divergence

            conditions_met = sum([
                rsi_1h_ok,
                candle_1h_ok,
                trigger_15m,
                rsi_15m_ok or rsi_crossing_up,
                vol_ok,
            ])

            # Need 3+ conditions + at minimum zone proximity
            if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
                signals.append({
                    'idx': i,
                    'side': 'LONG',
                    'entry': price_15m,
                    'support_zone': near_support['price'],
                    'zone_touches': near_support['touches'],
                    'rsi_1h': rsi_1h,
                    'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok,
                    'conditions': conditions_met,
                    'timestamp': ts_15m,
                })

        # ── SHORT ENTRY ──
        if near_resistance and trend_bear_4h:
            rsi_1h = row_1h['rsi']
            rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_SHORT_MIN_1H and rsi_1h <= RSI_SHORT_MAX_1H)

            candle_1h_ok = row_1h['is_bearish'] or row_1h['is_shooting_star']

            trigger_15m = (row_15m['is_bearish'] or row_15m['is_shooting_star'] or row_15m['is_engulfing_bear'])
            rsi_15m_ok = rsi_15m > 40  # not already oversold
            div_ok = row_15m['bear_div']

            conditions_met = sum([
                rsi_1h_ok,
                candle_1h_ok,
                trigger_15m,
                rsi_15m_ok or rsi_crossing_down,
                vol_ok,
            ])

            if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
                signals.append({
                    'idx': i,
                    'side': 'SHORT',
                    'entry': price_15m,
                    'resistance_zone': near_resistance['price'],
                    'zone_touches': near_resistance['touches'],
                    'rsi_1h': rsi_1h,
                    'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok,
                    'conditions': conditions_met,
                    'timestamp': ts_15m,
                })

    return signals


# ═══════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════
def simulate_trades(df_15m, signals, sl_pct, tp_pct):
    """Forward-simulate trades using 15m data"""
    trades = []
    signal_idx = 0
    active_signals = []

    for i in range(len(df_15m)):
        row = df_15m.iloc[i]

        # Add new signals
        while signal_idx < len(signals) and signals[signal_idx]['idx'] <= i:
            sig = signals[signal_idx]
            if sig['idx'] == i:
                entry_price = sig['entry']
                if sig['side'] == 'LONG':
                    sl_price = entry_price * (1 - sl_pct)
                    tp_price = entry_price * (1 + tp_pct)
                else:
                    sl_price = entry_price * (1 + sl_pct)
                    tp_price = entry_price * (1 - tp_pct)
                active_signals.append((sig, i, sl_price, tp_price))
            signal_idx += 1

        # Check active trades
        remaining = []
        for sig, entry_idx, sl_price, tp_price in active_signals:
            if i <= entry_idx:
                remaining.append((sig, entry_idx, sl_price, tp_price))
                continue

            exit_price = None
            exit_type = None

            if sig['side'] == 'LONG':
                if row['low'] <= sl_price:
                    exit_price = sl_price
                    exit_type = 'SL'
                elif row['high'] >= tp_price:
                    exit_price = tp_price
                    exit_type = 'TP'
                else:
                    remaining.append((sig, entry_idx, sl_price, tp_price))
                    continue
            else:
                if row['high'] >= sl_price:
                    exit_price = sl_price
                    exit_type = 'SL'
                elif row['low'] <= tp_price:
                    exit_price = tp_price
                    exit_type = 'TP'
                else:
                    remaining.append((sig, entry_idx, sl_price, tp_price))
                    continue

            pnl_pct = ((exit_price - sig['entry']) / sig['entry']) * (1 if sig['side'] == 'LONG' else -1)
            trades.append({
                'side': sig['side'],
                'entry_time': sig['timestamp'],
                'exit_time': df_15m.index[i],
                'entry_price': sig['entry'],
                'exit_price': exit_price,
                'exit_type': exit_type,
                'pnl_pct': pnl_pct,
                'zone_touches': sig.get('zone_touches', 0),
                'conditions': sig.get('conditions', 0),
                'rsi_1h': sig.get('rsi_1h', np.nan),
                'rsi_15m': sig.get('rsi_15m', np.nan),
                'divergence': sig.get('divergence', False),
            })

        active_signals = remaining

    return trades


# ═══════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════
def analyze_trades(trades):
    """Compute stats for a set of trades"""
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0,
            'pnl_total': 0, 'avg_win': 0, 'avg_loss': 0,
            'expectancy': 0, 'max_dd': 0,
            'long_trades': 0, 'long_wr': 0, 'short_trades': 0, 'short_wr': 0,
        }

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    longs = [t for t in trades if t['side'] == 'LONG']
    shorts = [t for t in trades if t['side'] == 'SHORT']

    cum_pnl = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cum_pnl += t['pnl_pct']
        peak = max(peak, cum_pnl)
        max_dd = max(max_dd, peak - cum_pnl)

    def _wr(tlist):
        if not tlist: return 0
        return sum(1 for t in tlist if t['pnl_pct'] > 0) / len(tlist) * 100

    return {
        'trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'wr': _wr(trades),
        'pnl_total': cum_pnl,
        'avg_win': np.mean([t['pnl_pct'] for t in wins]) if wins else 0,
        'avg_loss': np.mean([t['pnl_pct'] for t in losses]) if losses else 0,
        'expectancy': (np.mean([t['pnl_pct'] for t in wins]) * _wr(trades) / 100 +
                       np.mean([t['pnl_pct'] for t in losses]) * (1 - _wr(trades) / 100)) if trades else 0,
        'max_dd': max_dd,
        'long_trades': len(longs),
        'long_wr': _wr(longs),
        'short_trades': len(shorts),
        'short_wr': _wr(shorts),
    }


def backtest_symbol(symbol):
    """Full multi-TF backtest for one symbol"""
    print(f"\n{'='*60}")
    print(f"  {symbol}")
    print(f"{'='*60}")

    # Fetch all 3 timeframes
    print(f"  📡 Fetching 4H...")
    df_4h = fetch_ohlcv(symbol, '4h')
    print(f"  📡 Fetching 1H...")
    df_1h = fetch_ohlcv(symbol, '1h')
    print(f"  📡 Fetching 15m...")
    df_15m = fetch_ohlcv(symbol, '15m')

    if df_4h.empty or df_1h.empty or df_15m.empty:
        print(f"  ❌ Missing data")
        return {}

    # Add indicators to each TF
    df_4h = add_rsi(df_4h, 14)
    df_4h = add_emas(df_4h, TREND_EMA_FAST_4H, TREND_EMA_SLOW_4H)
    df_4h = add_swing_points(df_4h, SWING_LOOKBACK_4H)

    df_1h = add_rsi(df_1h, RSI_PERIOD_1H)
    df_1h = add_volume_avg(df_1h, 20)
    df_1h = add_candle_patterns(df_1h)

    df_15m = add_rsi(df_15m, RSI_PERIOD_15M)
    df_15m = add_candle_patterns(df_15m)
    df_15m = add_rsi_divergence(df_15m, 'rsi', DIVERGENCE_LOOKBACK)

    print(f"  📊 4H:{len(df_4h)}  1H:{len(df_1h)}  15m:{len(df_15m)} candles")

    # Detect zones from 4H
    support_zones, resistance_zones = detect_zones_4h(df_4h)
    print(f"  🏗️  Support zones: {len(support_zones)} | Resistance zones: {len(resistance_zones)}")

    if not support_zones and not resistance_zones:
        print(f"  ❌ No zones detected — skipping")
        return {}

    # Detect entries
    signals = align_timeframes(df_4h, df_1h, df_15m, support_zones, resistance_zones)
    n_long = sum(1 for s in signals if s['side'] == 'LONG')
    n_short = sum(1 for s in signals if s['side'] == 'SHORT')
    n_div = sum(1 for s in signals if s.get('divergence'))
    print(f"  🔍 Signals: {len(signals)} ({n_long}L / {n_short}S) | Divergence: {n_div}")

    # Test all SL/TP configs
    results = {}
    for label, sl_pct, tp_pct in SLTP_CONFIGS:
        trades = simulate_trades(df_15m, signals, sl_pct, tp_pct)
        stats = analyze_trades(trades)
        stats['label'] = label
        results[label] = stats

    return results


def print_symbol_results(symbol, results):
    """Print results for one symbol"""
    if not results:
        return
    print(f"\n  {'Config':<16} {'Trades':>6} {'WR':>7} {'PnL':>9} {'AvgW':>7} {'AvgL':>7} {'Exp':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>6}")
    print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*6}")
    for label, s in results.items():
        print(f"  {label:<16} {s['trades']:>6} {s['wr']:>6.1f}% {s['pnl_total']:>+8.2f}% "
              f"{s['avg_win']:>6.2f}% {s['avg_loss']:>6.2f}% {s['expectancy']:>6.2f}% "
              f"{s['max_dd']:>6.2f}% {s['long_trades']:>4} {s['long_wr']:>5.1f}% "
              f"{s['short_trades']:>4} {s['short_wr']:>5.1f}%")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 80)
    print("  FORSCHER V9 — MULTI-TF SNIPER")
    print("  4H Structure → 1H Confirmation → 15m Execution")
    print("  Target WR: ≥57% | Period: Dec 2025 – May 2026")
    print("=" * 80)

    all_results = {}

    for symbol in SYMBOLS:
        results = backtest_symbol(symbol)
        all_results[symbol] = results
        print_symbol_results(symbol, results)

    # ═══════════════════════════════════════════
    # GRAND SUMMARY
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  GRAND SUMMARY — All Pairs, All Configs (sorted by WR)")
    print("=" * 80)

    all_rows = []
    for symbol, results in all_results.items():
        for label, s in results.items():
            all_rows.append((symbol, label, s))

    all_rows.sort(key=lambda x: x[2]['wr'], reverse=True)

    print(f"\n  {'Symbol/Config':<40} {'Trades':>6} {'WR':>7} {'PnL':>9} {'AvgW':>7} {'AvgL':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>7}")
    print(f"  {'-'*40} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*7}")

    for symbol, label, s in all_rows:
        print(f"  {symbol} {label:<22} {s['trades']:>6} {s['wr']:>6.1f}% {s['pnl_total']:>8.2f}% "
              f"{s['avg_win']:>6.2f}% {s['avg_loss']:>6.2f}% {s['max_dd']:>6.2f}% "
              f"{s['long_trades']:>4} {s['long_wr']:>5.1f}% {s['short_trades']:>4} {s['short_wr']:>6.1f}%")

    # ═══════════════════════════════════════════
    # AGGREGATE BY CONFIG
    # ═══════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  AGGREGATE BY CONFIG")
    print(f"{'='*80}")

    for label, sl_pct, tp_pct in SLTP_CONFIGS:
        combined = [all_results[sym][label] for sym in all_results if sym in all_results and label in all_results[sym]]
        if not combined:
            continue

        total_trades = sum(s['trades'] for s in combined)
        total_wins = sum(s['wins'] for s in combined)
        wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(s['pnl_total'] for s in combined)
        pairs = sum(1 for s in combined if s['trades'] > 0)
        total_longs = sum(s['long_trades'] for s in combined)
        total_shorts = sum(s['short_trades'] for s in combined)

        print(f"  {label:<16} Trades:{total_trades:>5} | WR:{wr:>6.1f}% | PnL:{total_pnl:>+8.2f}% | "
              f"Pairs:{pairs:>2}/{len(SYMBOLS)} | L:{total_longs:>4} S:{total_shorts:>4}")

    # ═══════════════════════════════════════════
    # TOP CONFIGS
    # ═══════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  🏆 TOP CONFIGS (WR ≥ 50%, sorted by PnL)")
    print(f"{'='*80}")

    top = [(sym, lbl, s) for sym, lbl, s in all_rows if s['wr'] >= 50 and s['trades'] >= 5]
    top.sort(key=lambda x: x[2]['pnl_total'], reverse=True)

    if top:
        for sym, lbl, s in top[:20]:
            print(f"  {sym} {lbl:<22} WR:{s['wr']:.1f}% PnL:{s['pnl_total']:+.2f}% "
                  f"Trades:{s['trades']} MaxDD:{s['max_dd']:.2f}% L:{s['long_trades']}({s['long_wr']:.0f}%) S:{s['short_trades']}({s['short_wr']:.0f}%)")
    else:
        print("  ❌ No config with WR ≥ 50% and ≥ 5 trades")

    print(f"\n{'='*80}")
    print("  BACKTEST COMPLETE")
    print(f"{'='*80}")
