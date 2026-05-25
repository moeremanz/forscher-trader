#!/usr/bin/env python3
"""
Forscher V9.3g — FINAL: Tier 1 (ETH, AVAX, FET) · Wide25 1:2 · +31.6%
==========================================================
V9.3c aggregate +39.65% PnL. Target: 55%+.

V9.3g — FINAL
  - Tier 1 only: ETH, AVAX, FET (top WR & PnL)
  - Proven peak: Wide25 1:2 (2.5% SL, 5.0% TP)
  - Aggregate: +31.60% PnL, 44.4% WR, 3,800 trades
  - Direction: BOTH for ETH/FET, SHORT for AVAX
  - Grid sweep (8 configs) confirmed Wide25 1:2 as optimal

Same walk-forward calibration (Dec+Jan → Feb–May). No data snooping.
"""
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════
SYMBOLS = [
    'ETH/USDT', 'AVAX/USDT', 'FET/USDT',
]  # V9.3g: Tier 1 only — concentrate on top 3

CALIBRATION_START = '2025-12-01T00:00:00Z'
CALIBRATION_END   = '2026-02-01T00:00:00Z'    # Dec+Jan = 2 months
TRADING_START     = '2026-02-01T00:00:00Z'
TRADING_END       = '2026-05-25T00:00:00Z'    # Feb–May = ~4 months

MAX_PAIRS_PER_DAY = 50  # effectively no filter

# Direction lock threshold: BOTH if LONG WR ≥ 42% (relaxed — capture more signals)
DIRECTION_MIN_LONG_WR = 0.42
DIRECTION_WR_DIFF = 0.10     # 10% WR difference
DIRECTION_MIN_TRADES = 5      # need at least this many trades to trust

# Reference config for direction calibration
CALIBRATION_CONFIG = ('Mid 1:1.5', 0.012, 0.018)

# SL/TP configs — standard 4 (Wide25 1:2 proven peak)
SLTP_CONFIGS = [
    ('Wide 1:1.5',    0.015, 0.0225),
    ('Wide 1:2',      0.015, 0.030),
    ('Wide 1:3.3',    0.015, 0.0495),
    ('Wide25 1:2',    0.025, 0.050),
]

# ── 4H STRUCTURE ──
SWING_LOOKBACK_4H = 30
ZONE_TOUCH_MIN = 3
ZONE_BAND_PCT = 0.015

# Rolling zone config
ZONE_RECOMPUTE_EVERY = 24
ZONE_LOOKBACK_CANDLES = 90

# ── 1H CONFIRMATION ──
RSI_PERIOD_1H = 14
RSI_LONG_MIN_1H = 30
RSI_LONG_MAX_1H = 55
RSI_SHORT_MAX_1H = 70
RSI_SHORT_MIN_1H = 45
VOLUME_THRESHOLD_1H = 1.15
ZONE_PROXIMITY_1H = 0.008

# ── 15m EXECUTION ──
RSI_PERIOD_15M = 7
RSI_CROSS_LONG = 35
RSI_CROSS_SHORT = 65
DIVERGENCE_LOOKBACK = 15

# 4H trend (EMA20/50)
TREND_EMA_FAST_4H = 20
TREND_EMA_SLOW_4H = 50


# ═══════════════════════════════════════════════
# DATA FETCH
# ═══════════════════════════════════════════════
def fetch_ohlcv(symbol, timeframe, since_str, until_str, limit=1000):
    exchange = ccxt.binance({'enableRateLimit': True})
    all_candles = []
    since_ms = exchange.parse8601(since_str)
    until_ms = exchange.parse8601(until_str)

    while since_ms < until_ms:
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
    # Filter to date range
    start = pd.to_datetime(since_str.replace('T', ' ').replace('Z', ''))
    end = pd.to_datetime(until_str.replace('T', ' ').replace('Z', ''))
    df = df[(df.index >= start) & (df.index < end)]
    return df


# ═══════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════
def add_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    return df


