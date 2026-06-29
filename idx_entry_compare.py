# idx_entry_compare.py — UNBIASED side-by-side of entry styles, judged by Eric's framework:
# "bet early (could be wrong), cut fast if wrong, hold if jackpot." So we report the metrics
# that matter for THAT: win% (bet hit-rate), avg loss (how small the cut), and the jackpot
# stats (max R, % of trades >=5R / >=10R). Run on BOTH konglo AND the broad unbiased universe
# so the ranking isn't an artifact of cherry-picked names. Same robust ride exit throughout.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K
from idx_simplify import ride, add
from idx_walkforward import build, CUTOFF, WINDOW_YEARS
from idx_discover import UNIVERSE
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MODES = ["VOL+MA", "DONCH20", "DONCH50+200", "FULL"]
MODE_TAG = {"VOL+MA":"early bet (uncertain)", "DONCH20":"20d breakout (medium)",
            "DONCH50+200":"50d-hi+200MA (late/robust)", "FULL":"original 5-cond"}

def build_universe(tickers):
    built={}
    for k in range(0, len(tickers), 25):
        chunk=tickers[k:k+25]
        try: data=yf.download(chunk,period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
        except Exception: continue
        for t in chunk:
            try: built[t]=add(build(t,data[t].copy()))
            except Exception: built[t]=None
        if len(tickers)>40: print(f"    ...{min(k+25,len(tickers))}/{len(tickers)}", flush=True)
    return built

def evaluate(built, mode):
    trades=[]
    for t,d in built.items():
        if d is None: continue
        for x in ride(d, mode): x["ticker"]=t; trades.append(x)
    win=sorted([t for t in trades if t["entry"]>=CUTOFF], key=lambda x:x["entry"])
    if not win: return None
    df=pd.DataFrame(win)
    r=simulate(win,0.25,4)
    return dict(n=len(df), wr=(df.pnl>0).mean()*100,
                avgloss=df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0,
                avgwin=df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0,
                maxR=df.R.max(), p5=(df.R>=5).mean()*100, p10=(df.R>=10).mean()*100,
                hold=df.bars.mean(), final=r["final"], dd=r["maxdd"])

def show(title, built):
    print(f"\n{'='*94}\n  {title}\n{'='*94}")
    print(f"  {'entry':14}{'when':24}{'win%':>5}{'avgLoss':>8}{'avgWin':>8}{'maxR':>6}{'≥5R':>5}{'≥10R':>6}{'  $1k→':>9}{'DD':>5}")
    print("  "+"-"*92)
    for m in MODES:
        s=evaluate(built,m)
        if not s: print(f"  {m:14} no trades"); continue
        print(f"  {m:14}{MODE_TAG[m]:24}{s['wr']:>4.0f}%{s['avgloss']:>7.1f}%{s['avgwin']:>7.1f}%"
              f"{s['maxR']:>5.1f}{s['p5']:>4.0f}%{s['p10']:>5.0f}%  {s['final']/START:>6.1f}x{s['dd']:>4.0f}%")

def main():
    print(f"UNBIASED ENTRY COMPARISON · last {WINDOW_YEARS}y · 'bet early, cut wrong, hold jackpot'")
    print("  Scanning konglo...")
    kong=build_universe(K.all_tickers())
    show("KONGLO universe (~20 names)", kong)
    print("\n  Scanning BROAD unbiased universe (~395 names, a few min)...")
    broad=build_universe([t+".JK" for t in UNIVERSE])
    show("BROAD unbiased universe (~395 names)", broad)
    print("\n  READ IT THIS WAY:")
    print("   · 'cut wrong' = avgLoss (want small & similar across all — the stop enforces it)")
    print("   · 'hold jackpot' = maxR + %≥5R + %≥10R (how often/big the winners run)")
    print("   · early-bet (VOL+MA) vs late-robust (DONCH50+200): does early catch MORE jackpots,")
    print("     or does the robust late entry win on risk-adjusted return? Check BOTH universes.")

if __name__=="__main__":
    main()
