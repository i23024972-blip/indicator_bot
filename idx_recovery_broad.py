# idx_recovery_broad.py — UNBIASED forward test. Recovery-style vs DONCH50+200 on the BROAD
# IDX board (~395 names, NOT the hindsight-picked konglo winners), 2022-2026, with a
# point-in-time liquidity gate. This is "what would I have made betting it blind" — no
# knowing in advance which names recover/explode.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_recovery import simulate, atr14, START_EQ, TRAIL_ATR, INIT_ATR, MAXHOLD, SLIP, FEE
from idx_discover import UNIVERSE

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S, E = "2022-06-01", "2026-12-31"
MIN_TURN = 10e9

def ride_b(d, mode, risk):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
    sma20=pd.Series(cl).rolling(20).mean().values
    sma50=pd.Series(cl).rolling(50).mean().values
    sma200=pd.Series(cl).rolling(200).mean().values
    d20=pd.Series(hi).rolling(20).max().shift(1).values
    d50=pd.Series(hi).rolling(50).max().shift(1).values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURN: i+=1; continue
        ro=bool(risk.asof(pd.Timestamp(t[i])))
        if mode=="RECOVERY":
            fire = ro and not np.isnan(d20[i]) and not np.isnan(sma20[i]) and cl[i]>d20[i] and cl[i]>sma20[i]
        else:
            fire = not np.isnan(d50[i]) and not np.isnan(sma200[i]) and cl[i]>d50[i] and cl[i]>sma200[i]
        if not fire: i+=1; continue
        k=i+1
        if o[k]>hi[i]*1.04: i+=1; continue
        entry=o[k]*(1+SLIP); stop=entry-INIT_ATR*a; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
            if j>k and not np.isnan(sma50[j]) and cl[j]<sma50[j]: pnl=(cl[j]*(1-SLIP)-entry)/entry*100; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "pnl":pnl-FEE,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"UNBIASED recovery vs DONCH50+200 · BROAD board ({len(UNIVERSE)} names) · {S}→now\n")
    ih=yf.download("^JKSE",start=S,end=E,progress=False,auto_adjust=True)
    if hasattr(ih.columns,"levels"): ih.columns=ih.columns.get_level_values(0)
    ih.columns=[c.lower() for c in ih.columns]
    risk=pd.Series((ih["close"]>ih["close"].rolling(50).mean()).values, index=ih.index.tz_localize(None).normalize())

    built={}; tickers=[t+".JK" for t in UNIVERSE]
    for kk in range(0,len(tickers),25):
        chunk=tickers[kk:kk+25]
        try: data=yf.download(chunk,start=S,end=E,progress=False,auto_adjust=True,group_by="ticker")
        except Exception: continue
        for tk in chunk:
            try:
                d=data[tk].dropna().copy(); d.columns=[c.lower() for c in d.columns]
                if len(d)<210: continue
                d=d.reset_index().rename(columns={d.reset_index().columns[0]:"time"})
                d["time"]=pd.to_datetime(d["time"]); d["atr"]=atr14(d)
                d["turn20"]=(d["close"]*d["volume"]).rolling(20).median()
                built[tk]=d
            except Exception: pass
        print(f"  ...{min(kk+25,len(tickers))}/{len(tickers)} (usable {len(built)})", flush=True)

    for mode in ["RECOVERY","DONCH50+200"]:
        trades=[]
        for tk,d in built.items():
            for x in ride_b(d,mode,risk): x["ticker"]=tk; trades.append(x)
        if not trades: print(f"\n  {mode}: no trades"); continue
        df=pd.DataFrame(trades); wr=(df.pnl>0).mean()*100; final,maxdd=simulate(trades)
        print("\n"+"="*60+f"\n  {mode} — BROAD UNBIASED\n"+"="*60)
        print(f"  Trades {len(df)} across {df.ticker.nunique()} names · win {wr:.0f}% · hold {df.bars.mean():.0f}d")
        print(f"  Avg win +{df[df.pnl>0].pnl.mean():.0f}% / loss {df[df.pnl<=0].pnl.mean():.0f}% · exp {df.pnl.mean():+.1f}%")
        print(f"  $1k → ${final:,.0f} ({final/START_EQ:.1f}x) · MaxDD {maxdd:.0f}%")
    print(f"\n  vs KONGLO (survivorship): recovery 5.2x · DONCH 6.5x")
    print("  Honest forward expectation = the BROAD numbers above, not the konglo backtest.")

if __name__=="__main__":
    main()
