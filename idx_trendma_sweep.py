# idx_trendma_sweep.py — is the 200MA trend filter "too wide"? Sweep it (50/100/150/200) with
# the SAME DONCH50 breakout + ride exit. Looser MA = catch recoveries earlier (more trades) but
# more bull-traps in a downturn. Also counts RECENT (last ~180d crash) entries — the place a
# looser filter would generate false signals. Robustness check too: stable = solid, not overfit.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50

def ride(d, trend_n):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    sma = pd.Series(cl).rolling(trend_n).mean().values
    donch = pd.Series(hi).rolling(DONCH).max().shift(1).values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if np.isnan(sma[i]) or np.isnan(donch[i]) or not (cl[i]>donch[i] and cl[i]>sma[i]): i+=1; continue
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
    print(f"TREND-FILTER SWEEP · DONCH50 + N-day MA · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=build(tk,data[tk].copy())
        except Exception: built[tk]=None
    recent_cut = pd.Timestamp.now().normalize() - pd.DateOffset(days=180)
    print(f"  {'filter':10}{'trades':>7}{'win%':>6}{'hold':>6}{'exp/R':>7}{'  $1k→':>9}{'MaxDD':>7}{'  last6mo':>9}")
    print("  "+"-"*64)
    for N in [50,100,150,200]:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in ride(d,N): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {N}MA  no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
        recent=df[df.entry>=recent_cut]
        rec_wr = (recent.pnl>0).mean()*100 if len(recent) else 0
        tag=" ←current" if N==200 else ""
        print(f"  {str(N)+'MA':10}{len(df):>7}{wr:>5.0f}%{df.bars.mean():>5.0f}d{df.R.mean():>+6.2f}"
              f"   {r['final']/START:>5.1f}x{r['maxdd']:>6.0f}%   {len(recent):>3} ({rec_wr:.0f}%win){tag}")
    print("\n  'last6mo' = trades the filter took during the recent crash (and their win rate).")
    print("  Looser MA (50/100) trades MORE in the crash — check if those are wins or bull-traps.")

if __name__=="__main__":
    main()
