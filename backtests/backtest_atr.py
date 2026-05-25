#!/usr/bin/env python3
"""
Forscher 5-Pillar Backtest — ATR-based SL/TP, LONG+SHORT, no TIME exits.
"""
import ccxt, pandas as pd, numpy as np
from datetime import datetime

# ═══════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════
exchange = ccxt.binance({
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
    }
})

def fetch_ohlcv(symbol='BTCUSDT', tf='4h', since=None, limit=1500):
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
    highs, lows = df['high'].values, df['low'].values
    raw_swings = []
    for i in range(window, len(df) - window):
        if all(highs[i] > highs[i-j-1] for j in range(window)) and \
           all(highs[i] > highs[i+j+1] for j in range(window)):
            raw_swings.append((i, 'high', highs[i]))
        if all(lows[i] < lows[i-j-1] for j in range(window)) and \
           all(lows[i] < lows[i+j+1] for j in range(window)):
            raw_swings.append((i, 'low', lows[i]))
    
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
        
        w_start, w1, w2 = s[0][2], s[1][2], s[2][2]
        w3, w4, w5 = s[3][2], s[4][2], s[5][2]
        score = 20
        
        if direction == 'up':
            wave_size = [w1-w_start, w3-w2, w5-w4]
            if w1 <= w_start: score -= 4
            if wave_size[1] <= wave_size[0] * 0.8: score -= 3
            if w4 <= w1: score -= 3
            retrace_w2 = (w1 - w2) / max(w1 - w_start, 0.0001)
            if retrace_w2 < 0.2 or retrace_w2 > 0.95: score -= 2
            retrace_w4 = (w3 - w4) / max(w3 - w2, 0.0001)
            if retrace_w4 < 0.1 or retrace_w4 > 0.6: score -= 2
            if w5 < w3 * 0.95: score -= 3
            if wave_size[1] <= wave_size[0]: score -= 2
            if w5 <= w4: score -= 1
        else:
            wave_size = [w_start-w1, w2-w3, w4-w5]
            if w1 >= w_start: score -= 4
            if wave_size[1] <= wave_size[0] * 0.8: score -= 3
            if w4 >= w1: score -= 3
            retrace_w2 = (w2 - w1) / max(w_start - w1, 0.0001)
            if retrace_w2 < 0.2 or retrace_w2 > 0.95: score -= 2
            retrace_w4 = (w4 - w3) / max(w2 - w3, 0.0001)
            if retrace_w4 < 0.1 or retrace_w4 > 0.6: score -= 2
            if w5 > w3 * 1.05: score -= 3
            if wave_size[1] <= wave_size[0]: score -= 2
            if w5 >= w4: score -= 1
        
        score = max(0, score)
        if score > max_score:
            max_score = score
            best_waves = s
    return max_score, best_waves

# ═══════════════════════════════════════════════
# 5-PILLAR SCORING
# ═══════════════════════════════════════════════
def detect_bos(df, i, swings):
    prior_high = prior_low = None
    for s in swings:
        if s[0] < i:
            if s[1] == 'high': prior_high = s[2]
            else: prior_low = s[2]
    if prior_high is None or prior_low is None:
        return 0, 'no_swings'
    current = df.iloc[i]
    if current['close'] > prior_high:
        return 20, 'bullish'
    elif current['close'] < prior_low:
        return 20, 'bearish'
    else:
        mid = (prior_high + prior_low) / 2
        return 10, 'near_high' if current['close'] > mid else 'near_low'

def score_elliott(swings, direction='up'):
    score, _ = find_impulse_waves(swings, direction)
    return score

def score_fibonacci(df, i, swings):
    current_price = df.iloc[i]['close']
    relevant = [s for s in swings if s[0] < i]
    if len(relevant) < 3:
        return 5
    s3, s2, s1 = relevant[-3], relevant[-2], relevant[-1]
    move = abs(s1[2] - s2[2])
    if move < 0.001:
        return 5
    
    if s2[1] == 'high' and s1[1] == 'low':
        retrace = (current_price - s1[2]) / move
    elif s2[1] == 'low' and s1[1] == 'high':
        retrace = (s1[2] - current_price) / move
    else:
        return 5
    
    retrace = max(0, min(1, retrace))
    
    if 0.36 < retrace < 0.40:       return 20
    elif 0.21 < retrace < 0.36:     return 17
    elif 0.40 < retrace < 0.44:     return 15
    elif 0.48 < retrace < 0.52:     return 17
    elif 0.60 < retrace < 0.64:     return 20
    elif 0.53 < retrace < 0.60:     return 15
    elif 0.64 < retrace < 0.72:     return 12
    elif 0.72 < retrace < 0.80:     return 8
    elif 0.10 < retrace < 0.21:     return 8
    elif 0.44 < retrace < 0.48:     return 10
    elif 0.52 < retrace < 0.53:     return 10
    elif retrace < 0.05:             return 5
    elif retrace > 0.85:             return 4
    else:                            return 7

