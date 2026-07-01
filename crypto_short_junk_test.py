# crypto_short_junk_test.py — backtest: SHORT-ONLY breakdown strategy on "junk" alts (low-liquidity,
# high-vol perps that fall BELOW the main bot's top-45 liquid-universe cutoff). Question being
# tested: do low-quality alts bleed hard enough, independent of BTC's own bull/bear regime, that
# shorting their breakdowns is a standalone edge? No BTC regime gate — shorts fire whenever the
# per-coin signal fires. Same mechanics as the live bot: 3xATR stop, 4xATR chandelier trail,
# 200-EMA + 200-bar LR-slope filter, 1% risk/trade, cap 6 concurrent, 0.2% round-trip fee.
# $1k start. Read-only backtest — needs live Binance API access (this sandbox has none; run it
# somewhere with internet, e.g.: pip install python-binance pandas numpy && python crypto_short_junk_test.py
import sys, time, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

DAYS=380; INTERVAL="4h"
SL_ATR=3.0; TRAIL_ATR=4.0; FEE=0.2; START=1000.0; RISK=1.0; MAXPOS=6
JUNK_MIN_VOL=3e6; JUNK_MAX_VOL=50e6   # below the main bot's $50M liquidity floor = the "junk" tier
VOL_LO,VOL_HI=1.2,6.0                 # junk coins run hotter than the main bot's 0.8-3.2% ATR band
LR_LEN=200

def mkclient():
    for _ in range(6):
        try: return Client(requests_params={"timeout":30})
        except Exception: time.sleep(6)
    return Client(requests_params={"timeout":30})
client=mkclient()

def lr_slope(src,n=LR_LEN):
    N=len(src); idx=np.arange(N,dtype=float); s=pd.Series(src)
    Sx=n*(n-1)/2.0; Sxx=(n-1)*n*(2*n-1)/6.0; denom=n*Sxx-Sx*Sx
    Sy=s.rolling(n).sum().values; Sjy=pd.Series(idx*src).rolling(n).sum().values
    Sxy=Sjy-(idx-n+1)*Sy
    return (n*Sxy-Sx*Sy)/denom

def fetch(sym):
    kl=client.futures_historical_klines(sym, INTERVAL, f"{DAYS} days ago UTC")
    df=pd.DataFrame(kl,columns=["t","open","high","low","close","v","ct","q","n","tb","tq","ig"])
    for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["t"],unit="ms")
    pc=df["close"].shift(1); tr=pd.concat([(df["high"]-df["low"]),(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
    df["atr"]=tr.rolling(14).mean(); df["ema"]=df["close"].ewm(span=200,adjust=False).mean()
    df["lrslope"]=lr_slope(df["close"].values,LR_LEN)
    day=df["time"].dt.floor("D")
    df["pdl"]=day.map(df.groupby(day)["low"].min().shift(1))
    return df.set_index("time")

def pick_junk_universe():
    info=client.futures_exchange_info()
    syms=[s["symbol"] for s in info["symbols"] if s["symbol"].endswith("USDT")
          and s.get("contractType")=="PERPETUAL" and s["status"]=="TRADING"]
    vol={t["symbol"]:float(t["quoteVolume"]) for t in client.futures_ticker()}
    return sorted([s for s in syms if JUNK_MIN_VOL<=vol.get(s,0)<JUNK_MAX_VOL], key=lambda s:-vol.get(s,0))

def main():
    print(f"SHORT-ONLY JUNK-ALT BACKTEST · {INTERVAL} · {DAYS}d · ${START:,.0f} start · {RISK:g}% risk · cap {MAXPOS}\n")
    universe=pick_junk_universe()
    print(f"  junk universe (${JUNK_MIN_VOL/1e6:.0f}-{JUNK_MAX_VOL/1e6:.0f}M vol/day): {len(universe)} symbols")
    data={}
    for s in universe:
        try:
            d=fetch(s)
            if len(d)<220: continue
            volp=(d["atr"]/d["close"]).median()*100
            if VOL_LO<=volp<=VOL_HI: data[s]=d
        except Exception: pass
    print(f"  {len(data)} pass the volatility filter ({VOL_LO}-{VOL_HI}% ATR)\n")
    if not data:
        print("  nothing to trade — widen the filters."); return

    idx=sorted(set().union(*[set(d.index) for d in data.values()]))
    cash=START; positions={}; closed=[]; curve=[]
    for t in idx:
        # 1) manage open shorts — 4xATR chandelier trail, exit if stop hit
        for sym in list(positions):
            d=data[sym]
            if t not in d.index: continue
            r=d.loc[t]; p=positions[sym]; a=float(r["atr"])
            if pd.isna(a): continue
            p["peak"]=min(p["peak"],float(r["low"]))
            p["stop"]=min(p["stop"],p["peak"]+TRAIL_ATR*a)
            if float(r["high"])>=p["stop"]:
                px=p["stop"]; dir=-1
                pnl_pct=dir*(px-p["entry"])/p["entry"]*100-FEE
                cash+=p["units"]*p["entry"]+p["units"]*(px-p["entry"])*dir-p["units"]*p["entry"]*(FEE/100)
                closed.append({"sym":sym,"pnl":pnl_pct}); del positions[sym]

        # 2) new short entries — break below prev-day low, below 200-EMA, downtrend LR-slope
        if len(positions)<MAXPOS:
            for sym,d in data.items():
                if sym in positions or t not in d.index: continue
                i=d.index.get_loc(t)
                if i<1: continue
                r=d.iloc[i]; pr=d.iloc[i-1]; a=float(r["atr"])
                if pd.isna(a) or a<=0 or pd.isna(r["pdl"]) or pd.isna(r["ema"]): continue
                slp=r.get("lrslope"); slp=None if pd.isna(slp) else float(slp)
                sig=r["close"]<r["pdl"] and pr["close"]>=r["pdl"] and r["close"]<r["ema"] and (slp is None or slp<0)
                if not sig: continue
                entry=float(r["close"]); stop=entry+SL_ATR*a
                eq=cash+sum(pp["units"]*pp["entry"] for pp in positions.values())
                risk_usd=RISK/100*eq; units=risk_usd/(SL_ATR*a); cost=units*entry
                if cost>cash or units<=0: continue
                cash-=cost
                positions[sym]={"entry":entry,"units":units,"stop":stop,"peak":entry}
                if len(positions)>=MAXPOS: break

        eq=cash+sum(p["units"]*p["entry"] for p in positions.values())
        curve.append(eq)

    curve=np.array(curve); final=float(curve[-1]) if len(curve) else START
    peak=-1.0; dd=0.0
    for e in curve: peak=max(peak,e); dd=max(dd,(peak-e)/peak*100)
    n=len(closed); wr=(np.array([c["pnl"] for c in closed])>0).mean()*100 if n else 0.0
    months=DAYS/30.4
    total_ret=(final/START-1)*100
    monthly=((final/START)**(1/months)-1)*100 if final>0 else -100.0
    print("="*60)
    print(f"  trades closed: {n}  ·  win rate: {wr:.0f}%")
    print(f"  ${START:,.0f} -> ${final:,.0f}   ({total_ret:+.0f}% total, {monthly:+.1f}%/mo avg)")
    print(f"  max drawdown: {dd:.0f}%")
    print("="*60)
    if closed:
        by_sym=pd.DataFrame(closed).groupby("sym")["pnl"].agg(["count","sum"]).sort_values("sum")
        print("\n  worst 5 coins (sum R%):"); print(by_sym.head(5))
        print("\n  best 5 coins (sum R%):"); print(by_sym.tail(5))

if __name__=="__main__":
    main()
