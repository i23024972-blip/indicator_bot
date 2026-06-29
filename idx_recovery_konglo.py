# idx_recovery_konglo.py — does the RECOVERY-style entry work on KONGLO (the names that DO
# ignite)? Same engine as idx_recovery.py but on konglo names over the konglo era (2022+).
# RECOVERY  = IHSG risk-on (index > 50MA) + stock breaks 20-day high above 20MA  (fast, gated)
# DONCH50+200 = stock breaks 50-day high above 200MA                              (slow, late)
# The index green-light should keep the fast entry OUT of crashes (no knife-catching) — does
# that make the early entry finally beat the late one on explosive konglo names?
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K
from idx_recovery import ride, simulate, atr14, START_EQ

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S, E = "2022-06-01", "2026-12-31"

def main():
    print(f"RECOVERY-style vs DONCH50+200 · KONGLO names · {S}→ now\n")
    ih=yf.download("^JKSE",start=S,end=E,progress=False,auto_adjust=True)
    if hasattr(ih.columns,"levels"): ih.columns=ih.columns.get_level_values(0)
    ih.columns=[c.lower() for c in ih.columns]
    ma50=ih["close"].rolling(50).mean()
    risk=pd.Series((ih["close"]>ma50).values, index=ih.index.tz_localize(None).normalize())
    ro_now = bool(risk.iloc[-1])
    print(f"  IHSG risk-on right now (above 50MA)? {ro_now}  — recovery entries only fire when True\n")

    built={}
    for tk in K.all_tickers():
        try:
            d=yf.download(tk,start=S,end=E,progress=False,auto_adjust=True)
            if hasattr(d.columns,"levels"): d.columns=d.columns.get_level_values(0)
            d.columns=[c.lower() for c in d.columns]; d=d.dropna()
            if len(d)<210: built[tk]=None; continue
            d=d.reset_index().rename(columns={d.reset_index().columns[0]:"time"})
            d["time"]=pd.to_datetime(d["time"]); d["atr"]=atr14(d)
            built[tk]=d
        except Exception: built[tk]=None

    for mode in ["RECOVERY","DONCH50+200"]:
        trades=[]
        for tk,d in built.items():
            if d is None: continue
            for x in ride(d,mode,risk): x["ticker"]=tk.replace(".JK",""); trades.append(x)
        if not trades: print(f"  {mode}: no trades\n"); continue
        df=pd.DataFrame(trades); wr=(df.pnl>0).mean()*100
        final,maxdd=simulate(trades)
        big=df[df.pnl>=50]
        print("="*60+f"\n  {mode}\n"+"="*60)
        print(f"  Trades {len(df)} · win {wr:.0f}% · avg hold {df.bars.mean():.0f}d · exp {df.pnl.mean():+.1f}%")
        print(f"  Avg win +{df[df.pnl>0].pnl.mean():.0f}% / loss {df[df.pnl<=0].pnl.mean():.0f}%")
        print(f"  $1k → ${final:,.0f} ({final/START_EQ:.1f}x) · MaxDD {maxdd:.0f}%")
        print(f"  Jackpots (≥+50%): {len(big)}  ·  biggest {df.pnl.max():+.0f}%  ·  first entry {df.entry.min().date()}\n")
    print("  KEY: does index-gated EARLY entry finally beat the slow trend entry on konglo —")
    print("  or does the faster trigger still cost win-rate/return like every other early attempt?")

if __name__=="__main__":
    main()
