# idx_reversal.py — the REVERSAL bet (Eric's idea): instead of buying confirmed strength,
# bet the TURN early using indicator confluence:
#   · MACD(12,26,9) bullish cross   (momentum turning up)
#   · Stochastic(10,5,5) crossing up FROM oversold (<30)   (bounce from a low)
#   · close reclaims the 9 EMA      (price turning up)
# Entry = buy-stop above the signal-day high (only if the bounce follows through). Exit keeps
# the framework: cut at 2.5 ATR if wrong, ride a 4-ATR chandelier trail if jackpot ("hold till
# it reverses"). Tested vs the DONCH50+200 trend-follower (4.7x) — does catching the turn early
# beat buying confirmed strength, or just catch falling knives (esp. in the crash)?
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START
from ta.trend import MACD, EMAIndicator
from ta.momentum import StochasticOscillator

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
TRAIL_ATR, INIT_ATR, MAXHOLD = 4.0, 2.5, 250

def addind(d):
    c,h,l = d["close"], d["high"], d["low"]
    m = MACD(c, window_slow=26, window_fast=12, window_sign=9)
    d["macd"]=m.macd(); d["macd_sig"]=m.macd_signal()
    s = StochasticOscillator(h,l,c, window=10, smooth_window=5)
    d["k"]=s.stoch(); d["dst"]=s.stoch_signal()
    d["ema9"]=EMAIndicator(c, 9).ema_indicator()
    return d

def fire_reversal(d, i):
    if i<5: return False
    macd_bull = d["macd"].iloc[i] > d["macd_sig"].iloc[i]
    macd_fresh= d["macd"].iloc[i-1] <= d["macd_sig"].iloc[i-1] or d["macd"].iloc[i-2] <= d["macd_sig"].iloc[i-2]
    stoch_bull= d["k"].iloc[i] > d["dst"].iloc[i]
    oversold  = (d["k"].iloc[i-3:i+1] < 30).any()           # came from oversold = a real bounce
    reclaim   = d["close"].iloc[i] > d["ema9"].iloc[i]
    if any(pd.isna(d[x].iloc[i]) for x in ["macd","macd_sig","k","dst","ema9"]): return False
    return macd_bull and macd_fresh and stoch_bull and oversold and reclaim

def ride_rev(d):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_reversal(d,i): i+=1; continue
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
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry); xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "R":pnl/risk,"pnl":pnl/entry*100,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"REVERSAL bet · MACD+Stoch+9EMA · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=addind(build(tk,data[tk].copy()))
        except Exception: d=None
        if d is None: continue
        for x in ride_rev(d): x["ticker"]=tk; trades.append(x)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
    if not win:
        print("  no trades"); return
    df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.20,5)
    recent=df[df.entry>=pd.Timestamp.now().normalize()-pd.DateOffset(days=180)]
    rec_wr=(recent.pnl>0).mean()*100 if len(recent) else 0
    print("="*64+"\n  REVERSAL bet — results\n"+"="*64)
    print(f"  Trades        : {len(df)} across {df.ticker.nunique()} names")
    print(f"  Win rate      : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d   ·   exp {df.R.mean():+.2f}R")
    print(f"  Avg win/loss  : +{df[df.pnl>0].pnl.mean():.1f}% / {df[df.pnl<=0].pnl.mean():.1f}%")
    print(f"  $1k→ (20%x5)  : {r['final']/START:.1f}x   ·   MaxDD {r['maxdd']:.0f}%")
    print(f"  In the CRASH (last 6mo): {len(recent)} trades, {rec_wr:.0f}% win  ← knives or bottoms?")
    print(f"\n  BENCHMARK — DONCH50+200 trend-follower: 4.7x · 51% win · 8% DD")
    print("  Verdict: does betting the reversal early beat buying confirmed strength?")

if __name__=="__main__":
    main()
