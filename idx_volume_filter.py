# idx_volume_filter.py — test Eric's "low volume = few people = skip" logic.
# Adds a breakout-day VOLUME confirmation to DONCH50+200: only take the 50-day-high breakout
# if that day's volume >= VMULT x its 20-day average (real participation). Sweep VMULT.
# Does skipping low-volume breakouts improve win rate / return — or just cut good trades?
# (Note: a liquidity gate >Rp10bn/day already applies; this is the EXTRA conviction filter.)
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50

def ride(d, vmult):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    vol=d["volume"].values; atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
    ema=pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    sma200=pd.Series(cl).rolling(200).mean().values
    donch=pd.Series(hi).rolling(DONCH).max().shift(1).values
    volma=pd.Series(vol).rolling(20).mean().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if np.isnan(donch[i]) or np.isnan(sma200[i]) or not(cl[i]>donch[i] and cl[i]>sma200[i]): i+=1; continue
        if vmult>0 and (np.isnan(volma[i]) or vol[i] < vmult*volma[i]): i+=1; continue   # volume gate
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
    print(f"VOLUME-CONFIRMATION sweep · DONCH50+200 · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    print(f"  {'breakout volume req':22}{'trades':>7}{'win%':>6}{'exp/R':>7}{'  $1k→':>9}{'MaxDD':>7}")
    print("  "+"-"*60)
    for vm in [0,1.0,1.5,2.0,2.5]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in ride(d,vm): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {('vol>='+str(vm)+'x'):22} no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
        lab = "none (baseline)" if vm==0 else f"vol >= {vm}x avg"
        star=" ←current" if vm==0 else ""
        print(f"  {lab:22}{len(df):>7}{wr:>5.0f}%{df.R.mean():>+6.2f}   {r['final']/START:>5.1f}x{r['maxdd']:>6.0f}%{star}")
    print("\n  If higher volume req improves win%/return → Eric's logic holds (skip dead breakouts).")
    print("  If it just cuts trades without improving → the liquidity gate already handles it.")

if __name__=="__main__":
    main()
