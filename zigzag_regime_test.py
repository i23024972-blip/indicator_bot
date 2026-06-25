# zigzag_regime_test.py
# Lever #2: BTC macro-regime filter. All 3 coins are "crypto" and follow Bitcoin, so use BTC's
# daily 200-MA regime as a directional gate:
#   BTC bull (price > 200d MA) -> only take LONGs   |   BTC bear -> only take SHORTs
# Compare vs baseline (take both directions always). Fee = current per-side. 1000 days.
import pandas as pd
import numpy as np
import zigzag_basket as zb

DEV = zb.DEVIATION; START = zb.START_CAPITAL

def btc_regime():
    """Return (daily_times, bull_bool_array) from BTC daily 200-MA."""
    btc4h = zb.get_historical("BTCUSDT", zb.BIAS_IV, False, days=1000)
    d = btc4h.set_index("time")["close"].resample("1D").last().dropna()
    sma = d.rolling(200).mean()
    bull = (d > sma).values
    return d.index.values, bull

def gen_signals():
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
            side = "LONG" if bull else "SHORT"
            out.append({"time":pd.Timestamp(et[i]), "side":side, "net":pnl - zb.fee_of(side)})
    out.sort(key=lambda x: x["time"])
    return out

def report(trades, label):
    if not trades: print(f"  {label:>22} | no trades"); return
    df = pd.DataFrame(trades); n=len(df); w=(df["net"]>0).sum()
    bf=START; bh=START
    for net in df.sort_values("time")["net"]:
        bf*=(1+net/100.0); bh*=(1+0.5*net/100.0)
    print(f"  {label:>22} | {n:>5} | {w/n*100:>5.1f}% | {df['net'].mean():>+7.3f}% | ${bf:>8,.0f} | ${bh:>7,.0f}")

def main():
    print("BTC MACRO-REGIME filter | BTC+DOGE+HYPE | 1000d | BTC daily 200-MA gates direction\n")
    dt, bull = btc_regime()
    sig = gen_signals()
    # gate each signal by BTC regime at its time
    gated = []
    for s in sig:
        idx = np.searchsorted(dt, np.datetime64(s["time"]), side="right") - 1
        if idx < 0 or idx >= len(bull) or np.isnan(bull[idx]):
            gated.append(s); continue          # no regime info yet -> keep
        is_bull = bool(bull[idx])
        if (is_bull and s["side"]=="LONG") or ((not is_bull) and s["side"]=="SHORT"):
            gated.append(s)                      # direction agrees with macro regime
    print(f"  {'mode':>22} | {'trd':>5} | {'win':>6} | {'net/trd':>8} | {'$1000@100':>9} | {'$1000@50':>8}")
    print("  "+"-"*70)
    report(sig,   "BASELINE (both dirs)")
    report(gated, "BTC-REGIME gated")
    print(f"\n  Regime kept {len(gated)}/{len(sig)} signals (dropped the ones fighting BTC's macro trend).")
    print("  Better net/trade AND capital = the macro gate adds a real directional edge.")

if __name__ == "__main__":
    main()
