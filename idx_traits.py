# idx_traits.py — Two questions on big-cap volume spikes:
#  A) What traits separate a GOOD spike from a BAD one? (winners vs losers, pooled)
#  B) Does a spike behave differently AFTER A CRASH vs on normal bullish days?
import warnings; warnings.filterwarnings("ignore")
import sys, pandas as pd, numpy as np, yfinance as yf

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

BIGCAP = ["BBCA","BMRI","BREN","ANTM","AMMN","PTRO","BRPT","CUAN","BUMI","DEWA"]
SPIKE  = 2.5
FWD    = 10

def rsi(s, n=14):
    d = s.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1/n, adjust=False).mean(); rd = dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + ru/rd)

def flat(df):
    if hasattr(df.columns, "levels"): df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]; return df

# Market regime: Jakarta Composite drawdown from its 1y rolling high
idx = flat(yf.download("^JKSE", period="2y", interval="1d", progress=False, auto_adjust=True))
jdd = (idx["close"] / idx["close"].rolling(252, min_periods=60).max() - 1) * 100
jdd.index = pd.to_datetime(jdd.index)

rows = []
data = yf.download([t+".JK" for t in BIGCAP], period="2y", interval="1d",
                   progress=False, auto_adjust=True, group_by="ticker")
for t in BIGCAP:
    d = flat(data[t+".JK"].dropna().copy())
    if len(d) < 80: continue
    d["ret1"]  = d["close"].pct_change()
    d["volr"]  = d["volume"] / d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(50).mean()
    d["hi60"]  = d["high"].rolling(60).max()
    d["rsi"]   = rsi(d["close"])
    d["fwd"]   = d["close"].shift(-FWD) / d["close"] - 1
    sp = d[(d["ret1"] > 0) & (d["volr"] >= SPIKE)].copy()
    for ix, r in sp.iterrows():
        if pd.isna(r["fwd"]) or pd.isna(r["sma50"]) or pd.isna(r["rsi"]): continue
        rng = (r["high"] - r["low"]) or 1e-9
        rows.append({
            "ticker": t, "date": ix, "fwd": r["fwd"]*100,
            "spike_x":    r["volr"],
            "day_gain":   r["ret1"]*100,
            "close_str":  (r["close"] - r["low"]) / rng,          # 1.0 = closed at the high
            "abv_sma50":  (r["close"]/r["sma50"] - 1)*100,
            "vs_60high":  (r["close"]/r["hi60"] - 1)*100,         # 0 = new breakout high
            "rsi":        r["rsi"],
            "mkt_dd":     jdd.reindex([pd.to_datetime(ix)], method="ffill").iloc[0],
        })

df = pd.DataFrame(rows)
print(f"Big-cap UP+SPIKE days analyzed: {len(df)}  ({len(df[df.fwd>0])} winners / {len(df[df.fwd<=0])} losers)\n")

# ── A) winners vs losers traits ──
feats = ["spike_x","day_gain","close_str","abv_sma50","vs_60high","rsi"]
W, L = df[df.fwd > 0], df[df.fwd <= 0]
print("="*64)
print("  A) TRAITS OF A GOOD SPIKE  (winner avg vs loser avg)")
print("="*64)
print(f"  {'trait':12}{'WINNERS':>10}{'LOSERS':>10}{'gap':>9}")
for f in feats:
    w, l = W[f].mean(), L[f].mean()
    print(f"  {f:12}{w:>10.2f}{l:>10.2f}{w-l:>+9.2f}")

# ── B) regime: post-crash vs normal ──
print("\n" + "="*64)
print("  B) SPIKE OUTCOME BY MARKET REGIME (Jakarta Composite drawdown)")
print("="*64)
print(f"  {'regime':28}{'n':>5}{'avg fwd10':>11}{'win%':>7}")
bins = [("Normal/near highs (dd > -4%)", df.mkt_dd > -4),
        ("Mild pullback (-4% to -8%)",    (df.mkt_dd <= -4) & (df.mkt_dd > -8)),
        ("Post-crash / stressed (dd <= -8%)", df.mkt_dd <= -8)]
for label, mask in bins:
    s = df[mask]
    if len(s) == 0: print(f"  {label:28}{0:>5}"); continue
    print(f"  {label:28}{len(s):>5}{s.fwd.mean():>+10.1f}%{(s.fwd>0).mean()*100:>6.0f}%")
