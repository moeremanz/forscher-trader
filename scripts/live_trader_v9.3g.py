#!/usr/bin/env python3
"""
Forscher V9.3g — LIVE TRADER
============================
Live execution on Binance Futures Testnet.
Strategy: Multi-TF fusion — 4H structure → 1H confirmation → 15m execution
Pairs: ETH/USDT, AVAX/USDT, FET/USDT
Config: Wide25 1:2 (SL 2.5%, TP 5.0%)
Direction lock: BOTH (ETH, FET), SHORT-only (AVAX)

Usage:
    python3 scripts/live_trader_v9.3g.py           # one-shot: check + act
    python3 scripts/live_trader_v9.3g.py --watch   # continuous 15m loop
    python3 scripts/live_trader_v9.3g.py --status  # positions only
    python3 scripts/live_trader_v9.3g.py --close-all  # emergency close
"""

import os
import sys
import time
import hmac
import hashlib
import requests
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from dotenv import load_dotenv

# ── Load .env ──
load_dotenv(Path(__file__).parent.parent / '.env')

API_KEY    = os.getenv('BINANCE_TESTNET_API_KEY')
SECRET_KEY = os.getenv('BINANCE_TESTNET_SECRET_KEY')
BASE_URL   = 'https://testnet.binancefuture.com'

if not API_KEY or not SECRET_KEY:
    print("❌ Missing API credentials in .env")
    sys.exit(1)

# ═══════════════════════════════════════════════
# CONFIG — V9.3g FINAL
# ═══════════════════════════════════════════════
SYMBOLS = ['ETH/USDT', 'AVAX/USDT', 'FET/USDT']
DIRECTION_LOCK = {'ETH/USDT': 'BOTH', 'AVAX/USDT': 'SHORT', 'FET/USDT': 'BOTH'}

SL_PCT = 0.025   # 2.5%
TP_PCT = 0.050   # 5.0%
POSITION_SIZE_USDT = 100  # $100 per trade
LEVERAGE = 5

# ── 4H STRUCTURE ──
ZONE_TOUCH_MIN = 3
ZONE_BAND_PCT = 0.015

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

# ── 4H trend ──
TREND_EMA_FAST_4H = 20
TREND_EMA_SLOW_4H = 50

# ═══════════════════════════════════════════════
# BINANCE REST HELPERS (direct HTTP, bypass ccxt for private endpoints)
# ═══════════════════════════════════════════════
def binance_sign(params):
    """Add timestamp and signature to params dict."""
    params['timestamp'] = int(time.time() * 1000)
    params['recvWindow'] = 10000
    query = urlencode(params)
    signature = hmac.new(SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + '&signature=' + signature

def binance_get(endpoint, params=None):
    """Signed GET request to Binance testnet."""
    url = BASE_URL + endpoint + '?' + binance_sign(params or {})
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"  ⚠️  {endpoint} → {r.status_code}: {r.text[:150]}")
        return None
    return r.json()

def binance_post(endpoint, params=None):
    """Signed POST request to Binance testnet."""
    headers = {'X-MBX-APIKEY': API_KEY}
    query = binance_sign(params or {})
    r = requests.post(BASE_URL + endpoint + '?' + query, headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"  ⚠️  {endpoint} → {r.status_code}: {r.text[:200]}")
        return None
    return r.json()

def binance_delete(endpoint, params=None):
    """Signed DELETE request to Binance testnet."""
    headers = {'X-MBX-APIKEY': API_KEY}
    query = binance_sign(params or {})
    r = requests.delete(BASE_URL + endpoint + '?' + query, headers=headers, timeout=10)
    return r.json() if r.status_code == 200 else None

# ═══════════════════════════════════════════════
# ACCOUNT / POSITION / ORDER
# ═══════════════════════════════════════════════
def get_account():
    """Get account info with positions."""
    return binance_get('/fapi/v2/account')

def get_positions():
    """Get current open positions."""
    acct = get_account()
    if not acct:
        return []
    return [p for p in acct.get('positions', []) if float(p['positionAmt']) != 0]

def get_open_orders(symbol=None):
    """Get open orders, optionally filtered by symbol."""
    params = {}
    if symbol:
        params['symbol'] = symbol.replace('/', '')
    return binance_get('/fapi/v1/openOrders', params) or []

def cancel_all_orders(symbol):
    """Cancel all open orders for symbol."""
    sym = symbol.replace('/', '')
    result = binance_delete('/fapi/v1/allOpenOrders', {'symbol': sym})
    if result:
        print(f"  🗑️  Cancelled all orders for {symbol}")
    return result

