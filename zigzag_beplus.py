# zigzag_beplus.py
# Test the user's "stop-loss-plus" idea: once a trade is in profit by TRIGGER x ATR, move the
# stop UP into profit (entry + BUFFER x ATR) so a trade that first goes our way can't come back
# for a full loss. Compare WITH vs WITHOUT this rule, on BTC+DOGE+HYPE, long+short.
# Re-entry on rebound is already handled by the signal engine (it re-fires on fresh structure).
import pandas as pd
import numpy as np
from datetime import timedelta
import zigzag_basket as zb   # reuse data + indicator + zigzag functions

SYMBOLS   = zb.SYMBOLS
DAYS      = zb.DAYS
DEV       = zb.DEVIATION
TP, SL    = zb.ATR_TP, zb.ATR_SL
BULL, BEAR= zb.BULL, zb.BEAR
START     = zb.START_CAPITAL

# breakeven-plus settings (swept)
BE_CONFIGS = [
    ("plain (no BE+)",      None, None),
    ("BE+ trig1.0/lock0.1", 1.0,  0.1),
    ("BE+ trig1.5/lock0.2", 1.5,  0.2),
    ("BE+ trig2.0/lock0.5", 2.0,  0.5),
]

def exit_trade(h, l, c, e_idx, is_buy, atr, trigger, buffer):
    entry = c[e_idx]
    sl = entry - atr*SL if is_buy else entry + atr*SL
    tp = entry + atr*TP if is_buy else entry - atr*TP
    moved = False
    for i in range(e_idx+1, len(c)):
        hi, lo = h[i], l[i]
        if is_buy:
            if lo <= sl: return ((sl-entry)/entry)*100, i
            if hi >= tp: return ((tp-entry)/entry)*100, i
            if trigger is not None and not moved and hi >= entry + atr*trigger:
                sl = entry + atr*buffer; moved = True       # stop-loss-plus
        else:
            if hi >= sl: return ((entry-sl)/entry)*100, i
            if lo <= tp: return ((entry-tp)/entry)*100, i
            if trigger is not None and not moved and lo <= entry - atr*trigger:
                sl = entry - atr*buffer; moved = True
    return None, None

def run(trigger, buffer):
    all_tr = []
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
            pnl, xi = exit_trade(eh, el, ec, i, bull, atr_v[i], trigger, buffer)
            if pnl is None: continue
            side = "LONG" if bull else "SHORT"
            all_tr.append({"symbol":sym, "time":pd.Timestamp(et[i]), "pnl_pct":pnl,
                           "side":side, "net":pnl - zb.fee_of(side)})
    return all_tr

def stats(trs):
    if not trs: return None
    bal = START; w = 0
    for t in sorted(trs, key=lambda x:x["time"]):
        bal *= (1 + t["net"]/100.0); w += 1 if t["net"]>0 else 0
    n = len(trs)
    return {"n":n, "win":w/n*100, "bep":np.mean([t["pnl_pct"] for t in trs]),
            "net":np.mean([t["net"] for t in trs]), "bal":bal}

def show(label, s):
    if s is None: print(f"  {label:>22} |  no trades"); return
    print(f"  {label:>22} | {s['n']:>4} | {s['win']:>5.1f}% | {s['bep']:>+6.3f}% | "
          f"{s['net']:>+6.3f}% | ${s['bal']:>8,.0f}  ({(s['bal']-START)/10:+.0f}%)")

def main():
    print(f"STOP-LOSS-PLUS test | BTC+DOGE+HYPE | long+short | {DAYS}d | TP{TP}/SL{SL}")
    print(f"Idea: move stop into profit after trade goes TRIGGERxATR our way (lock BUFFERxATR).\n")
    hdr = f"  {'exit mode':>22} | {'trd':>4} | {'win':>6} | {'BEP':>7} | {'net':>7} | {'$1000 (1000d)':>14}"

    results = {}
    cut60 = pd.Timestamp.now(tz="UTC").tz_localize(None) - timedelta(days=60)

    print(hdr); print("  "+"-"*(len(hdr)-2))
    for label, trig, buf in BE_CONFIGS:
        trs = run(trig, buf); results[label] = trs
        show(label, stats(trs))

    print(f"\n  --- LAST 2 MONTHS (60 days) ---")
    print(hdr.replace("(1000d)","(60d) ")); print("  "+"-"*(len(hdr)-2))
    for label, trig, buf in BE_CONFIGS:
        recent = [t for t in results[label] if t["time"] >= cut60]
        show(label, stats(recent))

    print("\n  BEP = gross expectancy/trade. net = after fee (long 0.20% / short 0.10%).")
    print("  Full-equity compounding (aggressive). With 1% risk sizing the $ swings are much smaller.")

if __name__ == "__main__":
    main()
