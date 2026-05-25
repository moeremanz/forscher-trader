#!/usr/bin/env python3
"""
Forscher v5 Backtest — ICT-Inspired Pillars + Regime Filter
============================================================
Changes from v4:
  - P1 Structure: FVG + Order Block + Liquidity Sweep (real ICT concepts)
  - P2 Fibonacci: Retracement golden zone + Extension targets
  - P3 Volume: Surge + Divergence + Volume-weighted zone
  - P4 Trend: EMA ribbon + Pullback depth (reward pullback, penalize chase)
  - Elliott wave: SCRAPPED entirely
  - Gann: SCRAPPED entirely
  - Regime filter: ADX > 20 + EMA50/200 direction = HARD GATE
  - SL/TP: ATR-based (2x/4x default)
  - No TIME exits
"""
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime


# ═══════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════

def fetch_ohlcv(symbol='BTCUSDT', tf='4h', since='2025-12-01T00:00:00Z', limit=1500):
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    all_candles = []
    current_since = exchange.parse8601(since)
    remaining = limit
    while remaining > 0:
        batch = min(remaining, 1000)
        candles = exchange.fetch_ohlcv(symbol, tf, since=current_since, limit=batch)
        if not candles:
            break
        all_candles.extend(candles)
        current_since = candles[-1][0] + 1
        remaining -= len(candles)
        if len(candles) < batch:
            break
    df = pd.DataFrame(all_candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    return df


# ═══════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════

def compute_indicators(df):
    """Pre-compute all indicators."""
    high, low, close = df['high'], df['low'], df['close']

    # EMAs
    df['ema20'] = close.ewm(span=20, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    # ATR(14)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.ewm(span=14, adjust=False).mean()

    # ADX(14)
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0)
    atr_smooth = tr.ewm(span=14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr_smooth.replace(0, 1))
    minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr_smooth.replace(0, 1))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    df['adx'] = dx.ewm(span=14, adjust=False).mean()

    # Volume moving average
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['vol_ma50'] = df['volume'].rolling(50).mean()

    # Candle body and wick sizes
    df['body'] = (close - df['open']).abs()
    df['upper_wick'] = high - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low

    # Volume delta proxy: (close-open)/range * volume  (buy/sell pressure)
    candle_range = (high - low).replace(0, 1e-10)
    df['vol_pressure'] = ((close - df['open']) / candle_range) * df['volume']

    return df


# ═══════════════════════════════════════════════
# SWING DETECTION
# ═══════════════════════════════════════════════

def find_swings(df, window=3):
    """Detect swing highs and lows with strict alternation."""
    highs, lows = df['high'].values, df['low'].values
    raw_swings = []
    for i in range(window, len(df) - window):
        if all(highs[i] > highs[i - j - 1] for j in range(window)) and \
           all(highs[i] > highs[i + j + 1] for j in range(window)):
            raw_swings.append((i, 'high', highs[i]))
        if all(lows[i] < lows[i - j - 1] for j in range(window)) and \
           all(lows[i] < lows[i + j + 1] for j in range(window)):
            raw_swings.append((i, 'low', lows[i]))

    # Strict alternation
    swings = []
    last_type = None
    for s in raw_swings:
        if s[1] == last_type:
            if swings and last_type == 'high' and s[2] > swings[-1][2]:
                swings[-1] = s
            elif swings and last_type == 'low' and s[2] < swings[-1][2]:
                swings[-1] = s
        else:
            swings.append(s)
            last_type = s[1]
    return swings


# ═══════════════════════════════════════════════
# P1: STRUCTURE — FVG + Order Block + Liquidity Sweep (0-25)
# ═══════════════════════════════════════════════

