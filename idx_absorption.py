# idx_absorption.py — Eric's smart-money thesis as a PRICE/VOLUME footprint (Wyckoff/VSA).
# Can't see broker codes (retail vs whale), but absorption leaves a candle footprint:
#   ABSORPTION DAY = high volume (>=2x avg) + close near the HIGH (top 40% of range, long lower
#   wick = selling absorbed) + in a WEAK context (below 50MA or near 60-day low = where retail
#   panics). Tag each DONCH50+200 breakout by how many absorption days preceded it (60d window).
#   Do breakouts WITH prior accumulation outperform those without? (His thesis, price-proxied.)
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50
VOL_X=2.0; LOOKBACK=60      # absorption: vol>=2x avg, look back 60 days before breakout

def absorption_flags(d):
    o,hi,lo,cl,vol=d["open"].values,d["high"].values,d["low"].values,d["close"].values,d["volume"].values
    volma=pd.Series(vol).rolling(20).mean().values
    sma50=d["close"].rolling(50).mean().values
    low60=pd.Series(lo).rolling(60).min().values
    n=len(d); flag=np.zeros(n,dtype=bool)
    for i in range(20,n):
        if np.isnan(volma[i]) or volma[i]<=0: continue
        rng=hi[i]-lo[i]
        if rng<=0: continue
        high_vol = vol[i] >= VOL_X*volma[i]
        close_top = (hi[i]-cl[i]) <= 0.40*rng           # close in top 40% (long lower wick)
        real_range = rng/cl[i] >= 0.02                  # a meaningful range
        weak_ctx = (not np.isnan(sma50[i]) and cl[i]<sma50[i]) or (not np.isnan(low60[i]) and cl[i]<=low60[i]*1.15)
        if high_vol and close_top and real_range and weak_ctx:
            flag[i]=True
    return flag

def main():
    print(f"ABSORPTION footprint before breakout · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    rows=[]
    for tk in K.all_tickers():
        try: d=build(tk,data[tk].copy())
        except Exception: d=None
        if d is None: continue
        flag=absorption_flags(d)
        o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
        atr=d["atr"].values; turn=d["turn20"].values; t=d["time"].values
        ema=d["close"].ewm(span=EMA_LEN,adjust=False).mean().values
        sma200=d["close"].rolling(200).mean().values
        donch=d["high"].rolling(DONCH).max().shift(1).values
        n=len(d); i=200
        while i<n-2:
            a=atr[i]
            if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
            if np.isnan(donch[i]) or np.isnan(sma200[i]) or not(cl[i]>donch[i] and cl[i]>sma200[i]): i+=1; continue
            nacc=int(flag[max(0,i-LOOKBACK):i].sum())     # absorption days in prior 60d
            trig=hi[i]*(1+TRIG_BUF); k=i+1
            if o[k]>hi[i]*(1+MAXGAP): i+=1; continue
            if o[k]>=trig: entry=o[k]*(1+SLIP)
            elif hi[k]>=trig: entry=trig*(1+SLIP)
            else: i+=1; continue
            stop=entry-INIT_ATR*a; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
            for j in range(k,end+1):
                runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
                stop=max(stop,runmax-TRAIL_ATR*aj)
                if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
                if j>k and cl[j]<ema[j]: pnl=(cl[j]*(1-SLIP)-entry)/entry*100; xk=j; break
            if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
            if pd.Timestamp(t[k])>=CUTOFF:
                rows.append(dict(tk=tk.replace(".JK",""),nacc=nacc,pnl=pnl-FEE,bars=xk-k))
            i=xk+1
    df=pd.DataFrame(rows)
    print(f"  {len(df)} breakouts.  Absorption days before each: "
          f"0 → {len(df[df.nacc==0])}, 1-2 → {len(df[(df.nacc>=1)&(df.nacc<=2)])}, 3+ → {len(df[df.nacc>=3])}\n")
    def stat(s,lab):
        if len(s)==0: print(f"  {lab:26} (none)"); return
        print(f"  {lab:26}{len(s):>4} · win {(s.pnl>0).mean()*100:>3.0f}% · "
              f"fast-stop {(s.bars<=3).mean()*100:>3.0f}% · avg {s.pnl.mean():>+6.1f}%")
    print("="*64+"\n  BREAKOUT quality by PRIOR ACCUMULATION (absorption days)\n"+"="*64)
    stat(df[df.nacc==0],      "no prior absorption")
    stat(df[(df.nacc>=1)&(df.nacc<=2)], "1-2 absorption days")
    stat(df[df.nacc>=3],      "3+ absorption days (heavy)")
    print("\n  If 'more prior absorption → better breakout' → your smart-money thesis shows up in")
    print("  the candles. If flat/random → absorption footprints are too noisy to use alone.")

if __name__=="__main__":
    main()
