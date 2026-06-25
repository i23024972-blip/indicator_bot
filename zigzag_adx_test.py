# zigzag_adx_test.py
# Does adding an ADX (trend-strength) filter improve the ZigZag strategy?
# Only enter when 30m ADX >= threshold (skip choppy/rangebound conditions).
# Compare NO filter vs ADX 15/20/25 on BTC+DOGE+HYPE, long+short, 1000 days.
import pandas as pd
import numpy as np
from ta.trend import ADXIndicator
import zigzag_basket as zb

DEV = zb.DEVIATION; START = zb.START_CAPITAL

def backtest(bias_df, entry_df, adx_vals, adx_min):
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
        if adx_min > 0 and (np.isnan(adx_vals[i]) or adx_vals[i] < adx_min):
            continue                                   # ADX filter: skip weak-trend entries
        pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
        if pnl is None: continue
        side = "LONG" if bull else "SHORT"
        trades.append({"time":pd.Timestamp(et[i]), "net":pnl - zb.fee_of(side)})
    return trades

def report(trades):
    if not trades: return None
    df = pd.DataFrame(trades).sort_values("time")
    n = len(df); wins = (df["net"]>0).sum()
    bal_f = START; bal_h = START
    for net in df["net"]:
        bal_f *= (1+net/100.0); bal_h *= (1+0.5*net/100.0)
    return {"n":n, "win":wins/n*100, "net":df["net"].mean(), "full":bal_f, "half":bal_h}

def main():
    print("ADX filter test | BTC+DOGE+HYPE | 4H+30M | long+short | 1000d")
    print("  Only enter when 30m ADX >= threshold (filters choppy markets)\n")
    # preload data + ADX once per coin
    coins = []
    for sym, fut in zb.SYMBOLS:
        bias = zb.get_historical(sym, zb.BIAS_IV, fut, days=1000)
        entry = zb.get_historical(sym, zb.ENTRY_IV, fut, days=1000)
        if bias is None or entry is None: continue
        adx = ADXIndicator(entry["high"], entry["low"], entry["close"], window=14).adx().values
        coins.append((sym, bias, entry, adx))
        print(f"  loaded {sym}: {len(entry)} x 30m candles")

    print(f"\n  {'filter':>12} | {'trades':>6} | {'win':>6} | {'net/trade':>9} | {'$1000 full':>11} | {'$1000 @50%':>11}")
    print("  "+"-"*68)
    for adx_min in (0, 15, 20, 25):
        allt = []
        for sym, bias, entry, adx in coins:
            allt += backtest(bias, entry, adx, adx_min)
        s = report(allt)
        label = "NONE (now)" if adx_min==0 else f"ADX >= {adx_min}"
        if not s: print(f"  {label:>12} |  no trades"); continue
        print(f"  {label:>12} | {s['n']:>6} | {s['win']:>5.1f}% | {s['net']:>+8.3f}% | "
              f"${s['full']:>9,.0f} | ${s['half']:>9,.0f}")
    print("\n  Judge by: does win% AND capital go UP, with enough trades left to be meaningful?")

if __name__ == "__main__":
    main()
