# idx_ema_sweep.py — isolate the EXIT EMA. Holds confirmation entry + 4-ATR trail + 2.5-ATR
# initial stop constant; sweeps only the EMA the ride exits on (30/40/50/60/70). Answers
# "is 30 or 40 better than 50?" AND doubles as a robustness check: stable across values =
# solid edge; a lone spike at 50 = overfit warning.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
TRAIL_ATR, INIT_ATR, MAXHOLD = 4.0, 2.5, 250

def ride(d, ema_len):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=ema_len, adjust=False).mean().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_combo(d,i): i+=1; continue
        trig=hi[i]*(1+TRIG_BUF); k=i+1
        if o[k]>hi[i]*(1+MAXGAP): i+=1; continue
        if o[k]>=trig: entry=o[k]*(1+SLIP)
        elif hi[k]>=trig: entry=trig*(1+SLIP)
        else: i+=1; continue
        risk=INIT_ATR*a; stop=entry-risk; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry); xk=j; break
            if j>k and cl[j]<ema[j]: pnl=(cl[j]*(1-SLIP)-entry); xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry); xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "R":pnl/risk,"pnl":pnl/entry*100,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"EXIT-EMA SWEEP · konglo binary ride · last {WINDOW_YEARS}y  (only the EMA changes)\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    print(f"  {'EMA':>5}{'trades':>8}{'win%':>6}{'avgHold':>9}{'exp/R':>7}{'  $1k→(25%x4)':>15}{'MaxDD':>7}")
    print("  "+"-"*60)
    for el in [30,40,50,60,70]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in ride(d, el): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {el:>5}  no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.25,4)
        star=" ←50 baseline" if el==50 else ""
        print(f"  {el:>5}{len(df):>8}{wr:>5.0f}%{df.bars.mean():>7.0f}d{df.R.mean():>+6.2f}"
              f"   ${r['final']:>8,.0f} ({r['final']/START:.1f}x){r['maxdd']:>6.0f}%{star}")
    print("\n  Faster EMA (30/40) = exits sooner on the turn (shorter holds, gives back less)")
    print("  Slower EMA (60/70) = rides longer (holds the monsters, but bigger givebacks).")
    print("  If 40/50/60 are all close → robust. If 50 is a lone spike → overfit warning.")

if __name__=="__main__":
    main()