def detect_fvg(df, i, direction):
    """
    Fair Value Gap: 3-candle pattern where wicks don't overlap.
    Bullish FVG: candle[i-1].low > candle[i-3].high (price gapped up, imbalance)
    Bearish FVG: candle[i-1].high < candle[i-3].low (price gapped down)
    Score based on whether price is inside/above/below the FVG zone.
    """
    if i < 4:
        return 0

    c1 = df.iloc[i - 3]  # 3 bars ago
    c2 = df.iloc[i - 2]
    c3 = df.iloc[i - 1]  # most recent
    curr = df.iloc[i]

    if direction == 'long':
        # Bullish FVG: gap up where c3.low > c1.high
        if c3['low'] > c1['high']:
            fvg_top = c3['low']
            fvg_bot = c1['high']
            # Price retracing INTO the FVG = best entry
            if fvg_bot <= curr['close'] <= fvg_top:
                return 10  # Price inside FVG — optimal
            elif curr['close'] > fvg_top and curr['close'] <= fvg_top + (fvg_top - fvg_bot):
                return 7   # Just above FVG — still valid
            elif curr['close'] < fvg_bot and curr['close'] >= fvg_bot - (fvg_top - fvg_bot):
                return 5   # Below FVG — waiting for fill
            else:
                return 3   # Far from FVG

    else:  # short
        # Bearish FVG: gap down where c3.high < c1.low
        if c3['high'] < c1['low']:
            fvg_top = c1['low']
            fvg_bot = c3['high']
            if fvg_bot <= curr['close'] <= fvg_top:
                return 10
            elif curr['close'] < fvg_bot and curr['close'] >= fvg_bot - (fvg_top - fvg_bot):
                return 7
            elif curr['close'] > fvg_top and curr['close'] <= fvg_top + (fvg_top - fvg_bot):
                return 5
            else:
                return 3

    return 1  # No FVG detected


def detect_order_block(df, i, swings, direction):
    """
    Order Block: The last opposite-color candle before a strong impulsive move.
    Long: find last bearish candle before the current rally — OB is that candle's high/low.
    Short: find last bullish candle before the current drop — OB is that candle's high/low.
    Score based on price proximity to the OB.
    """
    if i < 10 or len(swings) < 2:
        return 0

    curr = df.iloc[i]

    # Find the last two significant swings
    recent_swings = [s for s in swings if s[0] < i]
    if len(recent_swings) < 2:
        return 0

    s1 = recent_swings[-1]
    s2 = recent_swings[-2]

    if direction == 'long':
        # Need: s2 = low, s1 = high (impulsive leg up just happened)
        if not (s2[1] == 'low' and s1[1] == 'high'):
            return 1
        # Find the last bearish candle before the impulsive move up
        # Look from s2 index backwards for bearish candles
        ob_high = ob_low = None
        for j in range(s2[0], max(0, s2[0] - 10), -1):
            c = df.iloc[j]
            if c['close'] < c['open']:  # bearish candle
                ob_high = c['high']
                ob_low = c['low']
                break

        if ob_high is None:
            return 1

        # Score based on price near OB
        if ob_low <= curr['close'] <= ob_high:
            return 8  # Inside OB — best
        dist_pct = (curr['close'] - ob_high) / ob_high * 100
        if -1 <= dist_pct <= 2:
            return 6  # Near OB
        elif -2 <= dist_pct <= 4:
            return 4
        else:
            return 2

    else:  # short
        if not (s2[1] == 'high' and s1[1] == 'low'):
            return 1
        # Find last bullish candle before the impulsive drop
        ob_high = ob_low = None
        for j in range(s2[0], max(0, s2[0] - 10), -1):
            c = df.iloc[j]
            if c['close'] > c['open']:  # bullish candle
                ob_high = c['high']
                ob_low = c['low']
                break

        if ob_high is None:
            return 1

        if ob_low <= curr['close'] <= ob_high:
            return 8
        dist_pct = (ob_low - curr['close']) / ob_low * 100
        if -2 <= dist_pct <= 1:
            return 6
        elif -4 <= dist_pct <= 2:
            return 4
        else:
            return 2


def detect_liquidity_sweep(df, i, swings, direction):
    """
    Liquidity Sweep: Price breaks a swing level then immediately reverses.
    Bullish: low breaks below prior swing low, then close > that low (trap)
    Bearish: high breaks above prior swing high, then close < that high (trap)
    """
    if i < 3:
        return 0

    recent_swings = [s for s in swings if s[0] < i - 1]  # exclude current candle
    if not recent_swings:
        return 0

    curr = df.iloc[i]
    prev = df.iloc[i - 1]

    if direction == 'long':
        # Find recent swing low(s) that may have been swept
        for s in reversed(recent_swings):
            if s[1] == 'low':
                # Check if prev candle wicked below the swing low (sweep)
                if prev['low'] < s[2] and curr['close'] > s[2]:
                    return 7  # Classic liquidity sweep — reversal confirmed
                elif prev['low'] < s[2]:
                    return 4  # Sweep, but not yet confirmed reversal
                break
        return 0

    else:  # short
        for s in reversed(recent_swings):
            if s[1] == 'high':
                if prev['high'] > s[2] and curr['close'] < s[2]:
                    return 7
                elif prev['high'] > s[2]:
                    return 4
                break
        return 0


