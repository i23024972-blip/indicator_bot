# idx_hybrid_backtest.py — Regime-switched HYBRID vs the two pure strategies.
#   HYBRID  : regime (IHSG) at entry decides the play —
#               HEALTHY        -> TREND entry (ride the uptrend for months)
#               CAUTION/CRASH  -> COMBO entry (defensive volume-spike swing)
#   HYBRID+CX: same, but ALSO force-exit any open trade the day regime flips to CRASH.
# Compared to pure COMBO and pure TREND. Same fees + portfolio framework.
import sys
import pandas as pd
import idx_konglo as K
from idx_scan import WATCHLIST
from idx_portfolio import simulate, START
from idx_regime import load_ihsg

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SPIKE_X, FEE = 2.5, 0.4
C_SL, C_TP, C_HOLD = 2.0, 6.0, 20
T_STOP, T_MAXHOLD = 3.0, 120

ix = load_ihsg()
RSERIES = ix["regime"].copy(); RSERIES.index = pd.to_datetime(RSERIES.index).normalize()
CRASH_DATES = set(RSERIES.index[RSERIES == "CRASH"])
def regime_at(ts):
    try: return RSERIES.asof(pd.Timestamp(ts).normalize())
    except Exception: return "HEALTHY"

def prep(t):
    d, w = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < 260 or w is None or len(w) < 20:
        return None
    d["atr"]=K.atr_series(d); d["volma"]=d["volume"].rolling(20).mean()
    d["sma50"]=d["close"].rolling(50).mean(); d["sma200"]=d["close"].rolling(200).mean()
    d["ret1"]=d["close"].pct_change()
    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    d["sd"]=[K.structure_at(zz_d,i) for i in range(len(d))]
    sw=[]
    for i in range(len(d)):
        wk=w[w["time"]<=d["time"].iloc[i]]; sw.append(K.structure_at(zz_w,wk.index[-1]) if len(wk) else "neutral")
    d["sw"]=sw
    return d

def fire_combo(d,i):
    return (d["ret1"].iloc[i]>0 and d["volume"].iloc[i]>=SPIKE_X*d["volma"].iloc[i]
            and d["close"].iloc[i]>d["sma50"].iloc[i]
            and d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL)
def fire_trend(d,i):
    return (d["close"].iloc[i]>d["sma50"].iloc[i] and d["close"].iloc[i-1]<=d["sma50"].iloc[i-1]
            and d["sma50"].iloc[i]>d["sma200"].iloc[i])

def sim_combo(d,i,cx=False):
    atr=d["atr"].iloc[i]; e=d["close"].iloc[i]; sl,tp=e-C_SL*atr,e+C_TP*atr; end=min(i+C_HOLD,len(d)-1)
    for j in range(i+1,end+1):
        if d["low"].iloc[j]<=sl: return (sl-e)/e*100,j-i
        if d["high"].iloc[j]>=tp: return (tp-e)/e*100,j-i
        if cx and d["time"].iloc[j].normalize() in CRASH_DATES and regime_at(d["time"].iloc[j-1])!="CRASH":
            return (d["close"].iloc[j]-e)/e*100,j-i
    return (d["close"].iloc[end]-e)/e*100,end-i
def sim_trend(d,i,cx=False):
    atr=d["atr"].iloc[i]; e=d["close"].iloc[i]; stop=e-T_STOP*atr; end=min(i+T_MAXHOLD,len(d)-1)
    for j in range(i+1,end+1):
        if d["low"].iloc[j]<=stop: return (stop-e)/e*100,j-i
        if d["close"].iloc[j]<d["sma50"].iloc[j]: return (d["close"].iloc[j]-e)/e*100,j-i
        if cx and d["time"].iloc[j].normalize() in CRASH_DATES and regime_at(d["time"].iloc[j-1])!="CRASH":
            return (d["close"].iloc[j]-e)/e*100,j-i
    return (d["close"].iloc[end]-e)/e*100,end-i

def collect(mode):   # mode: 'combo','trend','hybrid','hybrid_cx'
    trades=[]
    for t in WATCHLIST:
        d=prep(t)
        if d is None: continue
        last=-1
        for i in range(200,len(d)-1):
            if pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i]<=0 or pd.isna(d["sma200"].iloc[i]) or i<=last:
                continue
            reg=regime_at(d["time"].iloc[i])
            cx = (mode=="hybrid_cx")
            if mode in ("combo",):
                fire,fn=fire_combo(d,i),sim_combo
            elif mode in ("trend",):
                fire,fn=fire_trend(d,i),sim_trend
            else:  # hybrid: regime picks the play
                if reg=="HEALTHY":
                    fire,fn=fire_trend(d,i),sim_trend
                else:
                    fire,fn=fire_combo(d,i),sim_combo
            if fire:
                pnl,bars=fn(d,i,cx) if mode.startswith("hybrid") else fn(d,i)
                last=i+bars; xi=min(i+bars,len(d)-1)
                trades.append({"ticker":t,"entry":d["time"].iloc[i],"exit":d["time"].iloc[xi],
                               "pnl":pnl-FEE,"bars":bars})
    return trades

def stats(rows,label):
    if not rows: print(f"  {label:11} no trades"); return
    df=pd.DataFrame(rows); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al=df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  {label:11} n={len(df):4} win={wr:4.0f}%  avgW/L=+{aw:5.1f}/{al:6.1f}  "
          f"exp={df.pnl.mean():+5.2f}%  hold={df.bars.mean():3.0f}d  total={df.pnl.sum():+7.0f}%")

def main():
    print("Building strategies (this scans the watchlist a few times)...\n")
    runs={m:collect(m) for m in ["combo","trend","hybrid","hybrid_cx"]}
    print("="*80+"\n  SIGNAL EDGE (net fees, 3y)\n"+"="*80)
    for m,lab in [("combo","COMBO"),("trend","TREND"),("hybrid","HYBRID"),("hybrid_cx","HYBRID+CX")]:
        stats(runs[m],lab)
    print("\n"+"="*80+"\n  $1,000 PORTFOLIO  (25% × max4)\n"+"="*80)
    crash=lambda tr:[x for x in tr if x["entry"]>=pd.Timestamp("2025-08-01")]
    for m,lab in [("combo","COMBO"),("trend","TREND"),("hybrid","HYBRID"),("hybrid_cx","HYBRID+CX")]:
        a=simulate(runs[m],0.25,4); b=simulate(crash(runs[m]),0.25,4)
        print(f"  {lab:11} 3y: ${a['final']:>7,.0f} ({a['final']/START:4.1f}x, DD {a['maxdd']:2.0f}%)"
              f"   ·   crash: ${b['final']:>6,.0f} ({b['final']/START:.1f}x, DD {b['maxdd']:2.0f}%)")
    print("\n  HYBRID = TREND in healthy / COMBO in caution+crash · +CX also force-exits on a crash flip.")

if __name__ == "__main__":
    main()
