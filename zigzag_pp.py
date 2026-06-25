# zigzag_pp.py
# Causal ZigZag++ style structure (Depth / Backstep), matching the TradingView "ZigZag++ [LD]"
# look (new HH/HL/LH/LL swing every ~5-6 candles) WITHOUT repainting / look-ahead.
#
# Key difference vs the old %-deviation version:
#   old: a pivot only prints after price reverses DEVIATION% (late & sparse)
#   new: a pivot is a local extreme over a Depth window, CONFIRMED `right` bars later
#        (early & frequent, like the real indicator) but only ACTED ON after confirmation.
import os
import pandas as pd
import numpy as np
from binance.client import Client

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".klines_cache")

SYMBOLS       = [("BTCUSDT", False), ("HYPEUSDT", True)]   # traded as spot
BACKTEST_DAYS = 300
BIAS_IV  = Client.KLINE_INTERVAL_4HOUR
ENTRY_IV = Client.KLINE_INTERVAL_30MINUTE

# ZigZag++ pivot detection. Real indicator: Depth=12. A pivot is a local extreme with
# `left` bars lower/higher before it and `right` bars after it (right = confirmation lag).
PIVOT_STRENGTHS = [3, 5, 6]   # swept; ~5-6 matches "new swing every 5-6 candles" on your chart

ATR_TP, ATR_SL = 4.0, 1.5     # the R:R winner from the optimizer
FRESH_ONLY    = True
SPOT_FEE      = 0.20
START_CAPITAL = 1000.0

client = Client()
BULL = ("HH+HL", "HL")
BEAR = ("LL+LH", "LH")

# ─── DATA ─────────────────────────────────────────────
_CACHE = {}
def get_historical(symbol, interval, is_futures=False, days=BACKTEST_DAYS):
    key = (symbol, interval, is_futures)
    if key in _CACHE: return _CACHE[key]
    os.makedirs(CACHE_DIR, exist_ok=True)
    fpath = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{'fut' if is_futures else 'spot'}_{days}d.parquet")
    if os.path.exists(fpath):                       # disk cache -> instant reruns
        df = pd.read_parquet(fpath); _CACHE[key]=df; return df
    start_str = f"{days} days ago UTC"
    try:
        klines = (client.futures_historical_klines(symbol, interval, start_str) if is_futures
                  else client.get_historical_klines(symbol, interval, start_str))
    except Exception as e:
        print(f"  WARN {symbol} {interval}: {e}"); _CACHE[key]=None; return None
    if not klines: _CACHE[key]=None; return None
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    try: df.to_parquet(fpath)
    except Exception: pass
    _CACHE[key]=df; return df

def atr_series(df, window=14):
    h,l,c = df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(window).mean()

# ─── CAUSAL ZIGZAG++ PIVOTS ───────────────────────────
def compute_pivots(df, strength):
    """Local-extreme pivots: high[i] is the max of [i-strength, i+strength] => pivot high.
       Confirmed (actionable) at i+strength. Alternates high/low, keeping the more extreme
       when two of the same type occur in a row (Backstep behaviour).
       Returns list of (pivot_idx, price, 'high'/'low', confirm_idx)."""
    highs = df["high"].values; lows = df["low"].values; n = len(df)
    raw = []
    for i in range(strength, n-strength):
        wmaxH = highs[i-strength:i+strength+1].max()
        wminL = lows[i-strength:i+strength+1].min()
        if highs[i] == wmaxH:
            raw.append((i, highs[i], 'high', i+strength))
        if lows[i] == wminL:
            raw.append((i, lows[i], 'low',  i+strength))
    raw.sort(key=lambda p: (p[0], 0 if p[2]=='high' else 1))
    # enforce alternation, keep stronger extreme on same-type runs
    piv = []
    for p in raw:
        if not piv or piv[-1][2] != p[2]:
            piv.append(p)
        else:
            last = piv[-1]
            better = (p[1] > last[1]) if p[2]=='high' else (p[1] < last[1])
            if better: piv[-1] = p
    return piv

def structure_label_array(df, pivots):
    """Per-bar HH/HL/LH/LL label using only pivots CONFIRMED up to that bar (causal)."""
    n=len(df); labels=["neutral"]*n; hs=[]; ls=[]; pj=0
    sp = sorted(pivots, key=lambda p: p[3])   # by confirm idx
    def cur():
        if len(hs)>=2 and len(ls)>=2:
            hh,hl = hs[-1]>hs[-2], ls[-1]>ls[-2]
            ll,lh = ls[-1]<ls[-2], hs[-1]<hs[-2]
            if hh and hl: return "HH+HL"
            if ll and lh: return "LL+LH"
            if hl: return "HL"
            if lh: return "LH"
        return "neutral"
    for i in range(n):
        while pj < len(sp) and sp[pj][3] <= i:
            p=sp[pj]; (hs if p[2]=='high' else ls).append(p[1]); pj+=1
        labels[i]=cur()
    return labels

def structure_at_bias(labels, idx):
    return labels[idx] if 0 <= idx < len(labels) else "neutral"

