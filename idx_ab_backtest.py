# idx_ab_backtest.py — head-to-head backtest of the EXACT A/B strategies as the bot runs them.
#   A = DONCH50+200 : 50d-high breakout >200MA · confirm buy-stop · ride 50EMA + 4ATR trail
#   B = COMBO       : up + 2.5x vol + >50MA + zigzag · next-open entry · 2ATR stop / 6ATR target / 20d max
# Konglo, last 2y, 20%×5 sizing. So you see the backtest comparison before trusting it forward.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
A_EMA=50; A_TRAIL=4.0; A_INIT=2.5; DONCH=50
B_SL=2.0; B_TP=6.0; B_HOLD=20

def fire_donch(d,i):
    r=d.iloc[i]
    if pd.isna(r.get("donch")) or pd.isna(r["sma200"]): return False
    return r["close"]>r["donch"] and r["close"]>r["sma200"]

def ride_A(d):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
    ema=d["close"].ewm(span=A_EMA,adjust=False).mean().values
    sma200=d["close"].rolling(200).mean().values
    donch=d["high"].rolling(DONCH).max().shift(1).values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if np.isnan(donch[i]) or np.isnan(sma200[i]) or not(cl[i]>donch[i] and cl[i]>sma200[i]): i+=1; continue
        trig=hi[i]*(1+TRIG_BUF); k=i+1
        if o[k]>hi[i]*(1+MAXGAP): i+=1; continue
        if o[k]>=trig: entry=o[k]*(1+SLIP)
        elif hi[k]>=trig: entry=trig*(1+SLIP)
        else: i+=1; continue
        stop=entry-A_INIT*a; runmax=entry; end=min(k+250,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-A_TRAIL*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
            if j>k and cl[j]<ema[j]: pnl=(cl[j]*(1-SLIP)-entry)/entry*100; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),"pnl":pnl-FEE,"bars":xk-k}); i=xk+1
    return out

def ride_B(d):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_combo(d,i): i+=1; continue
        k=i+1
        if o[k]>hi[i]*(1+MAXGAP): i+=1; continue
        entry=o[k]*(1+SLIP); stop=entry-B_SL*a; tp=entry+B_TP*a
        end=min(k+B_HOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
            if hi[j]>=tp:   pnl=(tp*(1-SLIP)-entry)/entry*100; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),"pnl":pnl-FEE,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"A/B BACKTEST · konglo · last {WINDOW_YEARS}y · 20%×5 sizing\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try:
            d=build(tk,data[tk].copy())
            if d is not None: d["donch"]=d["high"].rolling(DONCH).max().shift(1)
            built[tk]=d
        except Exception: built[tk]=None
    print(f"  {'strategy':16}{'trades':>7}{'win%':>6}{'avgHold':>9}{'avg':>7}{'  $16M →':>14}{'MaxDD':>7}")
    print("  "+"-"*64)
    for name,fn in [("A · DONCH ride",ride_A),("B · COMBO 3:1",ride_B)]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in fn(d): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {name:16} no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
        rp=16_000_000*(r["final"]/START)
        print(f"  {name:16}{len(df):>7}{wr:>5.0f}%{df.bars.mean():>7.0f}d{df.pnl.mean():>+6.1f}%"
              f"   Rp {rp:>10,.0f}{r['maxdd']:>6.0f}%")
    print("\n  (Konglo backtest = optimistic/survivorship. Forward will be lower — the A/B")
    print("   paper test is the REAL judge. This is just the historical starting point.)")

if __name__=="__main__":
    main()