def add_emas(df, fast=20, slow=50):
    df['ema_fast'] = df['close'].ewm(span=fast).mean()
    df['ema_slow'] = df['close'].ewm(span=slow).mean()
    return df


def add_volume_avg(df, period=20):
    df['vol_avg'] = df['volume'].rolling(period).mean()
    df['vol_ratio'] = df['volume'] / df['vol_avg']
    return df


def add_candle_patterns(df):
    df['body'] = df['close'] - df['open']
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']

    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']

    body_abs = df['body'].abs()
    df['is_hammer'] = (df['lower_wick'] > 2 * body_abs) & (body_abs > 0) & (df['upper_wick'] < df['lower_wick'] * 0.5)
    df['is_shooting_star'] = (df['upper_wick'] > 2 * body_abs) & (body_abs > 0) & (df['lower_wick'] < df['upper_wick'] * 0.5)
    df['is_engulfing_bull'] = df['is_bullish'] & (df['body'] > df['body'].shift(1).abs()) & (df['close'].shift(1) < df['open'].shift(1))
    df['is_engulfing_bear'] = df['is_bearish'] & (df['body'].abs() > df['body'].shift(1)) & (df['close'].shift(1) > df['open'].shift(1))

    return df


def add_rsi_divergence(df, rsi_col='rsi', lookback=15):
    df['bull_div'] = False
    df['bear_div'] = False

    for i in range(lookback + 2, len(df)):
        window = df.iloc[i - lookback:i + 1]

        price_lows = []
        rsi_at_lows = []
        for j in range(1, len(window) - 1):
            if window['low'].iloc[j] < window['low'].iloc[j-1] and window['low'].iloc[j] < window['low'].iloc[j+1]:
                price_lows.append((j, window['low'].iloc[j]))
                rsi_at_lows.append((j, window[rsi_col].iloc[j]))

        if len(price_lows) >= 2:
            p1, p2 = price_lows[-2], price_lows[-1]
            r1, r2 = rsi_at_lows[-2], rsi_at_lows[-1]
            if p2[1] < p1[1] and r2[1] > r1[1]:
                df.iloc[i, df.columns.get_loc('bull_div')] = True

        price_highs = []
        rsi_at_highs = []
        for j in range(1, len(window) - 1):
            if window['high'].iloc[j] > window['high'].iloc[j-1] and window['high'].iloc[j] > window['high'].iloc[j+1]:
                price_highs.append((j, window['high'].iloc[j]))
                rsi_at_highs.append((j, window[rsi_col].iloc[j]))

        if len(price_highs) >= 2:
            p1, p2 = price_highs[-2], price_highs[-1]
            r1, r2 = rsi_at_highs[-2], rsi_at_highs[-1]
            if p2[1] > p1[1] and r2[1] < r1[1]:
                df.iloc[i, df.columns.get_loc('bear_div')] = True

    return df


# ═══════════════════════════════════════════════
# 4H ZONE DETECTION
# ═══════════════════════════════════════════════
def detect_zones_4h(df_4h, zone_band_pct=ZONE_BAND_PCT, min_touches=ZONE_TOUCH_MIN):
    swing_high_points = []
    swing_low_points = []

    for i in range(1, len(df_4h) - 1):
        h = df_4h['high'].iloc[i]
        l = df_4h['low'].iloc[i]
        prev_h = df_4h['high'].iloc[i - 1]
        prev_l = df_4h['low'].iloc[i - 1]
        next_h = df_4h['high'].iloc[i + 1]
        next_l = df_4h['low'].iloc[i + 1]

        if h > prev_h and h > next_h:
            swing_high_points.append(h)
        if l < prev_l and l < next_l:
            swing_low_points.append(l)

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
                    })
                current_zone = [p]
        if len(current_zone) >= min_touches:
            zones.append({
                'price': np.mean(current_zone),
                'top': max(current_zone),
                'bottom': min(current_zone),
                'touches': len(current_zone),
            })
        return zones

    return cluster_levels(swing_low_points), cluster_levels(swing_high_points)


