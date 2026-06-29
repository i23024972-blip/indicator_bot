# idx_r_distribution.py — the honest version of the influencer's screenshot.
# Runs your binary-ride konglo strategy and computes each trade's R-MULTIPLE (profit ÷ the
# initial risk you took). Shows how often a 1:10 (10R) winner actually happens on YOUR names,
# and how much of the total profit comes from the few big-R trades.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD = 50, 4.0, 2.5, 250

def ride_R(d):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
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
        risk = INIT_ATR*a                                  # the "1" you risked (per share)
        stop=entry-risk; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry); xk=j; break
            if j>k and cl[j]<ema[j]: pnl=(cl[j]*(1-SLIP)-entry); xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry); xk=end
        R = pnl / risk                                     # R-multiple
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"R":R,
                    "pnl_pct":pnl/entry*100,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"R-MULTIPLE DISTRIBUTION · konglo binary ride · last {WINDOW_YEARS}y\n")
    data = yf.download(K.all_tickers(), period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=build(tk, data[tk].copy())
        except Exception: d=None
        if d is None: continue
        for x in ride_R(d): x["ticker"]=tk.replace(".JK",""); trades.append(x)
    win=[t for t in trades if t["entry"]>=CUTOFF]
    df=pd.DataFrame(win)
    n=len(df)
    print(f"  {n} trades · expectancy {df.R.mean():+.2f}R/trade · max {df.R.max():.1f}R "
          f"({df.loc[df.R.idxmax(),'ticker']}, {df.R.max()*0+df.pnl_pct.max():.0f}%... see below)\n")

    buckets = [(-99,-0.8,"full loss  (≤ -0.8R)"),(-0.8,0,"partial loss (-0.8–0R)"),
               (0,1,"small win  (0–1R)"),(1,3,"1–3R"),(3,5,"3–5R"),
               (5,10,"5–10R"),(10,20,"10–20R  ← '1:10'"),(20,999,"20R+  🚀")]
    print("="*68)
    print(f"  {'bucket':24}{'trades':>8}{'% of all':>10}{'% of profit':>14}")
    print("="*68)
    tot_pos_R = df[df.R>0].R.sum()
    for lo_,hi_,lab in buckets:
        sub=df[(df.R>lo_)&(df.R<=hi_)]
        share_profit = (sub[sub.R>0].R.sum()/tot_pos_R*100) if tot_pos_R>0 else 0
        print(f"  {lab:24}{len(sub):>8}{len(sub)/n*100:>9.0f}%{share_profit:>13.0f}%")
    print("="*68)

    big = df[df.R>=5].sort_values("R",ascending=False)
    print(f"\n  Your '1:10-style' trades (≥5R):")
    if len(big)==0:
        print("    none hit 5R")
    for _,r in big.iterrows():
        print(f"    {str(r['entry'].date())}  {r['ticker']:6}  {r['R']:5.1f}R  ({r['pnl_pct']:+.0f}%, {r['bars']}d)")
    winrate=(df.R>0).mean()*100
    print(f"\n  Win rate {winrate:.0f}% · {len(big)} of {n} trades ({len(big)/n*100:.0f}%) were ≥5R")
    print(f"  Those {len(big)} trades made {df[df.R>=5].R.sum()/tot_pos_R*100:.0f}% of all the profit.")
    print(f"  → THIS is 'low win rate, big wins': a few fat-tail trades carry everything.")

if __name__=="__main__":
    main()