def score_p1_structure(df, i, swings, direction):
    """
    P1: Structure — FVG + Order Block + Liquidity Sweep
    Max: 25 points
    """
    score = 0

    # FVG (0-10)
    score += detect_fvg(df, i, direction)

    # Order Block (0-8)
    score += detect_order_block(df, i, swings, direction)

    # Liquidity Sweep (0-7)
    score += detect_liquidity_sweep(df, i, swings, direction)

    return min(25, score)


# ═══════════════════════════════════════════════
# P2: FIBONACCI — Retracement Golden Zone + Extension (0-25)
# ═══════════════════════════════════════════════

def score_p2_fibonacci(df, i, swings, direction):
    """
    P2: Fibonacci Retracement + Extension
    Find the most significant recent swing leg, compute fib levels.
    Score based on price proximity to golden zone (0.5-0.618). Max: 25
    """
    if i < 10 or len(swings) < 2:
        return 8  # Neutral

    recent = [s for s in swings if s[0] < i]
    if len(recent) < 2:
        return 8

    score = 0

    # Find the last major swing leg (high→low or low→high)
    s1 = recent[-1]
    s2 = recent[-2]

    # Need alternating types
    if s1[1] == s2[1]:
        return 8

    swing_high_idx, swing_high_val = max([(s[0], s[2]) for s in [s1, s2] if s[1] == 'high'], key=lambda x: x[1]) if any(s[1] == 'high' for s in [s1, s2]) else (None, None)
    swing_low_idx, swing_low_val = min([(s[0], s[2]) for s in [s1, s2] if s[1] == 'low'], key=lambda x: x[1]) if any(s[1] == 'low' for s in [s1, s2]) else (None, None)

    if swing_high_val is None or swing_low_val is None:
        return 8

    price_range = swing_high_val - swing_low_val
    if price_range <= 0:
        return 8

    curr = df.iloc[i]
    current_price = curr['close']

    # --- Retracement scoring (0-15) ---
    if direction == 'long':
        # Price is pulling back from high to low zone
        retrace = (swing_high_val - current_price) / price_range
    else:
        # Price is bouncing from low to high zone
        retrace = (current_price - swing_low_val) / price_range

    retrace = max(0, min(1, retrace))

    # Golden zone: 0.5 - 0.618 (8 pts)
    if 0.5 <= retrace <= 0.618:
        score += 15  # Golden zone
    elif 0.382 <= retrace <= 0.5:
        score += 12  # Strong
    elif 0.618 <= retrace <= 0.786:
        score += 10  # Deep retrace — still viable
    elif 0.236 <= retrace <= 0.382:
        score += 8   # Shallow
    elif 0.786 <= retrace <= 0.886:
        score += 6   # Very deep — risky
    elif retrace < 0.236:
        score += 4   # Barely retraced — chasing
    else:
        score += 3   # Beyond 0.886 — structure possibly broken

    # --- Extension target clarity (0-5) ---
    # Check if there's a clear extension level based on prior swing magnitude
    ext_1272 = swing_low_val + price_range * 1.272 if direction == 'long' else swing_high_val - price_range * 1.272
    ext_1618 = swing_low_val + price_range * 1.618 if direction == 'long' else swing_high_val - price_range * 1.618

    if direction == 'long':
        if current_price < ext_1272:
            score += 5  # Room to 1.272
        elif current_price < ext_1618:
            score += 3  # Room to 1.618
        else:
            score += 1  # Already extended
    else:
        if current_price > ext_1272:
            score += 5
        elif current_price > ext_1618:
            score += 3
        else:
            score += 1

    # --- Fib cluster bonus (0-5) ---
    # Check if current zone aligns with prior structure levels
    mid_price = (swing_high_val + swing_low_val) / 2
    if abs(current_price - mid_price) / current_price < 0.02:
        score += 5  # At the 0.5 level = strong confluence
    elif abs(current_price - swing_low_val) / current_price < 0.03 and direction == 'long':
        score += 3  # Near prior low = support
    elif abs(current_price - swing_high_val) / current_price < 0.03 and direction == 'short':
        score += 3  # Near prior high = resistance
    else:
        score += 1

    return min(25, score)