def score_supply_demand(df, i, swings):
    current = df.iloc[i]
    price_range = df.iloc[max(0,i-20):i]
    if len(price_range) < 5:
        return 10
    vol_weighted = np.average(price_range['close'].values, weights=price_range['volume'].values) if price_range['volume'].sum() > 0 else price_range['close'].mean()
    deviation = (current['close'] - vol_weighted) / vol_weighted * 100
    if deviation < -3:       return 18
    elif deviation < -1.5:   return 15
    elif deviation < -0.5:   return 14
    elif deviation > 3:       return 3
    elif deviation > 1.5:     return 6
    elif deviation > 0.5:     return 8
    else:                     return 10

def score_gann_time(df, i, swings):
    relevant = [s for s in swings if s[0] < i]
    if len(relevant) < 5:
        return 10
    cycles = [7, 14, 21, 30, 45, 60, 90, 120, 180]
    tolerance = 1
    recent = [s for s in relevant[-10:] if i - s[0] <= 180]
    recent_hits = 0
    for s in recent:
        bars_ago = i - s[0]
        for cycle in cycles:
            if abs(bars_ago % cycle) <= tolerance:
                recent_hits += 1
                break
    total = max(1, len(recent))
    hit_ratio = recent_hits / total
    all_hits = 0
    for s in relevant:
        bars_ago = i - s[0]
        for cycle in cycles:
            if abs(bars_ago % cycle) <= tolerance:
                all_hits += 1
                break
    if hit_ratio > 0.6 and all_hits >= 8:    return 18
    elif hit_ratio > 0.5 and all_hits >= 5:  return 15
    elif hit_ratio > 0.4 and all_hits >= 3:  return 12
    elif hit_ratio > 0.3:                    return 8
    elif all_hits < 2:                        return 3
    else:                                     return 5

def compute_pillars(df, i, swings):
    p1_bos = detect_bos(df, i, swings)
    if p1_bos[1] in ('bullish', 'near_high'):
        direction = 'up'
        p1 = p1_bos[0]
    elif p1_bos[1] in ('bearish', 'near_low'):
        direction = 'down'
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
    total, p1, p2, p3, p4, p5, direction = compute_pillars(df, i, swings)
    if direction == 'none':
        return None, None
    if total < threshold:
        return None, None
    if direction == 'up' and p4 <= 5:
        return None, None
    if direction == 'down' and p4 >= 15:
        return None, None
    return direction, {'total': total, 'p1': p1, 'p2': p2, 'p3': p3, 'p4': p4, 'p5': p5}

# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════
def run_backtest_atr(df, threshold=65, sl_mult=2.0, tp_mult=3.0, scan_interval=2):
    """ATR-based SL/TP. sl_mult * ATR = SL distance, tp_mult * ATR = TP distance."""
    swings = find_swings(df, window=3)
    trades = []
    in_trade = False
    trade = None
    
    for i in range(50, len(df)):
        current_swings = [s for s in swings if s[0] < i]
        
        # ATR(14) for this candle
        if i >= 14:
            atr = np.mean([df['high'].iloc[i-j] - df['low'].iloc[i-j] for j in range(14)])
        else:
            atr = df['high'].iloc[i] - df['low'].iloc[i]
        
        if in_trade:
            candle = df.iloc[i]
            if trade['direction'] == 'UP':
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
            else:  # DOWN
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
            direction, scores = detect_entry(df, i, current_swings, threshold)
            if direction:
                entry_price = df.iloc[i]['close']
                sl_dist = atr * sl_mult
                tp_dist = atr * tp_mult
                
                if direction == 'up':
                    sl = entry_price - sl_dist
                    tp = entry_price + tp_dist
                else:
                    sl = entry_price + sl_dist
                    tp = entry_price - tp_dist
                
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
    
    if in_trade and trade:
        last = df.iloc[-1]
        trade['exit_idx'] = len(df) - 1
        trade['exit_price'] = last['close']
        trade['exit_reason'] = 'EOD'
        if trade['direction'] == 'UP':
            trade['pnl_pct'] = (last['close'] - trade['entry_price']) / trade['entry_price'] * 100
        else:
            trade['pnl_pct'] = (trade['entry_price'] - last['close']) / trade['entry_price'] * 100
        trades.append(trade)
    return trades

