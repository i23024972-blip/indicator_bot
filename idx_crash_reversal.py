# idx_crash_reversal.py — During CRASH regime only, which reversal signals actually caught
# the bounce? Tests several on the watchlist, restricted to days the IHSG was in CRASH,
# so we can decide if a high-conviction "crash reversal" entry is worth adding.
import warnings; warnings.filterwarnings("ignore")
import sys
import pandas as pd, numpy as np
import idx_konglo as K
from idx_scan import WATCHLIST
from idx_regime import load_ihsg

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SL_X, TP_X, HOLD, FEE = 2.0, 6.0, 20, 0.4

def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1/n, adjust=False).mean(); rd = dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100*rd/(ru+rd).replace(0, np.nan)

def prep(t, crash_dates):
    d, _ = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < 80: return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["ma20"]  = d["close"].rolling(20).mean()
    d["ret1"]  = d["close"].pct_change()
    d["ret5"]  = d["close"]/d["close"].shift(5) - 1
    d["rsi"]   = rsi(d["close"])
    d["incrash"] = d["time"].dt.normalize().isin(crash_dates)
    return d

def sim_long(d, i):
    atr = d["atr"].iloc[i]; entry = d["close"].iloc[i]
    sl, tp = entry - SL_X*atr, entry + TP_X*atr
    end = min(i + HOLD, len(d)-1)
    for j in range(i+1, end+1):
        if d["low"].iloc[j]  <= sl: return (sl-entry)/entry*100, j-i
        if d["high"].iloc[j] >= tp: return (tp-entry)/entry*100, j-i
    return (d["close"].iloc[end]-entry)/entry*100, end-i

# ── reversal signals (each evaluated at day i, long only) ──
def s_capit(d, i):     # capitulation flush in last 3 bars, then up day
    flush = any(d["ret1"].iloc[k] < 0 and d["volume"].iloc[k] >= 3*d["volma"].iloc[k] for k in (i,i-1,i-2))
    return flush and d["ret1"].iloc[i] > 0
def s_rsi(d, i):       # RSI was <30 in last 5d, now back above 35, up day
    was = (d["rsi"].iloc[i-5:i] < 30).any()
    return was and d["rsi"].iloc[i] > 35 and d["ret1"].iloc[i] > 0
def s_reclaim(d, i):   # reclaim the 20-day MA from below, up day
    return d["close"].iloc[i] > d["ma20"].iloc[i] and d["close"].iloc[i-1] <= d["ma20"].iloc[i-1] and d["ret1"].iloc[i] > 0
def s_hammer(d, i):    # strong reversal candle: closes top 25% of range, vol>1.5x, after a drop
    rng = (d["high"].iloc[i]-d["low"].iloc[i]) or 1e-9
    strong = (d["close"].iloc[i]-d["low"].iloc[i])/rng >= 0.75
    return strong and d["volume"].iloc[i] >= 1.5*d["volma"].iloc[i] and d["ret5"].iloc[i] < -0.05

SIGS = {"capitulation": s_capit, "rsi_oversold": s_rsi, "reclaim_20ma": s_reclaim, "reversal_candle": s_hammer}

def valid(d, i):
    return not (pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i] <= 0 or pd.isna(d["volma"].iloc[i])
                or pd.isna(d["ma20"].iloc[i]) or pd.isna(d["rsi"].iloc[i]))

def main():
    ix = load_ihsg()
    crash_dates = set(ix.index[ix["regime"] == "CRASH"].normalize())
    print(f"IHSG CRASH days on record: {len(crash_dates)}. Testing reversal entries on those days only.\n")

    frames = {}
    for t in WATCHLIST:
        d = prep(t, crash_dates)
        if d is not None: frames[t] = d

    results = {name: [] for name in SIGS}
    for t, d in frames.items():
        for name, fn in SIGS.items():
            last = -1
            for i in range(25, len(d)-1):
                if not d["incrash"].iloc[i] or not valid(d, i) or i <= last: continue
                if fn(d, i):
                    pnl, bars = sim_long(d, i); last = i + bars
                    results[name].append(pnl - FEE)

    print("="*66)
    print("  REVERSAL SIGNALS DURING CRASH REGIME (net fees, exit 2/6 ATR)")
    print("="*66)
    print(f"  {'signal':18}{'n':>5}{'win%':>7}{'exp/trade':>12}{'total':>10}")
    for name, pnls in SIGS_sorted(results):
        if not pnls:
            print(f"  {name:18}{'0':>5}"); continue
        s = pd.Series(pnls)
        print(f"  {name:18}{len(s):>5}{(s>0).mean()*100:>6.0f}%{s.mean():>+11.2f}%{s.sum():>+9.0f}%")
    print("\n  (Positive expectancy here = a reversal entry that paid off mid-crash.)")

def SIGS_sorted(results):
    return sorted(results.items(), key=lambda kv: -(sum(kv[1])/len(kv[1]) if kv[1] else -99))

if __name__ == "__main__":
    main()
