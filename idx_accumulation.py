# idx_accumulation.py — "Bandarmology" proxy from price+volume (no broker data needed).
# Detects accumulation/capitulation footprints and tests if they precede pumps.
#   CAPIT  : heavy-volume DOWN day (retail flush) in last 3 bars, then an up-day bounce.
#   OBV    : OBV higher than 20d ago while price flat/down (quiet accumulation) + up-day.
#   MOMENT : the existing winner — up-day + 2.5x volume spike + above 50MA (for comparison).
# Long only. Same exit engine + fees as everything else, so it's directly comparable.
import sys
import pandas as pd
import idx_konglo as K
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

WATCH = ["BBCA","BMRI","BREN","CUAN","PTRO","BRPT","DEWA","BUMI","ANTM","AMMN","RAJA","PANI"]
SL_X, TP_X, HOLD, FEE, SPIKE = 2.0, 6.0, 20, 0.4, 2.5

def prep(t):
    d, _ = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < 90:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(50).mean()
    d["ret1"]  = d["close"].pct_change()
    sign = d["ret1"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    d["obv"]   = (sign * d["volume"]).cumsum()
    d["obv20"] = d["obv"].shift(20)
    d["price20"] = d["close"] / d["close"].shift(20) - 1
    return d

def valid(d, i):
    return not (pd.isna(d["atr"].iloc[i]) or pd.isna(d["sma50"].iloc[i])
                or pd.isna(d["volma"].iloc[i]) or pd.isna(d["obv20"].iloc[i]) or d["atr"].iloc[i] <= 0)

def signal(d, i, kind):
    up = d["ret1"].iloc[i] > 0
    if kind == "CAPIT":
        cap = any(d["ret1"].iloc[k] < 0 and d["volume"].iloc[k] >= 3 * d["volma"].iloc[k]
                  for k in (i, i-1, i-2))
        return cap and up
    if kind == "OBV":
        accum = d["obv"].iloc[i] > d["obv20"].iloc[i] and d["price20"].iloc[i] <= 0.02
        return accum and up and d["volume"].iloc[i] >= d["volma"].iloc[i]
    if kind == "MOMENT":
        return up and d["volume"].iloc[i] >= SPIKE * d["volma"].iloc[i] and d["close"].iloc[i] > d["sma50"].iloc[i]
    return False

def sim_long(d, i):
    atr = d["atr"].iloc[i]; entry = d["close"].iloc[i]
    sl, tp = entry - SL_X*atr, entry + TP_X*atr
    end = min(i + HOLD, len(d)-1)
    for j in range(i+1, end+1):
        if d["low"].iloc[j]  <= sl: return (sl-entry)/entry*100, j-i
        if d["high"].iloc[j] >= tp: return (tp-entry)/entry*100, j-i
    return (d["close"].iloc[end]-entry)/entry*100, end-i

def collect(frames, kind):
    trades = []
    for t, d in frames.items():
        last = -1
        for i in range(60, len(d)-1):
            if not valid(d, i) or i <= last:
                continue
            if signal(d, i, kind):
                pnl, bars = sim_long(d, i); last = i + bars
                xi = min(i+bars, len(d)-1)
                trades.append({"ticker": t, "entry": d["time"].iloc[i],
                               "exit": d["time"].iloc[xi], "pnl": pnl - FEE})
    return trades

def stats(trades, label):
    if not trades:
        print(f"  {label:22} no trades"); return
    df = pd.DataFrame(trades); n=len(df); wr=(df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  {label:22} n={n:4} win={wr:4.0f}%  avgW/L=+{aw:4.1f}/{al:5.1f}  exp={df.pnl.mean():+5.2f}%/trade")

def main():
    print(f"Loading {len(WATCH)} stocks...")
    frames = {t: d for t in WATCH if (d := prep(t)) is not None}
    print(f"Loaded {len(frames)}. Exit SL{SL_X}/TP{TP_X}xATR, {HOLD}d, fee {FEE}%.\n")

    runs = {k: collect(frames, k) for k in ["CAPIT", "OBV", "MOMENT"]}
    print("="*72 + "\n  SIGNAL EDGE (net fees)\n" + "="*72)
    stats(runs["CAPIT"],  "CAPITULATION bounce")
    stats(runs["OBV"],    "OBV accumulation")
    stats(runs["MOMENT"], "MOMENTUM (the champ)")

    print("\n" + "="*72 + "\n  $1,000 PORTFOLIO  (25% per trade, max 4)\n" + "="*72)
    print(f"  {'strategy':22}{'Final $':>12}{'x':>7}")
    for k in ["CAPIT", "OBV", "MOMENT"]:
        if runs[k]:
            f = simulate(runs[k], 0.25, 4)["final"]
            print(f"  {k:22}${f:>10,.0f}{f/START:>6.1f}x")
    # accumulation OR momentum combined
    merged = sorted(runs["CAPIT"] + runs["OBV"] + runs["MOMENT"], key=lambda x: x["entry"])
    # de-dup same ticker+entry
    seen=set(); uniq=[]
    for tr in merged:
        key=(tr["ticker"], tr["entry"])
        if key in seen: continue
        seen.add(key); uniq.append(tr)
    if uniq:
        f = simulate(uniq, 0.25, 4)["final"]
        print(f"  {'ALL combined':22}${f:>10,.0f}{f/START:>6.1f}x   (n={len(uniq)})")

if __name__ == "__main__":
    main()
