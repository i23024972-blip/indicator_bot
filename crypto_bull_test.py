# crypto_bull_test.py — REGIME-DIRECTIONAL strategy (Eric's idea): BULL→longs only, BEAR→shorts
# only, CRASH→cash. Backtested on a 5-month BULL window from history (2024 run-up) to see how
# the LONG side performs in its proper regime. 0.2% fees, $1k, risk-based sizing.
import sys, time, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

FETCH_START="2024-01-01"; FETCH_END="2025-03-01"          # data range (incl. warmup)
TEST_START="2024-09-01";  TEST_END="2025-02-01"           # 5-month test window (bull run)
INTERVAL="4h"; SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2; START=1000
MIN_VOL=50e6; TOPN=40; VOL_LO,VOL_HI=0.8,3.2; RISK=1.0

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
    kl=client.futures_historical_klines(sym, INTERVAL, FETCH_START, FETCH_END)
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

def trades(df,reg,lo,hi):
    o,hI,lO,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values; t=df["time"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]) or np.isnan(ma[i]): i+=1; continue
        rg=reg.asof(pd.Timestamp(t[i]).normalize())
        longb =rg=="BULL" and cl[i]>pdh[i] and cl[i-1]<=pdh[i] and cl[i]>ma[i]     # longs ONLY in bull
        shortb=rg=="BEAR" and cl[i]<pdl[i] and cl[i-1]>=pdl[i] and cl[i]<ma[i]     # shorts ONLY in bear
        if not (longb or shortb): i+=1; continue
        dir=1 if longb else -1; lvl=pdh[i] if longb else pdl[i]
        k=i+1; entry=o[k]; risk=SL_ATR*a[i]; SL=entry-dir*risk; runext=entry; end=min(k+120,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            if j<=i+FALSE_BARS and ((dir==1 and cl[j]<lvl) or (dir==-1 and cl[j]>lvl)): pnl=dir*(cl[j]-entry)/entry*100; xk=j; break
            runext=max(runext,hI[j]) if dir==1 else min(runext,lO[j]); aj=a[j] if not np.isnan(a[j]) else a[i]
            SL=max(SL,runext-TRAIL_ATR*aj) if dir==1 else min(SL,runext+TRAIL_ATR*aj)
            if (dir==1 and lO[j]<=SL) or (dir==-1 and hI[j]>=SL): pnl=dir*(SL-entry)/entry*100; xk=j; break
        if pnl is None: pnl=dir*(cl[end]-entry)/entry*100; xk=end
        if lo<=pd.Timestamp(t[k])<hi:
            out.append(dict(entry=pd.Timestamp(t[k]), R=(pnl-FEE)/(risk/entry*100), dir=dir))
        i+=max(1,xk-i)
    return out

def main():
    print(f"REGIME-DIRECTIONAL · BULL test window {TEST_START}→{TEST_END} · 0.2% fee · $1k\n")
    info=client.futures_exchange_info()
    syms=[s["symbol"] for s in info["symbols"] if s["symbol"].endswith("USDT") and s.get("contractType")=="PERPETUAL" and s["status"]=="TRADING"]
    vol={t["symbol"]:float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid=sorted([s for s in syms if vol.get(s,0)>=MIN_VOL], key=lambda s:-vol.get(s,0))[:TOPN]
    lo=pd.Timestamp(TEST_START); hi=pd.Timestamp(TEST_END)
    data={}
    for s in liquid:
        try: data[s]=fetch(s)
        except Exception: pass
    reg=btc_regime(data["BTCUSDT"])
    regwin=reg[(reg.index>=lo)&(reg.index<hi)]
    print(f"  Test-window regime mix: " + " · ".join(f"{r} {(regwin==r).mean()*100:.0f}%" for r in ['BULL','BEAR','CRASH']))
    allt=[]; used=0
    for s,df in data.items():
        if not (VOL_LO <= (df["atr"]/df["close"]).median()*100 <= VOL_HI): continue
        ts=trades(df,reg,lo,hi)
        if ts: used+=1
        for x in ts: allt.append(x)
    df=pd.DataFrame(allt).sort_values("entry")
    eq=1.0; c=[]
    for R in df.R: eq*=(1+RISK/100*R); c.append(eq)
    peak=-1; dd=0
    for e in c: peak=max(peak,e); dd=max(dd,(peak-e)/peak*100)
    L=df[df.dir==1]; S=df[df.dir==-1]
    pf=df[df.R>0].R.sum()/max(-df[df.R<=0].R.sum(),0.01)
    print(f"  {used} coins traded · {len(df)} trades ({len(L)} long / {len(S)} short)\n")
    print("="*56)
    print(f"  $1,000 → ${START*eq:,.0f}  (+{(eq-1)*100:.0f}% in 5 months) · MaxDD {dd:.0f}%")
    print(f"  win {(df.R>0).mean()*100:.0f}% · profit factor {pf:.2f} · risk {RISK}%/trade")
    print("="*56)
    print("\n  Regime-directional = longs in bull, shorts in bear, cash in crash. This window")
    print("  is the BULL test for the LONG side it couldn't show in the recent bear market.")

if __name__=="__main__":
    main()
