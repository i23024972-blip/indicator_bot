# idx_konglo_expanded.py — the FAIR universe: conglomerate-backed LIQUID names across MANY
# Indonesian tycoon groups (winners AND non-winners), with a point-in-time liquidity gate
# (only trades a name on days it actually had >Rp10bn/day turnover). This is forward-defensible
# — you could have listed these by OWNERSHIP in 2022 without knowing which would moon.
# If DONCH50+200 still works here (not just on the Prajogo rockets), the edge is real.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from idx_recovery import simulate, atr14, START_EQ
from idx_recovery_broad import ride_b

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

S, E = "2022-06-01", "2026-12-31"
# ~15 conglomerate/tycoon groups — selected by OWNERSHIP, not performance:
GROUPS = {
 "Prajogo/Barito": ["BRPT","TPIA","BREN","CUAN","PTRO","CDIA"],
 "Bakrie":         ["BNBR","BUMI","ENRG","BRMS","DEWA","ELTY","VKTR"],
 "Salim":          ["INDF","ICBP","SIMP","LSIP","PANI","AMRT"],
 "Sinarmas":       ["INKP","TKIM","DSSA","SMAR","BSDE","DUTI","GEMS"],
 "Lippo":          ["LPKR","LPPF","SILO","MPPA","MLPL"],
 "Astra":          ["ASII","AUTO","UNTR","AALI"],
 "MNC":            ["BMTR","MNCN","BHIT","KPIG","MSIN"],
 "Emtek":          ["EMTK","SCMA","BUKA"],
 "Thohir/Adaro":   ["ADRO","ADMR"],
 "Medco":          ["MEDC","AMMN"],
 "Indika":         ["INDY"], "Pakuwon":["PWON"], "Ciputra":["CTRA"],
 "GudangGaram":    ["GGRM"], "Sampoerna":["HMSP"],
}
UNIVERSE = sorted({t for v in GROUPS.values() for t in v})

def main():
    print(f"FAIR conglomerate universe · {len(UNIVERSE)} names · {len(GROUPS)} tycoon groups · {S}→now")
    print("  (winners AND non-winners · point-in-time liquidity gate)\n")
    ih=yf.download("^JKSE",start=S,end=E,progress=False,auto_adjust=True)
    if hasattr(ih.columns,"levels"): ih.columns=ih.columns.get_level_values(0)
    ih.columns=[c.lower() for c in ih.columns]
    risk=pd.Series((ih["close"]>ih["close"].rolling(50).mean()).values, index=ih.index.tz_localize(None).normalize())

    built={}; tickers=[t+".JK" for t in UNIVERSE]
    data=yf.download(tickers,start=S,end=E,progress=False,auto_adjust=True,group_by="ticker")
    for tk in tickers:
        try:
            d=data[tk].dropna().copy(); d.columns=[c.lower() for c in d.columns]
            if len(d)<210: continue
            d=d.reset_index().rename(columns={d.reset_index().columns[0]:"time"})
            d["time"]=pd.to_datetime(d["time"]); d["atr"]=atr14(d)
            d["turn20"]=(d["close"]*d["volume"]).rolling(20).median()
            built[tk.replace(".JK","")]=d
        except Exception: pass
    print(f"  {len(built)} names had usable data.\n")

    for mode in ["RECOVERY","DONCH50+200"]:
        trades=[]
        for tk,d in built.items():
            for x in ride_b(d,mode,risk): x["ticker"]=tk; trades.append(x)
        if not trades: print(f"  {mode}: no trades\n"); continue
        df=pd.DataFrame(trades); wr=(df.pnl>0).mean()*100; final,maxdd=simulate(trades)
        big=df[df.pnl>=50]
        # which groups produced the winners?
        grp_of={t:g for g,ts in GROUPS.items() for t in ts}
        topgrp=df[df.pnl>=50].ticker.map(grp_of).value_counts().head(4)
        print("="*62+f"\n  {mode}\n"+"="*62)
        print(f"  Trades {len(df)} across {df.ticker.nunique()} names · win {wr:.0f}% · hold {df.bars.mean():.0f}d")
        print(f"  Avg win +{df[df.pnl>0].pnl.mean():.0f}% / loss {df[df.pnl<=0].pnl.mean():.0f}% · exp {df.pnl.mean():+.1f}%")
        print(f"  $1k → ${final:,.0f} ({final/START_EQ:.1f}x) · MaxDD {maxdd:.0f}%")
        print(f"  Jackpots (≥+50%): {len(big)} · winners' groups: {dict(topgrp)}\n")
    print("  vs konglo-4group 6.5x · vs broad-395 0.9x — where does the FAIR universe land?")
    print("  If jackpots are ALL Prajogo/Bakrie → edge is those names, not 'conglomerate-backed'.")

if __name__=="__main__":
    main()
