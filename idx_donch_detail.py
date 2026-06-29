# idx_donch_detail.py — detailed 2y report card for the chosen DONCH50+200 (anti-manipulation)
# strategy on konglo. Answers: how many cut-losses & their cost, how much profit & from where,
# how long we normally hold, and total gain.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_simplify import ride, add
from idx_walkforward import build, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

ACCOUNT = 16_000_000   # your real paper capital, for relatable rupiah figures

def main():
    print(f"DONCH50+200 (anti-manipulation) · konglo · last {WINDOW_YEARS}y · detailed report\n")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=add(build(tk,data[tk].copy()))
        except Exception: d=None
        if d is None: continue
        for x in ride(d,"DONCH50+200"): x["ticker"]=tk.replace(".JK",""); trades.append(x)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF], key=lambda x:x["entry"])
    df=pd.DataFrame(win)
    W=df[df.pnl>0]; L=df[df.pnl<=0]

    # ── ledger ──
    print("="*72+"\n  EVERY TRADE (chronological)\n"+"="*72)
    print(f"  {'#':>2} {'entry':10} {'ticker':6} {'held':>5} {'result':>9} {'R':>6}  outcome")
    for n,(_,t) in enumerate(df.iterrows(),1):
        tag="🟢 PROFIT" if t.pnl>0 else "🔴 CUT"
        print(f"  {n:>2} {str(t['entry'].date()):10} {t['ticker']:6} {t['bars']:>4}d {t['pnl']:>+7.1f}% {t['R']:>+5.1f}R  {tag}")

    # ── cut losses ──
    print("\n"+"="*72+"\n  ✂️  CUT-LOSSES (when the bet was wrong)\n"+"="*72)
    print(f"  Count            : {len(L)} of {len(df)} trades ({len(L)/len(df)*100:.0f}%)")
    print(f"  Avg cut          : {L.pnl.mean():.1f}%  ({L.R.mean():.1f}R)")
    print(f"  Worst single cut : {L.pnl.min():.1f}%  ({L.loc[L.pnl.idxmin(),'ticker']})")
    print(f"  Typical hold before cut : {L.bars.median():.0f} days (you bleed out FAST)")

    # ── profits ──
    print("\n"+"="*72+"\n  💰 PROFITS TAKEN (when it was a jackpot)\n"+"="*72)
    print(f"  Count            : {len(W)} of {len(df)} trades ({len(W)/len(df)*100:.0f}% win)")
    print(f"  Avg profit       : +{W.pnl.mean():.1f}%  (+{W.R.mean():.1f}R)")
    print(f"  Biggest          : +{W.pnl.max():.0f}%  ({W.loc[W.pnl.idxmax(),'ticker']}, {W.loc[W.pnl.idxmax(),'bars']:.0f}d)")
    big=W[W.R>=5]
    print(f"  Jackpots (≥5R)   : {len(big)}  → made {big.R.sum()/W.R.sum()*100:.0f}% of all the R")

    # ── hold time ──
    print("\n"+"="*72+"\n  ⏱️  HOW LONG WE NORMALLY HOLD\n"+"="*72)
    print(f"  Median hold (all): {df.bars.median():.0f} days  ← 'normal'")
    print(f"  Winners hold     : {W.bars.median():.0f} days (median) — hold the runners")
    print(f"  Losers hold      : {L.bars.median():.0f} days (median) — cut the duds fast")
    print(f"  Longest hold     : {df.bars.max():.0f} days ({df.loc[df.bars.idxmax(),'ticker']})")

    # ── total gain ──
    print("\n"+"="*72+"\n  📈 TOTAL GAIN (portfolio, 25% × max4, compounded)\n"+"="*72)
    r=simulate(win,0.25,4)
    yrs=(df.entry.iloc[-1]-df.entry.iloc[0]).days/365.25
    end_rp = ACCOUNT*(r["final"]/START)
    print(f"  Start  : Rp {ACCOUNT:,.0f}")
    print(f"  End    : Rp {end_rp:,.0f}   ({r['final']/START:.1f}x)")
    print(f"  Gain   : +{(r['final']/START-1)*100:.0f}%   ·   CAGR {r['cagr']:+.0f}%/yr")
    print(f"  Worst drawdown along the way : {r['maxdd']:.0f}%")
    print(f"  Trades taken {r['taken']} / skipped {r['skipped']} (slots full)")
    print(f"\n  Expectancy: {df.R.mean():+.2f}R per trade · over {yrs:.1f} years.")
    print("  Net story: many small cuts + a few big holds = the gain. Discipline > prediction.")

if __name__=="__main__":
    main()
