# crypto_regime_equity.py — $1,000 over 3y: trade ALL regimes vs CRASH-FILTERED (sit out crashes
# like the IDX bot). Risk-based sizing, 0.2% fees. Shows final $, drawdown, and per-regime $ split.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT","HYPEUSDT"]
INTERVAL="4h"; DAYS=1095; SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2; START=1000
client=Client()

def atr(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    return pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1).rolling(n).mean()

def fetch(sym):
    kl=client.futures_historical_klines(sym, INTERVAL, f"{DAYS} days ago UTC")   # perp data
    df=pd.DataFrame(kl,columns=["t","open","high","low","close","v","ct","q","n","tb","tq","ig"])
    for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["t"],unit="ms"); df["atr"]=atr(df)
    df["day"]=df["time"].dt.floor("D")
    df["pdh"]=df["day"].map(df.groupby("day")["high"].max().shift(1))
    df["pdl"]=df["day"].map(df.groupby("day")["low"].min().shift(1))
    df["ma"]=df["close"].ewm(span=200,adjust=False).mean()
    return df

def btc_regime(btc):
    d=btc.set_index("time")["close"].resample("D").last().dropna()
    ma=d.rolling(200).mean(); dd=d/d.rolling(90).max()-1
    return pd.Series(["CRASH" if dd.get(t,0)<=-0.25 else ("BULL" if (not pd.isna(ma.get(t)) and d[t]>ma[t]) else ("BEAR" if not pd.isna(ma.get(t)) else "?")) for t in d.index], index=d.index)

def trades(df):
    o,hi,lo,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values; t=df["time"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]) or np.isnan(ma[i]): i+=1; continue
        longb=cl[i]>pdh[i] and cl[i-1]<=pdh[i] and cl[i]>ma[i]
        shortb=cl[i]<pdl[i] and cl[i-1]>=pdl[i] and cl[i]<ma[i]
        if not (longb or shortb): i+=1; continue
        dir=1 if longb else -1; lvl=pdh[i] if longb else pdl[i]
        k=i+1; entry=o[k]; risk=SL_ATR*a[i]; SL=entry-dir*risk; runext=entry; end=min(k+120,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            if j<=i+FALSE_BARS and ((dir==1 and cl[j]<lvl) or (dir==-1 and cl[j]>lvl)): pnl=dir*(cl[j]-entry)/entry*100; xk=j; break
            runext=max(runext,hi[j]) if dir==1 else min(runext,lo[j]); aj=a[j] if not np.isnan(a[j]) else a[i]
            SL=max(SL,runext-TRAIL_ATR*aj) if dir==1 else min(SL,runext+TRAIL_ATR*aj)
            if (dir==1 and lo[j]<=SL) or (dir==-1 and hi[j]>=SL): pnl=dir*(SL-entry)/entry*100; xk=j; break
        if pnl is None: pnl=dir*(cl[end]-entry)/entry*100; xk=end
        pnl-=FEE; out.append(dict(entry=pd.Timestamp(t[k]), R=pnl/(risk/entry*100))); i+=max(1,xk-i)
    return out

def maxdd(curve):
    peak=-1; dd=0
    for e in curve:
        peak=max(peak,e); dd=max(dd,(peak-e)/peak*100)
    return dd

def run(trs, rp):
    eq=1.0; curve=[]
    for R in trs: eq*=(1+rp/100*R); curve.append(eq)
    return eq, maxdd(curve)

def main():
    print(f"CRYPTO $1k · ALL vs CRASH-FILTERED · {INTERVAL} · {len(SYMBOLS)} coins · 3y · 0.2% fees\n")
    data={}
    for s in SYMBOLS:
        try: data[s]=fetch(s); print(f"  {s}: {len(data[s])} bars ({(data[s]['time'].iloc[-1]-data[s]['time'].iloc[0]).days}d)")
        except Exception as e: print(f"  {s}: skip ({e})")
    reg=btc_regime(data["BTCUSDT"])
    allt=[]
    for s,df in data.items():
        for x in trades(df): x["reg"]=reg.asof(x["entry"].normalize()); x["sym"]=s; allt.append(x)
    allt.sort(key=lambda x:x["entry"])
    df=pd.DataFrame(allt)
    yrs=DAYS/365

    print("="*70)
    print(f"  {'risk':6}{'TRADE ALL regimes':>26}{'CRASH-FILTERED (skip crash)':>30}")
    print("="*70)
    for rp in [0.5,1.0,2.0]:
        ea,dda=run(df.R.values, rp)
        eb,ddb=run(df[df.reg!="CRASH"].R.values, rp)
        print(f"  {rp:>4.1f}%   ${START*ea:>9,.0f}  ({(ea**(1/yrs)-1)*100:+.0f}%/yr, DD {dda:.0f}%)   "
              f"${START*eb:>9,.0f}  ({(eb**(1/yrs)-1)*100:+.0f}%/yr, DD {ddb:.0f}%)")
    print("="*70)
    # per-regime $ contribution at 1% risk
    print(f"\n  Where the money came from (1% risk, $1k start):")
    base=START
    for r in ["BULL","BEAR","CRASH"]:
        sub=df[df.reg==r]
        e,_=run(sub.R.values,1.0)
        print(f"    {r:6}: {len(sub):>4} trades · cum {sub.R.sum():>+5.0f}R · ${'+'if e>=1 else ''}{base*(e-1):>+8,.0f} effect")
    print("\n  Verdict: skipping crashes should LIFT the final $ AND cut the drawdown.")

if __name__=="__main__":
    main()
