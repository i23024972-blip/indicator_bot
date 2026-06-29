# crypto_regime.py — does the strategy work in ALL regimes or just the crash? Detect BTC regime
# (BULL / BEAR / CRASH) over 3 years and break the RIDE+trend-filter strategy's performance down
# by regime. If it earns in BULL (via longs) AND CRASH (via shorts) → adaptive & robust. If it
# only earns in crash → it's a bear strategy, and the +149% was just the down-year.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","DOGEUSDT"]
INTERVAL="4h"; DAYS=1095
SL_ATR=3.0; TRAIL_ATR=4.0; FALSE_BARS=2; FEE=0.2
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

def btc_regime(btc):
    d=btc.set_index("time")["close"].resample("D").last().dropna()
    ma200=d.rolling(200).mean()
    dd=d/d.rolling(90).max()-1
    reg=pd.Series(index=d.index, dtype=object)
    for dt in d.index:
        if pd.isna(ma200.get(dt)): reg[dt]="?"
        elif dd.get(dt,0) <= -0.25: reg[dt]="CRASH"
        elif d.get(dt) > ma200.get(dt): reg[dt]="BULL"
        else: reg[dt]="BEAR"
    return reg

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
        out.append(dict(entry=pd.Timestamp(t[k]), R=pnl/(risk/entry*100), pnl=pnl, dir=dir)); i+=max(1,xk-i)
    return out

def main():
    print(f"CRYPTO REGIME ANALYSIS · RIDE+trend-filter · {INTERVAL} · {len(SYMBOLS)} coins · {DAYS}d (3y)\n")
    data={}
    for s in SYMBOLS:
        try: data[s]=fetch(s); print(f"  {s}: {len(data[s])} bars")
        except Exception as e: print(f"  {s}: {e}")
    reg=btc_regime(data["BTCUSDT"])
    # time in each regime
    print(f"\n  BTC regime mix (3y): " + " · ".join(f"{r} {(reg==r).mean()*100:.0f}%" for r in ['BULL','BEAR','CRASH']))

    allt=[]
    for s,df in data.items():
        for x in trades(df):
            x["sym"]=s; x["reg"]=reg.asof(x["entry"].normalize()); allt.append(x)
    df=pd.DataFrame(allt)
    print(f"\n{'='*72}\n  STRATEGY PERFORMANCE BY REGIME\n{'='*72}")
    print(f"  {'regime':8}{'trades':>7}{'win%':>6}{'expR':>7}{'cumR':>8}{'  longs(cumR)':>15}{'  shorts(cumR)':>15}")
    print("  "+"-"*70)
    for r in ["BULL","BEAR","CRASH"]:
        s=df[df.reg==r]
        if len(s)==0: print(f"  {r:8} (no trades)"); continue
        L=s[s.dir==1]; S=s[s.dir==-1]
        print(f"  {r:8}{len(s):>7}{(s.pnl>0).mean()*100:>5.0f}%{s.R.mean():>+6.2f}{s.R.sum():>+7.0f}"
              f"{('+'+format(L.R.sum(),'.0f')+'R ('+str(len(L))+')'):>15}{('+'+format(S.R.sum(),'.0f')+'R ('+str(len(S))+')'):>15}")
    print("  "+"-"*70)
    print(f"  {'TOTAL':8}{len(df):>7}{(df.pnl>0).mean()*100:>5.0f}%{df.R.mean():>+6.2f}{df.R.sum():>+7.0f}")
    print("\n  cumR = sum of R-multiples (×your risk% = return). KEY: is it +R in BULL (longs) AND")
    print("  CRASH (shorts)? If yes → adaptive/robust. If only CRASH → it's just a bear strategy.")

if __name__=="__main__":
    main()
