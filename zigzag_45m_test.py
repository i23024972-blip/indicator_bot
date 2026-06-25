# zigzag_45m_test.py
# 45m doesn't exist on Binance, so build it (and 30m) from 15m candles and compare
# 4H bias + 45m entry  vs  4H bias + 30m entry, on BTC+DOGE+HYPE, long+short.
import pandas as pd
import numpy as np
import zigzag_basket as zb

ENTRY_DAYS = 1000         # full window (15m built into 30m & 45m for the comparison)
DEV   = zb.DEVIATION      # 5%
START = zb.START_CAPITAL

def resample(df15, rule):
    d = df15.set_index("time")
    out = pd.DataFrame({
        "open":  d["open"].resample(rule, label="left", closed="left").first(),
        "high":  d["high"].resample(rule, label="left", closed="left").max(),
        "low":   d["low"].resample(rule, label="left", closed="left").min(),
        "close": d["close"].resample(rule, label="left", closed="left").last(),
        "volume":d["volume"].resample(rule, label="left", closed="left").sum(),
    }).dropna().reset_index()
    return out

def backtest(bias_df, entry_df):
    entry_df = entry_df.copy(); entry_df["atr"] = zb.atr_series(entry_df)
    bias_lbl  = zb.structure_label_array(bias_df,  zb.compute_zigzag_pivots(bias_df,  DEV))
    entry_lbl = zb.structure_label_array(entry_df, zb.compute_zigzag_pivots(entry_df, DEV))
    bt = bias_df["time"].values; et = entry_df["time"].values
    bidx_for = np.searchsorted(bt, et, side="right") - 1
    atr_v = entry_df["atr"].values
    eh = entry_df["high"].values; el = entry_df["low"].values; ec = entry_df["close"].values
    trades = []; prev = None
    for i in range(50, len(entry_df)-1):
        if pd.isna(atr_v[i]): continue
        if bidx_for[i] < 10: continue
        s_bias = bias_lbl[bidx_for[i]]; s_entry = entry_lbl[i]
        fresh = (s_entry != prev); prev = s_entry
        if zb.FRESH_ONLY and not fresh: continue
        bull = (s_bias in zb.BULL) and (s_entry in zb.BULL)
        bear = (s_bias in zb.BEAR) and (s_entry in zb.BEAR)
        if not (bull or bear): continue
        pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
        if pnl is None: continue
        side = "LONG" if bull else "SHORT"
        trades.append({"time":pd.Timestamp(et[i]), "net":pnl - zb.fee_of(side)})
    return trades

def stats(trades):
    if not trades: return None
    df = pd.DataFrame(trades).sort_values("time")
    n = len(df); wins = (df["net"]>0).sum()
    # full-equity and 50%-fixed equity for context
    bal_f = START; bal_h = START
    for net in df["net"]:
        bal_f *= (1+net/100.0); bal_h *= (1+0.5*net/100.0)
    return {"n":n, "win":wins/n*100, "bep":df["net"].mean()+0.15, "net":df["net"].mean(),
            "full":bal_f, "half":bal_h}

def main():
    print(f"45m vs 30m test | 4H bias | BTC+DOGE+HYPE | long+short | ~{ENTRY_DAYS}d of 15m data")
    print("  (30m and 45m both BUILT from the same 15m candles -> fair comparison)\n")
    agg = {"30m": [], "45m": []}
    for sym, fut in zb.SYMBOLS:
        bias = zb.get_historical(sym, zb.BIAS_IV, fut, days=1000)
        df15 = zb.get_historical(sym, "15m", fut, days=ENTRY_DAYS)
        if bias is None or df15 is None:
            print(f"  {sym}: data missing, skipped"); continue
        e30 = resample(df15, "30min"); e45 = resample(df15, "45min")
        agg["30m"] += backtest(bias, e30)
        agg["45m"] += backtest(bias, e45)
        print(f"  {sym}: 15m candles {len(df15)} -> 30m {len(e30)}, 45m {len(e45)}")

    print(f"\n  {'entry TF':>9} | {'trades':>6} | {'win':>6} | {'net/trade':>9} | {'$1000 full':>11} | {'$1000 @50%':>11}")
    print("  "+"-"*66)
    for tf in ("30m","45m"):
        s = stats(agg[tf])
        if not s: print(f"  {tf:>9} |  no trades"); continue
        print(f"  {tf:>9} | {s['n']:>6} | {s['win']:>5.1f}% | {s['net']:>+8.3f}% | "
              f"${s['full']:>9,.0f} | ${s['half']:>9,.0f}")
    print("\n  net/trade = avg % after fee. Compare the two rows: does 45m actually beat 30m?")

if __name__ == "__main__":
    main()
