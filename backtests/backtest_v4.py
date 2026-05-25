#!/usr/bin/env python3
"""
Forscher v4 Backtest — 4 Pillars + Regime Filter
=================================================
Changes from v3:
  - Regime filter (HARD GATE): ADX > 20, EMA50/200 direction → LONG/SHORT only
  - 4 pillars (not 5): Structure, Fib-Elliott, Momentum, Trend
  - Equal weight: 25 each = 100 max
  - Gann: REMOVED from scoring (bonus only, not implemented in backtest)
  - P1+P4 merged → Structure
  - P2+P3 merged → Fib-Elliott
  - P3 NEW → Momentum (RSI + Volume)
  - P4 NEW → Trend Alignment (Multi-TF)
  - SL/TP: ATR-based (2x/4x)
  - No TIME exits
  - LONG + SHORT per regime direction
"""
import ccxt, pandas as pd, numpy as np
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
    df = pd.DataFrame(all_candles, columns=['ts','open','high','low','close','volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    return df


# ═══════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════

def compute_indicators(df):
    """Pre-compute all indicators on the dataframe."""
    # EMAs
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    # ATR(14)
    high, low, close = df['high'], df['low'], df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.ewm(span=14, adjust=False).mean()

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=14, adjust=False).mean()
    avg_loss = loss.ewm(span=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    df['rsi'] = 100 - (100 / (1 + rs))

    # ADX(14)
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    atr_smooth = tr.ewm(span=14, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(span=14, adjust=False).mean() / atr_smooth.replace(0, 1))
    minus_di = 100 * (minus_dm.ewm(span=14, adjust=False).mean() / atr_smooth.replace(0, 1))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    df['adx'] = dx.ewm(span=14, adjust=False).mean()

    # Volume moving average (20 periods)
    df['vol_ma20'] = df['volume'].rolling(20).mean()

    # Price momentum (close - close 4 bars ago)
    df['momentum'] = close - close.shift(4)

    return df


# ═══════════════════════════════════════════════
# SWING DETECTION (same as v3)
# ═══════════════════════════════════════════════

def find_swings(df, window=3):
    highs, lows = df['high'].values, df['low'].values
    raw_swings = []
    for i in range(window, len(df) - window):
        if all(highs[i] > highs[i-j-1] for j in range(window)) and \
           all(highs[i] > highs[i+j+1] for j in range(window)):
            raw_swings.append((i, 'high', highs[i]))
        if all(lows[i] < lows[i-j-1] for j in range(window)) and \
           all(lows[i] < lows[i+j+1] for j in range(window)):
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


def find_impulse_waves(swings, direction='up'):
    """Same as v3: find 5-wave impulse, return (score 0-20, wave_points)."""
    if len(swings) < 6:
        return 0, None
    
    max_score = 0
    best_waves = None
    
    for i in range(len(swings) - 5):
        s = swings[i:i+6]
        
        if direction == 'up':
            expected = ['low', 'high', 'low', 'high', 'low', 'high']
        else:
            expected = ['high', 'low', 'high', 'low', 'high', 'low']
        
        if [x[1] for x in s] != expected:
            continue
        
        w_start, w1, w2, w3, w4, w5 = s[0][2], s[1][2], s[2][2], s[3][2], s[4][2], s[5][2]
        score = 20
        wave_detail = {}
        
        if direction == 'up':
            wave_size = [w1-w_start, w3-w2, w5-w4]
            retrace_w2 = (w1 - w2) / max(w1 - w_start, 0.0001)
            retrace_w4 = (w3 - w4) / max(w3 - w2, 0.0001)
            
            if w1 <= w_start: score -= 4; wave_detail['w1_extend'] = 'fail'
            else: wave_detail['w1_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0] * 0.8: score -= 3; wave_detail['w3_longest'] = 'fail'
            else: wave_detail['w3_longest'] = 'ok'
            
            if w4 <= w1: score -= 3; wave_detail['w4_no_overlap'] = 'fail'
            else: wave_detail['w4_no_overlap'] = 'ok'
            
            if retrace_w2 < 0.2 or retrace_w2 > 0.95: score -= 2; wave_detail['w2_retrace'] = 'bad'
            else: wave_detail['w2_retrace'] = 'ok'
            
            if retrace_w4 < 0.1 or retrace_w4 > 0.6: score -= 2; wave_detail['w4_retrace'] = 'bad'
            else: wave_detail['w4_retrace'] = 'ok'
            
            if w5 < w3 * 0.95: score -= 3; wave_detail['w5_extend'] = 'fail'
            else: wave_detail['w5_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0]: score -= 2; wave_detail['w3_gt_w1'] = 'fail'
            else: wave_detail['w3_gt_w1'] = 'ok'
            
            if w5 <= w4: score -= 1; wave_detail['w5_gt_w4'] = 'fail'
            else: wave_detail['w5_gt_w4'] = 'ok'
        else:  # down
            wave_size = [w_start-w1, w2-w3, w4-w5]
            retrace_w2 = (w2 - w1) / max(w_start - w1, 0.0001)
            retrace_w4 = (w4 - w3) / max(w2 - w3, 0.0001)
            
            if w1 >= w_start: score -= 4; wave_detail['w1_extend'] = 'fail'
            else: wave_detail['w1_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0] * 0.8: score -= 3; wave_detail['w3_longest'] = 'fail'
            else: wave_detail['w3_longest'] = 'ok'
            
            if w4 >= w1: score -= 3; wave_detail['w4_no_overlap'] = 'fail'
            else: wave_detail['w4_no_overlap'] = 'ok'
            
            if retrace_w2 < 0.2 or retrace_w2 > 0.95: score -= 2; wave_detail['w2_retrace'] = 'bad'
            else: wave_detail['w2_retrace'] = 'ok'
            
            if retrace_w4 < 0.1 or retrace_w4 > 0.6: score -= 2; wave_detail['w4_retrace'] = 'bad'
            else: wave_detail['w4_retrace'] = 'ok'
            
            if w5 > w3 * 1.05: score -= 3; wave_detail['w5_extend'] = 'fail'
            else: wave_detail['w5_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0]: score -= 2; wave_detail['w3_gt_w1'] = 'fail'
            else: wave_detail['w3_gt_w1'] = 'ok'
            
            if w5 >= w4: score -= 1; wave_detail['w5_gt_w4'] = 'fail'
            else: wave_detail['w5_gt_w4'] = 'ok'
        
        score = max(0, score)
        if score > max_score:
            max_score = score
            best_waves = s
    
    return max_score, best_waves


# ═══════════════════════════════════════════════
# 4-PILLAR SCORING (v4)
# ═══════════════════════════════════════════════

def score_p1_structure(df, i, swings, direction):
    """
    P1: Structure (merged P1+P4) — 0-25 pts
    = BOS detection + FVG + OB zone quality
    """
    score = 0
    
    # --- BOS detection (0-10) ---
    prior_high = prior_low = None
    for s in swings:
        if s[0] < i:
            if s[1] == 'high':
                prior_high = s[2]
            else:
                prior_low = s[2]
    
    if prior_high is not None and prior_low is not None:
        current = df.iloc[i]
        
        if direction == 'long':
            if current['close'] > prior_high:
                score += 10  # Clear BOS bullish
            elif current['close'] > (prior_high + prior_low) / 2:
                score += 5   # Near high, leaning bullish
            else:
                score += 2   # Below mid, weak structure
        else:  # short
            if current['close'] < prior_low:
                score += 10  # Clear BOS bearish
            elif current['close'] < (prior_high + prior_low) / 2:
                score += 5   # Near low, leaning bearish
            else:
                score += 2   # Above mid, weak structure
    else:
        score += 3
    
    # --- FVG / Imbalance (0-5) ---
    # Check for FVG: candle gap indicating imbalance
    if i >= 2:
        prev_high = df.iloc[i-1]['high']
        prev_low = df.iloc[i-1]['low']
        curr_low = df.iloc[i]['low']
        curr_high = df.iloc[i]['high']
        
        if direction == 'long':
            # Bullish FVG: current low > previous high (gap up)
            if curr_low > prev_high:
                score += 5
            elif curr_low > (prev_high + prev_low) / 2:
                score += 3  # Partial gap
            else:
                score += 1
        else:  # short
            # Bearish FVG: current high < previous low (gap down)
            if curr_high < prev_low:
                score += 5
            elif curr_high < (prev_high + prev_low) / 2:
                score += 3
            else:
                score += 1
    
    # --- OB / Demand-Supply zone quality (0-5) ---
    if i >= 20:
        lookback = df.iloc[i-20:i]
        try:
            vol_weighted = np.average(lookback['close'].values, 
                                      weights=lookback['volume'].values) if lookback['volume'].sum() > 0 else lookback['close'].mean()
        except Exception:
            vol_weighted = lookback['close'].mean()
        deviation = (df.iloc[i]['close'] - vol_weighted) / vol_weighted * 100
        
        if direction == 'long':
            # Price below VWAP = demand zone = good for longs
            if deviation < -2: score += 5
            elif deviation < -1: score += 4
            elif deviation < 0: score += 3
            elif deviation < 1: score += 2
            else: score += 1  # Above VWAP, supply zone — worse for longs
        else:  # short
            # Price above VWAP = supply zone = good for shorts
            if deviation > 2: score += 5
            elif deviation > 1: score += 4
            elif deviation > 0: score += 3
            elif deviation > -1: score += 2
            else: score += 1  # Below VWAP, demand zone — worse for shorts
    
    # --- Volume spike at zone (0-5) ---
    if i >= 20:
        avg_vol = df.iloc[i-20:i]['volume'].rolling(5).mean().iloc[-1] if len(lookback) >= 5 else df.iloc[i-20:i]['volume'].mean()
        if df.iloc[i]['volume'] > avg_vol * 1.5:
            score += 5  # High volume confirms zone significance
        elif df.iloc[i]['volume'] > avg_vol * 1.2:
            score += 3
        else:
            score += 1
    
    return min(25, score)


def score_p2_fib_elliott(swings, direction):
    """
    P2: Fibonacci-Elliott (merged P2+P3) — 0-25 pts
    = Wave position (0-15) + Retracement depth quality (0-10)
    """
    score = 0
    
    # --- Elliott Wave component (0-15) ---
    elliott_score, waves = find_impulse_waves(swings, 
                                             'up' if direction == 'long' else 'down')
    # Scale from 0-20 to 0-15
    score += min(15, int(elliott_score * 15 / 20))
    
    # --- Fibonacci retracement quality (0-10) ---
    if len(swings) >= 3:
        recent = [s for s in swings]
        s3, s2, s1 = recent[-3], recent[-2], recent[-1]
        move = abs(s1[2] - s2[2])
        
        if move > 0.001:
            if s2[1] == 'high' and s1[1] == 'low':
                retrace = (s1[2] - s2[2]) / move if move > 0 else 0  # Bounce from low
            elif s2[1] == 'low' and s1[1] == 'high':
                retrace = (s2[2] - s1[2]) / move if move > 0 else 0  # Pullback from high
            else:
                retrace = 0.5  # Neutral
            
            retrace = abs(retrace)  # Absolute retrace depth
            retrace = max(0, min(1, retrace))
            
            # Score retracement quality
            if 0.36 < retrace < 0.40 or 0.60 < retrace < 0.64:
                score += 10  # Golden
            elif 0.48 < retrace < 0.52:
                score += 8   # 0.5 zone
            elif 0.21 < retrace < 0.36 or 0.40 < retrace < 0.48:
                score += 6   # Shallow/pre-382
            elif 0.52 < retrace < 0.60 or 0.64 < retrace < 0.72:
                score += 4   # Between 0.5-0.72
            elif retrace < 0.21:
                score += 3   # Too shallow
            elif retrace > 0.72:
                score += 2   # Too deep
            else:
                score += 3
        else:
            score += 3
    else:
        score += 3
    
    return min(25, score)


def score_p3_momentum(df, i, direction):
    """
    P3: Momentum (NEW) — 0-25 pts
    = RSI alignment (0-10) + Volume expansion (0-10) + Price acceleration (0-5)
    """
    score = 0
    
    if i < 20:
        return 12  # Not enough data — neutral
    
    current = df.iloc[i]
    
    # --- RSI alignment (0-10) ---
    rsi = current['rsi']
    
    if direction == 'long':
        # RSI rising from oversold → strong
        if 30 < rsi < 50 and df.iloc[i-1]['rsi'] < rsi:
            score += 10  # Recovery from oversold
        elif 50 <= rsi < 70:
            score += 8   # Healthy bullish momentum
        elif 30 < rsi < 50:
            score += 6   # Neutral, could go either way
        elif rsi >= 70:
            score += 4   # Overbought — caution
        elif rsi <= 30:
            score += 5   # Oversold — potential reversal
        else:
            score += 5
    else:  # short
        if 50 < rsi < 70 and df.iloc[i-1]['rsi'] > rsi:
            score += 10  # Rolling over from overbought
        elif 30 < rsi <= 50:
            score += 8   # Healthy bearish momentum
        elif 50 < rsi < 70:
            score += 6   # Neutral
        elif rsi <= 30:
            score += 4   # Oversold — caution for shorts
        elif rsi >= 70:
            score += 5   # Overbought — potential short opportunity
        else:
            score += 5
    
    # RSI divergence bonus
    if i >= 5:
        if direction == 'long':
            # Price making lower low but RSI making higher low = bullish divergence
            if current['close'] < df.iloc[i-3]['close'] and current['rsi'] > df.iloc[i-3]['rsi']:
                score = min(10, score + 2)
        else:
            # Price making higher high but RSI making lower high = bearish divergence
            if current['close'] > df.iloc[i-3]['close'] and current['rsi'] < df.iloc[i-3]['rsi']:
                score = min(10, score + 2)
    
    # --- Volume expansion (0-10) ---
    vol_ratio = current['volume'] / current['vol_ma20'] if current['vol_ma20'] > 0 else 1
    
    if direction == 'long':
        if current['close'] > df.iloc[i-1]['close']:
            # Bullish candle + high volume = strong
            if vol_ratio > 2.0: score += 10
            elif vol_ratio > 1.5: score += 8
            elif vol_ratio > 1.2: score += 6
            elif vol_ratio > 0.8: score += 4
            else: score += 2
        else:
            # Bearish candle — volume is selling pressure
            if vol_ratio > 2.0: score += 2   # High sell volume = bad
            elif vol_ratio > 1.5: score += 3
            elif vol_ratio > 0.8: score += 5
            else: score += 4
    else:  # short
        if current['close'] < df.iloc[i-1]['close']:
            if vol_ratio > 2.0: score += 10
            elif vol_ratio > 1.5: score += 8
            elif vol_ratio > 1.2: score += 6
            elif vol_ratio > 0.8: score += 4
            else: score += 2
        else:
            if vol_ratio > 2.0: score += 2   # High buy volume = bad for shorts
            elif vol_ratio > 1.5: score += 3
            elif vol_ratio > 0.8: score += 5
            else: score += 4
    
    # --- Price acceleration (0-5) ---
    momentum = current['momentum']  # Close change over 4 bars
    
    if direction == 'long':
        if momentum > 0:
            if momentum > current['atr'] * 1.5: score += 5
            elif momentum > current['atr'] * 0.5: score += 3
            else: score += 1
        else:
            score += 1  # Negative momentum = weak
    else:  # short
        if momentum < 0:
            if abs(momentum) > current['atr'] * 1.5: score += 5
            elif abs(momentum) > current['atr'] * 0.5: score += 3
            else: score += 1
        else:
            score += 1
    
    return min(25, score)


def score_p4_trend(df, i, direction):
    """
    P4: Trend Alignment (NEW) — 0-25 pts
    = EMA50/200 alignment (0-10) + HH/HL structure (0-10) + ADX strength (0-5)
    """
    score = 0
    
    if i < 200:
        return 12  # Not enough data for EMA200
    
    current = df.iloc[i]
    
    # --- EMA50/200 alignment (0-10) ---
    ema50, ema200 = current['ema50'], current['ema200']
    ema_diff_pct = (ema50 - ema200) / ema200 * 100  # % difference
    
    if direction == 'long':
        if ema50 > ema200:
            if ema_diff_pct > 2: score += 10  # Strong bullish trend
            elif ema_diff_pct > 1: score += 8
            elif ema_diff_pct > 0.3: score += 6
            else: score += 4  # Barely above — weak
        else:
            # EMA50 below EMA200 — counter-trend LONG
            if ema_diff_pct > -0.5: score += 3  # Very close, could cross
            elif ema_diff_pct > -2: score += 2
            else: score += 1  # Clear bearish trend
    
    else:  # short
        if ema50 < ema200:
            if ema_diff_pct < -2: score += 10  # Strong bearish trend
            elif ema_diff_pct < -1: score += 8
            elif ema_diff_pct < -0.3: score += 6
            else: score += 4
        else:
            if ema_diff_pct < 0.5: score += 3
            elif ema_diff_pct < 2: score += 2
            else: score += 1  # Clear bullish trend
    
    # --- HH/HL structure (0-10) ---
    if i >= 10:
        lookback_5 = df.iloc[i-5:i]
        lookback_10 = df.iloc[i-10:i-5]
        
        recent_high = lookback_5['high'].max()
        recent_low = lookback_5['low'].min()
        prior_high = lookback_10['high'].max()
        prior_low = lookback_10['low'].min()
        
        if direction == 'long':
            if recent_high > prior_high and recent_low > prior_low:
                score += 10  # Clear HH+HL = uptrend
            elif recent_high > prior_high:
                score += 6   # HH but no HL
            elif recent_low > prior_low:
                score += 5   # HL but no HH
            else:
                score += 2   # No trend structure
        else:  # short
            if recent_low < prior_low and recent_high < prior_high:
                score += 10  # Clear LH+LL = downtrend
            elif recent_low < prior_low:
                score += 6
            elif recent_high < prior_high:
                score += 5
            else:
                score += 2
    
    # --- ADX strength (0-5) ---
    adx = current['adx']
    if adx > 40: score += 5    # Extreme trend strength
    elif adx > 30: score += 4  # Strong trend
    elif adx > 25: score += 3  # Moderate trend
    elif adx > 20: score += 2  # Weak trend
    else: score += 1            # Ranging / no trend
    
    return min(25, score)


# ═══════════════════════════════════════════════
# REGIME FILTER + ENTRY DETECTION
# ═══════════════════════════════════════════════

def check_regime(df, i):
    """
    HARD GATE — must pass to proceed to pillar scoring.
    
    Returns:
        ('long', None)  — trade only LONG
        ('short', None) — trade only SHORT
        (None, reason)  — NO TRADE
    """
    if i < 200:
        return None, 'insufficient_data'
    
    current = df.iloc[i]
    
    # Rule 1: ADX must be above threshold (trending market)
    if current['adx'] < 20:
        return None, 'adx_below_20'
    
    # Rule 2: EMA50 vs EMA200 determines direction
    if current['ema50'] > current['ema200']:
        return 'long', None
    elif current['ema50'] < current['ema200']:
        return 'short', None
    else:
        return None, 'ema_flat'


def compute_pillars_v4(df, i, swings, direction):
    """Compute all 4 pillars at candle i."""
    p1 = score_p1_structure(df, i, swings, direction)
    p2 = score_p2_fib_elliott([s for s in swings if s[0] < i], direction)
    p3 = score_p3_momentum(df, i, direction)
    p4 = score_p4_trend(df, i, direction)
    
    total = p1 + p2 + p3 + p4
    return total, p1, p2, p3, p4


def detect_entry_v4(df, i, swings, threshold=65):
    """
    Check if candle i qualifies for entry.
    1. Regime filter (hard gate)
    2. 4-pillar scoring
    3. Hard rules enforcement
    """
    # HARD GATE: Regime filter
    regime, reason = check_regime(df, i)
    if regime is None:
        return None, None, {'regime_reason': reason}
    
    # Compute 4 pillars
    total, p1, p2, p3, p4 = compute_pillars_v4(df, i, swings, regime)
    
    scores = {'total': total, 'p1': p1, 'p2': p2, 'p3': p3, 'p4': p4, 'regime': regime}
    
    # Threshold check
    if total < threshold:
        return None, None, scores
    
    # HARD RULE: No momentum = max 60 (prevents all weak-energy trades)
    if p3 < 10 and total >= threshold:
        return None, None, scores  # Effectively: if P3 < 10, max possible is 60, threshold is 65
    
    # HARD RULE: Wave 5 filter — P2 < 10 means likely wave 5
    if p2 < 10 and regime == 'long':
        return None, None, scores
    
    return regime.upper(), ('LONG' if regime == 'long' else 'SHORT'), scores


# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════

def run_backtest_v4(df, threshold=65, atr_sl_mult=2.0, atr_tp_mult=4.0, scan_interval=2):
    """
    Run full v4 backtest.
    - Regime filter (hard gate)
    - 4 pillars
    - ATR-based SL/TP
    - No TIME exits
    """
    swings = find_swings(df, window=3)
    trades = []
    
    in_trade = False
    trade = None
    
    # Start after 200 candles (EMA200 needs warmup)
    start_idx = 200
    
    for i in range(start_idx, len(df)):
        current_swings = [s for s in swings if s[0] < i]
        
        if in_trade:
            candle = df.iloc[i]
            
            if trade['direction'] == 'LONG':
                if candle['low'] <= trade['sl']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = (trade['sl'] - trade['entry_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['high'] >= trade['tp']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = (trade['tp'] - trade['entry_price']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
            else:  # SHORT
                if candle['high'] >= trade['sl']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = (trade['entry_price'] - trade['sl']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['low'] <= trade['tp']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = (trade['entry_price'] - trade['tp']) / trade['entry_price'] * 100
                    trades.append(trade)
                    in_trade = False
                    trade = None
        
        if not in_trade and i % scan_interval == 0:
            direction, dir_label, scores = detect_entry_v4(df, i, current_swings, threshold)
            
            if direction:
                entry_price = df.iloc[i]['close']
                atr = df.iloc[i]['atr']
                
                if direction == 'LONG':
                    sl = entry_price - atr * atr_sl_mult
                    tp = entry_price + atr * atr_tp_mult
                else:  # SHORT
                    sl = entry_price + atr * atr_sl_mult
                    tp = entry_price - atr * atr_tp_mult
                
                trade = {
                    'direction': direction,
                    'entry_idx': i,
                    'entry_price': entry_price,
                    'sl': sl,
                    'tp': tp,
                    'atr': atr,
                    'entry_ts': df.index[i],
                    'scores': scores
                }
                in_trade = True
    
    # Close last trade at end
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


def analyze_trades_v4(trades):
    """Print v4 summary stats."""
    if not trades:
        print("No trades.")
        return
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_pnl = sum(t['pnl_pct'] for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    
    # Equity curve
    equity = 100
    max_equity = 100
    max_dd = 0
    for t in trades:
        equity *= (1 + t['pnl_pct'] / 100)
        max_equity = max(max_equity, equity)
        dd = (equity - max_equity) / max_equity * 100
        max_dd = min(max_dd, dd)
    
    print(f"{'='*65}")
    print(f"V4 BACKTEST — 4 Pillars + Regime Filter + ATR SL/TP")
    print(f"{'='*65}")
    print(f"Total trades: {len(trades)} ({len(longs)}L / {len(shorts)}S)")
    print(f"Wins: {len(wins)} | Losses: {len(losses)} | WR: {wr:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}%")
    print(f"Total PnL: {total_pnl:+.2f}%")
    if losses and wins:
        pf = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses))
        print(f"Profit Factor: {pf:.2f}")
    print(f"Final Equity: ${equity:.2f} | Max DD: {max_dd:.1f}%")
    
    # By direction
    print(f"\n--- BY DIRECTION ---")
    for label, group in [('LONG', longs), ('SHORT', shorts)]:
        if not group:
            print(f"{label}: 0 trades")
            continue
        g_wins = [t for t in group if t['pnl_pct'] > 0]
        g_pnl = sum(t['pnl_pct'] for t in group)
        g_wr = len(g_wins) / len(group) * 100
        print(f"{label}: {len(group)} trades | WR {g_wr:.0f}% | PnL {g_pnl:+.2f}%")
    
    # By regime
    print(f"\n--- BY REGIME ---")
    for regime in ['long', 'short']:
        subset = [t for t in trades if t['scores'].get('regime') == regime]
        if subset:
            pnl = sum(t['pnl_pct'] for t in subset)
            s_wins = [t for t in subset if t['pnl_pct'] > 0]
            print(f"Regime {regime}: {len(subset)} trades | WR {len(s_wins)/len(subset)*100:.0f}% | PnL {pnl:+.2f}%")
    
    # By exit
    print(f"\n--- BY EXIT ---")
    for reason in ['TP', 'SL', 'EOD']:
        subset = [t for t in trades if t['exit_reason'] == reason]
        if subset:
            pnl = sum(t['pnl_pct'] for t in subset)
            print(f"{reason}: {len(subset)} exits | PnL {pnl:+.2f}%")
    
    # Pillar breakdown
    print(f"\n--- PILLAR BREAKDOWN (WIN vs LOSS) ---")
    for label, key in [('P1 Structure', 'p1'), ('P2 Fib-Elliott', 'p2'), ('P3 Momentum', 'p3'), ('P4 Trend', 'p4')]:
        w_avg = np.mean([t['scores'][key] for t in wins]) if wins else 0
        l_avg = np.mean([t['scores'][key] for t in losses]) if losses else 0
        diff = w_avg - l_avg
        verdict = '✅ PREDICTIVE' if diff > 1.5 else ('⚠️ WEAK' if diff > 0.5 else '❌ RANDOM' if diff > -0.5 else '🔴 BROKEN')
        print(f"{label:20s}: Win {w_avg:5.1f} | Loss {l_avg:5.1f} | Δ {diff:+5.1f}  {verdict}")
    
    # Print trade log (concise)
    print(f"\n--- TRADE LOG ---")
    for i, t in enumerate(trades, 1):
        regime = t['scores'].get('regime', '?' )
        scores_str = f"P1={t['scores']['p1']} P2={t['scores']['p2']} P3={t['scores']['p3']} P4={t['scores']['p4']}"
        print(f"#{i:2d} {t['direction']:5s} [{regime:5s}] | {t['entry_price']:8.2f} → {t['exit_price']:8.2f} | {t['exit_reason']:3s} | {t['pnl_pct']:+5.1f}% | {t['entry_ts']}")
        print(f"     Scores: {scores_str} | Total: {t['scores']['total']}")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("  FORSCHER V4 BACKTEST — 4 Pillars + Regime Filter")
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
        print(f"\n{'#'*65}")
        print(f"# THRESHOLD = {th}%")
        print(f"#{'#'*64}")
        trades = run_backtest_v4(df, threshold=th, atr_sl_mult=2.0, atr_tp_mult=4.0, scan_interval=2)
        analyze_trades_v4(trades)
    
    print(f"\n{'='*65}")
    print("BACKTEST COMPLETE")
    print(f"{'='*65}")
