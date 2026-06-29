# idx_discover.py — Auto-discovery screener across a broad IDX universe.
# For each stock it measures (1) daily transaction value / turnover = liquidity, and
# (2) whether a volume spike has historically LED to gains (the strategy's edge).
# Then it ranks and suggests names worth adding to the watchlist (idx_scan.WATCH).
#
# Run occasionally (it scans ~130 stocks; takes a few minutes). Not a daily job.
import warnings; warnings.filterwarnings("ignore")
import sys
import pandas as pd, numpy as np, yfinance as yf
from idx_scan import WATCH

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# ── Universe: ~400-name sweep of the IDX board (illiquid names auto-filtered by turnover). ──
_RAW = """
BBCA BBRI BMRI BBNI BRIS ARTO BBTN BTPS BNGA AGRO BBYB BANK BBHI BBKP BJBR BJTM BNLI MAYA
PNBN BGTG SDRA NISP MCOR AMAR BABP BFIN ADMF CFIN WOMF BBLD MFIN SRTG BDMN BTPN BNII BBMD
BSIM BVIC BACA NOBU BPFI PNBS BCAP DNAR AMAG ASRM PNIN PNLF LPGI MREI
BRPT TPIA BREN CUAN PTRO CDIA
BUMI ENRG DEWA BRMS ELTY BNBR VKTR BUVA
INDF ICBP DNET SIMP PANI AMRT
ADRO ADMR PTBA ITMG HRUM INDY BYAN AADI GEMS DOID BSSR MBAP TOBA PKPK DSSA KKGI MYOH PTIS
PTMP GTBO BIPI MTFN
MEDC PGAS PGEO ELSA AKRA ESSA RAJA WINS RUIS KEEN ARKO WIFI APEX RGAS HITS SOCI BULL TPMA
ANTM INCO MDKA AMMN MBMA NCKL TINS PSAB NICL ZINC SMMT DKFT HRTA ARCI CITA SQMI NIKL CITY
PSGO IFSH
TLKM ISAT EXCL TOWR MTEL TBIG LINK CENT JAST GHON IBST CENT GOLD
UNVR MYOR KLBF SIDO HMSP GGRM CMRY ULTJ ROTI MLBI STTP CLEO ADES TSPC KAEF INAF MERK DVLA
PYFA SCPI KINO HOKI CAMP GOOD MGRO ENAK FOOD CEKA SKLT SKBM BUDI
BSDE CTRA PWON SMRA ASRI DMAS APLN LPKR BEST KIJA DILD MTLA RDTX SMDM CBDK POLL JRPT GPRA
DUTI PUDP RODA BAPA OMRE MKPI PLIN BKSL EMDE GWSA NIRO RISE PPRO LAND CBDK
WIKA WSKT PTPP ADHI WTON WEGE TOTL NRCA DGIK ACST IDPR SSIA JKON TOPS WSBP
ASII UNTR AUTO HEXA GJTL IMAS DRMA BOLT SMSM BRAM GDYR MASA INDS NIPS LPIN
TMAS SMDR ASSA BIRD GIAA CMPP NELY TNCA LEAD WEHA SAPX TAXI
GOTO BUKA EMTK MTDL DCII BELI MLPT DMMX PTSN AXIO WIRG ELIT NFCX MCAS KIOS EDGE ENVY DIVA
HDIT GLVA MLPL META AREA UVCR ZYRX
SCMA MNCN FILM BMTR MSIN DOOH MSKY MDIA TFAS IPTV ABBA VIVA
MIKA HEAL SILO PRDA SRAJ SAME HALO BMHS SAPX HEAL PRAY OBMD CARE RSGK
CPIN JPFA MAIN AALI LSIP DSNG TAPG SGRO ANJT BWPT TBLA SSMS SMAR PALM ANDI BISI CSRA GZCO
JAWA SGER MGRO
SMGR INTP SMCB MARK AGII INCI EKAD SRSN BRNA FPNI IGAR APLI TALF UNIC ETWA DPNS EPMT
MAPI MAPA ACES ERAA LPPF RALS MIDI CSAP RANC ECII CSIS MPPA HERO ASGR TELE EPMT
INKP TKIM FASW SPMA KBLI KBLM SCCO VOKS JECC KBLV
PBRX SRIL RICY TRIS UNIT ARGO ESTI INDR STAR ZONE BELL TFCO
RATU MABA COCO BABY GULA CBUT KOKA FORE COIN RAAM MASB SURI NSSS LMAX BREN HBAT FUTR
WIIM RMBA ITIC TGKA AKKU AISA HOMI BIKE GULA MENN
"""
UNIVERSE = sorted(set(_RAW.split()))

MIN_TURNOVER = 10e9     # Rp 10 billion/day minimum to be tradeable
SPIKE_X      = 2.5
FWD          = 10
MIN_SPIKES   = 8        # need enough spike samples to trust the edge

def flat(df):
    if hasattr(df.columns, "levels"): df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df