def set_leverage(symbol, leverage):
    """Set leverage for symbol."""
    sym = symbol.replace('/', '')
    return binance_post('/fapi/v1/leverage', {'symbol': sym, 'leverage': leverage})

def get_symbol_precision(symbol):
    """Get price and quantity precision from exchange info."""
    sym = symbol.replace('/', '')
    params = {}
    url = BASE_URL + '/fapi/v1/exchangeInfo?' + binance_sign(params)
    headers = {'X-MBX-APIKEY': API_KEY}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code != 200:
        return 2, 3
    data = r.json()
    for s in data.get('symbols', []):
        if s['symbol'] == sym:
            price_tick = float([f for f in s['filters'] if f['filterType'] == 'PRICE_FILTER'][0]['tickSize'])
            qty_step = float([f for f in s['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
            price_dec = len(str(price_tick).rstrip('0').split('.')[-1]) if '.' in str(price_tick) else 0
            qty_dec = len(str(qty_step).rstrip('0').split('.')[-1]) if '.' in str(qty_step) else 0
            return max(price_dec, 1), qty_dec
    return 2, 3

def place_order(symbol, side, order_type, quantity, price=None, stop_price=None,
                reduce_only=False, raw_side=False):
    """Place an order on Binance testnet.

    side: when raw_side=False, 'LONG'→BUY, 'SHORT'→SELL
          when raw_side=True,  passed directly as Binance side (buy/sell)
    """
    sym = symbol.replace('/', '')
    if raw_side:
        binance_side = side.upper()
    else:
        binance_side = 'BUY' if side.upper() == 'LONG' else 'SELL'
    params = {
        'symbol': sym,
        'side': binance_side,
        'type': order_type.upper(),
        'quantity': quantity,
    }
    if price:
        params['price'] = price
    if stop_price:
        params['stopPrice'] = stop_price
    if reduce_only:
        params['reduceOnly'] = 'true'

    result = binance_post('/fapi/v1/order', params)
    return result

# ═══════════════════════════════════════════════
# OHLCV DATA (via ccxt — public endpoints work)
# ═══════════════════════════════════════════════
def get_ccxt_exchange():
    ex = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
    })
    ex.set_sandbox_mode(True)
    return ex

def fetch_ohlcv(exchange, symbol, timeframe, limit=500):
    """Fetch OHLCV via ccxt (public endpoint, works on testnet)."""
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        df.set_index('ts', inplace=True)
        return df
    except Exception as e:
        print(f"  ⚠️  {symbol} {timeframe}: {e}")
        return pd.DataFrame()

# ═══════════════════════════════════════════════
# INDICATORS (ported from backtest_v9.3.py)
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
                    zones.append({'price': np.mean(current_zone), 'top': max(current_zone),
                                  'bottom': min(current_zone), 'touches': len(current_zone)})
                current_zone = [p]
        if len(current_zone) >= min_touches:
            zones.append({'price': np.mean(current_zone), 'top': max(current_zone),
                          'bottom': min(current_zone), 'touches': len(current_zone)})
        return zones

    return cluster_levels(swing_low_points), cluster_levels(swing_high_points)

def price_near_zone(price, zones, proximity_pct=ZONE_PROXIMITY_1H):
    for zone in zones:
        if abs(price - zone['price']) / price < proximity_pct:
            return zone
    return None

# ═══════════════════════════════════════════════
# SIGNAL CHECK (current candle only)
# ═══════════════════════════════════════════════
def check_latest_signal(df_4h, df_1h, df_15m):
    """Check if the current (latest) 15m candle generates a signal."""
    if len(df_15m) < 3:
        return []

    signals = []
    i = len(df_15m) - 1
    ts_15m = df_15m.index[i]
    price_15m = df_15m['close'].iloc[i]

    # 4H context
    mask_4h = df_4h.index <= ts_15m
    if not mask_4h.any():
        return []
    idx_4h = mask_4h.sum() - 1
    if idx_4h < 20:
        return []

    # 1H context
    mask_1h = df_1h.index <= ts_15m
    if not mask_1h.any():
        return []
    idx_1h = mask_1h.sum() - 1
    if idx_1h < 2:
        return []

    row_1h = df_1h.iloc[idx_1h]
    price_1h = row_1h['close']

    recent_4h = df_4h.iloc[max(0, idx_4h - 90):idx_4h + 1]
    supports, resistances = detect_zones_4h(recent_4h)

    near_support = price_near_zone(price_1h, supports)
    near_resistance = price_near_zone(price_1h, resistances)

    if near_support is None and near_resistance is None:
        return []

    vol_ok = row_1h['vol_ratio'] > VOLUME_THRESHOLD_1H if not pd.isna(row_1h.get('vol_ratio')) else False

    row_15m = df_15m.iloc[i]
    rsi_15m = row_15m['rsi']
    rsi_15m_prev = df_15m['rsi'].iloc[i - 1] if i > 0 else rsi_15m

    # ── LONG ──
    if near_support:
        rsi_1h = row_1h['rsi']
        rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_LONG_MIN_1H and rsi_1h <= RSI_LONG_MAX_1H)
        candle_1h_ok = row_1h['is_bullish'] or row_1h['is_hammer']
        trigger_15m = (row_15m['is_bullish'] or row_15m['is_hammer'] or row_15m['is_engulfing_bull'])
        rsi_15m_ok = rsi_15m < 60
        div_ok = row_15m['bull_div']
        conditions_met = sum([rsi_1h_ok, candle_1h_ok, trigger_15m,
                             rsi_15m_ok, vol_ok])
        if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
            signals.append({
                'side': 'LONG', 'entry': price_15m, 'zone_price': near_support['price'],
                'zone_touches': near_support['touches'], 'rsi_1h': rsi_1h, 'rsi_15m': rsi_15m,
                'conditions': conditions_met, 'divergence': div_ok,
            })

    # ── SHORT ──
    if near_resistance:
        rsi_1h = row_1h['rsi']
        rsi_1h_ok = (not pd.isna(rsi_1h)) and (rsi_1h >= RSI_SHORT_MIN_1H and rsi_1h <= RSI_SHORT_MAX_1H)
        candle_1h_ok = row_1h['is_bearish'] or row_1h['is_shooting_star']
        trigger_15m = (row_15m['is_bearish'] or row_15m['is_shooting_star'] or row_15m['is_engulfing_bear'])
        rsi_15m_ok = rsi_15m > 40
        div_ok = row_15m['bear_div']
        conditions_met = sum([rsi_1h_ok, candle_1h_ok, trigger_15m,
                             rsi_15m_ok, vol_ok])
        if conditions_met >= 3 and (trigger_15m or candle_1h_ok):
            signals.append({
                'side': 'SHORT', 'entry': price_15m, 'zone_price': near_resistance['price'],
                'zone_touches': near_resistance['touches'], 'rsi_1h': rsi_1h, 'rsi_15m': rsi_15m,
                'conditions': conditions_met, 'divergence': div_ok,
            })

    return signals

