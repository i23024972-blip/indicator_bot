# crypto_equity.py — proper equity curve + MAX DRAWDOWN for the winning crypto strategy
# (RIDE + trend-filter, both directions). Uses RISK-BASED sizing (risk fixed % of equity per
# trade, stop defines position size) — the correct way to size a leveraged strategy. Sweeps the
# risk % so you see return vs drawdown, and what's survivable BEFORE adding leverage.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT"]
INTERVAL="4h"; DAYS=365
SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2   # 0.2% round-trip per trade (taker + slippage)
START_USD=1000
client=Client()

def atr(df,n=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    return pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1).rolling(n).mean()

def fetch(sym):
    kl=client.get_historical_klines(sym, INTERVAL, f"{DAYS} days ago UTC")
    df=pd.DataFrame(kl,columns=["t","open","high","low","close","v","ct","q","n","tb","tq","ig"])
    for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["t"],unit="ms"); df["atr"]=atr(df)
    df["day"]=df["time"].dt.floor("D")
    dh=df.groupby("day")["high"].max().shift(1); dl=df.groupby("day")["low"].min().shift(1)
    df["pdh"]=df["day"].map(dh); df["pdl"]=df["day"].map(dl)
    df["ma"]=df["close"].ewm(span=200,adjust=False).mean()
    return df

def trades(df):
    o,hi,lo,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values; t=df["time"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]) or np.isnan(ma[i]): i+=1; continue
        longb  = cl[i]>pdh[i] and cl[i-1]<=pdh[i] and cl[i]>ma[i]
        shortb = cl[i]<pdl[i] and cl[i-1]>=pdl[i] and cl[i]<ma[i]
        if not (longb or shortb): i+=1; continue
        dir=1 if longb else -1; lvl=pdh[i] if longb else pdl[i]
        k=i+1; entry=o[k]; risk=SL_ATR*a[i]; SL=entry-dir*risk; runext=entry
        end=min(k+120,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            if j<=i+FALSE_BARS and ((dir==1 and cl[j]<lvl) or (dir==-1 and cl[j]>lvl)):
                pnl=dir*(cl[j]-entry)/entry*100; xk=j; break
            runext=max(runext,hi[j]) if dir==1 else min(runext,lo[j])
            aj=a[j] if not np.isnan(a[j]) else a[i]
            SL=max(SL,runext-TRAIL_ATR*aj) if dir==1 else min(SL,runext+TRAIL_ATR*aj)
            if (dir==1 and lo[j]<=SL) or (dir==-1 and hi[j]>=SL):
                pnl=dir*(SL-entry)/entry*100; xk=j; break
        if pnl is None: pnl=dir*(cl[end]-entry)/entry*100; xk=end
        pnl-=FEE
        riskpct=risk/entry*100
        out.append(dict(exit=pd.Timestamp(t[xk]), R=pnl/riskpct, pnl=pnl, dir=dir)); i=xk+1
    return out

def maxdd(curve):
    peak=-1; dd=0
    for e in curve:
        peak=max(peak,e); dd=max(dd,(peak-e)/peak*100)
    return dd

def main():
    print(f"CRYPTO EQUITY+DRAWDOWN · RIDE+trend-filter · {INTERVAL} · {len(SYMBOLS)} coins · {DAYS}d\n")
    allt=[]
    for s in SYMBOLS:
        try:
            for x in trades(fetch(s)): x["sym"]=s; allt.append(x)
        except Exception as e: print(f"  {s}: {e}")
    allt.sort(key=lambda x:x["exit"])
    df=pd.DataFrame(allt)
    wr=(df.pnl>0).mean()*100
    gp=df[df.R>0].R.sum(); gl=-df[df.R<=0].R.sum()
    pf=gp/gl if gl>0 else 99
    print(f"  {len(df)} trades · win {wr:.0f}% · avg {df.R.mean():+.2f}R · profit factor {pf:.2f}")
    print(f"  expectancy {df.R.mean():+.2f}R/trade · best {df.R.max():.1f}R · worst {df.R.min():.1f}R\n")
    print("="*68)
    print(f"  {'risk/trade':12}{'$1k →':>12}{'CAGR':>9}{'MaxDD':>8}{'worst $ dip':>15}")
    print("="*68)
    for rp in [0.5,1.0,2.0,3.0,5.0]:
        eq=1.0; curve=[]
        for R in df.R: eq*= (1+rp/100*R); curve.append(eq)
        dd=maxdd(curve); yrs=DAYS/365
        cagr=(eq**(1/yrs)-1)*100 if eq>0 else -100
        worst = START_USD*(1-dd/100)   # rough $ at the worst drawdown point (from peak)
        print(f"  {rp:>5.1f}%      ${START_USD*eq:>10,.0f}{cagr:>+8.0f}%{dd:>7.0f}%   (−{dd:.0f}% swing)")
    print("="*68)
    print("\n  MaxDD here is on REALIZED equity (closed trades). True intra-trade DD is a bit worse.")
    print("  Rule: if MaxDD at your risk level approaches ~50%, that's the leverage ceiling —")
    print("  beyond it a bad streak liquidates you. Pick risk% where MaxDD stays manageable.")

if __name__=="__main__":
    main()
