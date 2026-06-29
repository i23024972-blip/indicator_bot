# idx_recovery.py — a RECOVERY-phase strategy, tested on the COVID crash→recovery (2019-2021).
# DONCH50+200 is the HEALTHY-market tool (late). In a recovery you want earlier — but catching
# bottoms on individual stocks = knife-catching (proven). The fix: TOP-DOWN green light +
# BOTTOM-UP speed:
#   · Green light : the INDEX (IHSG) reclaims its 50-day MA = "the bottom is in, risk-on".
#                   (This filters out mid-crash dead-cat bounces — the thing that kills you.)
#   · Entry       : ONLY when risk-on, buy a stock breaking its 20-day high above its 20-day MA
#                   (much faster than the 50d-high/200MA combo → catches the recovery early).
#   · Exit        : ride a 4-ATR chandelier trail; exit on close below the 50-day MA.
# Compared head-to-head vs DONCH50+200 over the same COVID window + universe.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

START_EQ=1000.0; SLIP=0.003; FEE=0.4
TRAIL_ATR, INIT_ATR, MAXHOLD = 4.0, 2.5, 250
S, E = "2019-06-01", "2021-12-31"          # pre-COVID → crash → recovery
# liquid IDX names that existed & traded through 2020
UNIVERSE = ["BBCA","BBRI","BMRI","BBNI","ASII","TLKM","UNTR","ANTM","INCO","INDF",
            "ICBP","PGAS","ITMG","ADRO","KLBF","UNVR","SMGR","PTBA","AALI","GGRM",
            "HMSP","JPFA","CPIN","ERAA","MDKA","TINS","BRPT","TPIA","INKP","MNCN"]

def atr14(d):
    h,l,c=d["high"],d["low"],d["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(14).mean()

def simulate(trades, frac=0.20, mx=5):
    cash=START_EQ; openp=[]; peak=-1; maxdd=0
    for tr in sorted(trades,key=lambda x:x["entry"]):
        keep=[]                                  # release positions that have closed
        for p in openp:
            if p["exit"]<=tr["entry"]: cash+=p["cost"]*(1+p["pnl"]/100)
            else: keep.append(p)
        openp=keep
        eq=cash+sum(p["cost"] for p in openp)
        peak=max(peak,eq); maxdd=max(maxdd,(peak-eq)/peak*100)
        if len(openp)>=mx: continue
        cost=min(frac*eq,cash)
        if cost<=1: continue
        cash-=cost; openp.append({"exit":tr["exit"],"cost":cost,"pnl":tr["pnl"]})
    for p in openp: cash+=p["cost"]*(1+p["pnl"]/100)
    return cash, maxdd

def ride(d, mode, risk):
    o,hi,lo,cl=d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr=d["atr"].values; t=d["time"].values
    sma20=pd.Series(cl).rolling(20).mean().values
    sma50=pd.Series(cl).rolling(50).mean().values
    sma200=pd.Series(cl).rolling(200).mean().values
    d20=pd.Series(hi).rolling(20).max().shift(1).values
    d50=pd.Series(hi).rolling(50).max().shift(1).values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0: i+=1; continue
        ro = bool(risk.asof(pd.Timestamp(t[i])))
        if mode=="RECOVERY":
            fire = ro and not np.isnan(d20[i]) and not np.isnan(sma20[i]) and cl[i]>d20[i] and cl[i]>sma20[i]
        else:  # DONCH50+200
            fire = not np.isnan(d50[i]) and not np.isnan(sma200[i]) and cl[i]>d50[i] and cl[i]>sma200[i]
        if not fire: i+=1; continue
        k=i+1; entry=o[k]*(1+SLIP)
        if o[k]>hi[i]*1.04: i+=1; continue
        stop=entry-INIT_ATR*a; runmax=entry; end=min(k+MAXHOLD,n-1); pnl=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            if lo[j]<=stop: pnl=(stop*(1-SLIP)-entry)/entry*100; xk=j; break
            if j>k and not np.isnan(sma50[j]) and cl[j]<sma50[j]: pnl=(cl[j]*(1-SLIP)-entry)/entry*100; xk=j; break
        if pnl is None: pnl=(cl[end]*(1-SLIP)-entry)/entry*100; xk=end
        out.append({"ticker":None,"entry":pd.Timestamp(t[k]),"exit":pd.Timestamp(t[xk]),
                    "pnl":pnl-FEE,"bars":xk-k}); i=xk+1
    return out

def main():
    print(f"RECOVERY strategy vs DONCH50+200 · COVID lab {S}→{E}\n")
    ih=yf.download("^JKSE",start=S,end=E,progress=False,auto_adjust=True)
    if hasattr(ih.columns,"levels"): ih.columns=ih.columns.get_level_values(0)
    ih.columns=[c.lower() for c in ih.columns]
    ma50=ih["close"].rolling(50).mean()
    risk=pd.Series((ih["close"]>ma50).values, index=ih.index.tz_localize(None).normalize())
    # find the COVID green-light date (first risk-on after the March-2020 crash)
    gl = risk["2020-03-01":"2020-12-31"]
    green = gl[gl].index[0] if gl.any() else None
    print(f"  IHSG green-light (reclaimed 50MA post-crash): {green.date() if green is not None else 'n/a'}")
    bh = (ih['close'].loc[E if green is None else green:].iloc[-1]/ih['close'].loc[green:].iloc[0]-1)*100 if green is not None else 0
    print(f"  Buy-and-hold IHSG from green-light → end: {bh:+.0f}%\n")

    built={}
    for tk in UNIVERSE:
        try:
            d=yf.download(tk+".JK",start=S,end=E,progress=False,auto_adjust=True)
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
            for x in ride(d,mode,risk): x["ticker"]=tk; trades.append(x)
        if not trades: print(f"  {mode}: no trades"); continue
        df=pd.DataFrame(trades); wr=(df.pnl>0).mean()*100
        final,maxdd=simulate(trades)
        cov=df[(df.entry>=pd.Timestamp("2020-03-01"))&(df.entry<=pd.Timestamp("2020-12-31"))]
        first=df.entry.min()
        print("="*64)
        print(f"  {mode}")
        print("="*64)
        print(f"  Trades {len(df)} · win {wr:.0f}% · avg hold {df.bars.mean():.0f}d · exp {df.pnl.mean():+.1f}%")
        print(f"  $1k → ${final:,.0f} ({final/START_EQ:.1f}x) · MaxDD {maxdd:.0f}%")
        print(f"  First entry: {first.date()} · recovery-window (Mar-Dec'20) entries: {len(cov)} "
              f"(avg {cov.pnl.mean():+.0f}%)" if len(cov) else f"  First entry: {first.date()} · no recovery-window entries")
        print()
    print("  KEY: did RECOVERY enter earlier (closer to the bottom) and capture more of the V?")

if __name__=="__main__":
    main()