def analyze_trades(trades, label=""):
    if not trades:
        print(f"\n{label}: No trades.")
        return None
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    total_pnl = sum(t['pnl_pct'] for t in trades)
    wr = len(wins) / len(trades) * 100
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    longs = [t for t in trades if t['direction'] == 'UP']
    shorts = [t for t in trades if t['direction'] == 'DOWN']
    tp_wins = len([t for t in wins if t['exit_reason'] == 'TP'])
    sl_losses = len([t for t in losses if t['exit_reason'] == 'SL'])
    
    l_wins = len([t for t in longs if t['pnl_pct'] > 0])
    s_wins = len([t for t in shorts if t['pnl_pct'] > 0])
    
    result = {
        'label': label, 'trades': len(trades), 'wr': wr, 'total_pnl': total_pnl,
        'avg_win': avg_win, 'avg_loss': avg_loss, 'long_wr': l_wins/max(1,len(longs))*100,
        'short_wr': s_wins/max(1,len(shorts))*100, 'tp': tp_wins, 'sl': sl_losses,
        'n_long': len(longs), 'n_short': len(shorts)
    }
    
    print(f"\n{'='*50}")
    print(f"{label}")
    print(f"{'='*50}")
    print(f"Trades: {len(trades)} ({len(longs)}L/{len(shorts)}S) | WR: {wr:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}% | PnL: {total_pnl:+.2f}%")
    print(f"LONG WR: {l_wins}/{len(longs)} | SHORT WR: {s_wins}/{len(shorts)}")
    print(f"TP: {tp_wins} | SL: {sl_losses}")
    
    # Pillar diff
    if wins and losses:
        print(f"P1 Δ: {np.mean([t['scores']['p1'] for t in wins]) - np.mean([t['scores']['p1'] for t in losses]):+.1f} | "
              f"P2 Δ: {np.mean([t['scores']['p2'] for t in wins]) - np.mean([t['scores']['p2'] for t in losses]):+.1f} | "
              f"P3 Δ: {np.mean([t['scores']['p3'] for t in wins]) - np.mean([t['scores']['p3'] for t in losses]):+.1f} | "
              f"P4 Δ: {np.mean([t['scores']['p4'] for t in wins]) - np.mean([t['scores']['p4'] for t in losses]):+.1f} | "
              f"P5 Δ: {np.mean([t['scores']['p5'] for t in wins]) - np.mean([t['scores']['p5'] for t in losses]):+.1f}")
    
    return result

if __name__ == '__main__':
    print("Fetching BTCUSDT 4H data...")
    df = fetch_ohlcv('BTCUSDT', '4h', limit=1500)
    avg_atr = np.mean([df['high'].iloc[i] - df['low'].iloc[i] for i in range(14, len(df))])
    print(f"Data: {len(df)} candles ({df.index[0]} → {df.index[-1]})")
    print(f"Avg ATR(14): ${avg_atr:.0f} ({avg_atr/df['close'].mean()*100:.2f}%)")
    
    results = []
    
    # Test various ATR multipliers
    configs = [
        (60, 2.0, 3.0, "60% | 2x/3x ATR"),
        (60, 2.0, 4.0, "60% | 2x/4x ATR"),
        (65, 2.0, 3.0, "65% | 2x/3x ATR"),
        (65, 2.0, 4.0, "65% | 2x/4x ATR"),
        (65, 2.5, 4.0, "65% | 2.5x/4x ATR"),
        (70, 2.0, 3.0, "70% | 2x/3x ATR"),
    ]
    
    for th, sl_m, tp_m, label in configs:
        trades = run_backtest_atr(df, threshold=th, sl_mult=sl_m, tp_mult=tp_m, scan_interval=2)
        r = analyze_trades(trades, label)
        if r:
            results.append(r)
    
    # Summary table
    print(f"\n{'='*70}")
    print(f"{'SUMMARY':^70}")
    print(f"{'='*70}")
    print(f"{'Config':<22} {'Trades':>6} {'WR':>6} {'PnL':>8} {'L-WR':>6} {'S-WR':>6} {'TP':>4} {'SL':>4}")
    print(f"{'-'*70}")
    for r in results:
        print(f"{r['label']:<22} {r['trades']:>6} {r['wr']:>5.1f}% {r['total_pnl']:>+7.2f}% {r['long_wr']:>5.1f}% {r['short_wr']:>5.1f}% {r['tp']:>4} {r['sl']:>4}")
