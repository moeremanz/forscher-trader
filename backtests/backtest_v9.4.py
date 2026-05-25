#!/usr/bin/env python3
"""
Forscher V9.4 — ROLLING 30-DAY RECALIBRATION
============================================
V9.3 walk-forward calib gagal untuk NEAR/INJ/ONDO karena regime shift
— 2 bulan calib statis gak cukup adaptif.

V9.4: Rolling 60-day calibration window, direction lock diupdate
SETIAP 30 HARI. ETH & SOL disingkirkan — fokus 11 pair tersisa.

  - Dec+Jan (60d) → calibrate → lock Feb
  - Jan+Feb (60d) → calibrate → lock Mar
  - Feb+Mar (60d) → calibrate → lock Apr
  - Mar+Apr (60d) → calibrate → lock May

No data snooping. Each month's lock uses ONLY data BEFORE that month.
"""
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

# ═══════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════
SYMBOLS = [
    'NEAR/USDT', 'DOGE/USDT', 'ONDO/USDT', 'LINK/USDT',
    'AVAX/USDT', 'ARB/USDT', 'OP/USDT', 'INJ/USDT',
    'TIA/USDT', 'SUI/USDT', 'RUNE/USDT',
]

DATA_START = '2025-12-01T00:00:00Z'
DATA_END   = '2026-05-25T00:00:00Z'

# Trading months (each is a 30-day window)
# Calibration for month M uses the 60 days before M's start
TRADING_MONTHS = [
    ('Feb 2026', '2026-02-01T00:00:00Z', '2026-03-01T00:00:00Z'),
    ('Mar 2026', '2026-03-01T00:00:00Z', '2026-04-01T00:00:00Z'),
    ('Apr 2026', '2026-04-01T00:00:00Z', '2026-05-01T00:00:00Z'),
    ('May 2026', '2026-05-01T00:00:00Z', '2026-05-25T00:00:00Z'),
]

MAX_PAIRS_PER_DAY = 5

# Direction lock threshold
DIRECTION_WR_DIFF = 0.10       # 10% WR difference to lock
DIRECTION_MIN_TRADES = 5        # need at least this many trades to trust

# Reference config for direction calibration
CALIBRATION_CONFIG = ('Mid 1:1.5', 0.012, 0.018)

# SL/TP configs
SLTP_CONFIGS = [
    ('Tight 1:1.5',   0.008, 0.012),
    ('Tight 1:2',     0.008, 0.016),
    ('Mid 1:1.5',     0.012, 0.018),
    ('Mid 1:2',       0.012, 0.024),
    ('Wide 1:1.5',    0.015, 0.0225),
    ('Wide 1:2',      0.015, 0.030),
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
        # Bullish divergence: price lower low, RSI higher low
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
        # Bearish divergence: price higher high, RSI lower high
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
# SIGNAL GENERATION (V9.1 style)
# ═══════════════════════════════════════════════
def generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule):
    """Generate BOTH LONG and SHORT signals (no direction filtering)."""
    signals = []
    for i in range(3, len(df_15m)):
        ts_15m = df_15m.index[i]
        price_15m = df_15m['close'].iloc[i]

        # Find corresponding 4H candle
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
                    'idx': i, 'side': 'LONG', 'entry': price_15m,
                    'zone_price': near_support['price'],
                    'zone_touches': near_support['touches'],
                    'rsi_1h': rsi_1h, 'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok, 'conditions': conditions_met,
                    'timestamp': ts_15m, 'trend_4h_bull': trend_bull_4h,
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
                    'idx': i, 'side': 'SHORT', 'entry': price_15m,
                    'zone_price': near_resistance['price'],
                    'zone_touches': near_resistance['touches'],
                    'rsi_1h': rsi_1h, 'rsi_15m': rsi_15m,
                    'vol_ratio_1h': row_1h['vol_ratio'],
                    'divergence': div_ok, 'conditions': conditions_met,
                    'timestamp': ts_15m, 'trend_4h_bull': trend_bull_4h,
                })

    return signals


