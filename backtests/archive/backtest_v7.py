#!/usr/bin/env python3
"""
Forscher v7 — ALTCOIN SNIPER
=============================
Focus: ETH, SOL, NEAR — altcoins have stronger mean reversion,
cleaner support/resistance, and more predictable RSI extremes
than BTC.

Strategy: RSI Extreme + Key Level Bounce + Candle Confirmation
Goal: 60-75% WR with positive expectancy
"""
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime


# ═══════════════════════════════════════════════
# DATA
# ═══════════════════════════════════════════════

def fetch_ohlcv(symbol='ETHUSDT', tf='4h', since='2025-12-01T00:00:00Z', limit=1500):
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
    high, low, close = df['high'], df['low'], df['close']

    # ATR(14)
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

    # EMAs
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    # Volume
    df['vol_ma20'] = df['volume'].rolling(20).mean()

    # Candle properties
    df['body'] = (close - df['open']).abs()
    df['total_range'] = high - low
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low
    df['upper_wick'] = high - df[['open', 'close']].max(axis=1)
    df['is_bullish'] = close > df['open']
    df['is_bearish'] = close < df['open']

    # BB for confluence check
    df['bb_mid'] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std

    return df


# ═══════════════════════════════════════════════
# SWING DETECTION
# ═══════════════════════════════════════════════

def find_swings(df, window=3):
    highs, lows = df['high'].values, df['low'].values
    raw_swings = []
    for i in range(window, len(df) - window):
        if all(highs[i] > highs[i - j - 1] for j in range(window)) and \
           all(highs[i] > highs[i + j + 1] for j in range(window)):
            raw_swings.append((i, 'high', highs[i]))
        if all(lows[i] < lows[i - j - 1] for j in range(window)) and \
           all(lows[i] < lows[i + j + 1] for j in range(window)):
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


def get_nearest_swing(price, swings, current_idx, swing_type, max_bars=50):
    """Get the nearest swing high/low before current_idx."""
    candidates = [s for s in swings 
                  if s[1] == swing_type and s[0] < current_idx and (current_idx - s[0]) < max_bars]
    if not candidates:
        return None
    return min(candidates, key=lambda s: abs(price - s[2]))


# ═══════════════════════════════════════════════
# CANDLE PATTERNS
# ═══════════════════════════════════════════════

def is_bullish_reversal(df, i):
    if i < 2:
        return False
    c = df.iloc[i]
    p = df.iloc[i - 1]
    body = c['body']
    tr = c['total_range']
    lw = c['lower_wick']
    if tr <= 0:
        return False
    # Hammer: long lower wick >= 2x body, small upper wick
    if body > 0 and lw >= body * 2 and lw > tr * 0.5 and c['upper_wick'] < lw * 0.5:
        return True
    # Bullish engulfing
    if c['is_bullish'] and p['is_bearish'] and c['open'] <= p['close'] and c['close'] >= p['open']:
        return True
    # Strong bullish close: close in top 25% of range
    if c['is_bullish'] and (c['close'] - c['low']) / max(tr, 1e-10) > 0.75:
        return True
    return False


def is_bearish_reversal(df, i):
    if i < 2:
        return False
    c = df.iloc[i]
    p = df.iloc[i - 1]
    body = c['body']
    tr = c['total_range']
    uw = c['upper_wick']
    if tr <= 0:
        return False
    # Shooting star
    if body > 0 and uw >= body * 2 and uw > tr * 0.5 and c['lower_wick'] < uw * 0.5:
        return True
    # Bearish engulfing
    if c['is_bearish'] and p['is_bullish'] and c['open'] >= p['close'] and c['close'] <= p['open']:
        return True
    # Strong bearish close: close in bottom 25% of range
    if c['is_bearish'] and (c['high'] - c['close']) / max(tr, 1e-10) > 0.75:
        return True
    return False


# ═══════════════════════════════════════════════
# ENTRY SIGNALS
# ═══════════════════════════════════════════════

def check_long_alt(df, i, swings, rsi_max=40, level_dist_atr=1.0):
    """Check LONG entry for altcoins — relaxed filters."""
    if i < 50:
        return False, {}

    c = df.iloc[i]
    atr = c['atr']
    if pd.isna(atr) or atr <= 0:
        return False, {}

    checks = {}

    # FILTER 1: RSI oversold
    checks['rsi'] = c['rsi'] < rsi_max
    if not checks['rsi']:
        return False, checks

    # FILTER 2: Near swing low
    swing_low = get_nearest_swing(c['close'], swings, i, 'low', max_bars=60)
    if swing_low is None:
        checks['level'] = False
        return False, checks

    dist_to_low = (c['close'] - swing_low[2]) / atr
    checks['level'] = abs(dist_to_low) < level_dist_atr
    checks['dist_atr'] = dist_to_low
    if not checks['level']:
        return False, checks

    # FILTER 3: Candle reversal
    checks['candle'] = is_bullish_reversal(df, i)
    if not checks['candle']:
        return False, checks

    # FILTER 4: EMA200 trend check — price above EMA200 = stronger bounce
    checks['ema200'] = c['close'] > c['ema200'] if not pd.isna(c['ema200']) else True

    # BONUS: BB touch
    checks['bb'] = c['close'] <= c['bb_lower'] * 1.02 if not pd.isna(c['bb_lower']) else False

    return True, checks


