# idx_conviction_score.py — automated CONVICTION scorer: does it separate real breakouts from
# fakes? For each DONCH50+200 konglo breakout, score 0-3 (+commodity bonus) on AUTOMATED free
# data:
#   group  : >=1 other name in the same conglomerate group is also above its 50MA (coordinated)
#   RS     : stock's 20d return beats IHSG's 20d return (leadership)
#   turn   : 20d turnover > 60d turnover (participation RISING = accumulation, not a 1-day pop)
#   commod : (bonus, resource names) underlying commodity above its 50MA
# Then bucket trades by score and check: do high-conviction breakouts fake LESS / win MORE?
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50
COMMOD = {"BRPT":"CL=F","TPIA":"CL=F","PTRO":"CL=F","ENRG":"CL=F","BUMI":"CL=F",
          "CUAN":"CL=F","DEWA":"CL=F","BRMS":"GC=F"}   # energy/coal→oil proxy, gold

def main():
    print(f"CONVICTION scorer on DONCH50+200 breakouts · konglo · last {WINDOW_YEARS}y\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    ih=yf.download("^JKSE",period="3y",progress=False,auto_adjust=True)
    if hasattr(ih.columns,"levels"): ih.columns=ih.columns.get_level_values(0)
    ih.columns=[c.lower() for c in ih.columns]
    ih_ret20=pd.Series((ih["close"]/ih["close"].shift(20)-1).values, index=ih.index.tz_localize(None).normalize())
    comm_up={}
    for c in set(COMMOD.values()):
        cd=yf.download(c,period="3y",progress=False,auto_adjust=True)
        if hasattr(cd.columns,"levels"): cd.columns=cd.columns.get_level_values(0)
        cd.columns=[x.lower() for x in cd.columns]
        comm_up[c]=pd.Series((cd["close"]>cd["close"].rolling(50).mean()).values, index=cd.index.tz_localize(None).normalize())

    built={}; above50={}
    for tk in K.all_tickers():
        try:
            d=build(tk,data[tk].copy())
            if d is None: continue
            d["sma50"]=d["close"].rolling(50).mean()
            d["sma200_c"]=d["close"].rolling(200).mean()
            d["donch"]=d["high"].rolling(DONCH).max().shift(1)
            d["turn60"]=(d["close"]*d["volume"]).rolling(60).median()
            built[tk]=d
            above50[tk.replace(".JK","")]=pd.Series((d["close"]>d["sma50"]).values, index=d["time"].dt.normalize())
        except Exception: pass

    rows=[]
    for tk,d in built.items():
        name=tk.replace(".JK","")
        grp=K.group_of(tk); peers=[p.replace(".JK","") for p in K.KONGLO.get(grp,[]) if p!=tk]
        o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
        atr=d["atr"].values; turn=d["turn20"].values; turn60=d["turn60"].values; t=d["time"].values
        ema=d["close"].ewm(span=EMA_LEN,adjust=False).mean().values
        sma200=d["sma200_c"].values; donch=d["donch"].values
        n=len(d); i=200
        while i<n-2:
            a=atr[i]
            if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
            if np.isnan(donch[i]) or np.isnan(sma200[i]) or not(cl[i]>donch[i] and cl[i]>sma200[i]): i+=1; continue
            dnorm=pd.Timestamp(t[i]).normalize()
            gp = 1 if sum(1 for p in peers if p in above50 and bool(above50[p].asof(dnorm))) >= 1 else 0
            r20 = cl[i]/cl[i-20]-1 if i>=20 else 0
            ihr = ih_ret20.asof(dnorm); ihr = 0 if pd.isna(ihr) else ihr
            rs = 1 if r20 > ihr else 0
            tt = 1 if (not np.isnan(turn60[i]) and turn[i]>turn60[i]) else 0
            cm = 1 if (name in COMMOD and bool(comm_up[COMMOD[name]].asof(dnorm))) else 0
            score = gp+rs+tt
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
                rows.append(dict(tk=name,score=score,cm=cm,pnl=pnl-FEE,bars=xk-k))
            i=xk+1

    df=pd.DataFrame(rows)
    print(f"  {len(df)} breakouts scored.\n")
    print("="*64+"\n  WIN RATE & FAKE RATE by CONVICTION SCORE (0-3)\n"+"="*64)
    print(f"  {'score':7}{'trades':>7}{'win%':>6}{'fast-stop%':>11}{'avg pnl':>9}")
    for s in [0,1,2,3]:
        sub=df[df.score==s]
        if len(sub)==0: print(f"  {s:<7}{0:>7}"); continue
        print(f"  {s:<7}{len(sub):>7}{(sub.pnl>0).mean()*100:>5.0f}%{(sub.bars<=3).mean()*100:>10.0f}%{sub.pnl.mean():>+8.1f}%")
    hi_=df[df.score>=2]; lo_=df[df.score<=1]
    print("\n  HIGH conviction (score>=2): "
          f"{len(hi_)} trades, {(hi_.pnl>0).mean()*100:.0f}% win, {(hi_.bars<=3).mean()*100:.0f}% fast-stop, {hi_.pnl.mean():+.1f}% avg")
    print("  LOW  conviction (score<=1): "
          f"{len(lo_)} trades, {(lo_.pnl>0).mean()*100:.0f}% win, {(lo_.bars<=3).mean()*100:.0f}% fast-stop, {lo_.pnl.mean():+.1f}% avg")
    print(f"\n  Commodity tailwind: with {df[df.cm==1].pnl.mean():+.1f}% avg vs without {df[df.cm==0].pnl.mean():+.1f}%")
    print("  If high-conviction wins more / fakes less → the scorer filters fakes (build the bot).")

if __name__=="__main__":
    main()