# ═══════════════════════════════════════════════
# P3: VOLUME — Surge + Divergence + Pressure (0-25)
# ═══════════════════════════════════════════════

def score_p3_volume(df, i, direction):
    """
    P3: Volume Analysis
    - Volume surge relative to average (0-10)
    - Volume pressure (buy/sell) alignment (0-8)
    - Volume divergence (0-7)
    Max: 25
    """
    if i < 20:
        return 10

    score = 0
    curr = df.iloc[i]

    # --- Volume Surge (0-10) ---
    vol_ratio = curr['volume'] / curr['vol_ma20'] if curr['vol_ma20'] > 0 else 1

    if vol_ratio > 2.5:
        score += 10  # Massive volume — high conviction
    elif vol_ratio > 2.0:
        score += 9
    elif vol_ratio > 1.5:
        score += 8
    elif vol_ratio > 1.2:
        score += 7   # Above average
    elif vol_ratio > 0.8:
        score += 5   # Normal
    elif vol_ratio > 0.5:
        score += 3   # Low volume
    else:
        score += 2   # Very low — avoid

    # --- Volume Pressure (0-8) ---
    # vol_pressure > 0 = net buying, < 0 = net selling
    vp = curr.get('vol_pressure', 0)

    if direction == 'long':
        if vp > 0 and vol_ratio > 1.2:
            score += 8  # Strong buying pressure
        elif vp > 0:
            score += 6  # Buying, normal volume
        elif vp < -0.5 * curr['volume'] and vol_ratio > 1.5:
            score += 2  # Heavy selling on high volume — BAD for longs
        elif vp < 0:
            score += 4
        else:
            score += 5
    else:  # short
        if vp < 0 and vol_ratio > 1.2:
            score += 8  # Strong selling pressure
        elif vp < 0:
            score += 6
        elif vp > 0.5 * curr['volume'] and vol_ratio > 1.5:
            score += 2  # Heavy buying — BAD for shorts
        elif vp > 0:
            score += 4
        else:
            score += 5

    # --- Volume Divergence (0-7) ---
    # Price making new low but volume declining = bullish divergence
    if i >= 5:
        recent_vol_avg = df.iloc[i - 5:i]['volume'].mean()

        if direction == 'long':
            # Bullish divergence: price near swing low but volume declining
            price_5ago = df.iloc[i - 5]['close']
            if curr['close'] < price_5ago and curr['volume'] < recent_vol_avg:
                score += 7  # Bullish divergence
            elif curr['close'] < price_5ago:
                score += 4  # Price down, volume normal = not divergence
            elif curr['volume'] < recent_vol_avg:
                score += 3  # Low volume pullback = healthy
            else:
                score += 2
        else:  # short
            # Bearish divergence: price near swing high but volume declining
            price_5ago = df.iloc[i - 5]['close']
            if curr['close'] > price_5ago and curr['volume'] < recent_vol_avg:
                score += 7  # Bearish divergence
            elif curr['close'] > price_5ago:
                score += 4
            elif curr['volume'] < recent_vol_avg:
                score += 3
            else:
                score += 2

    return min(25, score)


# ═══════════════════════════════════════════════
# P4: TREND — EMA Ribbon + Pullback Depth (0-25)
# ═══════════════════════════════════════════════
# FIXED: v4 had this BROKEN (Δ -1.7). Root cause: rewarding trend
# confirmation = rewarding CHASING. New approach: reward pullback to EMA.

