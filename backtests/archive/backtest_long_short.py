#!/usr/bin/env python3
"""
Forscher 5-Pillar Backtest — LONG + SHORT, SL/TP only (no TIME exits).
"""
import ccxt, pandas as pd, numpy as np
from datetime import datetime, timedelta
from collections import deque

# ═══════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════
exchange = ccxt.binance({
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
})

def fetch_ohlcv(symbol='BTCUSDT', tf='4h', since=None, limit=1000):
    """Pull 1000 candles from Binance."""
    all_candles = []
    current_since = since or exchange.parse8601('2025-12-01T00:00:00Z')
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
# SWING DETECTION
# ═══════════════════════════════════════════════
def find_swings(df, window=3):
    """Find swing highs and lows with strict alternation."""
    highs, lows = df['high'].values, df['low'].values
    raw_swings = []  # (idx, type, price)
    
    for i in range(window, len(df) - window):
        # Swing high
        if all(highs[i] > highs[i-j-1] for j in range(window)) and \
           all(highs[i] > highs[i+j+1] for j in range(window)):
            raw_swings.append((i, 'high', highs[i]))
        # Swing low
        if all(lows[i] < lows[i-j-1] for j in range(window)) and \
           all(lows[i] < lows[i+j+1] for j in range(window)):
            raw_swings.append((i, 'low', lows[i]))
    
    # Strict alternation — enforce high/low/high/low...
    swings = []
    last_type = None
    for s in raw_swings:
        if s[1] == last_type:
            # Same type — take the more extreme one
            if swings and last_type == 'high' and s[2] > swings[-1][2]:
                swings[-1] = s
            elif swings and last_type == 'low' and s[2] < swings[-1][2]:
                swings[-1] = s
            # else: weaker — skip
        else:
            swings.append(s)
            last_type = s[1]
    
    # Ensure starts with the right type for 5-wave detection
    # We'll handle this in wave detection
    return swings

