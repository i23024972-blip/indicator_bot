# crypto_htf_breakout.py — LuxAlgo "Previous HTF High/Low breakout" on CRYPTO, BOTH directions.
# 4H bars · break ABOVE previous day's high = LONG, break BELOW previous day's low = SHORT.
# (Crypto futures let you short, so the indicator's full dual-direction finally gets used.)
# Tests FIXED 3:1 TP/SL (faithful to LuxAlgo) vs RIDE (trail, let winners run). Reports long vs
# short separately + false-breakout rate. Raw price moves — leverage would multiply these.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT"]
INTERVAL="4h"; DAYS=365
SL_ATR=3.0; TP_ATR=9.0          # 3:1  (TP 9ATR / SL 3ATR)
TRAIL_ATR=4.0; FALSE_BARS=2
FEE=0.08                         # % round-trip (taker perp ~0.04%*2 + slippage)
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
    df["ma"]=df["close"].ewm(span=200,adjust=False).mean()   # trend filter (≈33d on 4h)
    return df

def sim(df, mode, tfilter=False):
    o,hi,lo,cl=df["open"].values,df["high"].values,df["low"].values,df["close"].values
    a=df["atr"].values; pdh=df["pdh"].values; pdl=df["pdl"].values; ma=df["ma"].values
    n=len(df); out=[]; i=20
    while i<n-2:
        if np.isnan(a[i]) or a[i]<=0 or np.isnan(pdh[i]) or np.isnan(pdl[i]): i+=1; continue
        longb  = cl[i]>pdh[i] and cl[i-1]<=pdh[i]
        shortb = cl[i]<pdl[i] and cl[i-1]>=pdl[i]
        if tfilter and not np.isnan(ma[i]):                    # trade only WITH the trend
            longb  = longb  and cl[i]>ma[i]
            shortb = shortb and cl[i]<ma[i]
        if not (longb or shortb): i+=1; continue
        dir = 1 if longb else -1; lvl = pdh[i] if longb else pdl[i]
        k=i+1; entry=o[k]
        if mode=="FIXED":
            SL=entry-dir*SL_ATR*a[i]; TP=entry+dir*TP_ATR*a[i]
        else:
            SL=entry-dir*SL_ATR*a[i]; runext=entry
        end=min(k+120,n-1); pnl=None; how=None; xk=end
        for j in range(k,end+1):
            # false breakout: closes back through the level within N bars
            if j<=i+FALSE_BARS and ((dir==1 and cl[j]<lvl) or (dir==-1 and cl[j]>lvl)):
                pnl=dir*(cl[j]-entry)/entry*100; how="FALSE"; xk=j; break
            if mode=="FIXED":
                if dir==1:
                    if lo[j]<=SL: pnl=(SL-entry)/entry*100; how="SL"; xk=j; break
                    if hi[j]>=TP: pnl=(TP-entry)/entry*100; how="TP"; xk=j; break
                else:
                    if hi[j]>=SL: pnl=(entry-SL)/entry*100; how="SL"; xk=j; break
                    if lo[j]<=TP: pnl=(entry-TP)/entry*100; how="TP"; xk=j; break
            else:  # RIDE — chandelier trail
                runext = max(runext,hi[j]) if dir==1 else min(runext,lo[j])
                aj=a[j] if not np.isnan(a[j]) else a[i]
                SL = max(SL, runext-TRAIL_ATR*aj) if dir==1 else min(SL, runext+TRAIL_ATR*aj)
                if (dir==1 and lo[j]<=SL) or (dir==-1 and hi[j]>=SL):
                    px=SL; pnl=dir*(px-entry)/entry*100; how="TRAIL"; xk=j; break
        if pnl is None: pnl=dir*(cl[end]-entry)/entry*100; how="OPEN"; xk=end
        out.append(dict(dir="L" if dir==1 else "S", pnl=pnl-FEE, how=how, bars=xk-k)); i=xk+1
    return out

def report(rows,lab):
    if not rows: print(f"  {lab}: none"); return
    df=pd.DataFrame(rows);
    def stat(s):
        if len(s)==0: return "—"
        return f"{len(s):>3} · win {(s.pnl>0).mean()*100:>3.0f}% · avg {s.pnl.mean():>+5.1f}% · cum {s.pnl.sum():>+6.0f}%"
    print(f"  {lab}")
    print(f"     ALL  : {stat(df)}  · false {((df.how=='FALSE').mean()*100):.0f}%")
    print(f"     LONG : {stat(df[df.dir=='L'])}")
    print(f"     SHORT: {stat(df[df.dir=='S'])}")

def main():
    print(f"CRYPTO HTF-BREAKOUT (prev-day H/L) · {INTERVAL} · {len(SYMBOLS)} coins · {DAYS}d · both dirs\n")
    data={}
    for s in SYMBOLS:
        try: data[s]=fetch(s); print(f"  {s}: {len(data[s])} bars")
        except Exception as e: print(f"  {s}: {e}")
    for mode in ["FIXED","RIDE"]:
        for tf in [False,True]:
            rows=[]
            for s,df in data.items():
                for x in sim(df,mode,tf): x["sym"]=s; rows.append(x)
            tag=f"{mode} · {'TREND-FILTERED' if tf else 'unfiltered'}"
            print("\n"+"="*60+f"\n  {tag}\n"+"="*60)
            report(rows,"both directions")
    print("\n  'cum' = sum of per-trade % (≈ return at 1x). Leverage multiplies it (and the risk).")
    print("  Did the trend filter cut the false longs and lift the total into the green?")

if __name__=="__main__":
    main()