def score_p4_trend(df, i, direction):
    """
    P4: Trend Alignment + Pullback Depth
    - EMA ribbon alignment (0-10)
    - Pullback depth to EMA (0-10) — REWARD pullback, PENALIZE extension
    - Trend momentum (0-5)
    Max: 25
    """
    if i < 20:
        return 10

    curr = df.iloc[i]

    score = 0

    # --- EMA Ribbon Alignment (0-10) ---
    ema20 = curr['ema20']
    ema50 = curr['ema50']
    ema200 = curr['ema200']
    price = curr['close']

    # Count bullish conditions
    bullish_count = 0
    if price > ema20: bullish_count += 1
    if ema20 > ema50: bullish_count += 1
    if ema50 > ema200: bullish_count += 1
    if price > ema200: bullish_count += 1

    if direction == 'long':
        if bullish_count == 4:
            score += 10  # Full alignment
        elif bullish_count == 3:
            score += 8
        elif bullish_count == 2:
            score += 6
        elif bullish_count == 1:
            score += 4  # Weak alignment
        else:
            score += 2  # No alignment — counter-trend
    else:  # short
        bearish_count = 4 - bullish_count
        if bearish_count == 4:
            score += 10
        elif bearish_count == 3:
            score += 8
        elif bearish_count == 2:
            score += 6
        elif bearish_count == 1:
            score += 4
        else:
            score += 2

    # --- Pullback Depth (0-10) — THE FIX ---
    # KEY INSIGHT: reward pullback TO the EMA, penalize being far FROM it
    # This was the v4 bug — it rewarded being extended, which = chasing

    if direction == 'long':
        # Distance from price to EMA50 as % of price
        dist_to_ema50 = (price - ema50) / ema50 * 100

        if -1.0 <= dist_to_ema50 <= 1.0:
            score += 10  # At/near EMA50 — optimal entry zone
        elif 1.0 < dist_to_ema50 <= 3.0:
            score += 7   # Slightly above — decent
        elif -1.0 > dist_to_ema50 >= -3.0:
            score += 8   # Below EMA — potential bounce
        elif 3.0 < dist_to_ema50 <= 5.0:
            score += 4   # Extended — chase risk
        elif -3.0 > dist_to_ema50 >= -5.0:
            score += 5   # Deep below — possible breakdown
        elif dist_to_ema50 > 5.0:
            score += 2   # Way extended — HIGH chase risk
        else:
            score += 3   # Way below — trend possibly broken

    else:  # short
        dist_to_ema50 = (price - ema50) / ema50 * 100

        if -1.0 <= dist_to_ema50 <= 1.0:
            score += 10  # At EMA50 — optimal
        elif -3.0 <= dist_to_ema50 < -1.0:
            score += 7   # Slightly below — decent
        elif 1.0 < dist_to_ema50 <= 3.0:
            score += 8   # Above EMA — potential rejection
        elif -5.0 <= dist_to_ema50 < -3.0:
            score += 4   # Extended down
        elif 3.0 < dist_to_ema50 <= 5.0:
            score += 5   # Above — possible breakout
        elif dist_to_ema50 < -5.0:
            score += 2   # Way extended
        else:
            score += 3   # Way above

    # --- Trend Momentum (0-5) ---
    if i >= 5:
        delta_5 = (price - df.iloc[i - 5]['close']) / df.iloc[i - 5]['close'] * 100

        if direction == 'long':
            if -2 <= delta_5 <= 2:
                score += 5  # Stable — not chasing
            elif 2 < delta_5 <= 5:
                score += 3  # Rising — moderate
            elif -5 <= delta_5 < -2:
                score += 4  # Dipping — potential entry
            elif delta_5 > 5:
                score += 2  # Parabolic — high risk
            else:
                score += 2  # Falling hard
        else:  # short
            if -2 <= delta_5 <= 2:
                score += 5
            elif -5 <= delta_5 < -2:
                score += 3  # Falling — moderate
            elif 2 < delta_5 <= 5:
                score += 4  # Rising — potential short entry
            elif delta_5 < -5:
                score += 2  # Free-fall
            else:
                score += 2  # Rallying hard

    return min(25, score)


# ═══════════════════════════════════════════════
# REGIME FILTER (HARD GATE)
# ═══════════════════════════════════════════════