def check_short_alt(df, i, swings, rsi_min=60, level_dist_atr=1.0):
    """Check SHORT entry for altcoins."""
    if i < 50:
        return False, {}

    c = df.iloc[i]
    atr = c['atr']
    if pd.isna(atr) or atr <= 0:
        return False, {}

    checks = {}

    # FILTER 1: RSI overbought
    checks['rsi'] = c['rsi'] > rsi_min
    if not checks['rsi']:
        return False, checks

    # FILTER 2: Near swing high
    swing_high = get_nearest_swing(c['close'], swings, i, 'high', max_bars=60)
    if swing_high is None:
        checks['level'] = False
        return False, checks

    dist_to_high = (swing_high[2] - c['close']) / atr
    checks['level'] = abs(dist_to_high) < level_dist_atr
    checks['dist_atr'] = dist_to_high
    if not checks['level']:
        return False, checks

    # FILTER 3: Candle reversal
    checks['candle'] = is_bearish_reversal(df, i)
    if not checks['candle']:
        return False, checks

    # FILTER 4: EMA200 trend check
    checks['ema200'] = c['close'] < c['ema200'] if not pd.isna(c['ema200']) else True

    # BONUS: BB touch
    checks['bb'] = c['close'] >= c['bb_upper'] * 0.98 if not pd.isna(c['bb_upper']) else False

    return True, checks


# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════

def run_backtest_alt(df, sl_atr=1.5, tp_atr=3.0, rsi_long=40, rsi_short=60, 
                      level_dist=1.0, scan_interval=2):
    swaps = find_swings(df, window=3)
    trades = []
    in_trade = False
    trade = None

    for i in range(50, len(df)):
        if i % 100 == 0:
            swaps = find_swings(df.iloc[:i+1], window=3)

        # Exit
        if in_trade and trade:
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

        # Entry
        if not in_trade and i % scan_interval == 0:
            c = df.iloc[i]
            atr = c['atr']
            if pd.isna(atr) or atr <= 0:
                continue

            long_sig, lc = check_long_alt(df, i, swaps, rsi_max=rsi_long, level_dist_atr=level_dist)
            if long_sig:
                trade = {
                    'direction': 'LONG',
                    'entry_idx': i,
                    'entry_price': c['close'],
                    'entry_ts': df.index[i],
                    'sl': c['close'] - atr * sl_atr,
                    'tp': c['close'] + atr * tp_atr,
                    'checks': lc,
                }
                in_trade = True
                continue

            short_sig, sc = check_short_alt(df, i, swaps, rsi_min=rsi_short, level_dist_atr=level_dist)
            if short_sig:
                trade = {
                    'direction': 'SHORT',
                    'entry_idx': i,
                    'entry_price': c['close'],
                    'entry_ts': df.index[i],
                    'sl': c['close'] + atr * sl_atr,
                    'tp': c['close'] - atr * tp_atr,
                    'checks': sc,
                }
                in_trade = True

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

