# idx_alpha.py — What triggers the big up-moves? For each watchlist stock, find "launches"
# (days where the next 20d return > LAUNCH%) and measure what was distinctive at/just before
# the launch vs a normal day: accumulation (OBV), volume, volatility compression, breakout,
# how far below recent highs (basing). Tells us the common DNA of the moves.
import warnings; warnings.filterwarnings("ignore")
import sys
import pandas as pd, numpy as np
import idx_konglo as K
from idx_scan import WATCHLIST

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

LAUNCH = 0.20      # +20% over the next 20 days = a "launch"
FWD    = 20

def feats(d):
    d = d.dropna().copy()
    if len(d) < 120: return None
    c, v, h, l = d["close"], d["volume"], d["high"], d["low"]
    sign = c.diff().apply(lambda x: 1 if x>0 else (-1 if x<0 else 0))
    obv  = (sign*v).cumsum()
    vma  = v.rolling(20).mean()
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    sma50 = c.rolling(50).mean()
    hi20 = h.rolling(20).max()
    f = pd.DataFrame(index=d.index)
    f["fwd"]      = c.shift(-FWD)/c - 1
    # accumulation: OBV rising over last 20d while price ~flat (money in, price hasn't moved yet)
    f["obv_slope"]= (obv - obv.shift(20)) / (vma*20)        # >0 = net accumulation
    f["price_20"] = c/c.shift(20) - 1                       # was price flat/down before?
    f["accum"]    = ((f["obv_slope"] > 0.15) & (f["price_20"] < 0.05)).astype(int)
    # volume buildup just before
    f["vol_build"]= v.rolling(5).mean()/vma
    f["vol_spike"]= v/vma
    # volatility compression (coil) then expansion
    f["atr_ratio"]= atr/atr.shift(20)                      # <1 = was compressing
    # breakout above 20-day high
    f["breakout"] = (c/hi20)                                # ~1+ = new high
    # basing: how far below the 60-day high (recovering off a base?)
    f["below_hi"] = c/h.rolling(60).max() - 1
    f["above_ma"] = c/sma50 - 1
    return f.dropna()

def main():
    print(f"Alpha-driver study: what precedes a +{LAUNCH*100:.0f}% move in {FWD} days?\n"
          f"Watchlist: {len(WATCHLIST)} stocks\n")
    allf = []
    for t in WATCHLIST:
        d, _ = K.get_eod(t+".JK", period="3y")
        if d is None: continue
        f = feats(d)
        if f is not None and len(f):
            f["ticker"] = t; allf.append(f)
    F = pd.concat(allf, ignore_index=True)
    launch = F[F["fwd"] >= LAUNCH]
    base   = F

    print("="*66)
    print(f"  LAUNCH DAYS (n={len(launch)})  vs  ALL DAYS (n={len(base)})")
    print("="*66)
    rows = [
        ("Accumulation flag (OBV up, price flat)", "accum",     "share"),
        ("OBV slope (accumulation strength)",      "obv_slope", "mean"),
        ("Volume buildup (5d avg / 20d avg)",      "vol_build", "mean"),
        ("Volume spike that day (x avg)",          "vol_spike", "mean"),
        ("Volatility compression (ATR now/20d)",   "atr_ratio", "mean"),
        ("Breakout (price / 20d high)",            "breakout",  "mean"),
        ("Below 60d high (basing depth)",          "below_hi",  "mean"),
        ("Above 50-day MA",                        "above_ma",  "mean"),
    ]
    print(f"  {'driver':42}{'LAUNCH':>10}{'normal':>9}")
    for label, col, how in rows:
        if how == "share":
            a, b = launch[col].mean()*100, base[col].mean()*100
            print(f"  {label:42}{a:>9.0f}%{b:>8.0f}%")
        else:
            a, b = launch[col].mean(), base[col].mean()
            print(f"  {label:42}{a:>10.2f}{b:>9.2f}")

    # how launches START: breakout vs accumulation vs spike
    print("\n" + "="*66)
    print("  HOW DID THE LAUNCHES BEGIN? (share of launch days showing each)")
    print("="*66)
    print(f"  Prior accumulation (smart money in first) : {launch['accum'].mean()*100:>4.0f}%")
    print(f"  Volume spike >=2x on the day              : {(launch['vol_spike']>=2).mean()*100:>4.0f}%")
    print(f"  Breakout to new 20-day high               : {(launch['breakout']>=1.0).mean()*100:>4.0f}%")
    print(f"  Was still >10% below its 60-day high      : {(launch['below_hi']<=-0.10).mean()*100:>4.0f}%")
    print(f"  Volatility was compressing (atr<1)        : {(launch['atr_ratio']<1).mean()*100:>4.0f}%")

if __name__ == "__main__":
    main()
