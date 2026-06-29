# idx_entry_timing.py — Does BETTING EARLY beat waiting for high conviction?
# Holds the proven LOOSE ride exit constant (EMA50 break / 4-ATR trail) and varies ONLY
# when you enter, to answer: is it better to bet the breakout early, wait for follow-through
# confirmation, or chase once it's an "obvious" high-conviction mover?
#   EARLY   : buy-stop just above signal high, fill next session (bet before it's proven).
#   CONFIRM : wait up to 4d, enter only once it CLOSES above the trigger (follow-through).
#   CHASE   : enter only after price is already +8% past the signal high (now it's "obvious").
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
INIT_ATR=2.5; TRAIL_ATR=4.0; EMA_LEN=50; MAXHOLD=250   # the proven LOOSE exit

def ride_from(arrays, ema, k, entry):
    o,hi,lo,cl,atr = arrays
    n=len(cl); stop=entry-INIT_ATR*atr[k]; runmax=entry; end=min(k+MAXHOLD,n-1)
    for j in range(k,end+1):
        runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else atr[k]
        stop=max(stop,runmax-TRAIL_ATR*aj)
        if lo[j]<=stop:           return (stop*(1-SLIP)-entry)/entry*100, j
        if j>k and cl[j]<ema[j]:  return (cl[j]*(1-SLIP)-entry)/entry*100, j
    return (cl[end]*(1-SLIP)-entry)/entry*100, end

def trades_for(d, mode):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    arrays=(o,hi,lo,cl,atr); n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_combo(d,i): i+=1; continue
        trig=hi[i]*(1+TRIG_BUF); k=None; entry=None
        if mode=="EARLY":
            kk=i+1
            if o[kk]>hi[i]*(1+MAXGAP): i+=1; continue
            if o[kk]>=trig: k,entry=kk,o[kk]*(1+SLIP)
            elif hi[kk]>=trig: k,entry=kk,trig*(1+SLIP)
            else: i+=1; continue
        elif mode=="CONFIRM":                       # wait for a CLOSE above the trigger
            for kk in range(i+1,min(i+5,n)):
                if cl[kk]>trig:
                    if cl[kk]>hi[i]*(1+MAXGAP+0.05): break   # ran away — too far to enter
                    k,entry=kk,cl[kk]*(1+SLIP); break
            if k is None: i+=1; continue
        else:                                        # CHASE: enter only once +8% past signal high
            tgt=hi[i]*1.08
            for kk in range(i+1,min(i+16,n)):
                if hi[kk]>=tgt: k,entry=kk,max(o[kk],tgt)*(1+SLIP); break
            if k is None: i+=1; continue
        pnl,xk=ride_from(arrays,ema,k,entry)
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "pnl":pnl-FEE,"bars":xk-k,"delay":k-i})
        i=xk+1
    return out

def main():
    print(f"ENTRY-TIMING TEST · same LOOSE exit · konglo · last {WINDOW_YEARS}y\n")
    tickers=K.all_tickers()
    data=yf.download(tickers,period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in tickers:
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    print(f"  {'entry style':30}{'trades':>7}{'win%':>6}{'entryDelay':>11}{'exp%':>7}{'  $1k→':>14}{'MaxDD':>7}")
    print("  "+"-"*80)
    for mode,lab in [("EARLY","EARLY bet (breakout trigger)"),
                     ("CONFIRM","CONFIRM (wait for close>trigger)"),
                     ("CHASE","CHASE (+8% — 'obvious' winner)")]:
        trades=[]
        for tk in tickers:
            d=built[tk]
            if d is None: continue
            for x in trades_for(d,mode): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {lab:30} no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.25,4)
        print(f"  {lab:30}{len(df):>7}{wr:>5.0f}%{df.delay.mean():>9.1f}d{df.pnl.mean():>+6.1f}%"
              f"   ${r['final']:>7,.0f} ({r['final']/START:.1f}x){r['maxdd']:>6.0f}%")
    print(f"\n  'entryDelay' = days after the EOD signal that you actually got in.")
    print("  Question answered: does betting EARLY beat waiting until it's high-conviction?")

if __name__=="__main__":
    main()
