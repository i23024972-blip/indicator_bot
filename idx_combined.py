# idx_combined.py — combine the two tools: konglo momentum (offense) + regime basket (defense).
# Shows combined capital across split ratios, with the konglo half at BOTH optimistic
# (survivorship 4-group) and REALISTIC (fair 52-name conglomerate) numbers = an honest range.
# Same 2022-2026 window for all three. Simple capital-split blend (allocate once, let each run).
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_recovery import simulate, atr14, START_EQ
from idx_recovery_broad import ride_b
from idx_konglo_expanded import UNIVERSE as FAIR
from idx_regime_basket import run as regime_run, BASKET

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S, E = "2022-06-01", "2026-12-31"
ACCOUNT = 16_000_000

def close(tk):
    d=yf.download(tk,start=S,end=E,progress=False,auto_adjust=True)
    if d is None or len(d)==0: return None
    if hasattr(d.columns,"levels"): d.columns=d.columns.get_level_values(0)
    d.columns=[c.lower() for c in d.columns]
    return d

def build(tk):
    d=close(tk)
    if d is None or len(d)<210: return None
    d=d.dropna().reset_index(); d=d.rename(columns={d.columns[0]:"time"})
    d["time"]=pd.to_datetime(d["time"]); d["atr"]=atr14(d)
    d["turn20"]=(d["close"]*d["volume"]).rolling(20).median()
    return d

def konglo_mult(tickers, risk):
    trades=[]
    for tk in tickers:
        d=build(tk if tk.endswith(".JK") else tk+".JK")
        if d is None: continue
        for x in ride_b(d,"DONCH50+200",risk): trades.append(x)
    if not trades: return 0
    final,_=simulate(trades)
    return final/START_EQ

def main():
    print(f"COMBINED: konglo momentum + regime basket · {S}→now\n")
    ih=close("^JKSE")
    risk=pd.Series((ih["close"]>ih["close"].rolling(50).mean()).values, index=ih.index.tz_localize(None).normalize())

    print("  Computing the three components (a few min)...")
    k_opt = konglo_mult(K.all_tickers(), risk)
    print(f"   · konglo OPTIMISTIC (4-group survivorship): {k_opt:.1f}x")
    k_real= konglo_mult([t+".JK" for t in FAIR], risk)
    print(f"   · konglo REALISTIC (52 fair conglomerate) : {k_real:.1f}x")
    # regime basket over this window
    risk_d=(ih["close"]>ih["close"].rolling(50).mean()).shift(1).fillna(False)
    cols={}
    for tk in BASKET:
        c=close(tk+".JK")
        if c is not None: cols[tk]=c["close"]
    bdf=pd.DataFrame(cols).reindex(ih.index)
    bret=bdf.pct_change().mean(axis=1)
    beq,bdd,_,_=regime_run(bret, risk_d)
    b_mult=beq
    print(f"   · regime BASKET (defensive, this window)  : {b_mult:.2f}x  (MaxDD {bdd:.0f}%)\n")

    print("="*72)
    print(f"  COMBINED CAPITAL from Rp {ACCOUNT:,.0f}  (split once, let each run {((pd.Timestamp(E)-pd.Timestamp(S)).days/365.25):.0f}y)")
    print("="*72)
    print(f"  {'split (konglo/basket)':24}{'REALISTIC':>16}{'OPTIMISTIC':>16}")
    for w in [1.0,0.7,0.5,0.3,0.0]:
        real = w*k_real + (1-w)*b_mult
        opt  = w*k_opt  + (1-w)*b_mult
        lab = f"{int(w*100)}% / {int((1-w)*100)}%"
        print(f"  {lab:24}Rp {ACCOUNT*real:>12,.0f}  Rp {ACCOUNT*opt:>12,.0f}")
    print("="*72)
    print(f"\n  REALISTIC = fair conglomerate konglo · OPTIMISTIC = survivorship konglo.")
    print(f"  Truth is between — and the basket lowers the blended drawdown either way.")
    print(f"  100/0 = all konglo (max return, max risk) · 0/100 = all defensive basket.")

if __name__=="__main__":
    main()
