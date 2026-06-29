# idx_commodity_test.py — validate the commodity-confirmation lead on a BROAD resource universe
# with REAL commodity data. Map ~45 IDX resource stocks to their commodity, then for each
# DONCH50+200 breakout check if the commodity was in an uptrend (>50MA). Compare outcomes
# WITH vs WITHOUT tailwind — overall and per commodity group. Bigger sample = is it real?
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003; FEE=0.4
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD, DONCH = 50, 4.0, 2.5, 250, 50

# stock -> commodity symbol (real futures; BTU=coal-miner proxy, ZL=F=soybean-oil CPO proxy)
CMAP = {
 "ADRO":"BTU","ADMR":"BTU","PTBA":"BTU","ITMG":"BTU","INDY":"BTU","HRUM":"BTU","BUMI":"BTU",
 "DEWA":"BTU","GEMS":"BTU","DSSA":"BTU","BYAN":"BTU","AADI":"BTU","TOBA":"BTU","PTRO":"BTU",
 "MEDC":"CL=F","ENRG":"CL=F","PGAS":"CL=F","ELSA":"CL=F","AKRA":"CL=F","ESSA":"CL=F",
 "BRPT":"CL=F","TPIA":"CL=F","RAJA":"CL=F",
 "ANTM":"GC=F","MDKA":"GC=F","BRMS":"GC=F","ARCI":"GC=F","HRTA":"GC=F","PSAB":"GC=F",
 "AMMN":"HG=F","MBMA":"HG=F","NCKL":"HG=F","INCO":"HG=F","TINS":"HG=F",
 "AALI":"ZL=F","LSIP":"ZL=F","DSNG":"ZL=F","SSMS":"ZL=F","TAPG":"ZL=F","SIMP":"ZL=F",
 "SMAR":"ZL=F","TBLA":"ZL=F","BWPT":"ZL=F",
}
GRP={"BTU":"coal","CL=F":"oil/gas","GC=F":"gold","HG=F":"metals","ZL=F":"palmoil"}

def main():
    print(f"COMMODITY CONFIRMATION · broad resource universe ({len(CMAP)} stocks) · last {WINDOW_YEARS}y\n")
    comm={}
    for c in set(CMAP.values()):
        cd=yf.download(c,period="3y",progress=False,auto_adjust=True)
        if cd is None or len(cd)==0: print(f"  ! commodity {c} no data"); continue
        if hasattr(cd.columns,"levels"): cd.columns=cd.columns.get_level_values(0)
        cd.columns=[x.lower() for x in cd.columns]
        comm[c]=pd.Series((cd["close"]>cd["close"].rolling(50).mean()).values, index=cd.index.tz_localize(None).normalize())
    print(f"  commodities loaded: {list(comm)}\n")

    tickers=[t+".JK" for t in CMAP]
    rows=[]
    for kk in range(0,len(tickers),25):
        chunk=tickers[kk:kk+25]
        data=yf.download(chunk,period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
        for tk in chunk:
            name=tk.replace(".JK","")
            try: d=build(tk,data[tk].copy())
            except Exception: d=None
            if d is None: continue
            csym=CMAP[name]; cseries=comm.get(csym)
            if cseries is None: continue
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
                tail = bool(cseries.asof(pd.Timestamp(t[i]).normalize()))
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
                    rows.append(dict(tk=name,grp=GRP[csym],tw=tail,pnl=pnl-FEE,bars=xk-k,
                                     entry=pd.Timestamp(t[k]),exit=pd.Timestamp(t[xk])))
                i=xk+1
        print(f"  ...scanned {min(kk+25,len(tickers))}/{len(tickers)}", flush=True)

    df=pd.DataFrame(rows)
    print(f"\n  {len(df)} resource breakouts.\n")
    def stat(s,lab):
        if len(s)==0: print(f"  {lab:22} (none)"); return
        print(f"  {lab:22}{len(s):>5} trades · win {(s.pnl>0).mean()*100:>3.0f}% · "
              f"fast-stop {(s.bars<=3).mean()*100:>3.0f}% · avg {s.pnl.mean():>+6.1f}%")
    print("="*68+"\n  WITH vs WITHOUT commodity tailwind (overall)\n"+"="*68)
    stat(df[df.tw], "WITH tailwind")
    stat(df[~df.tw],"WITHOUT tailwind")
    print("\n"+"="*68+"\n  by commodity group\n"+"="*68)
    for g in ["coal","oil/gas","gold","metals","palmoil"]:
        sub=df[df.grp==g]
        if len(sub)==0: continue
        w=sub[sub.tw]; wo=sub[~sub.tw]
        print(f"  {g:9} WITH {w.pnl.mean():>+6.1f}% ({len(w):>2}) · WITHOUT {wo.pnl.mean():>+6.1f}% ({len(wo):>2})")
    print("\n"+"="*68+"\n  PORTFOLIO: trade ALL vs only WITH-tailwind (20%×5)\n"+"="*68)
    allr=df.to_dict("records"); withr=df[df.tw].to_dict("records")
    fa,da=simulate(allr,0.20,5); fw,dw=simulate(withr,0.20,5)
    print(f"  trade ALL breakouts      : {fa/START:.1f}x  (MaxDD {da:.0f}%, {len(allr)} trades)")
    print(f"  only WITH commodity tail : {fw/START:.1f}x  (MaxDD {dw:.0f}%, {len(withr)} trades)")
    print("\n  Real coal/nickel data would sharpen this (BTU=coal proxy, ZL=CPO proxy).")

if __name__=="__main__":
    main()
