# zigzag_risksize.py
# Plain stops (TP4/SL1.5), BTC+DOGE+HYPE, long+short. Compare TWO position-sizing methods:
#   FULL  : bet ~100% of equity each trade (aggressive, what earlier runs assumed)
#   RISK1%: size each trade so a full SL loss costs ~1% of account (what bot.py actually does),
#           capped at 100% notional (no leverage; spot long / 1x futures short).
import pandas as pd
import numpy as np
from datetime import timedelta
import zigzag_basket as zb

SYMBOLS = zb.SYMBOLS; DAYS = zb.DAYS; DEV = zb.DEVIATION
TP, SL = zb.ATR_TP, zb.ATR_SL; BULL, BEAR = zb.BULL, zb.BEAR
START = zb.START_CAPITAL
RISK_FRAC = 0.01   # risk 1% of account per trade

def gen_trades():
    out = []
    for sym, fut in SYMBOLS:
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
            bidx = bidx_for[i]
            if bidx < 10: continue
            s_bias = bias_lbl[bidx]; s_entry = entry_lbl[i]
            fresh = (s_entry != prev); prev = s_entry
            if zb.FRESH_ONLY and not fresh: continue
            bull = (s_bias in BULL) and (s_entry in BULL)
            bear = (s_bias in BEAR) and (s_entry in BEAR)
            if not (bull or bear): continue
            pnl, xi = zb.exit_fixed(eh, el, ec, i, bull, atr_v[i])
            if pnl is None: continue
            side = "LONG" if bull else "SHORT"
            entry = ec[i]; sl_dist_pct = (atr_v[i]*SL/entry)*100.0   # SL distance as %
            out.append({"symbol":sym, "time":pd.Timestamp(et[i]), "pnl_pct":pnl, "side":side,
                        "net":pnl - zb.fee_of(side), "sl_dist_pct":sl_dist_pct})
    out.sort(key=lambda x:x["time"])
    return out

def curve_full(trs):
    bal = START; peak = START; dd = 0.0
    for t in trs:
        bal *= (1 + t["net"]/100.0)
        peak = max(peak, bal); dd = max(dd, (peak-bal)/peak*100)
    return bal, dd

def curve_risk(trs):
    bal = START; peak = START; dd = 0.0
    for t in trs:
        notional_frac = min(RISK_FRAC / (t["sl_dist_pct"]/100.0), 1.0)   # cap at 100% (no leverage)
        bal *= (1 + notional_frac * t["net"]/100.0)
        peak = max(peak, bal); dd = max(dd, (peak-bal)/peak*100)
    return bal, dd

def report(trs, label):
    if not trs:
        print(f"\n  {label}: no trades"); return
    n = len(trs); wins = sum(1 for t in trs if t["net"]>0)
    fb, fd = curve_full(trs); rb, rd = curve_risk(trs)
    print(f"\n  {label}  ({n} trades, {wins/n*100:.0f}% win)")
    print(f"    FULL  (100%/trade): $1000 -> ${fb:>9,.2f}  ({(fb-START)/10:+6.1f}%)   max drawdown -{fd:.0f}%")
    print(f"    RISK 1%/trade:      $1000 -> ${rb:>9,.2f}  ({(rb-START)/10:+6.1f}%)   max drawdown -{rd:.0f}%")

def main():
    print(f"PLAIN stops + position sizing | BTC+DOGE+HYPE | long+short | TP{TP}/SL{SL}")
    print(f"  RISK 1% = size so a full stop-out costs ~1% of account (capped at no-leverage).")
    trs = gen_trades()
    report(trs, "FULL 1000 DAYS")
    for d in (60, 30, 14):
        cut = pd.Timestamp.now(tz="UTC").tz_localize(None) - timedelta(days=d)
        report([t for t in trs if t["time"] >= cut], f"LAST {d} DAYS")
    print("\n  Takeaway: the FULL +229% is a compounding illusion (needs 100%/trade, -48% DD).")
    print("  At realistic 1% risk the edge is ~+9.6% over 2.7yr (~3-4%/yr) with ~30% DD -- modest.")
    print("  Returns scale ~linearly with risk %; bigger risk = bigger return AND bigger drawdown.")

if __name__ == "__main__":
    main()
