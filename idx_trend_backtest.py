# idx_trend_backtest.py — Compare two philosophies on the same watchlist + portfolio:
#   COMBO  : our short swing — volume spike + structure, exit 2/6 ATR, ~10-day holds.
#   TREND  : DSSA-style position trade — buy a confirmed uptrend (price reclaims 50MA while
#            50MA>200MA), HOLD for months, ride it, exit only when trend breaks (close<50MA)
#            or a wide 3xATR stop. No profit cap — let winners run.
import sys
import pandas as pd
import idx_konglo as K
from idx_scan import WATCHLIST
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SPIKE_X, FEE = 2.5, 0.4
# Combo exit
C_SL, C_TP, C_HOLD = 2.0, 6.0, 20
# Trend params
T_STOP, T_MAXHOLD = 3.0, 120

def prep(t):
    d, w = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < 260 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(50).mean()
    d["sma200"]= d["close"].rolling(200).mean()
    d["ret1"]  = d["close"].pct_change()
    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    d["sd"] = [K.structure_at(zz_d, i) for i in range(len(d))]
    sw = []
    for i in range(len(d)):
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw.append(K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral")
    d["sw"] = sw
    return d

def sim_combo(d, i):
    atr=d["atr"].iloc[i]; e=d["close"].iloc[i]; sl,tp=e-C_SL*atr,e+C_TP*atr; end=min(i+C_HOLD,len(d)-1)
    for j in range(i+1,end+1):
        if d["low"].iloc[j]<=sl: return (sl-e)/e*100, j-i
        if d["high"].iloc[j]>=tp: return (tp-e)/e*100, j-i
    return (d["close"].iloc[end]-e)/e*100, end-i

def sim_trend(d, i):
    atr=d["atr"].iloc[i]; e=d["close"].iloc[i]; stop=e-T_STOP*atr; end=min(i+T_MAXHOLD,len(d)-1)
    for j in range(i+1,end+1):
        if d["low"].iloc[j]<=stop: return (stop-e)/e*100, j-i        # hard stop
        if d["close"].iloc[j]<d["sma50"].iloc[j]: return (d["close"].iloc[j]-e)/e*100, j-i  # trend break
    return (d["close"].iloc[end]-e)/e*100, end-i

def collect(strategy):
    trades=[]
    for t in WATCHLIST:
        d=prep(t)
        if d is None: continue
        last=-1
        for i in range(200, len(d)-1):
            if pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i]<=0 or pd.isna(d["sma200"].iloc[i]) or i<=last:
                continue
            if strategy=="combo":
                fire = (d["ret1"].iloc[i]>0 and d["volume"].iloc[i]>=SPIKE_X*d["volma"].iloc[i]
                        and d["close"].iloc[i]>d["sma50"].iloc[i]
                        and d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL)
                fn=sim_combo
            else:  # trend: reclaim 50MA while in a 50>200 uptrend (fresh cross)
                fire = (d["close"].iloc[i]>d["sma50"].iloc[i] and d["close"].iloc[i-1]<=d["sma50"].iloc[i-1]
                        and d["sma50"].iloc[i]>d["sma200"].iloc[i])
                fn=sim_trend
            if fire:
                pnl,bars=fn(d,i); last=i+bars
                xi=min(i+bars,len(d)-1)
                trades.append({"ticker":t,"entry":d["time"].iloc[i],"exit":d["time"].iloc[xi],
                               "pnl":pnl-FEE,"bars":bars})
    return trades

def stats(rows,label):
    if not rows: print(f"  {label:8} no trades"); return
    df=pd.DataFrame(rows); n=len(df); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al=df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  {label:8} n={n:4} win={wr:4.0f}%  avgW/L=+{aw:5.1f}/{al:6.1f}  "
          f"exp={df.pnl.mean():+5.2f}%  hold={df.bars.mean():3.0f}d  total={df.pnl.sum():+7.0f}%")

def main():
    print("Building both strategies on the watchlist...\n")
    combo=collect("combo"); trend=collect("trend")
    print("="*78+"\n  SIGNAL EDGE (net fees, 3y)\n"+"="*78)
    stats(combo,"COMBO"); stats(trend,"TREND")
    print("\n"+"="*78+"\n  $1,000 PORTFOLIO  (25% × max4)\n"+"="*78)
    crash=lambda tr:[x for x in tr if x["entry"]>=pd.Timestamp("2025-08-01")]
    for label,tr in [("COMBO",combo),("TREND",trend)]:
        a=simulate(tr,0.25,4); b=simulate(crash(tr),0.25,4)
        print(f"  {label:7} full 3y: ${a['final']:>7,.0f} ({a['final']/START:.1f}x, DD {a['maxdd']:.0f}%)"
              f"   ·   since Aug'25: ${b['final']:>7,.0f} ({b['final']/START:.1f}x, DD {b['maxdd']:.0f}%)")
    print("\n  COMBO = short volume-spike swing · TREND = ride the 50/200 uptrend for months.")

if __name__ == "__main__":
    main()
