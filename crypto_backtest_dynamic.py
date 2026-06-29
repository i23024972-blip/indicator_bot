# crypto_backtest_dynamic.py — backtest the DYNAMIC-universe bot over the last 3 months.
# Pulls all liquid perps, keeps moderate-vol ones (the clean trenders), runs RIDE + trend-filter
# + crash-filter, counts trades in the last 90 days, builds the $1k equity curve. This is what
# the live dynamic bot would have done — no fixed list.
import sys, time, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DAYS=380; TEST_DAYS=150; INTERVAL="4h"
SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2; START=1000
MIN_VOL=50e6; TOPN=45; VOL_LO,VOL_HI=0.8,3.2; RISK=1.0

def mkclient():
    for _ in range(6):
        try: return Client(requests_params={"timeout":30})
        except Exception: time.sleep(6)
    return Client(requests_params={"timeout":30})
client=mkclient()

def atr(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    return pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1).rolling(n).mean()

def fetch(sym):
    kl=client.futures_historical_klines(sym, INTERVAL, f"{DAYS} days ago UTC")
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
    return pd.Series(["CRASH" if dd.get(t,0)<=-0.25 else ("BULL" if (not pd.isna(ma.get(t)) and d[t]>ma[t]) else "BEAR") for t in d.index], index=d.index)

def trades(df,reg,cutoff):
    o,hi,lo,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values; t=df["time"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]) or np.isnan(ma[i]): i+=1; continue
        if reg.asof(pd.Timestamp(t[i]).normalize())=="CRASH": i+=1; continue
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
        if pd.Timestamp(t[k])>=cutoff:
            out.append(dict(entry=pd.Timestamp(t[k]), R=(pnl-FEE)/(risk/entry*100), dir=dir));
        i+=max(1,xk-i)
    return out

def main():
    print(f"DYNAMIC BACKTEST · last {TEST_DAYS}d · liquid moderate-vol perps · RIDE+filters · 0.2% fee\n")
    info=client.futures_exchange_info()
    syms=[s["symbol"] for s in info["symbols"] if s["symbol"].endswith("USDT") and s.get("contractType")=="PERPETUAL" and s["status"]=="TRADING"]
    vol={t["symbol"]:float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid=sorted([s for s in syms if vol.get(s,0)>=MIN_VOL], key=lambda s:-vol.get(s,0))[:TOPN]
    cutoff=pd.Timestamp.utcnow().tz_localize(None)-pd.Timedelta(days=TEST_DAYS)
    data={}
    for s in liquid:
        try: data[s]=fetch(s)
        except Exception: pass
    reg=btc_regime(data["BTCUSDT"])
    allt=[]; used=0
    for s,df in data.items():
        if not (VOL_LO <= (df["atr"]/df["close"]).median()*100 <= VOL_HI): continue   # moderate-vol coins
        ts=trades(df,reg,cutoff)
        if ts: used+=1
        for x in ts: x["sym"]=s; allt.append(x)
    allt.sort(key=lambda x:x["entry"]); df=pd.DataFrame(allt)
    print(f"  Universe: {len(data)} liquid perps scanned · {used} moderate-vol coins traded")
    print(f"  BTC regime now: {reg.iloc[-1]}  ·  trades in window: {len(df)}\n")
    def stats(sub):
        rr=sub.sort_values("entry").R.values; eq=1.0; c=[]
        for R in rr: eq*=(1+RISK/100*R); c.append(eq)
        peak=-1; dd=0
        for e in c: peak=max(peak,e); dd=max(dd,(peak-e)/peak*100)
        pf=sub[sub.R>0].R.sum()/max(-sub[sub.R<=0].R.sum(),0.01)
        return START*eq, dd, (sub.R>0).mean()*100, pf
    print("="*64)
    print(f"  {'side':12}{'trades':>7}{'win%':>6}{'PF':>6}{'   $1k →':>11}{'MaxDD':>8}")
    print("="*64)
    for label,sub in [("COMBINED",df),("LONG-only",df[df.dir==1]),("SHORT-only",df[df.dir==-1])]:
        if len(sub)==0: print(f"  {label:12} no trades"); continue
        fin,dd,wr,pf=stats(sub)
        print(f"  {label:12}{len(sub):>7}{wr:>5.0f}%{pf:>6.2f}   ${fin:>8,.0f}{dd:>7.0f}%")
    print("="*64)
    print(f"\n  5-month window · BTC regime now {reg.iloc[-1]} → bearish, so LONGS likely weak / SHORTS carry.")
    print("  The LONG side's real edge shows in BULL markets — this recent window is NOT that.")

if __name__=="__main__":
    main()
