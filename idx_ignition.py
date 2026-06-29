# idx_ignition.py — Eric's idea: enter near the IGNITION, not a month early.
# Replaces the plain "up-day + volume spike" trigger with a SQUEEZE→EXPANSION detector:
#   · Squeeze   : price coiled in a TIGHT range over the last CONSOL days (the boring base).
#   · Ignition  : today CLOSES above that base high on a VOLUME surge (the breakout).
# Then same confirmation entry + ride-above-50EMA + chandelier exit. Goal: skip the dead
# month + false starts. Trade-off: enter higher, miss movers that rip without coiling first.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

CONSOL=15; SQUEEZE_PCT=0.22; VOL_X=2.0          # base = 15d, range<22%, vol>=2x = ignition
TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD = 50, 4.0, 2.5, 250

def fire_ignition(d, i):
    if i < CONSOL+5: return False
    base = d.iloc[i-CONSOL:i]
    bh, bl = base["high"].max(), base["low"].min()
    if bl <= 0 or pd.isna(d["volma"].iloc[i]) or pd.isna(d["sma50"].iloc[i]): return False
    tight  = (bh - bl) / bl <= SQUEEZE_PCT                  # coiled tight
    broke  = d["close"].iloc[i] > bh                        # breaks the base
    volok  = d["volume"].iloc[i] >= VOL_X * d["volma"].iloc[i]
    trend  = d["close"].iloc[i] > d["sma50"].iloc[i]
    return tight and broke and volok and trend

def ride(d):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_ignition(d,i): i+=1; continue
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
    print(f"IGNITION ENTRY (squeeze→expansion) · konglo · last {WINDOW_YEARS}y")
    print(f"base {CONSOL}d, range<{SQUEEZE_PCT*100:.0f}%, vol>={VOL_X}x · then ride 50EMA\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=build(tk,data[tk].copy())
        except Exception: d=None
        if d is None: continue
        for x in ride(d): x["ticker"]=tk.replace(".JK",""); trades.append(x)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
    df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean(); al=df[df.pnl<=0].pnl.mean()
    print("="*72+"\n  IGNITION ENTRY — results\n"+"="*72)
    print(f"  Trades      : {len(df)} across {df.ticker.nunique()} names")
    print(f"  Win rate    : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d   ·   exp {df.R.mean():+.2f}R/trade")
    print(f"  Avg win/loss: +{aw:.1f}% / {al:.1f}%")
    print("\n  $1,000 PORTFOLIO:")
    for lab,f,m in [("25% × max4",0.25,4),("33% × max3",0.33,3)]:
        r=simulate(win,f,m)
        print(f"    {lab:14}${r['final']:>8,.0f} ({r['final']/START:.1f}x)  CAGR {r['cagr']:+.0f}%  MaxDD {r['maxdd']:.0f}%")
    print("\n  Entry dates on the big names (did it catch the IGNITION, not the early pop?):")
    for nm in ["DEWA","BUVA","PANI","BRPT","CUAN"]:
        sub=df[df.ticker==nm]
        for _,r in sub.iterrows():
            print(f"    {nm:6} {str(r['entry'].date())}  → {r['pnl']:+.0f}% ({r['bars']}d, {r['R']:+.1f}R)")
    print(f"\n  BENCHMARK — plain trigger (enters early): 4.1x · 60% win · DEWA entered 2025-07-22.")
    print("  Watch whether ignition pushes DEWA's entry toward Sept (near the real launch).")

if __name__=="__main__":
    main()