def get_regime(df, i):
    """
    Determine allowed direction based on regime.
    Returns:
      'long'  — only long entries allowed
      'short' — only short entries allowed
      'none'  — no entries (choppy market)
    """
    if i < 200:
        return 'none'

    row = df.iloc[i]

    # ADX must be > 20 (trending market)
    if pd.isna(row['adx']) or row['adx'] < 20:
        return 'none'

    # EMA50 vs EMA200 determines trend direction
    if pd.isna(row['ema50']) or pd.isna(row['ema200']):
        return 'none'

    if row['ema50'] > row['ema200']:
        return 'long'
    else:
        return 'short'


# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════

def run_backtest_v5(df, threshold=60, atr_sl_mult=2.0, atr_tp_mult=4.0, scan_interval=2):
    """
    Run the v5 backtest with 4 ICT-inspired pillars + regime filter.
    """
    swings = find_swings(df, window=3)

    trades = []
    in_trade = False
    trade = None

    for i in range(200, len(df)):
        current_swings = [s for s in swings if s[0] < i]

        # --- Check exit conditions ---
        if in_trade and trade:
            candle = df.iloc[i]

            if trade['direction'] == 'LONG':
                if candle['low'] <= trade['sl_price']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl_price']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = (trade['sl_price'] - trade['entry_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['high'] >= trade['tp_price']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp_price']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = (trade['tp_price'] - trade['entry_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None

            else:  # SHORT
                if candle['high'] >= trade['sl_price']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl_price']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = (trade['entry_price'] - trade['sl_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['low'] <= trade['tp_price']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp_price']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = (trade['entry_price'] - trade['tp_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None

        # --- Check entry conditions ---
        if not in_trade and i % scan_interval == 0:
            # Regime HARD GATE
            regime = get_regime(df, i)
            if regime == 'none':
                continue

            # Score all 4 pillars for both directions
            scores_long = {
                'p1': score_p1_structure(df, i, current_swings, 'long'),
                'p2': score_p2_fibonacci(df, i, current_swings, 'long'),
                'p3': score_p3_volume(df, i, 'long'),
                'p4': score_p4_trend(df, i, 'long'),
            }
            scores_long['total'] = sum(scores_long.values())

            scores_short = {
                'p1': score_p1_structure(df, i, current_swings, 'short'),
                'p2': score_p2_fibonacci(df, i, current_swings, 'short'),
                'p3': score_p3_volume(df, i, 'short'),
                'p4': score_p4_trend(df, i, 'short'),
            }
            scores_short['total'] = sum(scores_short.values())

            # Only allow entry in regime direction
            if regime == 'long':
                total = scores_long['total']
                if total >= threshold:
                    entry_price = df.iloc[i]['close']
                    atr_val = df.iloc[i]['atr']
                    if pd.isna(atr_val) or atr_val <= 0:
                        atr_val = entry_price * 0.01

                    trade = {
                        'direction': 'LONG',
                        'entry_idx': i,
                        'entry_price': entry_price,
                        'entry_ts': df.index[i],
                        'sl_price': entry_price - atr_val * atr_sl_mult,
                        'tp_price': entry_price + atr_val * atr_tp_mult,
                        'scores': scores_long,
                        'regime': regime,
                    }
                    in_trade = True

            else:  # regime == 'short'
                total = scores_short['total']
                if total >= threshold:
                    entry_price = df.iloc[i]['close']
                    atr_val = df.iloc[i]['atr']
                    if pd.isna(atr_val) or atr_val <= 0:
                        atr_val = entry_price * 0.01

                    trade = {
                        'direction': 'SHORT',
                        'entry_idx': i,
                        'entry_price': entry_price,
                        'entry_ts': df.index[i],
                        'sl_price': entry_price + atr_val * atr_sl_mult,
                        'tp_price': entry_price - atr_val * atr_tp_mult,
                        'scores': scores_short,
                        'regime': regime,
                    }
                    in_trade = True

    # Close any open trade at end of data
    if in_trade and trade:
        last = df.iloc[-1]
        trade['exit_idx'] = len(df) - 1
        trade['exit_price'] = last['close']
        trade['exit_reason'] = 'EOD'
        if trade['direction'] == 'LONG':
            trade['pnl_pct'] = (last['close'] - trade['entry_price']) / trade['entry_price'] * 100
        else:
            trade['pnl_pct'] = (trade['entry_price'] - last['close']) / trade['entry_price'] * 100
        trades.append(trade)

    return trades


