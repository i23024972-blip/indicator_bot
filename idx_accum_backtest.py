# idx_accum_backtest.py — Test the alpha-driven ACCUMULATION entry vs the Combo.
# ACCUM idea (from idx_alpha findings): buy when smart money is accumulating during a base,
# BEFORE the volume spike. Signal at day i (long only):
#   · OBV rising strongly over 20d  (accumulation)
#   · close > 50-day MA             (uptrend intact)
#   · still below its 60-day high   (basing / room to run, not chasing highs)
#   · price hasn't already exploded (price_20d < +20%)
#   · up day today                  (timing)
# Same exit engine + fees as everything else, so it's directly comparable.
import sys
import pandas as pd
import idx_konglo as K
from idx_scan import WATCHLIST
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TREND_MA, SL_X, TP_X, HOLD, FEE, SPIKE_X = 50, 2.0, 6.0, 20, 0.4, 2.5
OBV_SLOPE = 0.15

def prep(t):
    d, w = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < TREND_MA + 40 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(TREND_MA).mean()
    d["ret1"]  = d["close"].pct_change()
    d["hi60"]  = d["high"].rolling(60).max()
    sign = d["ret1"].apply(lambda x: 1 if x>0 else (-1 if x<0 else 0))
    d["obv"]   = (sign * d["volume"]).cumsum()
    d["obv_slope"] = (d["obv"] - d["obv"].shift(20)) / (d["volma"] * 20)
    d["price20"]   = d["close"] / d["close"].shift(20) - 1
    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    d["sd"] = [K.structure_at(zz_d, i) for i in range(len(d))]
    sw = []
    for i in range(len(d)):
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw.append(K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral")
    d["sw"] = sw
    return d

def valid(d, i):
    return not (pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i] <= 0 or pd.isna(d["sma50"].iloc[i])
                or pd.isna(d["volma"].iloc[i]) or pd.isna(d["obv_slope"].iloc[i]) or pd.isna(d["hi60"].iloc[i]))

def sig_combo(d, i):
    return (d["ret1"].iloc[i] > 0 and d["volume"].iloc[i] >= SPIKE_X*d["volma"].iloc[i]
            and d["close"].iloc[i] > d["sma50"].iloc[i]
            and d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL)

def sig_accum(d, i):
    return (d["obv_slope"].iloc[i] >= OBV_SLOPE
            and d["close"].iloc[i] > d["sma50"].iloc[i]
            and d["close"].iloc[i] <= 0.95 * d["hi60"].iloc[i]
            and d["price20"].iloc[i] < 0.20
            and d["ret1"].iloc[i] > 0)

def sim_long(d, i):
    atr = d["atr"].iloc[i]; entry = d["close"].iloc[i]
    sl, tp = entry - SL_X*atr, entry + TP_X*atr
    end = min(i + HOLD, len(d)-1)
    for j in range(i+1, end+1):
        if d["low"].iloc[j]  <= sl: return (sl-entry)/entry*100, j-i
        if d["high"].iloc[j] >= tp: return (tp-entry)/entry*100, j-i
    return (d["close"].iloc[end]-entry)/entry*100, end-i

def collect(frames, sigfn):
    trades = []
    for t, d in frames.items():
        last = -1
        for i in range(TREND_MA, len(d)-1):
            if not valid(d, i) or i <= last: continue
            if sigfn(d, i):
                pnl, bars = sim_long(d, i); last = i + bars
                xi = min(i+bars, len(d)-1)
                trades.append({"ticker": t, "entry": d["time"].iloc[i],
                               "exit": d["time"].iloc[xi], "pnl": pnl - FEE})
    return trades

def stats(rows, label):
    if not rows: print(f"  {label:16} no trades"); return
    df = pd.DataFrame(rows); n=len(df); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al=df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  {label:16} n={n:4} win={wr:4.0f}%  avgW/L=+{aw:4.1f}/{al:5.1f}  "
          f"exp={df.pnl.mean():+5.2f}%/trade  total={df.pnl.sum():+8.0f}%")

def main():
    print(f"Loading {len(WATCHLIST)} stocks...")
    frames = {t: d for t in WATCHLIST if (d := prep(t)) is not None}
    print(f"Loaded {len(frames)}.\n")

    combo = collect(frames, sig_combo)
    accum = collect(frames, sig_accum)
    # union: take whichever fires first, non-overlapping per ticker
    def union(frames):
        trades = []
        for t, d in frames.items():
            last = -1
            for i in range(TREND_MA, len(d)-1):
                if not valid(d, i) or i <= last: continue
                if sig_combo(d, i) or sig_accum(d, i):
                    pnl, bars = sim_long(d, i); last = i + bars
                    xi = min(i+bars, len(d)-1)
                    trades.append({"ticker": t, "entry": d["time"].iloc[i],
                                   "exit": d["time"].iloc[xi], "pnl": pnl - FEE})
        return trades
    both = union(frames)

    print("="*72 + "\n  SIGNAL EDGE (net fees, 3y)\n" + "="*72)
    stats(combo, "COMBO (spike)")
    stats(accum, "ACCUM (early)")
    stats(both,  "BOTH (union)")

    print("\n" + "="*72 + "\n  $1,000 PORTFOLIO  (25% × max4)\n" + "="*72)
    crash = lambda tr: [x for x in tr if x["entry"] >= pd.Timestamp("2025-08-01")]
    for label, tr in [("COMBO", combo), ("ACCUM", accum), ("BOTH", both)]:
        a = simulate(tr, 0.25, 4); b = simulate(crash(tr), 0.25, 4)
        print(f"  {label:7} full 3y: ${a['final']:>7,.0f} ({a['final']/START:.1f}x, DD {a['maxdd']:.0f}%)"
              f"   ·   since Aug'25: ${b['final']:>7,.0f} ({b['final']/START:.1f}x)")

if __name__ == "__main__":
    main()