# ═══════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════
def simulate_trades(df_15m, signals, sl_pct, tp_pct):
    """Forward-simulate trades using 15m data."""
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
    filtered = [t for t in trades if side is None or t['side'] == side]
    if not filtered:
        return 0, 0
    wins = sum(1 for t in filtered if t['pnl_pct'] > 0)
    return wins / len(filtered) * 100, len(filtered)


def determine_direction_lock(trades, min_trades=DIRECTION_MIN_TRADES, wr_diff=DIRECTION_WR_DIFF):
    """Determine direction lock from calibration trades."""
    long_wr, long_n = compute_wr(trades, 'LONG')
    short_wr, short_n = compute_wr(trades, 'SHORT')

    if long_n >= min_trades and short_n >= min_trades:
        if long_wr >= short_wr + wr_diff * 100:
            return 'LONG', long_wr, long_n, short_wr, short_n
        elif short_wr >= long_wr + wr_diff * 100:
            return 'SHORT', long_wr, long_n, short_wr, short_n
        else:
            return 'BOTH', long_wr, long_n, short_wr, short_n
    elif long_n >= min_trades:
        return ('LONG' if long_wr >= 50 else 'BOTH'), long_wr, long_n, short_wr, short_n
    elif short_n >= min_trades:
        return ('SHORT' if short_wr >= 50 else 'BOTH'), long_wr, long_n, short_wr, short_n
    else:
        return 'BOTH', long_wr, long_n, short_wr, short_n


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
        filtered[symbol] = [s for s in signals if symbol in selected[s['timestamp'].date()]]
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
        if not tlist:
            return 0
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


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 80)
    print("  FORSCHER V9.4 — ROLLING 30-DAY RECALIBRATION")
    print("  Pairs: NEAR, DOGE, ONDO, LINK, AVAX, ARB, OP, INJ, TIA, SUI, RUNE")
    print("  ETH & SOL excluded")
    print("  Rolling 60d calibration → lock updated every 30 days")
    print("  Phase 1: Dec+Jan → lock Feb")
    print("  Phase 2: Jan+Feb → lock Mar")
    print("  Phase 3: Feb+Mar → lock Apr")
    print("  Phase 4: Mar+Apr → lock May")
    print("=" * 80)

    # ═══════════════════════════════════════════
    # FETCH ALL DATA (Dec 2025 – May 2026)
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  FETCHING ALL DATA (Dec 2025 – May 2026)")
    print("=" * 80)

    all_4h = {}
    all_1h = {}
    all_15m = {}

    for symbol in SYMBOLS:
        print(f"  {symbol}...", end=' ', flush=True)
        try:
            df_4h  = fetch_ohlcv(symbol, '4h',  DATA_START, DATA_END)
            df_1h  = fetch_ohlcv(symbol, '1h',  DATA_START, DATA_END)
            df_15m = fetch_ohlcv(symbol, '15m', DATA_START, DATA_END)
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

        all_4h[symbol]  = df_4h
        all_1h[symbol]  = df_1h
        all_15m[symbol] = df_15m
        print(f"4H:{len(df_4h)} 1H:{len(df_1h)} 15m:{len(df_15m)} ✓")

    # ═══════════════════════════════════════════
    # GENERATE ALL SIGNALS FIRST
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  GENERATING SIGNALS (both directions, full period)")
    print("=" * 80)

    all_signals_raw = {}
    for symbol in SYMBOLS:
        if symbol not in all_4h:
            continue
        df_4h  = all_4h[symbol]
        df_1h  = all_1h[symbol]
        df_15m = all_15m[symbol]
        zone_schedule = build_zone_schedule(df_4h)
        signals = generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule)
        all_signals_raw[symbol] = signals
        n_long = sum(1 for s in signals if s['side'] == 'LONG')
        n_short = sum(1 for s in signals if s['side'] == 'SHORT')
        print(f"  {symbol:<14} {len(signals):>5} signals ({n_long}L/{n_short}S)")

    # ═══════════════════════════════════════════
    # ROLLING CALIBRATION + TRADE PER MONTH
    # ═══════════════════════════════════════════
    # All trading results accumulated here
    all_monthly_results = defaultdict(lambda: defaultdict(list))  # {symbol: {config: [stats_per_month]}}
    rolling_calib_log = []  # list of calib snapshots
    final_direction_lock = {}  # last known lock per pair

    for month_idx, (month_label, month_start_str, month_end_str) in enumerate(TRADING_MONTHS):
        month_start = pd.to_datetime(month_start_str.replace('T', ' ').replace('Z', ''))
        month_end   = pd.to_datetime(month_end_str.replace('T', ' ').replace('Z', ''))

        # Calibration window: 60 days before this month's start
        calib_end = month_start
        calib_start = calib_end - timedelta(days=60)

        print(f"\n\n{'='*80}")
        print(f"  MONTH {month_idx+1}/4: {month_label}")
        print(f"  Calibration window: {calib_start.date()} → {calib_end.date()} (60 days)")
        print(f"  Trading window: {month_start.date()} → {month_end.date()}")
        print(f"{'='*80}")

        # ── Step 1: Recalibrate direction per pair ──
        print(f"\n  🧭 Direction Recalibration:")
        month_lock = {}
        calib_stats_month = {}

        for symbol in SYMBOLS:
            if symbol not in all_signals_raw:
                month_lock[symbol] = 'BOTH'
                continue

            # Get signals within calibration window
            calib_signals = [
                s for s in all_signals_raw[symbol]
                if calib_start <= s['timestamp'] < calib_end
            ]

            if len(calib_signals) < DIRECTION_MIN_TRADES:
                month_lock[symbol] = 'BOTH'
                print(f"    {symbol:<14} → BOTH (insufficient calib signals: {len(calib_signals)})")
                continue

            # Simulate trades on calibration signals (use FULL 15m, filter by entry_time)
            _, sl_ref, tp_ref = CALIBRATION_CONFIG
            df_15m_full = all_15m[symbol]
            all_calib_trades = simulate_trades(df_15m_full, calib_signals, sl_ref, tp_ref)
            calib_trades = [
                t for t in all_calib_trades
                if calib_start <= t['entry_time'] < calib_end
            ]

            direction, lw, ln, sw, sn = determine_direction_lock(calib_trades)
            month_lock[symbol] = direction
            calib_stats_month[symbol] = (lw, ln, sw, sn)

            rolling_calib_log.append({
                'month': month_label,
                'symbol': symbol,
                'long_wr': lw, 'long_n': ln,
                'short_wr': sw, 'short_n': sn,
                'direction': direction,
                'calib_trades': len(calib_trades),
                'calib_signals': len(calib_signals),
            })

            print(f"    {symbol:<14} L:{lw:.1f}%({ln}) S:{sw:.1f}%({sn}) → {direction}")

        final_direction_lock = month_lock  # track last lock

        # ── Step 2: Get trading signals for this month ──
        month_signals_raw = {}
        for symbol in SYMBOLS:
            if symbol not in all_signals_raw:
                continue
            month_sigs = [
                s for s in all_signals_raw[symbol]
                if month_start <= s['timestamp'] < month_end
            ]
            if month_sigs:
                month_signals_raw[symbol] = month_sigs

        # ── Step 3: Apply direction lock ──
        print(f"\n  🔒 Applying direction lock...")
        month_signals_locked = {}
        for symbol, signals in month_signals_raw.items():
            lock = month_lock.get(symbol, 'BOTH')
            if lock == 'LONG':
                month_signals_locked[symbol] = [s for s in signals if s['side'] == 'LONG']
            elif lock == 'SHORT':
                month_signals_locked[symbol] = [s for s in signals if s['side'] == 'SHORT']
            else:
                month_signals_locked[symbol] = signals

            removed = len(signals) - len(month_signals_locked[symbol])
            if removed > 0:
                print(f"    {symbol:<14} {len(signals)} → {len(month_signals_locked[symbol])} (removed {removed})")

        # ── Step 4: Daily top-5 filter ──
        if month_signals_locked:
            month_signals_filtered = filter_top_pairs_daily(month_signals_locked)
            total_sigs = sum(len(s) for s in month_signals_filtered.values())
            print(f"  📊 {month_label}: {total_sigs} signals after top-5 filter")
        else:
            month_signals_filtered = {}

        # ── Step 5: Simulate trades with all configs ──
        # IMPORTANT: Simulate on FULL 15m dataframe (signals have absolute idx),
        # then filter trades by entry_time to this month only.
        for symbol in SYMBOLS:
            if symbol not in month_signals_filtered or not month_signals_filtered[symbol]:
                continue
            if symbol not in all_15m:
                continue

            df_15m_full = all_15m[symbol]

            for label, sl_pct, tp_pct in SLTP_CONFIGS:
                all_trades = simulate_trades(df_15m_full, month_signals_filtered[symbol], sl_pct, tp_pct)
                # Filter: only trades entered THIS month
                month_trades = [
                    t for t in all_trades
                    if month_start <= t['entry_time'] < month_end
                ]
                stats = analyze_trades(month_trades)
                stats['label'] = label
                all_monthly_results[symbol][label].append(stats)

    # ═══════════════════════════════════════════
    # AGGREGATE RESULTS (sum across months)
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  AGGREGATE RESULTS (Feb–May, monthly direction-locked + top-5)")
    print(f"{'='*80}")

    # Aggregate per config across all pairs
    aggregate_by_config = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'pnl_total': 0,
        'long_trades': 0, 'short_trades': 0,
        'pairs': set()
    })

    # Print per-pair results
    for symbol in SYMBOLS:
        if symbol not in all_monthly_results or not all_monthly_results[symbol]:
            continue

        print(f"\n  ── {symbol} ──")
        print(f"  {'Config':<16} {'Trades':>6} {'WR':>7} {'PnL':>9} {'AvgW':>7} {'AvgL':>7} {'Exp':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>6}")
        print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*6}")

        for label, monthly_stats_list in all_monthly_results[symbol].items():
            # Merge stats across months
            combined_trades = []
            total_trades = 0
            total_wins = 0
            total_pnl = 0
            total_longs = 0
            total_shorts = 0

            for s in monthly_stats_list:
                total_trades += s['trades']
                total_wins += s['wins']
                total_pnl += s['pnl_total']
                total_longs += s['long_trades']
                total_shorts += s['short_trades']

            if total_trades == 0:
                continue

            wr = total_wins / total_trades * 100
            # MaxDD — conservatively, sum of max drawdowns (not ideal but close enough)
            max_dd = sum(s['max_dd'] for s in monthly_stats_list)

            print(f"  {label:<16} {total_trades:>6} {wr:>6.1f}% {total_pnl:>+8.2f}% "
                  f"{'—':>7} {'—':>7} {'—':>7} {max_dd:>6.2f}% "
                  f"{total_longs:>4} {'—':>6} {total_shorts:>4} {'—':>6}")

            aggregate_by_config[label]['trades'] += total_trades
            aggregate_by_config[label]['wins'] += total_wins
            aggregate_by_config[label]['pnl_total'] += total_pnl
            aggregate_by_config[label]['long_trades'] += total_longs
            aggregate_by_config[label]['short_trades'] += total_shorts
            if total_trades > 0:
                aggregate_by_config[label]['pairs'].add(symbol)

    # Print aggregate summary
    print(f"\n\n{'='*80}")
    print("  AGGREGATE BY CONFIG (ALL PAIRS, FEB–MAY)")
    print(f"{'='*80}")

    for label, _, _ in SLTP_CONFIGS:
        agg = aggregate_by_config[label]
        if agg['trades'] == 0:
            continue
        wr = agg['wins'] / agg['trades'] * 100
        print(f"  {label:<16} Trades:{agg['trades']:>5} | WR:{wr:>6.1f}% | "
              f"PnL:{agg['pnl_total']:>+8.2f}% | Pairs:{len(agg['pairs'])}/{len(SYMBOLS)} | "
              f"L:{agg['long_trades']} S:{agg['short_trades']}")

    # ═══════════════════════════════════════════
    # ROLLING CALIBRATION LOG
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  🔄 ROLLING DIRECTION LOCK EVOLUTION (per pair, per month)")
    print(f"{'='*80}")
    print(f"  {'Symbol':<12} {'Feb':>7} {'Mar':>7} {'Apr':>7} {'May':>7}  (Direction Lock)")
    print(f"  {'-'*12} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")

    pair_lock_evolution = defaultdict(dict)
    for entry in rolling_calib_log:
        pair_lock_evolution[entry['symbol']][entry['month']] = entry['direction']

    for symbol in SYMBOLS:
        locks = []
        for month_label, _, _ in TRADING_MONTHS:
            locks.append(pair_lock_evolution.get(symbol, {}).get(month_label, '—'))
        print(f"  {symbol:<12} {locks[0]:>7} {locks[1]:>7} {locks[2]:>7} {locks[3]:>7}")

    # ═══════════════════════════════════════════
    # TOP PERFORMERS (per pair, per config, sorted by WR)
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  🏆 BEST PER-PAIR CONFIG (WR ≥ 50%, aggregated over Feb–May)")
    print(f"{'='*80}")

    best_pairs = []
    for symbol in SYMBOLS:
        if symbol not in all_monthly_results:
            continue
        for label, monthly_stats_list in all_monthly_results[symbol].items():
            total_trades = sum(s['trades'] for s in monthly_stats_list)
            total_wins = sum(s['wins'] for s in monthly_stats_list)
            total_pnl = sum(s['pnl_total'] for s in monthly_stats_list)
            if total_trades >= 5:
                wr = total_wins / total_trades * 100
                best_pairs.append((symbol, label, wr, total_pnl, total_trades))

    best_pairs.sort(key=lambda x: x[2], reverse=True)

    for sym, lbl, wr, pnl, trades in best_pairs:
        if wr >= 40:
            marker = "🔥" if wr >= 55 else ("✅" if wr >= 50 else "")
            print(f"  {sym} {lbl:<22} WR:{wr:.1f}% PnL:{pnl:+.2f}% T:{trades} {marker}")

    # ═══════════════════════════════════════════
    # HEAD-TO-HEAD: V9.3 vs V9.4
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  📊 V9.3 vs V9.4 COMPARISON (excl. ETH/SOL)")
    print(f"{'='*80}")
    print(f"  V9.3: Static 2-month calib → same lock for Feb–May")
    print(f"  V9.4: Rolling 60d calib → lock updated monthly")
    print(f"  {'Metric':<30} {'V9.3':>12} {'V9.4':>12}")
    print(f"  {'-'*30} {'-'*12} {'-'*12}")

    # Best aggregate configs
    best_agg = max(
        [(label, agg['wins']/agg['trades']*100, agg['pnl_total'], agg['trades'])
         for label, agg in aggregate_by_config.items() if agg['trades'] > 0],
        key=lambda x: x[2]  # by PnL
    )
    print(f"  {'Best Aggregate PnL':<30} {best_agg[2]:>+11.2f}% (V9.4)")

    # Count pairs with WR ≥ 50%, ≥ 55%, ≥ 57%
    v94_pairs_50 = sum(1 for _, _, wr, _, _ in best_pairs if wr >= 50)
    v94_pairs_55 = sum(1 for _, _, wr, _, _ in best_pairs if wr >= 55)
    v94_pairs_57 = sum(1 for _, _, wr, _, _ in best_pairs if wr >= 57)

    print(f"  {'Pairs ≥50% WR':<30} {v94_pairs_50:>12} (V9.4)")
    print(f"  {'Pairs ≥55% WR':<30} {v94_pairs_55:>12} (V9.4)")
    print(f"  {'Pairs ≥57% WR':<30} {v94_pairs_57:>12} (V9.4)")

    total_v94_trades = sum(t for _, _, _, _, t in best_pairs)
    print(f"  {'Total Trades':<30} {total_v94_trades:>12} (V9.4)")

    print(f"\n{'='*80}")
    print("  V9.4 BACKTEST COMPLETE")
    print(f"{'='*80}")