# ═══════════════════════════════════════════════
# TRADE EXECUTION
# ═══════════════════════════════════════════════
def enter_trade(symbol, side, entry_price):
    """Place entry market order + SL/TP algo orders on testnet."""
    print(f"\n{'='*60}")
    print(f"  🚀 ENTERING {side} on {symbol}")
    print(f"{'='*60}")

    price_dec, qty_dec = get_symbol_precision(symbol)

    # Get current price from ticker
    ex = get_ccxt_exchange()
    try:
        ticker = ex.fetch_ticker(symbol)
        current_price = ticker['last']
    except:
        current_price = entry_price

    # Calculate position size
    quantity = POSITION_SIZE_USDT / current_price
    quantity = round(quantity, qty_dec)
    if qty_dec == 0:
        quantity = int(quantity)
    if quantity == 0:
        print(f"  ❌ Quantity rounded to 0 (price={current_price})")
        return None

    # Set leverage
    set_leverage(symbol, LEVERAGE)

    # Market entry
    result = place_order(symbol, side.lower(), 'market', quantity)
    if not result:
        print(f"  ❌ Entry failed")
        return None

    # Get fill price
    fill_price = float(result.get('avgPrice', current_price)) if result.get('avgPrice') else current_price
    fill_qty = float(result.get('executedQty', quantity))
    print(f"  ✅ Entry: {side} {fill_qty} @ {fill_price}")

    entry_price = fill_price

    # SL/TP prices
    if side == 'LONG':
        sl_price = round(entry_price * (1 - SL_PCT), price_dec)
        tp_price = round(entry_price * (1 + TP_PCT), price_dec)
    else:
        sl_price = round(entry_price * (1 + SL_PCT), price_dec)
        tp_price = round(entry_price * (1 - TP_PCT), price_dec)

    sl_side = 'sell' if side == 'LONG' else 'buy'

    # Place STOP_MARKET for SL
    sl_result = place_order(symbol, sl_side, 'stop_market', fill_qty,
                            stop_price=sl_price, reduce_only=True, raw_side=True)
    if sl_result:
        print(f"  🛑 SL: {sl_side.upper()} @ {sl_price} ({SL_PCT*100:.1f}%)")
    else:
        print(f"  ❌ SL placement failed!")

    # Place TAKE_PROFIT_MARKET for TP
    tp_result = place_order(symbol, sl_side, 'take_profit_market', fill_qty,
                            stop_price=tp_price, reduce_only=True, raw_side=True)
    if tp_result:
        print(f"  🎯 TP: {sl_side.upper()} @ {tp_price} ({TP_PCT*100:.1f}%)")
    else:
        print(f"  ❌ TP placement failed!")

    return {
        'symbol': symbol, 'side': side, 'quantity': fill_qty,
        'entry': fill_price, 'sl': sl_price, 'tp': tp_price,
        'time': datetime.now().isoformat()
    }

