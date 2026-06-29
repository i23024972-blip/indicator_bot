# idx_htf_breakout.py — LuxAlgo "Previous HTF High breakout" ported to Python + backtested.
# Logic: break out when close crosses ABOVE the previous higher-timeframe period's high (we use
# previous WEEK's high). 2:1 TP/SL off ATR. FALSE breakout = price closes back below the level
# within 2 bars. Long-only (Eric's style). Compares BASE vs a FAKE-REDUCED version (uptrend
# filter + breakout buffer + volume) to see if we can cut the false breakouts he complained about.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SLIP=0.003; FEE=0.4; SL_ATR=3.0; TP_ATR=6.0; MAXHOLD=60   # 2:1 (TP 6ATR / SL 3ATR)
FALSE_BARS=2                                                # false breakout if reverses within N bars

def run(d, mode):
    d=d.copy()
    d["wk"]=d["time"].dt.to_period("W")
    wkhigh=d.groupby("wk")["high"].max()
    d["prevhi"]=d["wk"].map(wkhigh.shift(1))               # previous week's high (the level)
    d["volma"]=d["volume"].rolling(20).mean()
    d["sma200"]=d["close"].rolling(200).mean()
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    vol=d["volume"].values; volma=d["volma"].values; atr=d["atr"].values
    turn=d["turn20"].values; sma200=d["sma200"].values; lvl=d["prevhi"].values; t=d["time"].values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER or np.isnan(lvl[i]): i+=1; continue
        # breakout = close crosses above previous-week high
        broke = cl[i]>lvl[i] and cl[i-1]<=lvl[i]
        if not broke: i+=1; continue
        if mode=="FILTERED":
            if np.isnan(sma200[i]) or cl[i]<=sma200[i]: i+=1; continue          # uptrend only
            if cl[i] < lvl[i]*1.01: i+=1; continue                              # 1% buffer over level
            if np.isnan(volma[i]) or vol[i] < 1.5*volma[i]: i+=1; continue      # participation
        k=i+1; entry=o[k]*(1+SLIP); SL=entry-SL_ATR*a; TP=entry+TP_ATR*a
        end=min(k+MAXHOLD,n-1); pnl=None; how=None; xk=end
        for j in range(k,end+1):
            if j<=i+FALSE_BARS and cl[j]<lvl[i]:                                # FALSE breakout
                pnl=(cl[j]*(1-SLIP)-entry)/entry*100; how="FALSE"; xk=j; break
            if lo[j]<=SL: pnl=(SL*(1-SLIP)-entry)/entry*100; how="SL"; xk=j; break
            if hi[j]>=TP: pnl=(TP*(1-SLIP)-entry)/entry*100; how="TP"; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; how="OPEN"; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "pnl":pnl-FEE,"how":how,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"HTF-BREAKOUT (prev-week high) · konglo · last {WINDOW_YEARS}y · 2:1 TP/SL\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    print(f"  {'version':12}{'breaks':>7}{'false%':>8}{'TP%':>6}{'SL%':>6}{'win%':>6}{'avg':>7}{'  $1k→':>8}")
    print("  "+"-"*60)
    for mode,lab in [("BASE","all breakouts"),("FILTERED","uptrend+buffer+vol")]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in run(d,mode): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {lab:20} no trades"); continue
        df=pd.DataFrame(win); n=len(df)
        falsep=(df.how=="FALSE").mean()*100; tpp=(df.how=="TP").mean()*100; slp=(df.how=="SL").mean()*100
        wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
        print(f"  {lab:12}{n:>7}{falsep:>7.0f}%{tpp:>5.0f}%{slp:>5.0f}%{wr:>5.0f}%{df.pnl.mean():>+6.1f}%   {r['final']/START:.1f}x")
    print("\n  Compare BASE vs FILTERED: does the uptrend+buffer+volume filter cut false% and lift")
    print("  return? And how does it stack vs DONCH50+200 (4.7x)? Fixed 2:1 TP caps the runners.")

if __name__=="__main__":
    main()
