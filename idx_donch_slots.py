# idx_donch_slots.py — the last legitimate lever: position SLOTS.
# DONCH50+200 on konglo skipped 18 signals at max-4 (slots full). Here we spread the SAME
# ~100% exposure across more concurrent slots (25%x4 → 10%x10) to capture those skips.
# Pure diversification (frac×slots ≈ 100%, no leverage). Does it help or just dilute?
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K
from idx_simplify import ride, add
from idx_walkforward import build, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ACCOUNT=16_000_000

def main():
    print(f"SLOT TEST · DONCH50+200 · konglo · last {WINDOW_YEARS}y (~100% exposure, more slots)\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=add(build(tk,data[tk].copy()))
        except Exception: d=None
        if d is None: continue
        for x in ride(d,"DONCH50+200"): x["ticker"]=tk; trades.append(x)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF], key=lambda x:x["entry"])
    print(f"  {len(win)} total signals over the window.\n")
    print(f"  {'scheme':16}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}{'taken':>7}{'skipped':>9}{'   Rp end':>16}")
    print("  "+"-"*84)
    best=None
    for frac,m in [(0.25,4),(0.20,5),(0.167,6),(0.142,7),(0.125,8),(0.10,10)]:
        r=simulate(win,frac,m)
        rp=ACCOUNT*(r["final"]/START)
        lab=f"{frac*100:.0f}% × max{m}"
        flag=""
        if best is None or r["final"]>best[1]: best=(lab,r["final"],r["maxdd"])
        print(f"  {lab:16}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%{r['maxdd']:>6.0f}%"
              f"{r['taken']:>7}{r['skipped']:>9}   Rp {rp:>12,.0f}")
    print(f"\n  Baseline (25%×4): 4.6x, 8% DD, 18 skipped.")
    print(f"  Best by return  : {best[0]} → {best[1]/START:.1f}x at {best[2]:.0f}% DD")
    print("\n  Watch the 'skipped' column fall as slots rise. If return climbs WITHOUT")
    print("  drawdown ballooning → free improvement. If it flattens/dilutes → 4 slots was fine.")

if __name__=="__main__":
    main()
