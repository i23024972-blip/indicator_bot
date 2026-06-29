# idx_entry_breakout.py — Eric's question: buy BEFORE the breakout (cheaper) vs ON the breakout
# (confirmed)? Tests 3 entries into the same DONCH50+200 setup, same ride exit:
#   ANTICIPATE : buy at close when price is within 3% BELOW the 50-day high (pre-breakout bet)
#   AT-CLOSE   : buy at the close of the day it breaks the 50-day high (breakout, no wait)
#   CONFIRM    : buy-stop 0.5% above the breakout-day high, fill next day (current — double-confirm)
# Cheaper entry vs fewer fakeouts — which nets more? Also reports how often each gets
# stopped fast (the "fake breakout drops" Eric described).
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4; ANTIC=0.03
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50

def ride(d, mode):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
    ema=pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    sma200=pd.Series(cl).rolling(200).mean().values
    donch=pd.Series(hi).rolling(DONCH).max().shift(1).values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if np.isnan(donch[i]) or np.isnan(sma200[i]): i+=1; continue
        up=cl[i]>sma200[i]; k=None; entry=None
        if mode=="ANTICIPATE":
            # within 3% BELOW the 50d-high, not yet broken, uptrend → bet the break
            if up and cl[i]<donch[i] and cl[i]>=donch[i]*(1-ANTIC):
                k=i+1; entry=o[k]*(1+SLIP) if False else cl[i]*(1+SLIP)  # fill at this close
        elif mode=="AT-CLOSE":
            if up and cl[i]>donch[i]: k=i+1; entry=cl[i]*(1+SLIP)        # breakout-day close
        else:  # CONFIRM
            if up and cl[i]>donch[i]:
                trig=hi[i]*(1+TRIG_BUF); kk=i+1
                if o[kk]>hi[i]*(1+MAXGAP): i+=1; continue
                if o[kk]>=trig: k,entry=kk,o[kk]*(1+SLIP)
                elif hi[kk]>=trig: k,entry=kk,trig*(1+SLIP)
        if k is None or entry is None or k>=n: i+=1; continue
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
    print(f"ENTRY: before vs on breakout · DONCH50+200 · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    print(f"  {'entry':14}{'trades':>7}{'win%':>6}{'fast-stop%':>11}{'exp/R':>7}{'  $1k→':>9}{'MaxDD':>7}")
    print("  "+"-"*64)
    for mode,lab in [("ANTICIPATE","before breakout"),("AT-CLOSE","on breakout"),("CONFIRM","confirmed (now)")]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in ride(d,mode): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {lab:14} no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
        faststop=(df.bars<=3).mean()*100      # exited within 3 days = the fake-breakout drop
        print(f"  {lab:14}{len(df):>7}{wr:>5.0f}%{faststop:>10.0f}%{df.R.mean():>+6.2f}   {r['final']/START:>5.1f}x{r['maxdd']:>6.0f}%")
    print("\n  'fast-stop%' = trades killed within 3 days = the fake-breakout drops you described.")
    print("  Cheaper entry (anticipate) vs fewer fakes (confirm) — which wins net?")

if __name__=="__main__":
    main()
