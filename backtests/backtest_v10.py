#!/usr/bin/env python3
"""
Forscher V10 — MULTI-SOURCE FUSION ENGINE
==========================================
V9.3 aggregate WR 47% — direction lock helped PnL but WR still below target.
V10 adds two new independent data sources:

  L1: SMC Structure (4H S/R zones, 3+ touches)       ← from V9
  L2: Multi-TF Direction (4H→1H→15m)                  ← from V9
  L3: On-Chain Proxy Fundamentaal Filter (HARD GATE)  ← NEW
  L4: EMA Crossover 50/200 (momentum confirmation)     ← NEW

L3 HARD RULE: If L3 contradicts L1+L2 direction → SKIP trade entirely.
  - L1+L2 signal LONG but L3 says OVERVALUED  → SKIP
  - L1+L2 signal SHORT but L3 says UNDERVALUED → SKIP

Pairs: NEAR, DOGE, ONDO, LINK, AVAX, ARB, OP, INJ, TIA, SUI, RUNE
Backtest: Dec 2025 – May 2026 (6 months)
Walk-forward: Dec+Jan calibrate → Feb–May trade
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
    'NEAR/USDT', 'DOGE/USDT', 'ONDO/USDT', 'LINK/USDT',
    'AVAX/USDT', 'ARB/USDT', 'OP/USDT', 'INJ/USDT',
    'TIA/USDT', 'SUI/USDT', 'RUNE/USDT',
]

# Approximate circulating supply (millions) for NVT proxy calc
# Source: CoinGecko, May 2026
CIRCULATING_SUPPLY_M = {
    'NEAR/USDT': 1250,
    'DOGE/USDT': 148000,
    'ONDO/USDT': 1400,
    'LINK/USDT': 630,
    'AVAX/USDT': 410,
    'ARB/USDT': 4700,
    'OP/USDT': 5200,
    'INJ/USDT': 110,
    'TIA/USDT': 470,
    'SUI/USDT': 3200,
    'RUNE/USDT': 340,
}

CALIBRATION_START = '2025-12-01T00:00:00Z'
CALIBRATION_END   = '2026-02-01T00:00:00Z'    # Dec+Jan = 2 months
TRADING_START     = '2026-02-01T00:00:00Z'
TRADING_END       = '2026-05-25T00:00:00Z'    # Feb–May

MAX_PAIRS_PER_DAY = 5

# Direction lock threshold
DIRECTION_WR_DIFF = 0.10
DIRECTION_MIN_TRADES = 5

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

# ── L1: 4H STRUCTURE ──
SWING_LOOKBACK_4H = 30
ZONE_TOUCH_MIN = 3
ZONE_BAND_PCT = 0.015
ZONE_RECOMPUTE_EVERY = 24
ZONE_LOOKBACK_CANDLES = 90

# ── L2: 1H CONFIRMATION ──
RSI_PERIOD_1H = 14
RSI_LONG_MIN_1H = 30
RSI_LONG_MAX_1H = 55
RSI_SHORT_MAX_1H = 70
RSI_SHORT_MIN_1H = 45
VOLUME_THRESHOLD_1H = 1.15
ZONE_PROXIMITY_1H = 0.008

# ── L2: 15m EXECUTION ──
RSI_PERIOD_15M = 7
RSI_CROSS_LONG = 35
RSI_CROSS_SHORT = 65
DIVERGENCE_LOOKBACK = 15

# ── L3: ON-CHAIN PROXY ──
MVRV_EMA_PERIOD = 200          # close / EMA(200)
MVRV_OVERVALUED_THRESHOLD = 1.30   # >1.3 = overvalued → SHORT bias
MVRV_UNDERVALUED_THRESHOLD = 0.80  # <0.8 = undervalued → LONG bias
NVT_VOLUME_DAYS = 24            # hours for 24h volume proxy (on 1H TF = 24 bars)
VOL_TREND_SHORT = 5             # days for short vol trend
VOL_TREND_LONG = 30             # days for long vol trend
VOL_SPIKE_MULT = 1.5
VOL_SPIKE_WINDOW = 7            # days

# ── L4: EMA CROSSOVER ──
EMA_FAST_4H = 50
EMA_SLOW_4H = 200
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
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
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
        price_lows, rsi_at_lows = [], []
        for j in range(1, len(window) - 1):
            if window['low'].iloc[j] < window['low'].iloc[j-1] and window['low'].iloc[j] < window['low'].iloc[j+1]:
                price_lows.append((j, window['low'].iloc[j]))
                rsi_at_lows.append((j, window[rsi_col].iloc[j]))
        if len(price_lows) >= 2:
            p1, p2 = price_lows[-2], price_lows[-1]
            r1, r2 = rsi_at_lows[-2], rsi_at_lows[-1]
            if p2[1] < p1[1] and r2[1] > r1[1]:
                df.iloc[i, df.columns.get_loc('bull_div')] = True

        price_highs, rsi_at_highs = [], []
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
# L3: ON-CHAIN PROXY METRICS
# ═══════════════════════════════════════════════
def add_onchain_proxies(df, symbol, supply_m):
    """Compute on-chain proxy metrics from OHLCV data. Works on any timeframe."""
    if len(df) < MVRV_EMA_PERIOD:
        return df

    # 1. MVRV Proxy: price / EMA(200)
    df['ema_200'] = df['close'].ewm(span=MVRV_EMA_PERIOD).mean()
    df['mvrv_proxy'] = df['close'] / df['ema_200']

    # 2. NVT Proxy: market cap / volume
    # market_cap = close * circulating_supply (in USD)
    # nvt = market_cap / (volume * close)  → simplifies to supply / volume
    supply = supply_m * 1_000_000
    df['nvt_proxy'] = (df['close'] * supply) / df['volume'].replace(0, np.nan)

    # 3. Volume Trend: vol_5d / vol_30d
    # Convert to daily bars and compute
    # We'll use the 4H data's rolling window approximation
    # 5 days = 30 4H candles, 30 days = 180 4H candles
    df['vol_ma_5d'] = df['volume'].rolling(30).mean()
    df['vol_ma_30d'] = df['volume'].rolling(180).mean()
    df['vol_trend'] = df['vol_ma_5d'] / df['vol_ma_30d'].replace(0, np.nan)

    # 4. Volume Spike: count bars where vol > 1.5x avg in last 7 days
    # 7 days = 42 4H candles
    df['vol_spike_count'] = 0
    if len(df) > 42:
        for i in range(42, len(df)):
            vol_avg_7d = df['volume'].iloc[i-42:i].mean()
            spike_count = (df['volume'].iloc[i-42:i] > vol_avg_7d * VOL_SPIKE_MULT).sum()
            df.iloc[i, df.columns.get_loc('vol_spike_count')] = spike_count

    return df


def evaluate_l3(df, idx, signal_side):
    """
    L3 HARD GATE: evaluate on-chain proxy at time of entry.
    Returns: 'PASS' (confirm signal), 'SKIP' (contradict → hard skip), 'NEUTRAL' (no signal)
    """
    if idx < MVRV_EMA_PERIOD + 180:
        return 'NEUTRAL'  # Not enough warmup

    row = df.iloc[idx]

    mvrv = row.get('mvrv_proxy', np.nan)
    nvt = row.get('nvt_proxy', np.nan)
    vol_trend = row.get('vol_trend', np.nan)
    spike_count = row.get('vol_spike_count', 0)

    # Build directional signal from L3
    l3_long_signals = 0
    l3_short_signals = 0

    # MVRV signal
    if not pd.isna(mvrv):
        if mvrv < MVRV_UNDERVALUED_THRESHOLD:
            l3_long_signals += 1
        elif mvrv > MVRV_OVERVALUED_THRESHOLD:
            l3_short_signals += 1

    # NVT signal: high NVT = overvalued market cap relative to volume
    if not pd.isna(nvt):
        nvt_median = df['nvt_proxy'].iloc[max(0, idx-180):idx].median()
        if nvt < nvt_median * 0.7:
            l3_long_signals += 1  # Low NVT = undervalued
        elif nvt > nvt_median * 1.3:
            l3_short_signals += 1

    # Volume trend: rising volume supports bullish, falling supports bearish
    if not pd.isna(vol_trend):
        if vol_trend > 1.2:
            l3_long_signals += 1
        elif vol_trend < 0.8:
            l3_short_signals += 1

    # Volume spike count: many spikes = abnormal activity → neutral/risk
    # We don't use this for directional signal, it's informational

    # Determine L3 bias
    if l3_long_signals > l3_short_signals:
        l3_bias = 'LONG'
    elif l3_short_signals > l3_long_signals:
        l3_bias = 'SHORT'
    else:
        l3_bias = 'NEUTRAL'

    # HARD GATE: contradict → SKIP
    if l3_bias == 'NEUTRAL':
        return 'PASS'  # Neutral = no contradiction, let it through

    if signal_side != l3_bias:
        return 'SKIP'  # CONTRADICTION → hard skip

    return 'PASS'  # Confirmed


# ═══════════════════════════════════════════════
# L4: EMA CROSSOVER (50/200) on 4H
# ═══════════════════════════════════════════════
def add_ema_crossover(df):
    """Add EMA 50/200 for L4 momentum filter."""
    df['ema_50'] = df['close'].ewm(span=EMA_FAST_4H).mean()
    df['ema_200'] = df['close'].ewm(span=EMA_SLOW_4H).mean()
    # Golden cross / Death cross
    df['ema50_above_200'] = df['ema_50'] > df['ema_200']
    return df


def evaluate_l4(df_4h, idx_4h, signal_side):
    """
    L4: EMA 50/200 momentum confirmation.
    Returns: 'PASS' (momentum aligned) or 'WEAK' (momentum contradicts)
    """
    if idx_4h < EMA_SLOW_4H:
        return 'WEAK'

    ema50_above_200 = df_4h['ema50_above_200'].iloc[idx_4h]

    if signal_side == 'LONG' and ema50_above_200:
        return 'PASS'
    elif signal_side == 'SHORT' and not ema50_above_200:
        return 'PASS'
    else:
        return 'WEAK'


# ═══════════════════════════════════════════════
# 4H ZONE DETECTION (L1)
# ═══════════════════════════════════════════════
def detect_zones_4h(df_4h, zone_band_pct=ZONE_BAND_PCT, min_touches=ZONE_TOUCH_MIN):
    swing_high_points = []
    swing_low_points = []

    for i in range(1, len(df_4h) - 1):
        h = df_4h['high'].iloc[i]
        l = df_4h['low'].iloc[i]
        if h > df_4h['high'].iloc[i-1] and h > df_4h['high'].iloc[i+1]:
            swing_high_points.append(h)
        if l < df_4h['low'].iloc[i-1] and l < df_4h['low'].iloc[i+1]:
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
# SIGNAL GENERATION (L1+L2 from V9 + L3 gate + L4 filter)
# ═══════════════════════════════════════════════
def generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule, supply_m):
    """Generate signals with L1+L2+L3+L4 fusion."""
    signals = []
    l3_skips = 0
    l4_weak = 0

    for i in range(3, len(df_15m)):
        ts_15m = df_15m.index[i]
        price_15m = df_15m['close'].iloc[i]

        # Find 4H candle
        mask_4h = df_4h.index <= ts_15m
        if not mask_4h.any():
            continue
        idx_4h = mask_4h.sum() - 1
        if idx_4h < EMA_SLOW_4H + 180:
            continue

        trend_bull_4h = df_4h['ema_fast'].iloc[idx_4h] > df_4h['ema_slow'].iloc[idx_4h]

        # Find 1H candle
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
                # L3 HARD GATE
                l3_result = evaluate_l3(df_4h, idx_4h, 'LONG')
                if l3_result == 'SKIP':
                    l3_skips += 1
                    continue

                # L4 EMA momentum filter
                l4_result = evaluate_l4(df_4h, idx_4h, 'LONG')
                if l4_result == 'WEAK':
                    l4_weak += 1
                    # L4 is NOT a hard gate — it reduces conviction but still trades

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
                    'l3_mvrv': df_4h['mvrv_proxy'].iloc[idx_4h],
                    'l3_vol_trend': df_4h['vol_trend'].iloc[idx_4h],
                    'l4_ema_50_200': df_4h['ema50_above_200'].iloc[idx_4h],
                    'l4_result': l4_result,
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
                # L3 HARD GATE
                l3_result = evaluate_l3(df_4h, idx_4h, 'SHORT')
                if l3_result == 'SKIP':
                    l3_skips += 1
                    continue

                # L4 EMA momentum filter
                l4_result = evaluate_l4(df_4h, idx_4h, 'SHORT')
                if l4_result == 'WEAK':
                    l4_weak += 1

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
                    'l3_mvrv': df_4h['mvrv_proxy'].iloc[idx_4h],
                    'l3_vol_trend': df_4h['vol_trend'].iloc[idx_4h],
                    'l4_ema_50_200': df_4h['ema50_above_200'].iloc[idx_4h],
                    'l4_result': l4_result,
                })

    return signals, l3_skips, l4_weak


# ═══════════════════════════════════════════════
# TRADE SIMULATION
# ═══════════════════════════════════════════════
def simulate_trades(df_15m, signals, sl_pct, tp_pct):
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
                'l4_result': sig.get('l4_result', 'UNKNOWN'),
            })

        active_signals = remaining

    return trades


def compute_wr(trades, side=None):
    filtered = [t for t in trades if side is None or t['side'] == side]
    if not filtered:
        return 0, 0
    wins = sum(1 for t in filtered if t['pnl_pct'] > 0)
    return wins / len(filtered) * 100, len(filtered)


# ═══════════════════════════════════════════════
# PHASE 1: CALIBRATION
# ═══════════════════════════════════════════════
def calibrate_direction(symbol, data_4h, data_1h, data_15m, supply_m):
    print(f"  📐 Calibrating {symbol}...")
    df_4h = data_4h[symbol]
    df_1h = data_1h[symbol]
    df_15m = data_15m[symbol]

    if df_4h.empty or df_1h.empty or df_15m.empty:
        return 'BOTH', 0, 0, 0, 0

    zone_schedule = build_zone_schedule(df_4h)
    signals, l3s, l4w = generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule, supply_m)

    if not signals:
        return 'BOTH', 0, 0, 0, 0

    _, sl_ref, tp_ref = CALIBRATION_CONFIG
    trades = simulate_trades(df_15m, signals, sl_ref, tp_ref)

    long_wr, long_n = compute_wr(trades, 'LONG')
    short_wr, short_n = compute_wr(trades, 'SHORT')

    if long_n >= DIRECTION_MIN_TRADES and short_n >= DIRECTION_MIN_TRADES:
        if long_wr >= short_wr + DIRECTION_WR_DIFF * 100:
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
            'l4_pass_trades': 0, 'l4_pass_wr': 0,
        }

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    longs = [t for t in trades if t['side'] == 'LONG']
    shorts = [t for t in trades if t['side'] == 'SHORT']
    l4_pass = [t for t in trades if t.get('l4_result') == 'PASS']

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
        'l4_pass_trades': len(l4_pass),
        'l4_pass_wr': _wr(l4_pass),
    }


def print_pair_results(symbol, results):
    if not results:
        return
    print(f"\n  {'Config':<16} {'Trades':>6} {'WR':>7} {'PnL':>9} {'AvgW':>7} {'AvgL':>7} {'Exp':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>6} {'L4':>4} {'L4WR':>6}")
    print(f"  {'-'*16} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*6} {'-'*4} {'-'*6}")
    for label, s in results.items():
        print(f"  {label:<16} {s['trades']:>6} {s['wr']:>6.1f}% {s['pnl_total']:>+8.2f}% "
              f"{s['avg_win']:>6.2f}% {s['avg_loss']:>6.2f}% {s['expectancy']:>6.2f}% "
              f"{s['max_dd']:>6.2f}% {s['long_trades']:>4} {s['long_wr']:>5.1f}% "
              f"{s['short_trades']:>4} {s['short_wr']:>5.1f}% "
              f"{s['l4_pass_trades']:>4} {s['l4_pass_wr']:>5.1f}%")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 90)
    print("  FORSCHER V10 — MULTI-SOURCE FUSION ENGINE")
    print("  L1: SMC Structure | L2: Multi-TF | L3: On-Chain Proxy (HARD GATE)")
    print("  L4: EMA 50/200 | Walk-forward: Dec+Jan calib → Feb–May trade")
    print("  Pairs:", len(SYMBOLS), "| Target WR: ≥57% | L3 contradict = SKIP")
    print("=" * 90)

    # ═══════════════════════════════════════════
    # PHASE 1: CALIBRATION
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 90)
    print("  PHASE 1: CALIBRATION (Dec 2025 – Jan 2026)")
    print("=" * 90)
    print("  📡 Fetching data...")

    calib_4h = {}
    calib_1h = {}
    calib_15m = {}

    for symbol in SYMBOLS:
        supply_m = CIRCULATING_SUPPLY_M.get(symbol, 1000)
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
        df_4h  = add_ema_crossover(df_4h)
        df_4h  = add_onchain_proxies(df_4h, symbol, supply_m)
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

    # Direction calibration
    print("\n  🧭 Direction Calibration Results:")
    print(f"  {'Symbol':<14} {'LONG WR':>9} {'LONG N':>7} {'SHORT WR':>10} {'SHORT N':>8} {'→':>3} {'DIRECTION':>10}")
    print(f"  {'-'*14} {'-'*9} {'-'*7} {'-'*10} {'-'*8} {'-'*3} {'-'*10}")

    direction_lock = {}
    calib_stats = {}

    for symbol in SYMBOLS:
        if symbol not in calib_4h:
            direction_lock[symbol] = 'BOTH'
            continue
        supply_m = CIRCULATING_SUPPLY_M.get(symbol, 1000)
        d, lw, ln, sw, sn = calibrate_direction(
            symbol, calib_4h, calib_1h, calib_15m, supply_m
        )
        direction_lock[symbol] = d
        calib_stats[symbol] = (lw, ln, sw, sn)
        print(f"  {symbol:<14} {lw:>8.1f}% {ln:>7} {sw:>9.1f}% {sn:>8} {'→':>3} {d:>10}")

    # ═══════════════════════════════════════════
    # PHASE 2: TRADING
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 90)
    print("  PHASE 2: TRADING (Feb – May 2026) — DIRECTION LOCK + L3 GATE + L4 FILTER")
    print("=" * 90)
    print("  📡 Fetching data...")

    trade_4h = {}
    trade_1h = {}
    trade_15m = {}

    for symbol in SYMBOLS:
        supply_m = CIRCULATING_SUPPLY_M.get(symbol, 1000)
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
        df_4h  = add_ema_crossover(df_4h)
        df_4h  = add_onchain_proxies(df_4h, symbol, supply_m)
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

    # Generate signals
    print("\n  🔍 Generating signals (full L1+L2+L3+L4)...")
    all_signals = {}
    total_signal_count = 0
    total_l3_skips = 0

    for symbol in SYMBOLS:
        if symbol not in trade_4h:
            continue
        supply_m = CIRCULATING_SUPPLY_M.get(symbol, 1000)
        df_4h  = trade_4h[symbol]
        df_1h  = trade_1h[symbol]
        df_15m = trade_15m[symbol]
        zone_schedule = build_zone_schedule(df_4h)
        signals, l3_skips, l4_weak = generate_signals(symbol, df_4h, df_1h, df_15m, zone_schedule, supply_m)
        all_signals[symbol] = signals
        total_l3_skips += l3_skips

        n_long = sum(1 for s in signals if s['side'] == 'LONG')
        n_short = sum(1 for s in signals if s['side'] == 'SHORT')
        total_signal_count += len(signals)
        lock = direction_lock.get(symbol, 'BOTH')
        print(f"    {symbol:<14} {len(signals):>5} sigs ({n_long}L/{n_short}S) L3skip:{l3_skips} L4weak:{l4_weak} → lock: {lock}")

    print(f"\n  📊 Total signals: {total_signal_count} | L3 hard skips: {total_l3_skips}")

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

    # Daily top-5
    print(f"\n  📋 Applying daily top-{MAX_PAIRS_PER_DAY} pair filter...")
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

    # Trade simulation
    print("\n\n" + "=" * 90)
    print("  TRADE SIMULATION (All Configs, Direction-Locked + Top-5 + L3 Gate + L4)")
    print("=" * 90)

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

    for symbol, results in filtered_results.items():
        if results:
            print(f"\n  ── {symbol} (lock: {direction_lock.get(symbol, 'BOTH')}) ──")
            print_pair_results(symbol, results)

    # ═══════════════════════════════════════════
    # AGGREGATE
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("  AGGREGATE BY CONFIG (FEB–MAY, V10 FULL FUSION)")
    print(f"{'='*90}")

    for label, sl_pct, tp_pct in SLTP_CONFIGS:
        combined = [filtered_results[sym][label] for sym in filtered_results if label in filtered_results[sym]]
        if not combined:
            continue

        total_trades = sum(s['trades'] for s in combined)
        total_wins = sum(s['wins'] for s in combined)
        wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(s['pnl_total'] for s in combined)
        pairs = sum(1 for s in combined if s['trades'] > 0)

        print(f"  {label:<16} Trades:{total_trades:>5} | WR:{wr:>6.1f}% | PnL:{total_pnl:>+8.2f}% | Pairs:{pairs:>2}/{len(SYMBOLS)}")

    # ═══════════════════════════════════════════
    # TOP CONFIGS
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("  🏆 TOP CONFIGS (WR ≥ 50%, PnL > 0, Trades ≥ 5)")
    print(f"{'='*90}")

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
                  f"T:{s['trades']} MaxDD:{s['max_dd']:.2f}% L3OK:{s['l4_pass_trades']}({s['l4_pass_wr']:.0f}%)")
    else:
        print("  ❌ None")

    # ═══════════════════════════════════════════
    # COMPARISON: DIRECTION LOCK IMPACT
    # ═══════════════════════════════════════════
    print(f"\n{'='*90}")
    print("  📊 V10 PER-PAIR SUMMARY")
    print(f"{'='*90}")
    print(f"  {'Symbol':<12} {'Lock':>8} {'Best WR':>8} {'Best PnL':>10} {'Best Config':<16} {'Trades':>7} {'L4Pass':>7}")
    print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*10} {'-'*16} {'-'*7} {'-'*7}")

    for symbol in SYMBOLS:
        if symbol not in filtered_results:
            continue
        lock = direction_lock.get(symbol, 'BOTH')
        results = filtered_results[symbol]
        best = max(results.items(), key=lambda x: x[1]['pnl_total'])
        label, s = best
        print(f"  {symbol:<12} {lock:>8} {s['wr']:>7.1f}% {s['pnl_total']:>+9.2f}% {label:<16} {s['trades']:>7} {s['l4_pass_trades']:>7}")

    print(f"\n{'='*90}")
    print("  V10 BACKTEST COMPLETE")
    print(f"{'='*90}")