# ═══════════════════════════════════════════════
# ANALYSIS
# ═══════════════════════════════════════════════

def analyze_trades_v5(trades, label=""):
    if not trades:
        print(f"\n{label}: NO TRADES")
        return

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    long_wins = [t for t in longs if t['pnl_pct'] > 0]
    short_wins = [t for t in shorts if t['pnl_pct'] > 0]
    tp_trades = [t for t in trades if t['exit_reason'] == 'TP']
    sl_trades = [t for t in trades if t['exit_reason'] == 'SL']
    eod_trades = [t for t in trades if t['exit_reason'] == 'EOD']

    total_pnl = sum(t['pnl_pct'] for t in trades)
    wr = len(wins) / len(trades) * 100
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0

    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"Trades: {len(trades)} ({len(longs)}L/{len(shorts)}S) | WR: {wr:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}% | PnL: {total_pnl:+.2f}%")
    print(f"LONG WR: {len(long_wins)}/{len(longs)} ({len(long_wins)/len(longs)*100:.0f}%)" if longs else "LONG: 0")
    print(f"SHORT WR: {len(short_wins)}/{len(shorts)} ({len(short_wins)/len(shorts)*100:.0f}%)" if shorts else "SHORT: 0")
    print(f"TP: {len(tp_trades)} | SL: {len(sl_trades)} | EOD: {len(eod_trades)}")

    # Pillar diagnostics
    for label, key in [('P1 Structure', 'p1'), ('P2 Fibonacci', 'p2'), ('P3 Volume', 'p3'), ('P4 Trend', 'p4')]:
        w_avg = np.mean([t['scores'][key] for t in wins]) if wins else 0
        l_avg = np.mean([t['scores'][key] for t in losses]) if losses else 0
        diff = w_avg - l_avg
        verdict = '✅ PREDICTIVE' if diff > 1.5 else ('⚠️ WEAK' if diff > 0.5 else '❌ RANDOM' if diff > -0.5 else '🔴 BROKEN')
        print(f"{label:20s}: Win {w_avg:5.1f} | Loss {l_avg:5.1f} | Δ {diff:+5.1f}  {verdict}")

    # Trade log (compact)
    print(f"\n{'─'*65}")
    print(f"  TRADE LOG")
    print(f"{'─'*65}")
    for i, t in enumerate(trades, 1):
        scores = t['scores']
        color = "🟢" if t['pnl_pct'] > 0 else "🔴"
        print(f"{color} #{i:2d} {t['direction']:5s} [{t.get('regime','?'):5s}] | "
              f"{t['entry_price']:8.2f} → {t['exit_price']:8.2f} | "
              f"{t['exit_reason']:3s} | {t['pnl_pct']:+6.2f}% | "
              f"P1={scores['p1']:2d} P2={scores['p2']:2d} P3={scores['p3']:2d} P4={scores['p4']:2d} | "
              f"T={scores['total']:3d} | {t['entry_ts']}")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("  FORSCHER V5 BACKTEST — ICT-Inspired 4 Pillars + Regime")
    print("=" * 65)

    print("\nFetching BTCUSDT 4H data (Dec 2025 — now)...")
    df = fetch_ohlcv('BTCUSDT', '4h', limit=1500)
    print(f"Data: {len(df)} candles ({df.index[0]} → {df.index[-1]})")

    print("Computing indicators...")
    df = compute_indicators(df)
    print(f"Price range: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    print(f"ADX range: {df['adx'].min():.1f} — {df['adx'].max():.1f}")
    print(f"Regime filter pass rate: {(df['adx'] > 20).mean()*100:.0f}% (ADX > 20)")

    # Test different thresholds
    thresholds = [60, 65, 70]

    for th in thresholds:
        trades = run_backtest_v5(df, threshold=th, atr_sl_mult=2.0, atr_tp_mult=4.0, scan_interval=2)
        analyze_trades_v5(trades, f"THRESHOLD = {th}%")

    print(f"\n{'='*65}")
    print("BACKTEST COMPLETE")
    print(f"{'='*65}")