def analyze_trades(trades, label=""):
    if not trades:
        return {'trades': 0, 'wr': 0, 'pnl': 0, 'avg_win': 0, 'avg_loss': 0, 'max_dd': 0, 'label': label}

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    tp_trades = [t for t in trades if t['exit_reason'] == 'TP']
    sl_trades = [t for t in trades if t['exit_reason'] == 'SL']

    total_pnl = sum(t['pnl_pct'] for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0

    cumulative = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cumulative += t['pnl_pct']
        peak = max(peak, cumulative)
        max_dd = min(max_dd, cumulative - peak)

    long_wr = len([t for t in longs if t['pnl_pct'] > 0]) / len(longs) * 100 if longs else 0
    short_wr = len([t for t in shorts if t['pnl_pct'] > 0]) / len(shorts) * 100 if shorts else 0

    result = {
        'trades': len(trades),
        'wr': wr,
        'pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_dd': max_dd,
        'long_wr': long_wr,
        'short_wr': short_wr,
        'tp': len(tp_trades),
        'sl': len(sl_trades),
        'label': label,
    }
    return result


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    SYMBOLS = ['ETHUSDT', 'SOLUSDT', 'NEARUSDT']
    
    # Configurations to test
    configs = [
        # (sl_atr, tp_atr, rsi_long, rsi_short, level_dist, label)
        (1.0, 2.0, 40, 60, 1.0, "TightSL 1:2"),
        (1.0, 1.5, 40, 60, 1.0, "TightSL 1:1.5"),
        (1.5, 3.0, 35, 65, 1.0, "MidSL 1:2"),
        (1.5, 2.0, 35, 65, 1.0, "MidSL 1:1.33"),
        (2.0, 3.0, 30, 70, 1.5, "WideSL 1:1.5"),
        (2.0, 4.0, 30, 70, 1.5, "WideSL 1:2"),
    ]

    print("=" * 80)
    print("  FORSCHER V7 — ALTCOIN SNIPER (ETH | SOL | NEAR)")
    print("=" * 80)
    print("Strategy: RSI Extreme + Key Level Bounce + Candle Confirmation")
    print("=" * 80)

    all_results = []

    for symbol in SYMBOLS:
        print(f"\n{'#'*80}")
        print(f"# {symbol}")
        print(f"{'#'*80}")

        print(f"Fetching {symbol} 4H data...")
        df = fetch_ohlcv(symbol, '4h', limit=1500)
        print(f"Data: {len(df)} candles ({df.index[0]} → {df.index[-1]})")

        df = compute_indicators(df)
        print(f"Price: ${df['close'].min():.2f} — ${df['close'].max():.2f}")
        print(f"Avg ATR: ${df['atr'].mean():.2f} ({df['atr'].mean()/df['close'].mean()*100:.1f}%)")

        for sl, tp, rsi_l, rsi_s, ld, label in configs:
            trades = run_backtest_alt(df, sl_atr=sl, tp_atr=tp,
                                       rsi_long=rsi_l, rsi_short=rsi_s,
                                       level_dist=ld, scan_interval=2)
            result = analyze_trades(trades, f"{symbol} {label}")
            result['symbol'] = symbol
            all_results.append(result)

    # ── Summary per symbol ──
    for symbol in SYMBOLS:
        sym_results = [r for r in all_results if r['symbol'] == symbol and r['trades'] > 0]
        if not sym_results:
            continue

        # Show top 3 by WR
        print(f"\n{'─'*80}")
        print(f"  {symbol} — TOP BY WIN RATE")
        print(f"{'─'*80}")
        print(f"{'Config':25s} {'Trades':>6s} {'WR':>6s} {'PnL':>8s} {'Avg W':>7s} {'Avg L':>7s} {'MaxDD':>7s} {'L/S WR':>10s}")
        print(f"{'-'*25} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*10}")
        for r in sorted(sym_results, key=lambda x: x['wr'], reverse=True)[:4]:
            print(f"{r['label']:25s} {r['trades']:6d} {r['wr']:5.1f}% {r['pnl']:+7.2f}% "
                  f"{r['avg_win']:+6.2f}% {r['avg_loss']:+6.2f}% {r['max_dd']:+6.2f}% "
                  f"{r['long_wr']:.0f}%/{r['short_wr']:.0f}%")

        # Top by PnL
        print(f"\n  {symbol} — TOP BY PNL")
        print(f"{'Config':25s} {'Trades':>6s} {'WR':>6s} {'PnL':>8s} {'Avg W':>7s} {'Avg L':>7s} {'MaxDD':>7s}")
        print(f"{'-'*25} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7}")
        for r in sorted(sym_results, key=lambda x: x['pnl'], reverse=True)[:4]:
            print(f"{r['label']:25s} {r['trades']:6d} {r['wr']:5.1f}% {r['pnl']:+7.2f}% "
                  f"{r['avg_win']:+6.2f}% {r['avg_loss']:+6.2f}% {r['max_dd']:+6.2f}%")

        # Show trade log for best config
        best = max(sym_results, key=lambda x: x['pnl'])
        if best['trades'] > 2:
            sl, tp, rsi_l, rsi_s, ld, _ = [(s,t,rl,rs,l,la) for s,t,rl,rs,l,la in configs 
                                             if f"{symbol} {la}" == best['label']][0]
            trades = run_backtest_alt(df, sl_atr=sl, tp_atr=tp,
                                       rsi_long=rsi_l, rsi_short=rsi_s,
                                       level_dist=ld, scan_interval=2)
            print(f"\n  {symbol} BEST TRADE LOG ({best['label']}):")
            for i, t in enumerate(trades, 1):
                color = "🟢" if t['pnl_pct'] > 0 else "🔴"
                print(f"  {color} #{i:2d} {t['direction']:5s} | {t['entry_price']:8.2f} → {t['exit_price']:8.2f} | "
                      f"{t['exit_reason']:3s} | {t['pnl_pct']:+6.2f}% | {t['entry_ts']}")

    # ── Grand Summary ──
    print(f"\n{'='*80}")
    print(f"  GRAND SUMMARY — All Altcoins, All Configs (sorted by WR)")
    print(f"{'='*80}")
    print(f"{'Symbol/Config':30s} {'Trades':>6s} {'WR':>6s} {'PnL':>8s} {'Avg W':>7s} {'Avg L':>7s} {'MaxDD':>7s}")
    print(f"{'-'*30} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7}")
    for r in sorted([r for r in all_results if r['trades'] > 0], key=lambda x: x['wr'], reverse=True):
        label = f"{r['symbol']} {r['label']}"
        print(f"{label:30s} {r['trades']:6d} {r['wr']:5.1f}% {r['pnl']:+7.2f}% "
              f"{r['avg_win']:+6.2f}% {r['avg_loss']:+6.2f}% {r['max_dd']:+6.2f}%")

    print(f"\n{'='*80}")
    print("BACKTEST COMPLETE")
    print(f"{'='*80}")
