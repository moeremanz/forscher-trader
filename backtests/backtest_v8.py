#!/usr/bin/env python3
"""
Forscher v8 — MULTI-ALTCOIN 15M SCALPER
=======================================
Target: WR ≥57%, daily trader with scalping tendency.
Strategy: RSI Extreme + Key Level + Volume Surge + Candle Confirmation
Timeframe: 15m | Period: Dec 2025 – May 2026 | SL/TP: tight (scalper)
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
    'BTC/USDT',   # baseline
    'ETH/USDT',
    'SOL/USDT',
    'NEAR/USDT',
    'DOGE/USDT',
    'ONDO/USDT',
    'LINK/USDT',
    'AVAX/USDT',
    'MATIC/USDT',
    'ARB/USDT',
    'OP/USDT',
    'INJ/USDT',
    'TIA/USDT',
    'SUI/USDT',
]

TIMEFRAME = '15m'
SINCE = '2025-12-01T00:00:00Z'
UNTIL = '2026-05-25T00:00:00Z'
RISK_PER_TRADE = 0.02  # 2% risk per trade

# SL/TP configurations to test (as % of entry price)
SLTP_CONFIGS = [
    # (label, sl_pct, tp_pct, description)
    ('Tight 1:1.5',   0.008, 0.012, 'SL 0.8% / TP 1.2%'),
    ('Tight 1:2',     0.008, 0.016, 'SL 0.8% / TP 1.6%'),
    ('Mid 1:1.5',     0.012, 0.018, 'SL 1.2% / TP 1.8%'),
    ('Mid 1:2',       0.012, 0.024, 'SL 1.2% / TP 2.4%'),
    ('Wide 1:1.5',    0.015, 0.0225, 'SL 1.5% / TP 2.25%'),
    ('Wide 1:2',      0.015, 0.030, 'SL 1.5% / TP 3.0%'),
]

# Entry parameters
RSI_PERIOD = 7
RSI_LONG_MAX = 35
RSI_SHORT_MIN = 65
SWING_LOOKBACK = 20
LEVEL_PROXIMITY_PCT = 0.01  # 1% from level
VOLUME_PERIOD = 20
VOLUME_THRESHOLD = 1.2  # 1.2x average
TREND_EMA_FAST = 20
TREND_EMA_SLOW = 50

# ═══════════════════════════════════════════════
# DATA FETCH
# ═══════════════════════════════════════════════
def fetch_ohlcv(symbol):
    """Fetch 15m candles from Binance"""
    exchange = ccxt.binance({'enableRateLimit': True})
    all_candles = []
    since_ms = exchange.parse8601(SINCE)
    until_ms = exchange.parse8601(UNTIL)

    while since_ms < until_ms:
        try:
            candles = exchange.fetch_ohlcv(symbol, TIMEFRAME, since_ms, 1000)
            if not candles:
                break
            all_candles.extend(candles)
            since_ms = candles[-1][0] + 1
        except Exception as e:
            print(f"  ⚠️  {symbol} fetch error: {e}")
            break

    df = pd.DataFrame(all_candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df.set_index('ts', inplace=True)
    df.drop_duplicates(inplace=True)
    return df


def add_indicators(df):
    """Add all technical indicators"""
    df = df.copy()

    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(RSI_PERIOD).mean()
    avg_loss = loss.rolling(RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    # Swing highs/lows
    df['swing_high'] = df['high'].rolling(SWING_LOOKBACK).max()
    df['swing_low'] = df['low'].rolling(SWING_LOOKBACK).min()

    # Volume average
    df['vol_avg'] = df['volume'].rolling(VOLUME_PERIOD).mean()
    df['vol_ratio'] = df['volume'] / df['vol_avg']

    # EMAs for trend
    df['ema_fast'] = df['close'].ewm(span=TREND_EMA_FAST).mean()
    df['ema_slow'] = df['close'].ewm(span=TREND_EMA_SLOW).mean()
    df['trend_bull'] = df['ema_fast'] > df['ema_slow']
    df['trend_bear'] = df['ema_fast'] < df['ema_slow']

    # Candle characteristics
    df['body'] = df['close'] - df['open']
    df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
    df['candle_range'] = df['high'] - df['low']

    # Candle patterns
    df['is_bullish'] = df['close'] > df['open']
    df['is_bearish'] = df['close'] < df['open']
    df['is_hammer'] = (df['lower_wick'] > 2 * df['body'].abs()) & (df['body'].abs() > 0)
    df['is_shooting_star'] = (df['upper_wick'] > 2 * df['body'].abs()) & (df['body'].abs() > 0)

    # Distance to swing levels (as %)
    df['dist_to_swing_high'] = (df['swing_high'] - df['close']) / df['close']
    df['dist_to_swing_low'] = (df['close'] - df['swing_low']) / df['close']

    # Support/resistance strength (proxy: how many touches)
    # Simplified: just use swing high/low proximity

    return df.dropna()


def detect_entries(df, use_trend_filter=True):
    """Detect LONG and SHORT entry signals"""
    signals = []

    for i in range(len(df)):
        row = df.iloc[i]

        # ── LONG SIGNAL ──
        long_conditions = [
            row['rsi'] < RSI_LONG_MAX,                          # RSI oversold
            row['dist_to_swing_low'] < LEVEL_PROXIMITY_PCT,      # Near swing low
            row['vol_ratio'] > VOLUME_THRESHOLD,                 # Volume surge
            row['is_bullish'] or row['is_hammer'],               # Bullish candle
        ]

        if use_trend_filter:
            long_conditions.append(row['trend_bull'])

        if all(long_conditions):
            signals.append({
                'idx': i,
                'side': 'LONG',
                'entry': row['close'],
                'swing_level': row['swing_low'],
                'rsi': row['rsi'],
                'vol_ratio': row['vol_ratio'],
                'timestamp': df.index[i],
            })

        # ── SHORT SIGNAL ──
        short_conditions = [
            row['rsi'] > RSI_SHORT_MIN,                         # RSI overbought
            row['dist_to_swing_high'] < LEVEL_PROXIMITY_PCT,     # Near swing high
            row['vol_ratio'] > VOLUME_THRESHOLD,                 # Volume surge
            row['is_bearish'] or row['is_shooting_star'],        # Bearish candle
        ]

        if use_trend_filter:
            short_conditions.append(row['trend_bear'])

        if all(short_conditions):
            signals.append({
                'idx': i,
                'side': 'SHORT',
                'entry': row['close'],
                'swing_level': row['swing_high'],
                'rsi': row['rsi'],
                'vol_ratio': row['vol_ratio'],
                'timestamp': df.index[i],
            })

    return signals


def simulate_trades(df, signals, sl_pct, tp_pct):
    """Forward-simulate trades using future candles after signal"""
    trades = []
    signal_idx = 0
    active_signals = []  # (signal, entry_idx, sl_price, tp_price)

    for i in range(len(df)):
        row = df.iloc[i]

        # Add new signals that trigger on this candle
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

        # Check active trades — exit on next candle
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
            else:  # SHORT
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
                'exit_time': df.index[i],
                'entry_price': sig['entry'],
                'exit_price': exit_price,
                'exit_type': exit_type,
                'pnl_pct': pnl_pct,
                'entry_rsi': sig['rsi'],
                'entry_vol_ratio': sig['vol_ratio'],
            })

        active_signals = remaining

    return trades


def analyze_trades(trades, config_label):
    """Compute stats for a set of trades"""
    if not trades:
        return {
            'trades': 0, 'wins': 0, 'losses': 0, 'wr': 0,
            'pnl_total': 0, 'avg_win': 0, 'avg_loss': 0,
            'expectancy': 0, 'max_dd': 0, 'long_trades': 0,
            'long_wr': 0, 'short_trades': 0, 'short_wr': 0,
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


def backtest_symbol(symbol, use_trend_filter=True):
    """Full backtest pipeline for one symbol"""
    print(f"\n{'='*60}")
    print(f"  {symbol} @ 15m")
    print(f"{'='*60}")

    df = fetch_ohlcv(symbol)
    if df.empty:
        print(f"  ❌ No data")
        return {}

    df = add_indicators(df)
    print(f"  📊 Candles: {len(df)}")

    signals = detect_entries(df, use_trend_filter)
    print(f"  🔍 Signals: {len(signals)} ({sum(1 for s in signals if s['side']=='LONG')}L / {sum(1 for s in signals if s['side']=='SHORT')}S)")

    results = {}
    for label, sl_pct, tp_pct, desc in SLTP_CONFIGS:
        trades = simulate_trades(df, signals, sl_pct, tp_pct)
        stats = analyze_trades(trades, label)
        stats['label'] = label
        stats['desc'] = desc
        stats['sl_pct'] = sl_pct
        stats['tp_pct'] = tp_pct
        results[label] = stats

    return results


def print_symbol_results(symbol, results):
    """Print per-symbol results table"""
    if not results:
        return

    print(f"\n  {'Config':<16} {'Trades':>6} {'WR':>6} {'PnL':>8} {'AvgW':>7} {'AvgL':>7} {'Exp':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>6} {'Desc'}")
    print(f"  {'-'*16} {'-'*6} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*6} {'-'*20}")

    for label, s in results.items():
        print(f"  {label:<16} {s['trades']:>6} {s['wr']:>5.1f}% {s['pnl_total']:>7.2f}% "
              f"{s['avg_win']:>6.2f}% {s['avg_loss']:>6.2f}% {s['expectancy']:>6.2f}% "
              f"{s['max_dd']:>6.2f}% {s['long_trades']:>4} {s['long_wr']:>5.1f}% "
              f"{s['short_trades']:>4} {s['short_wr']:>5.1f}% {s['desc']:<20}")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    print("=" * 80)
    print("  FORSCHER V8 — MULTI-ALTCOIN 15M SCALPER")
    print("  Target WR: ≥57% | Period: Dec 2025 – May 2026")
    print("=" * 80)

    all_results = {}  # symbol -> {config_label -> stats}
    all_trades = []   # (symbol, config_label, trade)

    for symbol in SYMBOLS:
        results = backtest_symbol(symbol, use_trend_filter=True)
        all_results[symbol] = results
        print_symbol_results(symbol, results)

    # ═══════════════════════════════════════════
    # CROSS-PAIR GRAND SUMMARY
    # ═══════════════════════════════════════════
    print("\n\n" + "=" * 80)
    print("  GRAND SUMMARY — All Pairs, All Configs (sorted by WR)")
    print("=" * 80)

    all_rows = []
    for symbol, results in all_results.items():
        for label, s in results.items():
            all_rows.append((symbol, label, s))

    # Sort by WR descending
    all_rows.sort(key=lambda x: x[2]['wr'], reverse=True)

    print(f"\n  {'Symbol/Config':<36} {'Trades':>6} {'WR':>7} {'PnL':>9} {'AvgW':>7} {'AvgL':>7} {'MaxDD':>7} {'L':>4} {'L_WR':>6} {'S':>4} {'S_WR':>6}")
    print(f"  {'-'*36} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7} {'-'*4} {'-'*6} {'-'*4} {'-'*6}")

    for symbol, label, s in all_rows:
        print(f"  {symbol} {label:<20} {s['trades']:>6} {s['wr']:>6.1f}% {s['pnl_total']:>8.2f}% "
              f"{s['avg_win']:>6.2f}% {s['avg_loss']:>6.2f}% {s['max_dd']:>6.2f}% "
              f"{s['long_trades']:>4} {s['long_wr']:>5.1f}% {s['short_trades']:>4} {s['short_wr']:>5.1f}%")

    # ═══════════════════════════════════════════
    # AGGREGATE BY CONFIG
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  AGGREGATE BY CONFIG (all pairs combined)")
    print(f"{'='*80}")

    for label, sl_pct, tp_pct, desc in SLTP_CONFIGS:
        combined_trades = []
        for symbol in SYMBOLS:
            if symbol in all_results and label in all_results[symbol]:
                s = all_results[symbol][label]
                # We don't have individual trades stored separately, but we can aggregate stats
                combined_trades.append(s)

        if not combined_trades:
            continue

        total_trades = sum(s['trades'] for s in combined_trades)
        total_wins = sum(s['wins'] for s in combined_trades)
        total_losses = sum(s['losses'] for s in combined_trades)
        wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
        total_pnl = sum(s['pnl_total'] for s in combined_trades)

        # Weighted averages
        total_long_trades = sum(s['long_trades'] for s in combined_trades)
        total_short_trades = sum(s['short_trades'] for s in combined_trades)

        # Count pairs with trades
        pairs_with_trades = sum(1 for s in combined_trades if s['trades'] > 0)

        print(f"\n  {label} ({desc})")
        print(f"    Total Trades: {total_trades} | WR: {wr:.1f}% | PnL: {total_pnl:+.2f}%")
        print(f"    Pairs active: {pairs_with_trades}/{len(SYMBOLS)} | LONG: {total_long_trades} | SHORT: {total_short_trades}")

    # ═══════════════════════════════════════════
    # BEST OVERALL CONFIG
    # ═══════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  🏆 TOP CONFIGS (WR ≥ 50%, sorted by PnL)")
    print(f"{'='*80}")

    top = [(sym, lbl, s) for sym, lbl, s in all_rows if s['wr'] >= 50 and s['trades'] >= 5]
    top.sort(key=lambda x: x[2]['pnl_total'], reverse=True)

    if top:
        for sym, lbl, s in top[:15]:
            print(f"  {sym} {lbl:<20} WR: {s['wr']:.1f}% | PnL: {s['pnl_total']:+.2f}% | "
                  f"Trades: {s['trades']} | MaxDD: {s['max_dd']:.2f}%")
    else:
        print("  ❌ No config meets WR≥50% with ≥5 trades")

    print(f"\n{'='*80}")
    print("  BACKTEST COMPLETE")
    print(f"{'='*80}")
