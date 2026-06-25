# zigzag_portfolio.py
# "Trade small + re-enter often" vs "trade big, one at a time".
#   PORTFOLIO: up to MAX_CONC concurrent positions, each POS_FRAC of equity, shared account.
#              Captures overlapping signals; idle cash earns nothing.
#   ONE-BIG  : at most ONE position across all coins, full equity, skips signals while in a trade.
import pandas as pd
import numpy as np
import zigzag_basket as zb

MAX_CONC  = 4
POS_FRAC  = 0.25
START     = zb.START_CAPITAL
DEV       = zb.DEVIATION
BULL, BEAR= zb.BULL, zb.BEAR

def gen_candidates():
    """All signals across all symbols with entry_time, exit_time, net%."""
    cand = []
    for sym, fut in zb.SYMBOLS:
        bias_df = zb.get_historical(sym, zb.BIAS_IV, fut)
        entry_df = zb.get_historical(sym, zb.ENTRY_IV, fut)
        if bias_df is None or entry_df is None: continue
        entry_df = entry_df.copy(); entry_df["atr"] = zb.atr_series(entry_df)
        bias_lbl = zb.structure_label_array(bias_df, zb.compute_zigzag_pivots(bias_df, DEV))
        entry_lbl= zb.structure_label_array(entry_df, zb.compute_zigzag_pivots(entry_df, DEV))
        bt = bias_df["time"].values; et = entry_df["time"].values
        bidx_for = np.searchsorted(bt, et, side="right") - 1
        atr_v = entry_df["atr"].values
        eh = entry_df["high"].values; el = entry_df["low"].values; ec = entry_df["close"].values
        prev = None
        for i in range(50, len(entry_df)-1):
            if pd.isna(atr_v[i]): continue
            if bidx_for[i] < 10: continue
            s_bias = bias_lbl[bidx_for[i]]; s_entry = entry_lbl[i]
            fresh = (s_entry != prev); prev = s_entry
            if zb.FRESH_ONLY and not fresh: continue
            bull = (s_bias in BULL) and (s_entry in BULL)
            bear = (s_bias in BEAR) and (s_entry in BEAR)
            if not (bull or bear): continue
            pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
            if pnl is None: continue
            side = "LONG" if bull else "SHORT"
            cand.append({"sym":sym, "t_in":pd.Timestamp(et[i]), "t_out":pd.Timestamp(et[xi]),
                         "net":pnl - zb.fee_of(side)})
    cand.sort(key=lambda x: x["t_in"])
    return cand

def sim_one_big(cand):
    eq = START; busy_until = pd.Timestamp.min; taken = 0; peak = START; dd = 0.0
    for c in cand:
        if c["t_in"] >= busy_until:
            eq *= (1 + c["net"]/100.0); busy_until = c["t_out"]; taken += 1
            peak = max(peak, eq); dd = max(dd, (peak-eq)/peak*100)
    return eq, taken, dd

def sim_portfolio(cand):
    cash = START; openpos = []; taken = 0; skipped = 0; peak = START; dd = 0.0
    def realized_equity():
        return cash + sum(p["notional"] for p in openpos)
    for c in cand:
        # close anything that exited before this signal
        still = []
        for p in openpos:
            if p["t_out"] <= c["t_in"]:
                cash += p["notional"] * (1 + p["net"]/100.0)
            else:
                still.append(p)
        openpos = still
        eq = realized_equity()
        peak = max(peak, eq); dd = max(dd, (peak-eq)/peak*100)
        # try to open
        if len(openpos) < MAX_CONC:
            size = POS_FRAC * eq
            if cash >= size and size > 0:
                cash -= size
                openpos.append({"t_out":c["t_out"], "notional":size, "net":c["net"]})
                taken += 1
            else:
                skipped += 1
        else:
            skipped += 1
    for p in openpos:                      # close remaining
        cash += p["notional"] * (1 + p["net"]/100.0)
    return cash, taken, skipped, dd

def main():
    print(f"PORTFOLIO MODE TEST | BTC+DOGE+HYPE | long+short | 1000d")
    print(f"  Portfolio = up to {MAX_CONC} positions x {POS_FRAC*100:.0f}% equity each (re-enter often)")
    print(f"  One-big   = 1 position at a time, full equity (skip signals while in a trade)\n")
    cand = gen_candidates()
    print(f"  Total signals available: {len(cand)}\n")

    ob_eq, ob_taken, ob_dd = sim_one_big(cand)
    pf_eq, pf_taken, pf_skip, pf_dd = sim_portfolio(cand)

    print(f"  {'mode':>12} | {'signals taken':>13} | {'$1000 ->':>12} | {'return':>8} | {'max DD':>7}")
    print("  "+"-"*62)
    print(f"  {'ONE-BIG':>12} | {ob_taken:>4} / {len(cand):<7} | ${ob_eq:>9,.0f}  | {(ob_eq-START)/10:>+6.0f}% | -{ob_dd:>4.0f}%")
    print(f"  {'PORTFOLIO':>12} | {pf_taken:>4} / {len(cand):<7} | ${pf_eq:>9,.0f}  | {(pf_eq-START)/10:>+6.0f}% | -{pf_dd:>4.0f}%")
    print(f"\n  One-big skips {len(cand)-ob_taken} signals (busy in a trade); portfolio catches {pf_taken} "
          f"(skips {pf_skip} when full/no cash).")
    print("  Note: portfolio often runs UNDER-deployed (idle cash earns nothing) -> smoother but")
    print("  usually lower total return unless signals overlap a lot. Compare the two columns above.")

if __name__ == "__main__":
    main()
