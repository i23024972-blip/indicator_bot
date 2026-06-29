# idx_regime_basket.py — the RECOVERY tool: regime-timed broad exposure, HELD (no stock stops).
# Rule: when IHSG is above its 50-day MA = risk-on → hold (index or a liquid basket). When it
# drops below = risk-off → go to cash. Ride the whole recovery tide; sidestep the crash.
# Tested 2018-2026 (COVID + 2022 dip + konglo era) vs plain buy-and-hold. Daily equity, costs,
# no lookahead (act on yesterday's signal).
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S, E = "2018-01-01", "2026-12-31"
SWITCH_COST = 0.0015      # 0.15% each entry/exit
BASKET = ["BBCA","BBRI","BMRI","BBNI","ASII","TLKM","UNTR","ANTM","INCO","INDF",
          "ICBP","PGAS","ITMG","ADRO","KLBF","UNVR","SMGR","PTBA","AALI","GGRM",
          "HMSP","BRPT","TPIA","MDKA","ACES","ERAA"]

def dl(tkr):
    d=yf.download(tkr,start=S,end=E,progress=False,auto_adjust=True)
    if d is None or len(d)==0: return None
    if hasattr(d.columns,"levels"): d.columns=d.columns.get_level_values(0)
    d.columns=[c.lower() for c in d.columns]
    return d["close"]

def run(daily_ret, risk_on):
    """Daily equity: invested when risk_on (shifted), cash otherwise, with switch costs."""
    eq=1.0; curve=[]; prev=False; peak=1.0; maxdd=0; days_in=0; switches=0
    for dt in daily_ret.index:
        ro=bool(risk_on.get(dt, False))
        if ro != prev: eq*=(1-SWITCH_COST); switches+=1
        if ro:
            r=daily_ret.get(dt, 0.0)
            if not np.isnan(r): eq*=(1+r)
            days_in+=1
        curve.append(eq); peak=max(peak,eq); maxdd=max(maxdd,(peak-eq)/peak*100)
        prev=ro
    return eq, maxdd, days_in/len(daily_ret)*100, switches

def main():
    print(f"REGIME-TIMED BASKET (recovery tool) · {S}→now\n")
    ihsg=dl("^JKSE")
    risk=(ihsg > ihsg.rolling(50).mean()).shift(1).fillna(False)   # act next day, no lookahead
    idx_ret=ihsg.pct_change()

    # basket daily return = equal-weight mean across available names
    cols={}
    for tk in BASKET:
        s=dl(tk+".JK")
        if s is not None: cols[tk]=s
    bdf=pd.DataFrame(cols).reindex(ihsg.index)
    basket_ret=bdf.pct_change().mean(axis=1)
    print(f"  {len(cols)} basket names · {len(ihsg)} trading days\n")

    # buy & hold index (always invested)
    bh = ihsg.iloc[-1]/ihsg.iloc[0]
    bh_dd=0; peak=ihsg.iloc[0]
    for v in ihsg:
        peak=max(peak,v); bh_dd=max(bh_dd,(peak-v)/peak*100)

    ei,ddi,inv_i,sw_i = run(idx_ret, risk)
    eb,ddb,inv_b,sw_b = run(basket_ret, risk)
    yrs=(ihsg.index[-1]-ihsg.index[0]).days/365.25

    print("="*72)
    print(f"  {'strategy':30}{'return':>9}{'CAGR':>8}{'MaxDD':>7}{'in mkt':>8}")
    print("="*72)
    print(f"  {'Buy & hold IHSG (always in)':30}{(bh-1)*100:>+8.0f}%{(bh**(1/yrs)-1)*100:>+7.0f}%{bh_dd:>6.0f}%{'100%':>8}")
    print(f"  {'Regime-timed INDEX':30}{(ei-1)*100:>+8.0f}%{(ei**(1/yrs)-1)*100:>+7.0f}%{ddi:>6.0f}%{inv_i:>7.0f}%")
    print(f"  {'Regime-timed BASKET':30}{(eb-1)*100:>+8.0f}%{(eb**(1/yrs)-1)*100:>+7.0f}%{ddb:>6.0f}%{inv_b:>7.0f}%")
    print("="*72)
    print(f"\n  Switches: index {sw_i}, basket {sw_b} (round-trips ≈ half) over {yrs:.1f}y")
    print("  KEY: does cutting risk at the red light (lower MaxDD) + riding the green light")
    print("  beat just holding? And does the quality basket beat the plain index?")

if __name__=="__main__":
    main()
