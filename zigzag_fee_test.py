# zigzag_fee_test.py
# Capital is hugely sensitive to FEES when the edge is thin (+0.34%/trade).
# Cutting fees with MAKER (limit) orders + BNB discount is "free" capital — no strategy change,
# zero overfitting risk. Model the impact on BTC+DOGE+HYPE, long+short, 1000d.
import pandas as pd
import numpy as np
import zigzag_basket as zb

DEV = zb.DEVIATION; START = zb.START_CAPITAL

def gen_gross():
    """All trades with GROSS % (before fees) and side, so we can apply any fee scenario."""
    out = []
    for sym, fut in zb.SYMBOLS:
        bias = zb.get_historical(sym, zb.BIAS_IV, fut, days=1000)
        entry = zb.get_historical(sym, zb.ENTRY_IV, fut, days=1000)
        if bias is None or entry is None: continue
        entry = entry.copy(); entry["atr"] = zb.atr_series(entry)
        bl = zb.structure_label_array(bias, zb.compute_zigzag_pivots(bias, DEV))
        el_ = zb.structure_label_array(entry, zb.compute_zigzag_pivots(entry, DEV))
        bt = bias["time"].values; et = entry["time"].values
        bidx = np.searchsorted(bt, et, side="right") - 1
        atr_v = entry["atr"].values
        eh = entry["high"].values; el = entry["low"].values; ec = entry["close"].values
        prev = None
        for i in range(50, len(entry)-1):
            if pd.isna(atr_v[i]) or bidx[i] < 10: continue
            sb = bl[bidx[i]]; se = el_[i]
            fresh = (se != prev); prev = se
            if zb.FRESH_ONLY and not fresh: continue
            bull = (sb in zb.BULL) and (se in zb.BULL)
            bear = (sb in zb.BEAR) and (se in zb.BEAR)
            if not (bull or bear): continue
            pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
            if pnl is None: continue
            out.append({"time":pd.Timestamp(et[i]), "gross":pnl, "side":"LONG" if bull else "SHORT"})
    out.sort(key=lambda x: x["time"])
    return out

def equity(trades, long_fee, short_fee, frac):
    bal = START
    for t in trades:
        fee = long_fee if t["side"]=="LONG" else short_fee
        bal *= (1 + frac*(t["gross"]-fee)/100.0)
    return bal

def main():
    print("FEE sensitivity | BTC+DOGE+HYPE | long+short | 1000d | (thin edge -> fees matter a LOT)\n")
    tr = gen_gross()
    n = len(tr); gross_avg = np.mean([t["gross"] for t in tr])
    print(f"  {n} trades, avg GROSS {gross_avg:+.3f}%/trade (before fees)\n")
    scenarios = [
        ("Old assumption TAKER (.20 / .10)",      0.20, 0.10),
        ("MAKER limit orders  (.15 / .04)",       0.15, 0.04),
        ("YOUR MEASURED FEE (~.04 rt both)",      0.04, 0.04),
        ("Zero fees (theoretical ceiling)",       0.00, 0.00),
    ]
    print(f"  {'fee scenario':>38} | {'net/trade':>9} | {'$1000 @100%':>11} | {'$1000 @50%':>10}")
    print("  "+"-"*78)
    for name, lf, sf in scenarios:
        net = np.mean([t["gross"] - (lf if t["side"]=="LONG" else sf) for t in tr])
        full = equity(tr, lf, sf, 1.0); half = equity(tr, lf, sf, 0.5)
        print(f"  {name:>38} | {net:>+8.3f}% | ${full:>9,.0f} | ${half:>8,.0f}")
    print("\n  Same trades, only the FEE differs. Switching market->limit orders is pure free capital.")

if __name__ == "__main__":
    main()