# ═══════════════════════════════════════════════
# RUN ONCE
# ═══════════════════════════════════════════════
def run_once(exchange):
    """One-shot: check signals, execute if valid."""
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  FORSCHER V9.3g LIVE — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # ── Current positions ──
    positions = get_positions()
    open_symbols = {}
    if positions:
        print(f"\n  📊 OPEN POSITIONS:")
        total_pnl = 0
        for pos in positions:
            sym = pos['symbol']
            amt = abs(float(pos['positionAmt']))
            entry = float(pos['entryPrice'])
            pnl = float(pos.get('unrealizedProfit', 0))
            side = 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT'
            total_pnl += pnl
            open_symbols[sym] = pos
            pnl_pct = (pnl / (amt * entry)) * 100
            print(f"    {sym:10s} {side:5s} | Qty: {amt:.3f} | Entry: {entry:.4f} | PnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%)")
        if total_pnl != 0:
            print(f"    {'─'*55}")
            print(f"    💰 Total unrealized PnL: {total_pnl:+.2f} USDT")
    else:
        print(f"\n  📊 No open positions")

    # ── Fetch data & check signals ──
    print(f"\n  📡 Fetching data...")
    new_trades = []

    for symbol in SYMBOLS:
        lock = DIRECTION_LOCK[symbol]
        sym_clean = symbol.replace('/', '')

        # Skip if already in position
        if sym_clean in open_symbols:
            pos = open_symbols[sym_clean]
            side = 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT'
            print(f"\n  ── {symbol} (lock: {lock}) ──")
            print(f"    ⏭️  Already in {side} — skip")
            continue

        # Fetch data
        df_4h  = fetch_ohlcv(exchange, symbol, '4h', 500)
        df_1h  = fetch_ohlcv(exchange, symbol, '1h', 500)
        df_15m = fetch_ohlcv(exchange, symbol, '15m', 500)

        if df_4h.empty or df_1h.empty or df_15m.empty:
            print(f"\n  ── {symbol} (lock: {lock}) ──")
            print(f"    ⚠️  Insufficient data")
            continue

        # Add indicators
        df_4h  = add_emas(df_4h, TREND_EMA_FAST_4H, TREND_EMA_SLOW_4H)
        df_1h  = add_rsi(df_1h, RSI_PERIOD_1H)
        df_1h  = add_volume_avg(df_1h, 20)
        df_1h  = add_candle_patterns(df_1h)
        df_15m = add_rsi(df_15m, RSI_PERIOD_15M)
        df_15m = add_candle_patterns(df_15m)
        df_15m = add_rsi_divergence(df_15m, 'rsi', DIVERGENCE_LOOKBACK)

        # Check signal
        signals = check_latest_signal(df_4h, df_1h, df_15m)

        # Show zone info
        recent_4h = df_4h.iloc[-90:]
        supports, resistances = detect_zones_4h(recent_4h)
        price = df_15m['close'].iloc[-1]
        rsi = df_15m['rsi'].iloc[-1]

        print(f"\n  ── {symbol} (lock: {lock}) ──")
        print(f"    💵 Price: {price:.4f} | RSI(15m): {rsi:.1f}")
        if supports:
            top_s = supports[:3]
            print(f"    📗 Supports: " + " | ".join(f"${z['price']:.4f}({z['touches']}t)" for z in top_s))
        if resistances:
            top_r = sorted(resistances, key=lambda z: z['touches'], reverse=True)[:3]
            print(f"    📕 Resist:  " + " | ".join(f"${z['price']:.4f}({z['touches']}t)" for z in top_r))

        if not signals:
            print(f"    ⏳ No signal")
            continue

        for sig in signals:
            # Direction lock
            if lock == 'LONG' and sig['side'] != 'LONG':
                print(f"    🔒 {sig['side']} blocked by LONG lock")
                continue
            if lock == 'SHORT' and sig['side'] != 'SHORT':
                print(f"    🔒 {sig['side']} blocked by SHORT lock")
                continue

            print(f"    ⚡ SIGNAL: {sig['side']:5s} | Entry: {sig['entry']:.4f} | "
                  f"Zone: {sig['zone_price']:.4f} ({sig['zone_touches']}t) | "
                  f"Cond: {sig['conditions']}/5 | RSI: {sig['rsi_15m']:.1f}")

            trade = enter_trade(symbol, sig['side'], sig['entry'])
            if trade:
                new_trades.append(trade)

    # ── Summary ──
    print(f"\n{'='*60}")
    if new_trades:
        print(f"  ✅ EXECUTED {len(new_trades)} trades:")
        for t in new_trades:
            print(f"    {t['symbol']} {t['side']} | Entry: {t['entry']:.4f} | SL: {t['sl']:.4f} | TP: {t['tp']:.4f}")
    else:
        print(f"  ⏳ No new trades. Next check: ~{(now + timedelta(minutes=15 - now.minute % 15)).strftime('%H:%M')}")
    print(f"{'='*60}")

    return new_trades

