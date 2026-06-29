# idx_scaled_exit.py — Eric's scaled-exit management on the 89-name QUALITY universe.
# Instead of binary in/out (which gives back gains on high-ADR whipsaws), SCALE:
#   · Take profit in tiers as it rallies  → TP1 +12% (sell 1/3), TP2 +30% (sell 1/3),
#     final 1/3 RIDES (captures the 40%+ strong runs). After TP1, stop → breakeven.
#   · Reduce bit-by-bit on WEAKNESS       → each close below the fast EMA(10), sell half
#     of what's left (a dud bleeds out small instead of taking a full stop).
#   · Hard floor                          → wide initial stop; final dump on close < EMA50.
# Goal: lift the quality universe's 36% win / 2.3x by banking strength + shrinking losers.
import sys, json, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4; MAXHOLD=250
INIT_ATR=2.5
TP1, TP1F = 12.0, 1/3
TP2, TP2F = 30.0, 1/3
EMA_FAST, EMA_SLOW = 10, 50
WEAK_SELL = 0.5

def scaled(arrays, ef, es, k, entry, a):
    o,hi,lo,cl = arrays; n=len(cl)
    rem=1.0; realized=0.0; tp1=tp2=False; stop=entry-INIT_ATR*a; end=min(k+MAXHOLD,n-1); xk=end
    for j in range(k, end+1):
        if rem>1e-6 and lo[j] <= stop:                                   # hard / breakeven stop
            realized += rem*((stop*(1-SLIP)-entry)/entry*100); rem=0; xk=j; break
        if not tp1 and hi[j] >= entry*(1+TP1/100):                       # bank TP1
            realized += TP1F*((entry*(1+TP1/100)*(1-SLIP)-entry)/entry*100); rem-=TP1F; tp1=True; stop=max(stop,entry)
        if not tp2 and hi[j] >= entry*(1+TP2/100):                       # bank TP2
            realized += TP2F*((entry*(1+TP2/100)*(1-SLIP)-entry)/entry*100); rem-=TP2F; tp2=True
        if j>k and rem>1e-6 and cl[j] < ef[j]:                           # weakness: scale out half
            sell=WEAK_SELL*rem; realized += sell*((cl[j]*(1-SLIP)-entry)/entry*100); rem-=sell
        if j>k and rem>1e-6 and cl[j] < es[j]:                           # trend over: dump remainder
            realized += rem*((cl[j]*(1-SLIP)-entry)/entry*100); rem=0; xk=j; break
        if rem<=1e-6: xk=j; break
    if rem>1e-6:
        realized += rem*((cl[xk]*(1-SLIP)-entry)/entry*100)
    return realized - FEE, xk-k

def find(d):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn=d["atr"].values,d["turn20"].values; t=d["time"].values
    ef=pd.Series(cl).ewm(span=EMA_FAST,adjust=False).mean().values
    es=pd.Series(cl).ewm(span=EMA_SLOW,adjust=False).mean().values
    arrays=(o,hi,lo,cl); n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_combo(d,i): i+=1; continue
        trig=hi[i]*(1+TRIG_BUF); k=i+1
        if o[k]>hi[i]*(1+MAXGAP): i+=1; continue
        if o[k]>=trig: entry=o[k]*(1+SLIP)
        elif hi[k]>=trig: entry=trig*(1+SLIP)
        else: i+=1; continue
        pnl,bars=scaled(arrays,ef,es,k,entry,a)
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[k+bars]),
                    "pnl":pnl,"bars":bars}); i=k+bars+1
    return out

def main():
    uni=json.load(open("idx_universe.json"))["tickers"]
    print(f"SCALED-EXIT · quality universe ({len(uni)} names) · last {WINDOW_YEARS}y")
    print(f"TP1 +{TP1:.0f}%(⅓) · TP2 +{TP2:.0f}%(⅓) · runner rides · scale out ½ per weak EMA{EMA_FAST} close\n")
    tickers=[t+".JK" for t in uni]; trades=[]
    for kk in range(0,len(tickers),25):
        chunk=tickers[kk:kk+25]
        try: data=yf.download(chunk,period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
        except Exception: continue
        for t in chunk:
            try: d=build(t,data[t].copy())
            except Exception: d=None
            if d is None: continue
            for x in find(d): x["ticker"]=t.replace(".JK",""); trades.append(x)
        print(f"  ...{min(kk+25,len(tickers))}/{len(tickers)}", flush=True)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
    df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean(); al=df[df.pnl<=0].pnl.mean()
    print("\n"+"="*78+"\n  SCALED-EXIT on quality universe\n"+"="*78)
    print(f"  Trades      : {len(df)} across {df.ticker.nunique()} names")
    print(f"  Win rate    : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d   ·   exp {df.pnl.mean():+.2f}%/trade")
    print(f"  Avg win/loss: +{aw:.1f}% / {al:.1f}%")
    print("\n"+"="*78+"\n  $1,000 PORTFOLIO\n"+"="*78)
    print(f"  {'scheme':22}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}")
    for lab,f,m in [("25% × max4",0.25,4),("15% × max6",0.15,6),("12% × max8",0.12,8),("10% × max10",0.10,10)]:
        r=simulate(win,f,m)
        print(f"  {lab:22}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%{r['maxdd']:>6.0f}%")
    print(f"\n  vs BINARY trend-ride on same universe: 2.3x / 36% win / 20% MaxDD.")
    print("  Did scaling lift win rate + shrink losers + improve risk-adjusted return?")

if __name__=="__main__":
    main()
