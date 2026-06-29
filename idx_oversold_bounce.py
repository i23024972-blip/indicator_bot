# idx_oversold_bounce.py — the long shot from the crash-pump pattern. Buy oversold PULLBACKS,
# but ONLY where relative strength held (still above 200MA = not a deep-crash knife) and ONLY on
# bounce CONFIRMATION (reclaiming the 20MA = the turn started, not catching the fall).
#   fire = above 200MA  AND  >10% off the recent 15d high (real pullback)  AND  closes back
#          up through the 20MA (cl crosses above sma20). Entry next open, ride trail + 20MA exit.
# Broad liquid universe, 2023-now. Reports overall AND the crash sub-period (2026+). Is it +EV
# or just a prettier knife-catch?
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_discover import UNIVERSE
from idx_recovery import simulate, START_EQ

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S="2023-01-01"; SLIP=0.003; FEE=0.4; MIN_TURN=10e9
INIT_ATR, TRAIL_ATR, MAXHOLD = 2.0, 3.5, 120

def atr14(d):
    h,l,c=d["high"],d["low"],d["close"]; pc=c.shift(1)
    return pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1).rolling(14).mean()

def find(d):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; t=d["time"].values
    turn=(d["close"]*d["volume"]).rolling(20).median().values
    sma20=pd.Series(cl).rolling(20).mean().values
    sma200=pd.Series(cl).rolling(200).mean().values
    hh15=pd.Series(hi).rolling(15).max().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURN: i+=1; continue
        if np.isnan(sma200[i]) or np.isnan(sma20[i]) or np.isnan(hh15[i]): i+=1; continue
        above200 = cl[i]>sma200[i]
        pulled = cl[i] < 0.90*hh15[i]                       # >10% off recent high = real dip
        reclaim = cl[i]>sma20[i] and cl[i-1]<=sma20[i-1]    # turning up through 20MA = confirmation
        if not (above200 and pulled and reclaim): i+=1; continue
        k=i+1;
        if o[k]>cl[i]*1.05: i+=1; continue                 # gapped up too far
        entry=o[k]*(1+SLIP); stop=entry-INIT_ATR*a; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
            if j>k and not np.isnan(sma20[j]) and cl[j]<sma20[j]: pnl=(cl[j]*(1-SLIP)-entry)/entry*100; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "pnl":pnl-FEE,"bars":xk-k}); i=xk+1
    return out

def report(rows,lab):
    if not rows: print(f"  {lab}: no trades"); return
    df=pd.DataFrame(rows); wr=(df.pnl>0).mean()*100; final,dd=simulate(rows,0.20,5)
    print(f"  {lab:18}{len(df):>4} trades · win {wr:>3.0f}% · avg {df.pnl.mean():>+6.1f}% · "
          f"hold {df.bars.mean():>3.0f}d · {final/START_EQ:>4.1f}x · DD {dd:>3.0f}%")

def main():
    print(f"OVERSOLD-BOUNCE (above-200MA pullback + 20MA reclaim) · broad · {S}→now\n")
    tickers=[t+".JK" for t in UNIVERSE]; trades=[]
    for kk in range(0,len(tickers),25):
        chunk=tickers[kk:kk+25]
        data=yf.download(chunk,start=S,progress=False,auto_adjust=True,group_by="ticker")
        for tk in chunk:
            try:
                d=data[tk].dropna().copy(); d.columns=[c.lower() for c in d.columns]
                if len(d)<260: continue
                d=d.reset_index(); d=d.rename(columns={d.columns[0]:"time"}); d["time"]=pd.to_datetime(d["time"])
                d["atr"]=atr14(d)
                for x in find(d): x["ticker"]=tk.replace(".JK",""); trades.append(x)
            except Exception: pass
        print(f"  ...{min(kk+25,len(tickers))}/{len(tickers)}", flush=True)
    print("\n"+"="*78)
    report(trades,"ALL (2023-now)")
    crash=[t for t in trades if t["entry"]>=pd.Timestamp("2026-01-01")]
    report(crash,"CRASH (2026+)")
    print("="*78)
    print("\n  Verdict: is buying confirmed bounces in still-uptrending names +EV, or still a")
    print("  net loser like the pure reversal? Especially in the crash sub-period.")

if __name__=="__main__":
    main()
