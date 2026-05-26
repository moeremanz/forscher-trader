#!/usr/bin/env python3
"""
Forscher MTF Screener — Cron-ready
Usage: python3 scripts/forscher_screener.py
Output: Clean signal report with STRONG/WEAK/WAIT classification
"""
import requests
import pandas as pd
import numpy as np
from datetime import datetime

MEXC_BASE = "https://contract.mexc.com/api/v1/contract"

# Forscher pair universe (V9.3f — Tier1 + Tier2)
PAIRS = [
    'ETH_USDT', 'AVAX_USDT', 'FET_USDT',  # Tier1
    'SOL_USDT', 'DOGE_USDT', 'ONDO_USDT', 'SUI_USDT',
    'NEAR_USDT', 'TIA_USDT', 'ROSE_USDT', 'XPL_USDT',
]

# ─── Helpers ───
def get_klines(sym, interval, limit=300):
    try:
        r = requests.get(f"{MEXC_BASE}/kline/{sym}",
                        params={'interval': interval, 'limit': limit}, timeout=10)
        d = r.json()
        if not d.get('success') or not d.get('data'):
            return None
        dd = d['data']
        rows = [{'time': dd['time'][i], 'open': float(dd['open'][i]),
                 'high': float(dd['high'][i]), 'low': float(dd['low'][i]),
                 'close': float(dd['close'][i]), 'volume': float(dd['vol'][i])}
                for i in range(len(dd['time']))]
        df = pd.DataFrame(rows)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df.set_index('time')
    except:
        return None

def cluster_zones(pts, band=0.015, mint=3):
    if not pts: return []
    sp = sorted(set(pts))
    zones = []
    for p in sp:
        found = False
        for z in zones:
            if abs(p - z['mid']) / z['mid'] <= band:
                z['touches'] += 1
                z['mid'] = round((z['mid'] * (z['touches'] - 1) + p) / z['touches'], 6)
                found = True; break
        if not found:
            zones.append({'mid': round(p, 6), 'touches': 1})
    return [z for z in zones if z['touches'] >= mint]

# ─── SCREEN ───
print(f"🔍 FORSCHER SCREENER — {datetime.now().strftime('%Y-%m-%d %H:%M')} UTC")
print("=" * 60)

results, errors = [], []

for pair in PAIRS:
    ticker = pair.replace('_USDT', '')
    
    df_1h = get_klines(pair, 'Min60', 300)
    if df_1h is None or len(df_1h) < 20:
        errors.append(ticker)
        continue
    
    # Resample to 4H
    df_4h = df_1h.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min',
        'close': 'last', 'volume': 'sum'
    }).dropna()
    
    if len(df_4h) < 15:
        errors.append(ticker)
        continue
    
    cp = float(df_1h['close'].iloc[-1])
    
    # ─── 4H ZONES ───
    dz = df_4h.iloc[-min(50, len(df_4h)):]
    sh, sl = [], []
    for i in range(2, len(dz) - 2):
        if dz['high'].iloc[i] == dz['high'].iloc[i-2:i+3].max():
            sh.append(float(dz['high'].iloc[i]))
        if dz['low'].iloc[i] == dz['low'].iloc[i-2:i+3].min():
            sl.append(float(dz['low'].iloc[i]))
    
    res_z = cluster_zones(sh)
    sup_z = cluster_zones(sl)
    
    # Nearest zones
    nr = None; ns = None
    for z in sorted(res_z, key=lambda x: x['mid']):
        if z['mid'] > cp: nr = z; break
    for z in sorted(sup_z, key=lambda x: x['mid'], reverse=True):
        if z['mid'] < cp: ns = z; break
    
    # ─── RSI 1H ───
    d1 = df_1h['close'].diff()
    g1 = d1.where(d1 > 0, 0).rolling(14).mean()
    l1 = (-d1.where(d1 < 0, 0)).rolling(14).mean()
    rsi_c = float(100 - 100 / (1 + g1 / l1).iloc[-1]) if not pd.isna((g1/l1).iloc[-1]) else 50
    
    # ─── TREND 4H ───
    e20 = df_4h['close'].ewm(span=20).mean().iloc[-1]
    e50 = df_4h['close'].ewm(span=50).mean().iloc[-1]
    trend_b = float(e20) > float(e50)
    
    # ─── VOLUME ───
    va = df_1h['volume'].rolling(20).mean().iloc[-1]
    vc = float(df_1h['volume'].iloc[-1])
    vol_r = vc / va if va > 0 else 1.0
    
    # ─── SCORING ───
    sc = 0; bias = None; zd = 0; zi = ""
    
    if nr:
        d = round((nr['mid'] - cp) / cp * 100, 2)
        if d < 3.0 and nr['touches'] >= 3:
            if rsi_c > 55: sc += 40; bias = 'SHORT'; zd = d; zi = f"${nr['mid']:.4f}({nr['touches']}t)"
            elif d < 1.5: sc += 25; bias = 'SHORT'; zd = d; zi = f"${nr['mid']:.4f}({nr['touches']}t)"
    
    if ns and (bias is None or sc < 30):
        d = round((cp - ns['mid']) / cp * 100, 2)
        if d < 3.0 and ns['touches'] >= 3:
            if rsi_c < 45: sc += 40; bias = 'LONG'; zd = d; zi = f"${ns['mid']:.4f}({ns['touches']}t)"
            elif d < 1.5: sc += 25; bias = 'LONG'; zd = d; zi = f"${ns['mid']:.4f}({ns['touches']}t)"
    
    if bias == 'SHORT' and not trend_b: sc += 15
    elif bias == 'LONG' and trend_b: sc += 15
    elif bias and ((bias == 'SHORT' and trend_b) or (bias == 'LONG' and not trend_b)): sc -= 8
    
    # Execution layer (15m RSI proxy via volume momentum)
    if bias == 'SHORT': sc += 5  # overbought bias confirmed by trend
    if vol_r > 1.2: sc += 10
    
    sig = 'WAIT'
    if sc >= 55: sig = f'STRONG_{bias}'
    elif sc >= 40: sig = f'WEAK_{bias}'
    
    results.append(dict(ticker=ticker, price=cp, bias=bias or 'NONE',
        score=sc, signal=sig, zone=zi, dist=zd, rsi1h=rsi_c,
        trend='BULL' if trend_b else 'BEAR', vol=vol_r))

# ─── OUTPUT ───
strong = [r for r in results if r['signal'].startswith('STRONG')]
weak = [r for r in results if r['signal'].startswith('WEAK')]

if strong:
    print("\n🔥 STRONG SIGNALS:")
    for r in sorted(strong, key=lambda x: x['score'], reverse=True):
        print(f"  {r['ticker']:<6} {r['bias']:<6} Score:{r['score']:<4} {r['zone']:<20} Dist:{r['dist']:.1f}% RSI:{r['rsi1h']:.0f} Trend:{r['trend']}")

if weak:
    print("\n⚠️ WEAK SIGNALS:")
    for r in sorted(weak, key=lambda x: x['score'], reverse=True):
        print(f"  {r['ticker']:<6} {r['bias']:<6} Score:{r['score']:<4} {r['zone']:<20} Dist:{r['dist']:.1f}% RSI:{r['rsi1h']:.0f} Trend:{r['trend']}")

wait = [r for r in results if r['signal'] == 'WAIT']
print(f"\n⏳ WAIT: {len(wait)} pairs | ⚠️ Errors: {len(errors)} ({', '.join(errors) if errors else 'none'})")
print(f"📊 Total: {len(results)}/{len(PAIRS)} screened")
