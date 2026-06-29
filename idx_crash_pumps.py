# idx_crash_pumps.py — pattern DISCOVERY: what pumped during the Jan-2026→now crash, and what
# did the setup look like RIGHT BEFORE each pump? (Descriptive — uses forward returns to FIND
# pumps, then characterizes precursors. If a common signature emerges, we test it causally next.)
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_discover import UNIVERSE

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S="2025-01-01"; PUMP_START="2026-01-01"; FWD=20; MIN_PUMP=0.30; MIN_TURN=10e9

def main():
    print(f"CRASH PUMP DISCOVERY · {PUMP_START}→now · pumps >= {MIN_PUMP*100:.0f}% over {FWD}d\n")
    tickers=[t+".JK" for t in UNIVERSE]
    pumps=[]
    for kk in range(0,len(tickers),25):
        chunk=tickers[kk:kk+25]
        data=yf.download(chunk,start=S,progress=False,auto_adjust=True,group_by="ticker")
        for tk in chunk:
            try:
                d=data[tk].dropna().copy(); d.columns=[c.lower() for c in d.columns]
                if len(d)<210: continue
                d=d.reset_index(); d=d.rename(columns={d.columns[0]:"time"}); d["time"]=pd.to_datetime(d["time"])
                cl=d["close"].values; hi=d["high"].values; lo=d["low"].values; vol=d["volume"].values
                volma=pd.Series(vol).rolling(20).mean().values
                sma20=pd.Series(cl).rolling(20).mean().values
                sma200=pd.Series(cl).rolling(200).mean().values
                turn=(d["close"]*d["volume"]).rolling(20).median().values
                hh20=pd.Series(hi).rolling(20).max().shift(1).values
                t=d["time"].values; n=len(d)
                # find best forward-20d run in the crash window
                start_i=int(np.searchsorted(d["time"].values, np.datetime64(PUMP_START)))
                best=None
                for i in range(max(start_i,210), n-2):
                    if np.isnan(turn[i]) or turn[i]<MIN_TURN: continue
                    fwd=cl[min(i+FWD,n-1)]/cl[i]-1
                    if best is None or fwd>best[0]: best=(fwd,i)
                if best is None or best[0]<MIN_PUMP: continue
                f,i=best
                # absorption in prior 10d (high vol + close top 40% + weak ctx)
                absn=0
                for j in range(max(0,i-10),i):
                    rng=hi[j]-lo[j]
                    if rng>0 and not np.isnan(volma[j]) and vol[j]>=2*volma[j] and (hi[j]-cl[j])<=0.4*rng \
                       and (not np.isnan(sma20[j]) and cl[j]<sma20[j]): absn+=1
                pumps.append(dict(tk=tk.replace(".JK",""), date=pd.Timestamp(t[i]).date(), gain=f*100,
                    volspike=vol[i]/volma[i] if volma[i]>0 else 0,
                    broke20=bool(not np.isnan(hh20[i]) and cl[i]>hh20[i]),
                    prior20=cl[i]/cl[i-20]-1 if i>=20 else 0,
                    vs200=cl[i]/sma200[i]-1 if not np.isnan(sma200[i]) else np.nan,
                    above20=bool(not np.isnan(sma20[i]) and cl[i]>sma20[i]),
                    absn=absn))
            except Exception: pass
        print(f"  ...scanned {min(kk+25,len(tickers))}/{len(tickers)}", flush=True)

    df=pd.DataFrame(pumps).sort_values("gain",ascending=False)
    print(f"\n  {len(df)} stocks pumped >= {MIN_PUMP*100:.0f}% during the crash.\n")
    print("="*78+"\n  THE PUMPS (biggest first)\n"+"="*78)
    print(f"  {'ticker':7}{'date':12}{'gain':>7}{'volX':>6}{'broke20d':>9}{'prior20d':>10}{'vs200MA':>9}{'absorb':>7}")
    for _,r in df.head(20).iterrows():
        print(f"  {r['tk']:7}{str(r['date']):12}{r['gain']:>+6.0f}%{r['volspike']:>5.1f}x"
              f"{('YES' if r['broke20'] else 'no'):>9}{r['prior20']*100:>+9.0f}%"
              f"{(f'{r.vs200*100:+.0f}%' if not pd.isna(r['vs200']) else '—'):>9}{r['absn']:>7}")
    print("\n"+"="*78+"\n  COMMON SIGNATURE across the pumps (the pattern)\n"+"="*78)
    print(f"  Broke a 20-day high on pump start : {df.broke20.mean()*100:.0f}%")
    print(f"  Above the 20-day MA               : {df.above20.mean()*100:.0f}%")
    print(f"  Volume spike >=2x on start day    : {(df.volspike>=2).mean()*100:.0f}%")
    print(f"  Had absorption footprint (prior10d): {(df.absn>=1).mean()*100:.0f}%")
    print(f"  Median volume on start vs avg     : {df.volspike.median():.1f}x")
    print(f"  Median 20d return BEFORE the pump : {df.prior20.median()*100:+.0f}%  "
          f"(negative = beaten down first)")
    print(f"  Median distance from 200MA        : {df.vs200.median()*100:+.0f}%")
    print("\n  Look for what MOST pumps share — that's the catchable signature (if any).")

if __name__=="__main__":
    main()
