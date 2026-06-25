# zigzag_pyramid_test.py
# Does PYRAMIDING (adding to winning trades) gain more capital?
# Rule: when a fresh same-direction signal fires while an existing position on that coin is in
#       profit, ADD another unit (up to MAX_ADDS). Each unit has its own TP4/SL1.5.
# Compare vs baseline (one position per coin, no adds). Shared $1000, no leverage.
import pandas as pd
import numpy as np
import zigzag_basket as zb

DEV = zb.DEVIATION; START = zb.START_CAPITAL
POS_FRAC = 0.33        # each unit ~1/3 of equity (so ~3 units = fully deployed)
MAX_ADDS = 2           # up to 2 extra units stacked on a winning coin (3 total)

def gen_signals():
    out = []
    for sym, fut in zb.SYMBOLS:
        bias = zb.get_historical(sym, zb.BIAS_IV, fut, days=1000)
        entry = zb.get_historical(sym, zb.ENTRY_IV, fut, days=1000)
        if bias is None or entry is None: continue
        entry = entry.copy(); entry["atr"] = zb.atr_series(entry)
        bias_lbl = zb.structure_label_array(bias, zb.compute_zigzag_pivots(bias, DEV))
        entry_lbl= zb.structure_label_array(entry, zb.compute_zigzag_pivots(entry, DEV))
        bt = bias["time"].values; et = entry["time"].values
        bidx = np.searchsorted(bt, et, side="right") - 1
        atr_v = entry["atr"].values
        eh = entry["high"].values; el = entry["low"].values; ec = entry["close"].values
        prev = None
        for i in range(50, len(entry)-1):
            if pd.isna(atr_v[i]) or bidx[i] < 10: continue
            s_b = bias_lbl[bidx[i]]; s_e = entry_lbl[i]
            fresh = (s_e != prev); prev = s_e
            if zb.FRESH_ONLY and not fresh: continue
            bull = (s_b in zb.BULL) and (s_e in zb.BULL)
            bear = (s_b in zb.BEAR) and (s_e in zb.BEAR)
            if not (bull or bear): continue
            pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
            if pnl is None: continue
            side = "LONG" if bull else "SHORT"
            out.append({"symbol":sym, "t_in":pd.Timestamp(et[i]), "t_out":pd.Timestamp(et[xi]),
                        "side":side, "entry":ec[i], "net":pnl - zb.fee_of(side)})
    out.sort(key=lambda x: x["t_in"])
    return out

def simulate(cands, pyramid):
    cash = START; pos = []; peak = START; dd = 0.0; base = 0; adds = 0
    for c in cands:
        for p in list(pos):                      # close matured positions
            if p["t_out"] <= c["t_in"]:
                cash += p["stake"]*(1+p["net"]/100.0); pos.remove(p)
        eq = cash + sum(p["stake"] for p in pos)
        peak = max(peak, eq); dd = max(dd, (peak-eq)/peak*100)
        same = [p for p in pos if p["symbol"]==c["symbol"]]
        if not same:
            size = min(POS_FRAC*eq, cash)
            if size > 0:
                cash -= size; pos.append({**c, "stake":size}); base += 1
        elif pyramid:
            last = same[-1]
            winning = (c["entry"]>last["entry"]) if c["side"]=="LONG" else (c["entry"]<last["entry"])
            if c["side"]==last["side"] and winning and len(same) <= MAX_ADDS:
                size = min(POS_FRAC*eq, cash)
                if size > 0:
                    cash -= size; pos.append({**c, "stake":size}); adds += 1
    for p in pos: cash += p["stake"]*(1+p["net"]/100.0)
    return cash, dd, base, adds

def main():
    print("PYRAMIDING test | BTC+DOGE+HYPE | 4H+30M | long+short | 1000d")
    print(f"  Add to WINNING trades (up to {MAX_ADDS} extra units), each ~{POS_FRAC*100:.0f}% of equity\n")
    cands = gen_signals()
    print(f"  Total signals: {len(cands)}\n")
    print(f"  {'mode':>16} | {'base':>5} | {'adds':>5} | {'$1000 ->':>10} | {'return':>8} | {'max DD':>7}")
    print("  "+"-"*60)
    for label, pyr in (("BASELINE (no add)", False), ("PYRAMID (add wins)", True)):
        bal, dd, base, adds = simulate(cands, pyr)
        print(f"  {label:>16} | {base:>5} | {adds:>5} | ${bal:>8,.0f} | {(bal-START)/10:>+6.0f}% | -{dd:>4.0f}%")
    print("\n  More capital with pyramiding = adding to winners pays. Watch the drawdown too.")

if __name__ == "__main__":
    main()