def show_status():
    """Show current positions and open orders."""
    print(f"\n{'='*60}")
    print(f"  V9.3g STATUS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    positions = get_positions()
    if not positions:
        print("\n  📊 No open positions")
    else:
        print(f"\n  📊 POSITIONS:")
        total_pnl = 0
        for pos in positions:
            amt = abs(float(pos['positionAmt']))
            entry = float(pos['entryPrice'])
            mark = float(pos.get('markPrice', entry))
            pnl = float(pos.get('unrealizedProfit', 0))
            side = 'LONG' if float(pos['positionAmt']) > 0 else 'SHORT'
            liq = float(pos.get('liquidationPrice', 0))
            total_pnl += pnl
            pnl_pct = (pnl / (amt * entry)) * 100 if amt > 0 else 0
            print(f"    {pos['symbol']:10s} {side:5s} | Qty: {amt:.3f} | "
                  f"Entry: {entry:.4f} | Mark: {mark:.4f} | "
                  f"PnL: {pnl:+.2f} USDT ({pnl_pct:+.1f}%) | Liq: {liq:.4f}")
        print(f"\n    💰 Total Unrealized PnL: {total_pnl:+.2f} USDT")

    # Open orders
    orders = get_open_orders()
    if orders:
        print(f"\n  📋 OPEN ORDERS:")
        for o in orders:
            stop_price = o.get('stopPrice', o.get('price', 'N/A'))
            print(f"    {o['symbol']} {o['side']} {o['type']} | Qty: {o['origQty']} | "
                  f"Trigger: {stop_price}")
    else:
        print(f"\n  📋 No open orders")

def close_all():
    """Emergency close all positions and cancel orders."""
    print(f"\n{'='*60}")
    print(f"  🚨 EMERGENCY CLOSE ALL")
    print(f"{'='*60}")

    positions = get_positions()
    for pos in positions:
        sym = pos['symbol']
        amt = abs(float(pos['positionAmt']))
        side = 'sell' if float(pos['positionAmt']) > 0 else 'buy'
        symbol = sym + '/USDT' if not sym.endswith('USDT') else sym
        symbol = symbol.replace(sym, sym[:3] + '/' + sym[3:]) if '/' not in symbol else symbol
        # Use market close
        try:
            place_order(symbol, side, 'market', amt, reduce_only=True)
            print(f"  ✅ Closed {sym}: {side.upper()} {amt}")
        except Exception as e:
            print(f"  ❌ Failed {sym}: {e}")

    for symbol in SYMBOLS:
        cancel_all_orders(symbol)

    print(f"\n  ✅ All done")

# ═══════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════
if __name__ == '__main__':
    exchange = get_ccxt_exchange()

    if '--status' in sys.argv:
        show_status()
    elif '--close-all' in sys.argv:
        close_all()
    elif '--watch' in sys.argv:
        print("🔄 V9.3g LIVE — Monitoring every 15 minutes (Ctrl+C to stop)")
        try:
            while True:
                run_once(exchange)
                now = datetime.now()
                next_15m = now + timedelta(minutes=15 - now.minute % 15)
                next_15m = next_15m.replace(second=10, microsecond=0)
                wait_seconds = max((next_15m - now).total_seconds(), 1)
                print(f"\n  ⏰ Next check: {next_15m.strftime('%H:%M:%S')} ({wait_seconds:.0f}s)")
                time.sleep(wait_seconds)
        except KeyboardInterrupt:
            print("\n\n👋 V9.3g stopped.")
    else:
        run_once(exchange)