def study(d):
    d = d.dropna().copy()
    if len(d) < 120: return None
    d["ret1"]  = d["close"].pct_change()
    d["volr"]  = d["volume"] / d["volume"].rolling(20).mean()
    d["fwd"]   = d["close"].shift(FWD) / d["close"] - 1     # placeholder; fixed below
    d["fwd"]   = d["close"].shift(-FWD) / d["close"] - 1
    d["turn"]  = d["close"] * d["volume"]
    turnover   = d["turn"].tail(60).median()               # robust daily turnover
    spikes = d[(d["ret1"] > 0) & (d["volr"] >= SPIKE_X)]["fwd"].dropna()
    base   = d["fwd"].dropna()
    if len(spikes) < MIN_SPIKES:
        return dict(turnover=turnover, n=len(spikes), edge=None, win=None,
                    spike_ret=None, last=float(d["close"].iloc[-1]))
    return dict(turnover=turnover, n=len(spikes),
                edge=(spikes.mean() - base.mean())*100, win=(spikes > 0).mean()*100,
                spike_ret=spikes.mean()*100, last=float(d["close"].iloc[-1]))

def main():
    print(f"Scanning {len(UNIVERSE)} IDX stocks (turnover >= Rp {MIN_TURNOVER/1e9:.0f}bn/day, "
          f"spike >= {SPIKE_X}x, fwd {FWD}d)...\n")
    rows = []
    tickers = [t + ".JK" for t in UNIVERSE]
    for k in range(0, len(tickers), 25):                   # download in chunks
        chunk = tickers[k:k+25]
        data = yf.download(chunk, period="2y", interval="1d", progress=False,
                           auto_adjust=True, group_by="ticker")
        for t in chunk:
            try:
                s = study(flat(data[t].copy()))
            except Exception:
                s = None
            if s is None: continue
            rows.append({"ticker": t.replace(".JK", ""), **s})

    df = pd.DataFrame(rows)
    liquid = df[df["turnover"] >= MIN_TURNOVER].copy()
    scored = liquid[liquid["edge"].notna()].copy()
    scored = scored.sort_values("edge", ascending=False)

    def tn(x): return f"{x/1e9:,.0f}bn"
    print("="*78)
    print(f"  TOP CANDIDATES BY VOLUME-SPIKE EDGE  (liquid, >= Rp {MIN_TURNOVER/1e9:.0f}bn/day)")
    print("="*78)
    print(f"  {'ticker':7}{'turnover/d':>12}{'spikes':>8}{'edge':>8}{'win%':>7}{'spikeRet':>10}  in list?")
    for _, r in scored.head(25).iterrows():
        here = "✓ HAVE" if r["ticker"] in WATCH else ""
        print(f"  {r['ticker']:7}{tn(r['turnover']):>12}{int(r['n']):>8}"
              f"{r['edge']:>+7.1f}%{r['win']:>6.0f}%{r['spike_ret']:>+9.1f}%  {here}")

    def tier(turn):
        return "BIG" if turn >= 100e9 else ("MID" if turn >= 30e9 else "OKAY")

    new = scored[(~scored["ticker"].isin(WATCH)) & (scored["edge"] >= 4) & (scored["win"] >= 50)].copy()
    new["tier"] = new["turnover"].apply(tier)
    print("\n" + "="*78)
    print("  💡 SUGGESTED ADDITIONS, GROUPED BY LIQUIDITY  (edge >= +4%, win >= 50%)")
    print("="*78)
    labels = {"BIG":  "🟦 BIG LIQUIDITY  (> Rp 100bn/day — safe for size, blue-chip movers)",
              "MID":  "🟩 MID LIQUIDITY  (Rp 30–100bn/day — solid)",
              "OKAY": "🟨 OKAY LIQUIDITY (Rp 10–30bn/day — high conviction but trade smaller)"}
    for tg in ["BIG", "MID", "OKAY"]:
        grp = new[new["tier"] == tg].sort_values("edge", ascending=False)
        if not len(grp): continue
        print(f"\n  {labels[tg]}")
        for _, r in grp.iterrows():
            print(f"     + {r['ticker']:7} {tn(r['turnover']):>8}/d · edge {r['edge']:+5.1f}% · "
                  f"win {r['win']:.0f}% · {int(r['n'])} spikes")

    weak = scored[(scored["ticker"].isin(WATCH)) & ((scored["edge"] < 2) | (scored["win"] < 45))]
    if len(weak):
        print("\n  ⚠️ CURRENT WATCHLIST NAMES LOOKING WEAK (consider dropping):")
        for _, r in weak.iterrows():
            print(f"  - {r['ticker']:7} edge {r['edge']:+.1f}% · win {r['win']:.0f}%")

    print(f"\n  Scanned {len(df)} with data · {len(liquid)} liquid · {len(scored)} had enough spikes.")
    print("  (edge = avg 10d return after UP+SPIKE minus the any-day baseline.)")

if __name__ == "__main__":
    main()