def find_impulse_waves(swings, direction='up'):
    """
    Find 5-wave impulse: W1→W2→W3→W4→W5.
    Returns (score, wave_points) or (0, None).
    """
    if len(swings) < 6:
        return 0, None
    
    max_score = 0
    best_waves = None
    
    for i in range(len(swings) - 5):
        s = swings[i:i+6]
        
        if direction == 'up':
            # Pattern: low, high, low, high, low, high
            expected = ['low', 'high', 'low', 'high', 'low', 'high']
        else:
            # Pattern: high, low, high, low, high, low
            expected = ['high', 'low', 'high', 'low', 'high', 'low']
        
        if [x[1] for x in s] != expected:
            continue
        
        # Extract wave points
        w_start = s[0][2]  # W0 (base)
        w1 = s[1][2]       # W1 peak
        w2 = s[2][2]       # W2 trough
        w3 = s[3][2]       # W3 peak
        w4 = s[4][2]       # W4 trough
        w5 = s[5][2]       # W5 peak
        
        score = 20
        wave_detail = {}
        
        if direction == 'up':
            wave_size = [w1-w_start, w3-w2, w5-w4]  # W1, W3, W5 sizes
            retrace_w2 = (w1 - w2) / max(w1 - w_start, 0.0001)
            retrace_w4 = (w3 - w4) / max(w3 - w2, 0.0001)
            
            # Wave 1 must extend from start
            if w1 <= w_start:
                score -= 4
                wave_detail['w1_extend'] = 'fail'
            else:
                wave_detail['w1_extend'] = 'ok'
            
            # Wave 3 must be the longest impulse (not always but usually)
            if wave_size[1] <= wave_size[0] * 0.8:
                score -= 3
                wave_detail['w3_longest'] = 'fail'
            else:
                wave_detail['w3_longest'] = 'ok'
            
            # Wave 4 must not overlap Wave 1 (w4 > w1 for UP)
            if w4 <= w1:
                score -= 3
                wave_detail['w4_no_overlap'] = 'fail'
            else:
                wave_detail['w4_no_overlap'] = 'ok'
            
            # Wave 2 retrace — should be 0.382-0.786 of W1
            if retrace_w2 < 0.2 or retrace_w2 > 0.95:
                score -= 2
                wave_detail['w2_retrace'] = 'bad'
            else:
                wave_detail['w2_retrace'] = 'ok'
            
            # Wave 4 retrace — should be 0.236-0.5 of W3
            if retrace_w4 < 0.1 or retrace_w4 > 0.6:
                score -= 2
                wave_detail['w4_retrace'] = 'bad'
            else:
                wave_detail['w4_retrace'] = 'ok'
            
            # W5 should extend (not truncated, w5 > w3 for strong impulse)
            if w5 < w3 * 0.95:
                score -= 3
                wave_detail['w5_extend'] = 'fail'
            else:
                wave_detail['w5_extend'] = 'ok'
            
            # W3 > W1 (basic rule)
            if wave_size[1] <= wave_size[0]:
                score -= 2
                wave_detail['w3_gt_w1'] = 'fail'
            else:
                wave_detail['w3_gt_w1'] = 'ok'
            
            # W5 > W4 (must trend upward)
            if w5 <= w4:
                score -= 1
                wave_detail['w5_gt_w4'] = 'fail'
            else:
                wave_detail['w5_gt_w4'] = 'ok'
        
        else:  # down
            wave_size = [w_start-w1, w2-w3, w4-w5]  # W1, W3, W5 sizes (downward)
            retrace_w2 = (w2 - w1) / max(w_start - w1, 0.0001)
            retrace_w4 = (w4 - w3) / max(w2 - w3, 0.0001)
            
            if w1 >= w_start:
                score -= 4
                wave_detail['w1_extend'] = 'fail'
            else:
                wave_detail['w1_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0] * 0.8:
                score -= 3
                wave_detail['w3_longest'] = 'fail'
            else:
                wave_detail['w3_longest'] = 'ok'
            
            if w4 >= w1:
                score -= 3
                wave_detail['w4_no_overlap'] = 'fail'
            else:
                wave_detail['w4_no_overlap'] = 'ok'
            
            if retrace_w2 < 0.2 or retrace_w2 > 0.95:
                score -= 2
                wave_detail['w2_retrace'] = 'bad'
            else:
                wave_detail['w2_retrace'] = 'ok'
            
            if retrace_w4 < 0.1 or retrace_w4 > 0.6:
                score -= 2
                wave_detail['w4_retrace'] = 'bad'
            else:
                wave_detail['w4_retrace'] = 'ok'
            
            if w5 > w3 * 1.05:
                score -= 3
                wave_detail['w5_extend'] = 'fail'
            else:
                wave_detail['w5_extend'] = 'ok'
            
            if wave_size[1] <= wave_size[0]:
                score -= 2
                wave_detail['w3_gt_w1'] = 'fail'
            else:
                wave_detail['w3_gt_w1'] = 'ok'
            
            if w5 >= w4:
                score -= 1
                wave_detail['w5_gt_w4'] = 'fail'
            else:
                wave_detail['w5_gt_w4'] = 'ok'
        
        score = max(0, score)
        if score > max_score:
            max_score = score
            best_waves = s
    
    return max_score, best_waves


# ═══════════════════════════════════════════════
# 5-PILLAR SCORING
# ═══════════════════════════════════════════════

def detect_bos(df, i, swings):
    """P1: Structure — detect Break of Structure (BOS)."""
    # Find prior swing high/low before idx i
    prior_high = prior_low = None
    for s in swings:
        if s[0] < i:
            if s[1] == 'high':
                prior_high = s[2]
            else:
                prior_low = s[2]
    
    if prior_high is None or prior_low is None:
        return 0, 'no_swings'
    
    current = df.iloc[i]
    bullish = current['close'] > prior_high  # BOS bullish
    bearish = current['close'] < prior_low    # BOS bearish
    
    if bullish:
        return 20, 'bullish'
    elif bearish:
        return 20, 'bearish'
    else:
        # Check proximity — closer to high = leaning bullish, closer to low = bearish
        mid = (prior_high + prior_low) / 2
        if current['close'] > mid:
            return 10, 'near_high'
        else:
            return 10, 'near_low'

def score_elliott(swings, direction='up'):
    """P2: Elliott Wave — 20 pts max."""
    score, waves = find_impulse_waves(swings, direction)
    return score

def score_fibonacci(df, i, swings):
    """P3: Fibonacci retracement/extension levels — 20 pts max."""
    current = df.iloc[i]
    current_price = current['close']
    
    # Find most recent complete swing structure — at least 3 swings
    relevant = [s for s in swings if s[0] < i]
    if len(relevant) < 3:
        return 5  # neutral, not enough data
    
    # Take last 3 swings: s[−3], s[−2], s[−1]
    s3, s2, s1 = relevant[-3], relevant[-2], relevant[-1]
    
    # Determine the move direction from last completed wave
    # s3 → s2 = first leg. s2 → s1 = second leg (the most recent move)
    move = abs(s1[2] - s2[2])
    if move < 0.001:
        return 5
    
    # What is the overall structure direction?
    # s3→s2→s1: if s3=low, s2=high, s1=low → DOWN structure (retracing from high)
    if s2[1] == 'high' and s1[1] == 'low':
        # Structure: swing HIGH → LOW (bearish leg). Check retracement FROM the low.
        retrace = (current_price - s1[2]) / move  # Bounce from recent low
        label = f"bounce_from_{s1[2]:.0f}"
    elif s2[1] == 'low' and s1[1] == 'high':
        # Structure: swing LOW → HIGH (bullish leg). Check retracement FROM the high.
        retrace = (s1[2] - current_price) / move  # Pullback from recent high
        label = f"pullback_from_{s1[2]:.0f}"
    else:
        return 5  # Shouldn't happen with strict alternation
    
    retrace = max(0, min(1, retrace))
    
    # Fibonacci scoring
    if 0.36 < retrace < 0.40:       score = 20   # 0.382 exact
    elif 0.21 < retrace < 0.36:     score = 17   # approaching 0.382
    elif 0.40 < retrace < 0.44:     score = 15   # slightly past 0.382
    elif 0.48 < retrace < 0.52:     score = 17   # 0.5 zone
    elif 0.60 < retrace < 0.64:     score = 20   # 0.618 golden
    elif 0.53 < retrace < 0.60:     score = 15   # approaching 0.618
    elif 0.64 < retrace < 0.72:     score = 12   # 0.65-0.72
    elif 0.72 < retrace < 0.80:     score = 8    # 0.72-0.786
    elif 0.10 < retrace < 0.21:     score = 8    # 0.1-0.21
    elif 0.44 < retrace < 0.48:     score = 10   # between 0.382 and 0.5
    elif 0.52 < retrace < 0.53:     score = 10   # between 0.5 and 0.618
    elif retrace < 0.05:             score = 5    # barely retraced
    elif retrace > 0.85:             score = 4    # too deep
    else:                            score = 7    # other
    
    return score

def score_supply_demand(df, i, swings):
    """P4: Supply/Demand — volume profile zones — 20 pts max."""
    score = 10  # neutral base
    
    current = df.iloc[i]
    price_range = df.iloc[i-20:i] if i >= 20 else df.iloc[:i]
    if len(price_range) < 5:
        return 10
    
    # Find volume node — where most volume traded
    vol_weighted = np.average(price_range['close'].values, weights=price_range['volume'].values) if price_range['volume'].sum() > 0 else price_range['close'].mean()
    
    # Current price relative to volume-weighted average
    deviation = (current['close'] - vol_weighted) / vol_weighted * 100
    
    # Price BELOW VWAP = demand zone (buyers stepped in at lower prices)
    # Price ABOVE VWAP = supply zone (sellers active at higher prices)
    
    if deviation < -3:      # Well below VWAP — strong demand zone
        score = 18
    elif deviation < -1.5:   # Below VWAP — demand zone
        score = 15
    elif deviation < -0.5:   # Slightly below — leaning demand
        score = 14
    elif deviation > 3:       # Well above VWAP — supply zone
        score = 3
    elif deviation > 1.5:     # Above VWAP — supply zone
        score = 6
    elif deviation > 0.5:     # Slightly above — leaning supply
        score = 8
    else:                     # At VWAP — neutral
        score = 10
    
    # Volume spike check — high relative volume = significant zone
    avg_vol = price_range['volume'].rolling(5).mean().iloc[-1] if len(price_range) >= 5 else price_range['volume'].mean()
    if price_range['volume'].iloc[-1] > avg_vol * 1.5 and score >= 10:
        score = min(20, score + 2)  # Bonus for high volume at demand
    
    return score

def score_gann_time(df, i, swings):
    """P5: Gann Time Cycle — 20 pts max."""
    if len(swings) < 5:
        return 10
    
    # Get all swing dates relative to current candle
    current_ts = df.index[i]
    relevant_swings = [s for s in swings if s[0] < i]
    
    # Gann cycles to check (in 4H bars)
    cycles = [7, 14, 21, 30, 45, 60, 90, 120, 180]  # ~1d, 2d, 3.5d, 5d, 7.5d, 10d, 15d, 20d, 30d
    
    # Check if we're at a cycle confluence
    hits = 0
    tolerance = 1  # ±1 bar
    
    for s in relevant_swings[-20:]:  # Check last 20 swings
        bars_ago = i - s[0]
        for cycle in cycles:
            if abs(bars_ago % cycle) <= tolerance:
                hits += 1
                break  # Count once per swing
    
    # Only consider recent swings more heavily
    recent_swings = [s for s in relevant_swings[-10:] if i - s[0] <= 180]
    
    # Weighted: how many recent swings land on cycle points
    recent_hits = 0
    for s in recent_swings:
        bars_ago = i - s[0]
        for cycle in cycles:
            if abs(bars_ago % cycle) <= tolerance:
                recent_hits += 1
                break
    
    total_recent = max(1, len(recent_swings))
    hit_ratio = recent_hits / total_recent
    
    # Score based on how concentrated swings are around cycle points
    if hit_ratio > 0.6 and hits >= 8:
        score = 18  # Strong time cluster
    elif hit_ratio > 0.5 and hits >= 5:
        score = 15  # Moderate cluster
    elif hit_ratio > 0.4 and hits >= 3:
        score = 12  # Weak cluster
    elif hit_ratio > 0.3:
        score = 8   # Minor
    elif hits < 2:
        score = 3   # No Gann cluster
    else:
        score = 5   # Minimal
    
    return score


# ═══════════════════════════════════════════════
# ENTRY DETECTION
# ═══════════════════════════════════════════════

def compute_pillars(df, i, swings):
    """Compute all 5 pillars at candle i."""
    p1_bos = detect_bos(df, i, swings)
    
    # Direction from BOS
    if p1_bos[1] in ('bullish', 'near_high'):
        direction = 'up'   # LONG
        p1 = p1_bos[0]
    elif p1_bos[1] in ('bearish', 'near_low'):
        direction = 'down'  # SHORT
        p1 = p1_bos[0]
    else:
        direction = 'none'
        p1 = p1_bos[0]
    
    p2 = score_elliott(swings, direction) if direction != 'none' else 0
    p3 = score_fibonacci(df, i, swings)
    p4 = score_supply_demand(df, i, swings)
    p5 = score_gann_time(df, i, swings)
    
    total = p1 + p2 + p3 + p4 + p5
    return total, p1, p2, p3, p4, p5, direction


def detect_entry(df, i, swings, threshold=65):
    """Check if candle i qualifies for entry. Returns direction or None."""
    total, p1, p2, p3, p4, p5, direction = compute_pillars(df, i, swings)
    
    if direction == 'none':
        return None, None
    
    if total < threshold:
        return None, None
    
    # S/D hard rule: below supply zone = WAIT for LONG
    if direction == 'up' and p4 <= 5:
        return None, None
    
    # S/D hard rule for SHORT: above demand zone = WAIT
    if direction == 'down' and p4 >= 15:
        return None, None
    
    return direction, {'total': total, 'p1': p1, 'p2': p2, 'p3': p3, 'p4': p4, 'p5': p5}


# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════

def run_backtest(df, threshold=65, sl_pct=1.5, tp_pct=3.0, scan_interval=2):
    """Run full backtest with LONG + SHORT, SL/TP only (no TIME exits)."""
    
    swings = find_swings(df, window=3)
    trades = []
    
    in_trade = False
    trade = None
    
    for i in range(50, len(df)):  # Start after enough data
        # Update swings up to this candle
        current_swings = [s for s in swings if s[0] < i]
        
        if in_trade:
            # Check SL/TP
            candle = df.iloc[i]
            
            if trade['direction'] == 'LONG':
                if candle['low'] <= trade['sl']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = -sl_pct
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['high'] >= trade['tp']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = tp_pct
                    trades.append(trade)
                    in_trade = False
                    trade = None
            else:  # SHORT
                if candle['high'] >= trade['sl']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['sl']
                    trade['exit_reason'] = 'SL'
                    trade['pnl_pct'] = -sl_pct
                    trades.append(trade)
                    in_trade = False
                    trade = None
                elif candle['low'] <= trade['tp']:
                    trade['exit_idx'] = i
                    trade['exit_price'] = trade['tp']
                    trade['exit_reason'] = 'TP'
                    trade['pnl_pct'] = tp_pct
                    trades.append(trade)
                    in_trade = False
                    trade = None
        
        if not in_trade and i % scan_interval == 0:
            direction, scores = detect_entry(df, i, current_swings, threshold)
            
            if direction:
                entry_price = df.iloc[i]['close']
                
                if direction == 'up':  # LONG
                    sl = entry_price * (1 - sl_pct / 100)
                    tp = entry_price * (1 + tp_pct / 100)
                else:  # SHORT
                    sl = entry_price * (1 + sl_pct / 100)
                    tp = entry_price * (1 - tp_pct / 100)
                
                trade = {
                    'direction': direction.upper(),
                    'entry_idx': i,
                    'entry_price': entry_price,
                    'sl': sl,
                    'tp': tp,
                    'entry_ts': df.index[i],
                    'scores': scores
                }
                in_trade = True
    
    # Close last trade at end of data
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


def analyze_trades(trades):
    """Print summary stats."""
    if not trades:
        print("No trades.")
        return
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_pnl = sum(t['pnl_pct'] for t in trades)
    wr = len(wins) / len(trades) * 100
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    
    longs = [t for t in trades if t['direction'] == 'UP']
    shorts = [t for t in trades if t['direction'] == 'DOWN']
    
    print(f"{'='*60}")
    print(f"BACKTEST RESULTS — SL/TP only, LONG+SHORT")
    print(f"{'='*60}")
    print(f"Total trades: {len(trades)} ({len(longs)}L / {len(shorts)}S)")
    print(f"Wins: {len(wins)} | Losses: {len(losses)} | WR: {wr:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}%")
    print(f"Total PnL: {total_pnl:+.2f}%")
    if losses:
        print(f"Profit Factor: {abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)):.2f}" if wins else "Profit Factor: 0")
    
    # By direction
    print(f"\n--- BY DIRECTION ---")
    for label, group in [('LONG', longs), ('SHORT', shorts)]:
        if not group:
            print(f"{label}: 0 trades")
            continue
        g_wins = [t for t in group if t['pnl_pct'] > 0]
        g_pnl = sum(t['pnl_pct'] for t in group)
        print(f"{label}: {len(group)} trades, {len(g_wins)}W/{len(group)-len(g_wins)}L, PnL {g_pnl:+.2f}%")
    
    # By exit reason
    print(f"\n--- BY EXIT ---")
    for reason in ['TP', 'SL', 'EOD']:
        subset = [t for t in trades if t['exit_reason'] == reason]
        if subset:
            pnl = sum(t['pnl_pct'] for t in subset)
            print(f"{reason}: {len(subset)} exits, PnL {pnl:+.2f}%")
    
    # Pillar analysis
    print(f"\n--- PILLAR BREAKDOWN ---")
    for label, key in [('P1 Structure', 'p1'), ('P2 Elliott', 'p2'), ('P3 Fibonacci', 'p3'), ('P4 Supply/Demand', 'p4'), ('P5 Gann Time', 'p5')]:
        w_avg = np.mean([t['scores'][key] for t in wins]) if wins else 0
        l_avg = np.mean([t['scores'][key] for t in losses]) if losses else 0
        diff = w_avg - l_avg
        print(f"{label}: Win {w_avg:.1f} | Loss {l_avg:.1f} | Δ {diff:+.1f}")
    
    # Print individual trades
    print(f"\n--- TRADE LOG ---")
    for i, t in enumerate(trades, 1):
        print(f"#{i} {t['direction']:5s} | Entry: {t['entry_price']:.2f} | Exit: {t['exit_price']:.2f} | {t['exit_reason']:3s} | PnL: {t['pnl_pct']:+.2f}% | {t['entry_ts']}")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    print("Fetching BTCUSDT 4H data...")
    df = fetch_ohlcv('BTCUSDT', '4h', limit=1500)
    print(f"Data: {len(df)} candles ({df.index[0]} → {df.index[-1]})")
    
    thresholds = [60, 65, 70]
    
    for th in thresholds:
        print(f"\n{'#'*60}")
        print(f"# THRESHOLD = {th}%")
        print(f"{'#'*60}")
        trades = run_backtest(df, threshold=th, sl_pct=1.5, tp_pct=3.0, scan_interval=2)
        analyze_trades(trades)
