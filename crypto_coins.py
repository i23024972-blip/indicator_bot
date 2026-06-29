# crypto_coins.py — which coins make the strategy money, and what do the winners share?
# Runs RIDE+trend-filter+crash-filter per coin over 1y, ranks by profit (cumR), and measures
# each coin's volatility (ATR%) + trendiness (how often price stays on one side of its MA) to
# find the characteristic of the WINNING coins — so we know what kind of coins to add.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

UNIVERSE=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT",
 "LINKUSDT","DOTUSDT","LTCUSDT","NEARUSDT","APTUSDT","ARBUSDT","OPUSDT","INJUSDT","SUIUSDT",
 "SEIUSDT","TIAUSDT","FILUSDT","ATOMUSDT","UNIUSDT","AAVEUSDT","TRXUSDT","1000PEPEUSDT",
 "1000SHIBUSDT","WIFUSDT","ENAUSDT","HYPEUSDT","ORDIUSDT"]
INTERVAL="4h"; DAYS=365; SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2
import time
def mkclient():
    for _ in range(6):
        try: return Client(requests_params={"timeout":30})
        except Exception as e: print(f"  (binance connect retry: {str(e)[:60]})"); time.sleep(6)
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

def trades(df,reg):
    o,hi,lo,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values; t=df["time"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]) or np.isnan(ma[i]): i+=1; continue
        if reg.asof(pd.Timestamp(t[i]).normalize())=="CRASH": i+=1; continue        # crash filter
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
        out.append(pnl-FEE if False else (pnl-FEE)/(risk/entry*100)); i+=max(1,xk-i)   # R-multiple
    return out

def main():
    print(f"PER-COIN PROFIT · RIDE+filters · {INTERVAL} · 1y · {len(UNIVERSE)} coins\n")
    data={}
    for s in UNIVERSE:
        try: data[s]=fetch(s)
        except Exception: pass
    reg=btc_regime(data["BTCUSDT"]); rows=[]
    for s,df in data.items():
        rs=trades(df,reg)
        if not rs: continue
        rs=np.array(rs)
        volpct=float((df["atr"]/df["close"]).median()*100)            # volatility characteristic
        # trendiness: % of bars price is on one side of MA (high = trendy, ~50% = choppy)
        above=(df["close"]>df["ma"]).mean(); trendy=abs(above-0.5)*200
        rows.append(dict(sym=s.replace("USDT",""), n=len(rs), cumR=rs.sum(),
                         win=(rs>0).mean()*100, vol=volpct, trend=trendy))
    d=pd.DataFrame(rows).sort_values("cumR",ascending=False)
    print(f"  {'coin':9}{'cumR':>7}{'win%':>6}{'trades':>7}{'vol%':>6}{'trendy':>8}")
    print("  "+"-"*46)
    for _,r in d.iterrows():
        print(f"  {r['sym']:9}{r['cumR']:>+6.0f}{r['win']:>5.0f}%{int(r['n']):>7}{r['vol']:>5.1f}%{r['trend']:>7.0f}%")
    top=d.head(8); bot=d.tail(8)
    print("\n"+"="*52+"\n  WHAT DO THE WINNERS SHARE?\n"+"="*52)
    print(f"  TOP 8 coins : avg vol {top.vol.mean():.1f}% · avg trendiness {top.trend.mean():.0f}% · avg cumR {top.cumR.mean():+.0f}")
    print(f"  BOTTOM 8    : avg vol {bot.vol.mean():.1f}% · avg trendiness {bot.trend.mean():.0f}% · avg cumR {bot.cumR.mean():+.0f}")
    print(f"\n  Winners: {', '.join(top.sym.head(6))}")
    print("  → Add coins matching the winners' vol% / trendiness profile (not just 'popular' ones).")

if __name__=="__main__":
    main()
