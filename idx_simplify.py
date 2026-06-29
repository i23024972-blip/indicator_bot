# idx_simplify.py — strip the strategy down. Market makers can FAKE volume spikes (wash
# trades), breakout levels (stop hunts) and zigzag structure (painted candles). They CANNOT
# fake a sustained multi-month uptrend (needs real capital). So we test an entry-complexity
# ladder — from the full 5-condition trigger down to a pure "is it in a real uptrend?" — all
# riding the SAME robust exit (ride 50EMA + 4-ATR trail). Question: can simpler match it,
# while leaning on the harder-to-manipulate signal?
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SPIKE_X=2.5; TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD = 50, 4.0, 2.5, 250
BULL = {"HH+HL","HL"}

def add(d):
    d=d.copy()
    d["donch20"]=d["high"].rolling(20).max().shift(1)
    d["donch50"]=d["high"].rolling(50).max().shift(1)
    return d

def trig_for(mode, d, i):
    r=d.iloc[i]
    if pd.isna(r["sma50"]) or pd.isna(r["volma"]): return False
    up   = r["ret1"]>0
    vol  = r["volume"]>=SPIKE_X*r["volma"]
    a50  = r["close"]>r["sma50"]
    a200 = r["close"]>r["sma200"] if not pd.isna(r["sma200"]) else False
    if mode=="FULL":        return up and vol and a50 and r["sd"] in BULL and r["sw"] in BULL
    if mode=="VOL+MA":      return up and vol and a50
    if mode=="DONCH20":     return (not pd.isna(r["donch20"])) and r["close"]>r["donch20"] and a50
    if mode=="DONCH50+200": return (not pd.isna(r["donch50"])) and r["close"]>r["donch50"] and a200
    if mode=="MA_RECLAIM":
        if i<1 or pd.isna(r["sma200"]): return False
        return r["close"]>r["sma50"] and d["close"].iloc[i-1]<=d["sma50"].iloc[i-1] and r["sma50"]>r["sma200"]
    return False

def ride(d, mode):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not trig_for(mode,d,i): i+=1; continue
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

MODES=[("FULL","5 cond: up+vol2.5x+>50MA+zz_d+zz_w","🔴 most fakeable"),
       ("VOL+MA","up + vol2.5x + >50MA","🟠 vol = wash-tradeable"),
       ("DONCH20","20d-high breakout + >50MA","🟡 breakout = stop-huntable"),
       ("DONCH50+200","50d-high breakout + >200MA","🟢 sustained trend, hard to fake"),
       ("MA_RECLAIM","reclaim 50MA while 50>200","🟢 pure trend, hard to fake")]

def main():
    print(f"SIMPLIFY LADDER · konglo · last {WINDOW_YEARS}y · same robust ride exit\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    built={}
    for tk in K.all_tickers():
        try: built[tk]=add(build(tk,data[tk].copy()))
        except Exception: built[tk]=None
    print(f"  {'entry mode':14}{'trades':>7}{'win%':>6}{'hold':>6}{'exp/R':>7}{'  $1k→':>13}{'MaxDD':>7}  fakeability")
    print("  "+"-"*82)
    for mode,desc,fake in MODES:
        trades=[]
        for tk in K.all_tickers():
            d=built[tk]
            if d is None: continue
            for x in ride(d,mode): x["ticker"]=tk; trades.append(x)
        win=sorted([t for t in trades if t["entry"]>=CUTOFF],key=lambda x:x["entry"])
        if not win: print(f"  {mode:14} no trades"); continue
        df=pd.DataFrame(win); wr=(df.pnl>0).mean()*100; r=simulate(win,0.25,4)
        print(f"  {mode:14}{len(df):>7}{wr:>5.0f}%{df.bars.mean():>5.0f}d{df.R.mean():>+6.2f}"
              f"   ${r['final']:>7,.0f}({r['final']/START:.1f}x){r['maxdd']:>6.0f}%  {fake}")
    print("\n  Legend (what each entry leans on):")
    for mode,desc,fake in MODES: print(f"    {mode:14} {desc:38} {fake}")
    print("\n  KEY QUESTION: do the 🟢 simple trend entries match FULL? If yes → you can drop")
    print("  the fakeable volume/zigzag triggers and lean on the manipulation-resistant trend.")

if __name__=="__main__":
    main()