# ─── EXIT ─────────────────────────────────────────────
def exit_fixed(highs, lows, closes, entry_idx, is_buy, atr):
    entry = closes[entry_idx]
    sl = entry - atr*ATR_SL if is_buy else entry + atr*ATR_SL
    tp = entry + atr*ATR_TP if is_buy else entry - atr*ATR_TP
    n = len(closes)
    for i in range(entry_idx+1, n):
        hi,lo = highs[i], lows[i]
        if is_buy:
            if lo<=sl: return ((sl-entry)/entry)*100,"SL"
            if hi>=tp: return ((tp-entry)/entry)*100,"TP"
        else:
            if hi>=sl: return ((entry-sl)/entry)*100,"SL"
            if lo<=tp: return ((entry-tp)/entry)*100,"TP"
    return None,"OPEN"

# ─── BACKTEST ─────────────────────────────────────────
def backtest_symbol(sym, bias_df, entry_df, strength):
    entry_df = entry_df.copy(); entry_df["atr"]=atr_series(entry_df)
    bias_piv  = compute_pivots(bias_df, strength)
    entry_piv = compute_pivots(entry_df, strength)
    bias_lbl  = structure_label_array(bias_df, bias_piv)
    entry_lbl = structure_label_array(entry_df, entry_piv)
    # map each entry bar -> index of most recent CLOSED bias bar, in one vectorised pass (no O(n^2))
    bias_times  = bias_df["time"].values
    entry_times = entry_df["time"].values
    bias_idx_for = np.searchsorted(bias_times, entry_times, side="right") - 1
    atr_vals = entry_df["atr"].values
    e_high = entry_df["high"].values; e_low = entry_df["low"].values; e_close = entry_df["close"].values
    trades=[]; prev=None
    for i in range(50, len(entry_df)-1):
        if pd.isna(atr_vals[i]): continue
        bidx = bias_idx_for[i]
        if bidx < 10: continue
        s_bias = structure_at_bias(bias_lbl, bidx)
        s_entry = entry_lbl[i]
        fresh = (s_entry!=prev); prev=s_entry
        if FRESH_ONLY and not fresh: continue
        bull = (s_bias in BULL) and (s_entry in BULL)
        bear = (s_bias in BEAR) and (s_entry in BEAR)
        if bull or bear:
            pnl,ex = exit_fixed(e_high, e_low, e_close, i, bull, atr_vals[i])
            if pnl is not None:
                trades.append({"time":entry_times[i],"pnl_pct":pnl,"exit":ex})
    return trades

def metrics(trades):
    if not trades: return None
    df=pd.DataFrame(trades); n=len(df)
    return {"n":n,"wr":(df["pnl_pct"]>0).mean()*100,
            "bep":df["pnl_pct"].mean(),"net":(df["pnl_pct"]-SPOT_FEE).mean()}

def equity(trades, fee=SPOT_FEE, start=START_CAPITAL):
    if not trades: return start,0
    df=pd.DataFrame(trades).sort_values("time"); bal=start; peak=start; dd=0.0
    for pnl in df["pnl_pct"]:
        bal*=(1+(pnl-fee)/100.0)
        if bal<=0: bal=0.0; break
        peak=max(peak,bal); dd=max(dd,(peak-bal)/peak*100)
    return bal,dd

def main():
    print(f"Causal ZigZag++ structure | {BACKTEST_DAYS}d | 4H bias + 30M entry | TP{ATR_TP}/SL{ATR_SL} | BTC+HYPE spot")
    print(f"Pivot = local extreme over +/- strength bars, confirmed `strength` bars late (no repaint)\n")
    hdr=f"  {'Strength':>8} | {'~candles':>8} | {'Trd':>5} | {'Win':>6} | {'BEP/trd':>8} | {'net@spot':>8} | {'$1000':>14}"
    print(hdr); print("  "+"-"*(len(hdr)-2))
    for s in PIVOT_STRENGTHS:
        trades=[]
        for sym,fut in SYMBOLS:
            bias_df=get_historical(sym,BIAS_IV,fut); entry_df=get_historical(sym,ENTRY_IV,fut)
            if bias_df is None or entry_df is None: continue
            trades += backtest_symbol(sym,bias_df,entry_df,s)
        m=metrics(trades)
        if m is None:
            print(f"  {s:>8} | {'~'+str(2*s+1):>8} |   n/a"); continue
        bal,dd=equity(trades)
        print(f"  {s:>8} | {'~'+str(2*s+1):>8} | {m['n']:>5} | {m['wr']:>5.1f}% | {m['bep']:>+7.3f}% | "
              f"{m['net']:>+7.3f}% | {('$'+format(bal,',.0f')+' (-'+format(dd,'.0f')+'%)'):>14}")
    print("\n  strength = bars on each side of a pivot. ~candles = full window (2*strength+1).")
    print("  BEP/trd = gross expectancy = max round-trip fee before you stop earning.")
    print(f"  net@spot after {SPOT_FEE:.2f}% fee. $1000 = compounded final balance (max DD in parens).")

if __name__ == "__main__":
    main()
