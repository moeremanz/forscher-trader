#!/usr/bin/env python3
"""
Forscher v6 — SNIPER STRATEGY
==============================
Target: 75%+ Win Rate, consistent profit.
Approach: NOT pillar scoring. HARD FILTERS — all must pass or no entry.

Strategy: "Level Reversal with Triple Confirmation"
  1. Price at key support/resistance zone (swing level tested 2+ times)
  2. RSI extreme (oversold for long, overbought for short)
  3. Reversal candle (engulfing, hammer, shooting star)
  4. Volume confirmation (above average)

R:R: 1:2 to 2:1 (tested across multiple ratios)
No regime filter, no Elliott, no Gann, no ICT.
Pure price action + RSI + volume at key levels.
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
    df['ema20'] = close.ewm(span=20, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()
    df['ema200'] = close.ewm(span=200, adjust=False).mean()

    # Volume MA
    df['vol_ma20'] = df['volume'].rolling(20).mean()

    # Bollinger Bands (20,2)
    df['bb_mid'] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std

    # Candle features
    df['body'] = (close - df['open']).abs()
    df['total_range'] = high - low
    df['upper_wick'] = high - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - low

    # Candle type
    df['is_bullish'] = close > df['open']
    df['is_bearish'] = close < df['open']

    return df


# ═══════════════════════════════════════════════
# KEY LEVEL DETECTION
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


def build_zones(df, swings, tolerance_pct=1.5):
    """
    Group nearby swing levels into zones.
    A zone is stronger when multiple swings cluster at the same price area.
    Returns: list of {'price': float, 'type': 'support'/'resistance', 'touches': int}
    """
    if not swings:
        return []

    # Cluster swings by proximity
    clusters = []
    used = set()

    for i, (idx, stype, price) in enumerate(swings):
        if i in used:
            continue
        cluster = [swings[i]]
        used.add(i)
        for j, (idx2, stype2, price2) in enumerate(swings):
            if j in used or stype != stype2:
                continue
            if abs(price - price2) / price < tolerance_pct / 100:
                cluster.append(swings[j])
                used.add(j)

        avg_price = np.mean([c[2] for c in cluster])
        clusters.append({
            'price': avg_price,
            'type': 'resistance' if stype == 'high' else 'support',
            'touches': len(cluster),
            'first_idx': min(c[0] for c in cluster),
            'last_idx': max(c[0] for c in cluster),
        })

    # Sort by touches (strongest first), then by recency
    clusters.sort(key=lambda z: (z['touches'], z['last_idx']), reverse=True)

    return clusters


def get_nearby_zone(price, zones, direction, atr, max_dist_atr=1.0):
    """
    Check if price is near a key zone.
    For LONG: need nearby support zone.
    For SHORT: need nearby resistance zone.
    Returns the zone or None.
    """
    target_type = 'support' if direction == 'long' else 'resistance'
    max_dist = atr * max_dist_atr

    candidates = [z for z in zones if z['type'] == target_type]
    if not candidates:
        return None

    # Find closest zone
    closest = min(candidates, key=lambda z: abs(price - z['price']))

    if abs(price - closest['price']) <= max_dist:
        return closest

    return None


# ═══════════════════════════════════════════════
# CANDLE PATTERN DETECTION
# ═══════════════════════════════════════════════

def is_bullish_reversal(df, i):
    """
    Check for bullish reversal candle patterns:
    - Bullish engulfing
    - Hammer / Pin bar (long lower wick)
    - Morning star (simplified)
    Returns True/False
    """
    if i < 2:
        return False

    c = df.iloc[i]
    p = df.iloc[i - 1]
    pp = df.iloc[i - 2] if i >= 2 else None

    body = c['body']
    total_range = c['total_range']
    lower_wick = c['lower_wick']

    if total_range <= 0:
        return False

    # Hammer: small body, long lower wick (>= 2x body), small upper wick
    if body > 0 and lower_wick >= body * 2.0 and lower_wick > total_range * 0.5:
        if c['upper_wick'] < lower_wick * 0.5:
            # Hammer at the bottom of a move (price near recent low)
            return True

    # Bullish engulfing: current bullish candle engulfs previous bearish candle
    if c['is_bullish'] and p['is_bearish']:
        if c['open'] <= p['close'] and c['close'] >= p['open']:
            return True

    # Piercing pattern: bullish candle opens below prev low, closes above prev mid
    if c['is_bullish'] and p['is_bearish']:
        if c['open'] < p['low'] and c['close'] > (p['open'] + p['close']) / 2:
            return True

    return False


def is_bearish_reversal(df, i):
    """
    Check for bearish reversal candle patterns:
    - Bearish engulfing
    - Shooting star (long upper wick)
    Returns True/False
    """
    if i < 2:
        return False

    c = df.iloc[i]
    p = df.iloc[i - 1]

    body = c['body']
    total_range = c['total_range']
    upper_wick = c['upper_wick']

    if total_range <= 0:
        return False

    # Shooting star: small body, long upper wick, small lower wick
    if body > 0 and upper_wick >= body * 2.0 and upper_wick > total_range * 0.5:
        if c['lower_wick'] < upper_wick * 0.5:
            return True

    # Bearish engulfing
    if c['is_bearish'] and p['is_bullish']:
        if c['open'] >= p['close'] and c['close'] <= p['open']:
            return True

    # Dark cloud cover
    if c['is_bearish'] and p['is_bullish']:
        if c['open'] > p['high'] and c['close'] < (p['open'] + p['close']) / 2:
            return True

    return False


# ═══════════════════════════════════════════════
# ENTRY SIGNAL — ALL FILTERS MUST PASS
# ═══════════════════════════════════════════════

def check_long_signal(df, i, zones):
    """
    Check ALL conditions for LONG entry.
    Returns (True/False, dict with debug info)
    """
    if i < 50:
        return False, {}

    c = df.iloc[i]
    atr = c['atr']
    if pd.isna(atr) or atr <= 0:
        return False, {}

    checks = {}

    # FILTER 1: Zone — price near support
    zone = get_nearby_zone(c['close'], zones, 'long', atr, max_dist_atr=0.8)
    checks['zone'] = zone is not None
    if not checks['zone']:
        return False, checks

    # FILTER 2: RSI — oversold or recovering from oversold
    rsi = c['rsi']
    rsi_prev = df.iloc[i - 1]['rsi'] if i >= 1 else 50
    checks['rsi'] = rsi < 40 or (rsi < 50 and rsi > rsi_prev and rsi_prev < 35)
    if not checks['rsi']:
        return False, checks

    # FILTER 3: Candle — reversal pattern
    checks['candle'] = is_bullish_reversal(df, i)
    if not checks['candle']:
        return False, checks

    # FILTER 4: Volume — above average (shows conviction)
    vol_ratio = c['volume'] / c['vol_ma20'] if c['vol_ma20'] > 0 else 0
    checks['volume'] = vol_ratio > 0.8  # At least normal volume
    if not checks['volume']:
        return False, checks

    # FILTER 5: Zone strength — prefer tested levels (2+ touches)
    checks['zone_strength'] = zone['touches'] >= 2
    if not checks['zone_strength']:
        return False, checks

    # BONUS: Bollinger Band confluence
    checks['bb'] = c['close'] <= c['bb_lower'] * 1.02  # At or below lower BB
    # Not a hard filter, but recorded

    return True, checks


def check_short_signal(df, i, zones):
    """
    Check ALL conditions for SHORT entry.
    """
    if i < 50:
        return False, {}

    c = df.iloc[i]
    atr = c['atr']
    if pd.isna(atr) or atr <= 0:
        return False, {}

    checks = {}

    # FILTER 1: Zone — price near resistance
    zone = get_nearby_zone(c['close'], zones, 'short', atr, max_dist_atr=0.8)
    checks['zone'] = zone is not None
    if not checks['zone']:
        return False, checks

    # FILTER 2: RSI — overbought or rolling over
    rsi = c['rsi']
    rsi_prev = df.iloc[i - 1]['rsi'] if i >= 1 else 50
    checks['rsi'] = rsi > 60 or (rsi > 50 and rsi < rsi_prev and rsi_prev > 65)
    if not checks['rsi']:
        return False, checks

    # FILTER 3: Candle — reversal pattern
    checks['candle'] = is_bearish_reversal(df, i)
    if not checks['candle']:
        return False, checks

    # FILTER 4: Volume — above average
    vol_ratio = c['volume'] / c['vol_ma20'] if c['vol_ma20'] > 0 else 0
    checks['volume'] = vol_ratio > 0.8
    if not checks['volume']:
        return False, checks

    # FILTER 5: Zone strength
    checks['zone_strength'] = zone['touches'] >= 2
    if not checks['zone_strength']:
        return False, checks

    # BONUS: Bollinger Band confluence
    checks['bb'] = c['close'] >= c['bb_upper'] * 0.98  # At or above upper BB
    # Not a hard filter

    return True, checks


# ═══════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════

def run_backtest_v6(df, sl_atr=1.5, tp_atr=3.0, scan_interval=2):
    """
    Run the sniper strategy.
    sl_atr: stop loss in ATR multiples
    tp_atr: take profit in ATR multiples
    """
    swings = find_swings(df, window=3)
    zones = build_zones(df, swings, tolerance_pct=1.5)

    print(f"Zones detected: {len(zones)} "
          f"(support: {len([z for z in zones if z['type']=='support'])}, "
          f"resistance: {len([z for z in zones if z['type']=='resistance'])})")
    print(f"Strong zones (2+ touches): {len([z for z in zones if z['touches'] >= 2])}")

    trades = []
    in_trade = False
    trade = None

    for i in range(50, len(df)):
        # Update zones periodically (every 50 candles)
        if i % 50 == 0:
            zones = build_zones(df.iloc[:i+1], find_swings(df.iloc[:i+1], window=3), tolerance_pct=1.5)

        # --- Exit checks ---
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

        # --- Entry checks ---
        if not in_trade and i % scan_interval == 0:
            c = df.iloc[i]
            atr = c['atr']
            if pd.isna(atr) or atr <= 0:
                continue

            # Check LONG
            long_signal, long_checks = check_long_signal(df, i, zones)
            if long_signal:
                entry = c['close']
                trade = {
                    'direction': 'LONG',
                    'entry_idx': i,
                    'entry_price': entry,
                    'entry_ts': df.index[i],
                    'sl': entry - atr * sl_atr,
                    'tp': entry + atr * tp_atr,
                    'checks': long_checks,
                }
                in_trade = True
                continue

            # Check SHORT
            short_signal, short_checks = check_short_signal(df, i, zones)
            if short_signal:
                entry = c['close']
                trade = {
                    'direction': 'SHORT',
                    'entry_idx': i,
                    'entry_price': entry,
                    'entry_ts': df.index[i],
                    'sl': entry + atr * sl_atr,
                    'tp': entry - atr * tp_atr,
                    'checks': short_checks,
                }
                in_trade = True

    # Close open trade at end
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

def analyze_trades_v6(trades, label=""):
    if not trades:
        print(f"\n{label}: NO TRADES")
        return None

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
    max_dd = 0
    cumulative = 0
    for t in trades:
        cumulative += t['pnl_pct']
        max_dd = min(max_dd, cumulative)

    long_wr = len([t for t in longs if t['pnl_pct'] > 0]) / len(longs) * 100 if longs else 0
    short_wr = len([t for t in shorts if t['pnl_pct'] > 0]) / len(shorts) * 100 if shorts else 0

    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")
    print(f"Trades: {len(trades)} ({len(longs)}L/{len(shorts)}S) | WR: {wr:.1f}%")
    print(f"Avg Win: {avg_win:+.2f}% | Avg Loss: {avg_loss:+.2f}%")
    print(f"Net PnL: {total_pnl:+.2f}% | Max DD: {max_dd:+.2f}%")
    print(f"LONG WR: {long_wr:.0f}% | SHORT WR: {short_wr:.0f}%")
    print(f"TP: {len(tp_trades)} | SL: {len(sl_trades)}")

    # Filter pass rate analysis
    if trades:
        zone_pass = sum(1 for t in trades if t.get('checks', {}).get('zone', False)) / len(trades) * 100
        rsi_pass = sum(1 for t in trades if t.get('checks', {}).get('rsi', False)) / len(trades) * 100
        candle_pass = sum(1 for t in trades if t.get('checks', {}).get('candle', False)) / len(trades) * 100
        vol_pass = sum(1 for t in trades if t.get('checks', {}).get('volume', False)) / len(trades) * 100
        print(f"Filter pass: Zone={zone_pass:.0f}% RSI={rsi_pass:.0f}% Candle={candle_pass:.0f}% Vol={vol_pass:.0f}%")

    return {
        'trades': len(trades),
        'wr': wr,
        'pnl': total_pnl,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'max_dd': max_dd,
    }


def print_trade_log(trades):
    if not trades:
        return
    print(f"\n{'─'*80}")
    print(f"  TRADE LOG")
    print(f"{'─'*80}")
    for i, t in enumerate(trades, 1):
        color = "🟢" if t['pnl_pct'] > 0 else "🔴"
        checks = t.get('checks', {})
        filters = ""
        for key in ['zone', 'rsi', 'candle', 'volume']:
            if checks.get(key):
                filters += key[0].upper()
            else:
                filters += "-"
        print(f"{color} #{i:2d} {t['direction']:5s} | {t['entry_price']:8.2f} → {t['exit_price']:8.2f} | "
              f"{t['exit_reason']:3s} | {t['pnl_pct']:+6.2f}% | [{filters}] | {t['entry_ts']}")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 65)
    print("  FORSCHER V6 — SNIPER STRATEGY (Level Reversal)")
    print("=" * 65)
    print("\nFilters: Support/Resistance Zone + RSI Extreme + Reversal Candle + Volume")
    print("-" * 65)

    print("\nFetching BTCUSDT 4H data (Dec 2025 — now)...")
    df = fetch_ohlcv('BTCUSDT', '4h', limit=1500)
    print(f"Data: {len(df)} candles ({df.index[0]} → {df.index[-1]})")

    print("Computing indicators...")
    df = compute_indicators(df)
    print(f"Price: ${df['close'].min():.0f} — ${df['close'].max():.0f}")
    print(f"Avg ATR(14): ${df['atr'].mean():.0f} ({df['atr'].mean()/df['close'].mean()*100:.1f}%)")

    # Test multiple R:R ratios
    # Format: (sl_atr, tp_atr, label)
    configs = [
        (1.0, 1.5, "1:1.5  (tight SL)"),
        (1.0, 2.0, "1:2.0  (tight SL)"),
        (1.5, 1.5, "1:1    (balanced)"),
        (1.5, 2.0, "1:1.33 (balanced)"),
        (1.5, 3.0, "1:2    (wide TP)"),
        (2.0, 2.0, "1:1    (wide SL)"),
        (2.0, 3.0, "1:1.5  (wide SL)"),
        (2.0, 4.0, "1:2    (wide SL)"),
    ]

    all_results = []

    for sl, tp, label in configs:
        print(f"\n{'#'*65}")
        print(f"# SL={sl}xATR  TP={tp}xATR  ({label})")
        print(f"{'#'*65}")

        trades = run_backtest_v6(df, sl_atr=sl, tp_atr=tp, scan_interval=2)
        result = analyze_trades_v6(trades, f"SL={sl}xATR TP={tp}xATR")
        if result:
            result['config'] = label
            result['sl'] = sl
            result['tp'] = tp
            all_results.append(result)

        # Print detailed log only for best performers
        if result and result['wr'] >= 60:
            print_trade_log(trades)

    # Summary
    print(f"\n{'='*65}")
    print(f"  SUMMARY — All Configurations")
    print(f"{'='*65}")
    print(f"{'Config':25s} {'Trades':>6s} {'WR':>6s} {'PnL':>8s} {'Avg W':>7s} {'Avg L':>7s} {'MaxDD':>7s}")
    print(f"{'-'*25} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7}")
    for r in sorted(all_results, key=lambda x: x['pnl'], reverse=True):
        print(f"{r['config']:25s} {r['trades']:6d} {r['wr']:5.1f}% {r['pnl']:+7.2f}% "
              f"{r['avg_win']:+6.2f}% {r['avg_loss']:+6.2f}% {r['max_dd']:+6.2f}%")

    print(f"\n{'='*65}")
    print("BACKTEST COMPLETE")
    print(f"{'='*65}")