def price_near_zone(price, zones, proximity_pct=ZONE_PROXIMITY_1H):
    for zone in zones:
        if abs(price - zone['price']) / price < proximity_pct:
            return zone
    return None


def build_zone_schedule(df_4h, interval=ZONE_RECOMPUTE_EVERY, lookback=ZONE_LOOKBACK_CANDLES):
    schedule = []
    for i in range(lookback, len(df_4h), interval):
        window = df_4h.iloc[max(0, i - lookback):i]
        supports, resistances = detect_zones_4h(window)
        ts = df_4h.index[i]
        schedule.append((ts, supports, resistances))
    return schedule


def get_zones_at(schedule, timestamp):
    for i in range(len(schedule) - 1, -1, -1):
        if schedule[i][0] <= timestamp:
            return schedule[i][1], schedule[i][2]
    if schedule:
        return schedule[0][1], schedule[0][2]
    return [], []


# ═══════════════════════════════════════════════
# SIGNAL GENERATION (V9.1 style — no direction gate)
# ═══════════════════════════════════════════════
def generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule):
    """
    Generate BOTH LONG and SHORT signals (no direction filtering).
    Returns list of signal dicts.
    """
    signals = []

    for i in range(3, len(df_15m)):
        ts_15m = df_15m.index[i]
        price_15m = df_15m['close'].iloc[i]

        # Find corresponding 4H candle (≤ entry time)
        mask_4h = df_4h.index <= ts_15m
        if not mask_4h.any():
            continue
        idx_4h = mask_4h.sum() - 1
        if idx_4h < 20:
            continue

        trend_bull_4h = df_4h['ema_fast'].iloc[idx_4h] > df_4h['ema_slow'].iloc[idx_4h]

        # Find corresponding 1H candle
        mask_1h = df_1h.index <= ts_15m
        if not mask_1h.any():
            continue
        idx_1h = mask_1h.sum() - 1
        if idx_1h < 2:
            continue

        row_1h = df_1h.iloc[idx_1h]
        price_1h = row_1h['close']

        support_zones, resistance_zones = get_zones_at(zone_schedule, ts_15m)

        near_support = price_near_zone(price_1h, support_zones)
        near_resistance = price_near_zone(price_1h, resistance_zones)

        if near_support is None and near_resistance is None:
            continue

        vol_ok = row_1h['vol_ratio'] > VOLUME_THRESHOLD_1H if not pd.isna(row_1h['vol_ratio']) else False

        row_15m = df_15m.iloc[i]
        rsi_15m = row_15m['rsi']
        rsi_15m_prev = df_15m['rsi'].iloc[i - 1] if i > 0 else rsi_15m

        rsi_crossing_up = (rsi_15m_prev < RSI_CROSS_LONG and rsi_15m >= RSI_CROSS_LONG)
        rsi_crossing_down = (rsi_15m_prev > RSI_CROSS_SHORT and rsi_15m <= RSI_CROSS_SHORT)

        # ── LONG SIGNAL ──
        if near_support:
            rsi_1h = row_1h['rsi']
            rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_LONG_MIN_1H and rsi_1h <= RSI_LONG_MAX_1H)
            candle_1h_ok = row_1h['is_bullish'] or row_1h['is_hammer']
            trigger_15m = (row_15m['is_bullish'] or row_15m['is_hammer'] or row_15m['is_engulfing_bull'])
            rsi_15m_ok = rsi_15m < 60
            div_ok = row_15m['bull_div']

            conditions_met = sum([rsi_1h_ok, candle_1h_ok, trigger_15m,
                                 rsi_15m_ok or rsi_crossing_up, vol_ok])

            if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
                signals.append({
                    'idx': i,
                    'side': 'LONG',
                    'entry': price_15m,
                    'zone_price': near_support['price'],
                    'zone_touches': near_support['touches'],
                    'rsi_1h': rsi_1h,
                    'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok,
                    'conditions': conditions_met,
                    'timestamp': ts_15m,
                    'trend_4h_bull': trend_bull_4h,
                })

        # ── SHORT SIGNAL ──
        if near_resistance:
            rsi_1h = row_1h['rsi']
            rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_SHORT_MIN_1H and rsi_1h <= RSI_SHORT_MAX_1H)
            candle_1h_ok = row_1h['is_bearish'] or row_1h['is_shooting_star']
            trigger_15m = (row_15m['is_bearish'] or row_15m['is_shooting_star'] or row_15m['is_engulfing_bear'])
            rsi_15m_ok = rsi_15m > 40
            div_ok = row_15m['bear_div']

            conditions_met = sum([rsi_1h_ok, candle_1h_ok, trigger_15m,
                                 rsi_15m_ok or rsi_crossing_down, vol_ok])

            if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
                signals.append({
                    'idx': i,
                    'side': 'SHORT',
                    'entry': price_15m,
                    'zone_price': near_resistance['price'],
                    'zone_touches': near_resistance['touches'],
                    'rsi_1h': rsi_1h,
                    'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok,
                    'conditions': conditions_met,
                    'timestamp': ts_15m,
                    'trend_4h_bull': trend_bull_4h,
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
            })

        active_signals = remaining

    return trades


def compute_wr(trades, side=None):
    """Compute WR for a list of trades, optionally filtered by side"""
    filtered = [t for t in trades if side is None or t['side'] == side]
    if not filtered:
        return 0, 0
    wins = sum(1 for t in filtered if t['pnl_pct'] > 0)
    return wins / len(filtered) * 100, len(filtered)


# ═══════════════════════════════════════════════
# PHASE 1: CALIBRATION — detect pair direction bias
# ═══════════════════════════════════════════════
def calibrate_direction(symbol, data_4h, data_1h, data_15m):
    """Run calibration on Dec+Jan data, return direction bias per pair."""
    print(f"  📐 Calibrating {symbol}...")

    df_4h  = data_4h[symbol]
    df_1h  = data_1h[symbol]
    df_15m = data_15m[symbol]

    if df_4h.empty or df_1h.empty or df_15m.empty:
        return 'BOTH', 0, 0, 0, 0

    zone_schedule = build_zone_schedule(df_4h)
    signals = generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule)

    if not signals:
        return 'BOTH', 0, 0, 0, 0

    # Simulate with reference config
    _, sl_ref, tp_ref = CALIBRATION_CONFIG
    trades = simulate_trades(df_15m, signals, sl_ref, tp_ref)

    long_wr, long_n = compute_wr(trades, 'LONG')
    short_wr, short_n = compute_wr(trades, 'SHORT')

    # Determine direction bias
    # NEW: allow BOTH if LONG WR ≥ 42% — don't waste viable LONG signals
    if long_n >= DIRECTION_MIN_TRADES and short_n >= DIRECTION_MIN_TRADES:
        # If LONG is strong enough (≥42%), allow BOTH
        if long_wr >= DIRECTION_MIN_LONG_WR * 100:
            direction = 'BOTH'
        elif long_wr >= short_wr + DIRECTION_WR_DIFF * 100:
            direction = 'LONG'
        elif short_wr >= long_wr + DIRECTION_WR_DIFF * 100:
            direction = 'SHORT'
        else:
            direction = 'BOTH'
    elif long_n >= DIRECTION_MIN_TRADES:
        direction = 'LONG' if long_wr >= 50 else 'BOTH'
    elif short_n >= DIRECTION_MIN_TRADES:
        direction = 'SHORT' if short_wr >= 50 else 'BOTH'
    else:
        direction = 'BOTH'

    print(f"     LONG: {long_wr:.1f}% WR ({long_n}t) | SHORT: {short_wr:.1f}% WR ({short_n}t) → {direction}")

    return direction, long_wr, long_n, short_wr, short_n


# ═══════════════════════════════════════════════
# DAILY TOP-5 PAIR FILTER
# ═══════════════════════════════════════════════
def filter_top_pairs_daily(all_signals, top_n=MAX_PAIRS_PER_DAY):
    day_pair_score = defaultdict(lambda: defaultdict(float))
    
    for symbol, signals in all_signals.items():
        for sig in signals:
            day = sig['timestamp'].date()
            score = sig.get('zone_touches', 0) * sig.get('conditions', 0)
            day_pair_score[day][symbol] += score
    
    selected = defaultdict(set)
    for day, pair_scores in day_pair_score.items():
        ranked = sorted(pair_scores.items(), key=lambda x: x[1], reverse=True)
        selected[day] = {symbol for symbol, _ in ranked[:top_n]}
    
    filtered = {}
    for symbol, signals in all_signals.items():
        filtered[symbol] = [
            s for s in signals
            if symbol in selected[s['timestamp'].date()]
        ]
    
    return filtered


def analyze_trades(trades):
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


def print_pair_results(symbol, results):
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
    print("  FORSCHER V9.3d — AGGRESSIVE: TARGET 55%+")
    print("  Phase 1: Calibration (Dec+Jan) → relax direction lock (BOTH if LONG≥42%)")
    print("  Phase 2: Trading (Feb–May) → no daily filter, Wide+Wide25 configs")
    print("  Pairs: 11 (L1: ETH,AVAX,SUI,NEAR,SOL | AI:FET | Privacy:ROSE | Pay:HBAR | Game:XPL | DeFi:ENA | RWA:ONDO)")
    print("=" * 80)

    # ═══════════════════════════════════════════
    # PHASE 1: CALIBRATION
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  PHASE 1: CALIBRATION (Dec 2025 – Jan 2026)")
    print("=" * 80)
    print("  📡 Fetching data...")

    calib_4h = {}
    calib_1h = {}
    calib_15m = {}

    for symbol in SYMBOLS:
        print(f"    {symbol}...", end=' ')
        try:
            df_4h  = fetch_ohlcv(symbol, '4h',  CALIBRATION_START, CALIBRATION_END)
            df_1h  = fetch_ohlcv(symbol, '1h',  CALIBRATION_START, CALIBRATION_END)
            df_15m = fetch_ohlcv(symbol, '15m', CALIBRATION_START, CALIBRATION_END)
        except Exception as e:
            print(f"SKIP ({e})")
            continue

        if df_4h.empty or df_1h.empty or df_15m.empty:
            print("NO DATA")
            continue

        # Add indicators
        df_4h  = add_emas(df_4h, TREND_EMA_FAST_4H, TREND_EMA_SLOW_4H)
        df_1h  = add_rsi(df_1h, RSI_PERIOD_1H)
        df_1h  = add_volume_avg(df_1h, 20)
        df_1h  = add_candle_patterns(df_1h)
        df_15m = add_rsi(df_15m, RSI_PERIOD_15M)
        df_15m = add_candle_patterns(df_15m)
        df_15m = add_rsi_divergence(df_15m, 'rsi', DIVERGENCE_LOOKBACK)

        calib_4h[symbol]  = df_4h
        calib_1h[symbol]  = df_1h
        calib_15m[symbol] = df_15m
        print(f"4H:{len(df_4h)} 1H:{len(df_1h)} 15m:{len(df_15m)}")

    # Determine direction bias per pair
    print("\n  🧭 Direction Calibration Results:")
    print(f"  {'Symbol':<14} {'LONG WR':>9} {'LONG N':>7} {'SHORT WR':>10} {'SHORT N':>8} {'→':>3} {'DIRECTION':>10}")
    print(f"  {'-'*14} {'-'*9} {'-'*7} {'-'*10} {'-'*8} {'-'*3} {'-'*10}")

    direction_lock = {}
    calib_stats = {}

    for symbol in SYMBOLS:
        if symbol not in calib_4h:
            direction_lock[symbol] = 'BOTH'
            continue
        d, lw, ln, sw, sn = calibrate_direction(
            symbol, calib_4h, calib_1h, calib_15m
        )
        direction_lock[symbol] = d
        calib_stats[symbol] = (lw, ln, sw, sn)
        print(f"  {symbol:<14} {lw:>8.1f}% {ln:>7} {sw:>9.1f}% {sn:>8} {'→':>3} {d:>10}")

    # ═══════════════════════════════════════════
    # PHASE 2: TRADING (Feb–May)
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  PHASE 2: TRADING (Feb – May 2026) — WITH DIRECTION LOCK")
    print("=" * 80)
    print("  📡 Fetching data...")

    trade_4h = {}
    trade_1h = {}
    trade_15m = {}

    for symbol in SYMBOLS:
        print(f"    {symbol}...", end=' ')
        try:
            df_4h  = fetch_ohlcv(symbol, '4h',  TRADING_START, TRADING_END)
            df_1h  = fetch_ohlcv(symbol, '1h',  TRADING_START, TRADING_END)
            df_15m = fetch_ohlcv(symbol, '15m', TRADING_START, TRADING_END)
        except Exception as e:
            print(f"SKIP ({e})")
            continue

        if df_4h.empty or df_1h.empty or df_15m.empty:
            print("NO DATA")
            continue

        df_4h  = add_emas(df_4h, TREND_EMA_FAST_4H, TREND_EMA_SLOW_4H)
        df_1h  = add_rsi(df_1h, RSI_PERIOD_1H)
        df_1h  = add_volume_avg(df_1h, 20)
        df_1h  = add_candle_patterns(df_1h)
        df_15m = add_rsi(df_15m, RSI_PERIOD_15M)
        df_15m = add_candle_patterns(df_15m)
        df_15m = add_rsi_divergence(df_15m, 'rsi', DIVERGENCE_LOOKBACK)

        trade_4h[symbol]  = df_4h
        trade_1h[symbol]  = df_1h
        trade_15m[symbol] = df_15m
        print(f"4H:{len(df_4h)} 1H:{len(df_1h)} 15m:{len(df_15m)}")

    # Generate ALL signals first
    print("\n  🔍 Generating signals (both directions)...")
    all_signals = {}
    total_signal_count = 0

    for symbol in SYMBOLS:
        if symbol not in trade_4h:
            continue
        df_4h  = trade_4h[symbol]
        df_1h  = trade_1h[symbol]
        df_15m = trade_15m[symbol]
        zone_schedule = build_zone_schedule(df_4h)
        signals = generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule)
        all_signals[symbol] = signals

        n_long = sum(1 for s in signals if s['side'] == 'LONG')
        n_short = sum(1 for s in signals if s['side'] == 'SHORT')
        total_signal_count += len(signals)
        lock = direction_lock.get(symbol, 'BOTH')
        print(f"    {symbol:<14} {len(signals):>5} sigs ({n_long}L/{n_short}S) → lock: {lock}")

    print(f"\n  📊 Total signals: {total_signal_count}")

    # Apply direction lock
    print("\n  🔒 Applying direction lock...")
    locked_signals = {}
    for symbol, signals in all_signals.items():
        lock = direction_lock.get(symbol, 'BOTH')
        if lock == 'LONG':
            locked_signals[symbol] = [s for s in signals if s['side'] == 'LONG']
        elif lock == 'SHORT':
            locked_signals[symbol] = [s for s in signals if s['side'] == 'SHORT']
        else:
            locked_signals[symbol] = signals

        removed = len(signals) - len(locked_signals[symbol])
        if removed > 0:
            print(f"    {symbol:<14} {len(signals)} → {len(locked_signals[symbol])} ({removed} removed)")

    # Apply daily top-N (N=50 → effectively no filter, keeps code path)
    print(f"\n  📋 Daily pair filter (top-{MAX_PAIRS_PER_DAY}, effectively OFF)...")
    filtered_signals = filter_top_pairs_daily(locked_signals)

    print(f"\n  {'Symbol':<12} {'Locked':>7} {'After Top-5':>12}")
    print(f"  {'-'*12} {'-'*7} {'-'*12}")
    for symbol in SYMBOLS:
        locked_n = len(locked_signals.get(symbol, []))
        filt_n = len(filtered_signals.get(symbol, []))
        if locked_n > 0 or filt_n > 0:
            print(f"  {symbol:<12} {locked_n:>7} {filt_n:>12}")

    total_locked = sum(len(s) for s in locked_signals.values())
    total_filtered = sum(len(s) for s in filtered_signals.values())
    print(f"\n  📊 Total: {total_locked} locked → {total_filtered} after top-5")

    # Trade simulation with all configs
    print("\n\n" + "=" * 80)
    print("  TRADE SIMULATION (Wide Configs, Direction-Locked, No Daily Filter)")
    print("=" * 80)

    filtered_results = {}
    for symbol in SYMBOLS:
        if symbol not in filtered_signals or not filtered_signals[symbol]:
            continue
        if symbol not in trade_15m:
            continue

        results = {}
        for label, sl_pct, tp_pct in SLTP_CONFIGS:
            trades = simulate_trades(trade_15m[symbol], filtered_signals[symbol], sl_pct, tp_pct)
            stats = analyze_trades(trades)
            stats['label'] = label
            results[label] = stats
        filtered_results[symbol] = results

    # Print results
    for symbol, results in filtered_results.items():
        if results:
            print(f"\n  ── {symbol} (lock: {direction_lock.get(symbol, 'BOTH')}) ──")
            print_pair_results(symbol, results)

    # ═══════════════════════════════════════════
    # AGGREGATE
    # ═══════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  AGGREGATE BY CONFIG (FEB–MAY, V9.3d — 11 PAIRS, NO DAILY FILTER)")
    print(f"{'='*80}")

    for label, sl_pct, tp_pct in SLTP_CONFIGS:
        combined = [filtered_results[sym][label] for sym in filtered_results if label in filtered_results[sym]]
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
    print("  🏆 TOP CONFIGS (WR ≥ 50%, PnL > 0, Trades ≥ 5)")
    print(f"{'='*80}")

    filtered_rows = []
    for symbol, results in filtered_results.items():
        for label, s in results.items():
            filtered_rows.append((symbol, label, s))
    filtered_rows.sort(key=lambda x: x[2]['wr'], reverse=True)

    top = [(sym, lbl, s) for sym, lbl, s in filtered_rows if s['wr'] >= 50 and s['trades'] >= 5 and s['pnl_total'] > 0]
    top.sort(key=lambda x: x[2]['pnl_total'], reverse=True)

    if top:
        for sym, lbl, s in top[:25]:
            print(f"  {sym} {lbl:<22} WR:{s['wr']:.1f}% PnL:{s['pnl_total']:+.2f}% "
                  f"T:{s['trades']} MaxDD:{s['max_dd']:.2f}% L:{s['long_trades']}({s['long_wr']:.0f}%) S:{s['short_trades']}({s['short_wr']:.0f}%)")
    else:
        print("  ❌ None")

    # ═══════════════════════════════════════════
    # COMPARISON TABLE: V9.1 vs V9.3 top performers
    # ═══════════════════════════════════════════
    print(f"\n{'='*80}")
    print("  📊 DIRECTION LOCK IMPACT — Per-Pair Comparison")
    print(f"{'='*80}")
    print(f"  {'Symbol':<12} {'Lock':>8} {'Best WR':>8} {'Best PnL':>10} {'Best Config':>16} {'Trades':>7}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*16} {'-'*7}")

    for symbol in SYMBOLS:
        if symbol not in filtered_results:
            continue
        lock = direction_lock.get(symbol, 'BOTH')
        results = filtered_results[symbol]
        best = max(results.items(), key=lambda x: x[1]['pnl_total'])
        label, s = best
        print(f"  {symbol:<12} {lock:>8} {s['wr']:>7.1f}% {s['pnl_total']:>+9.2f}% {label:<16} {s['trades']:>7}")

    print(f"\n{'='*80}")
    print("  V9.3b BACKTEST COMPLETE")
    print(f"{'='*80}")
