# idx_demand_zone.py — Supply/Demand ZONE strategy, mechanical + backtestable.
# A DEMAND ZONE = a base candle that launches a sharp rally (buyers overwhelm sellers).
# Theory: unfilled buy orders rest there, so the FIRST pullback into the zone bounces.
# This is MEAN-REVERSION (buy the dip into demand) — a different edge from the momentum
# system, so it could complement it. Same honest treatment: konglo universe, point-in-time
# liquidity gate, realistic fills (limit entry at zone top, slippage on exits, fees).
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np
import yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# ── Zone params ──
IMP_BARS = 3        # rally must complete within this many bars off the base
IMP_ATR  = 2.0      # rally height >= this * ATR above the base high = "sharp"
VOL_X    = 2.0      # volume during the rally >= this * 20d avg = real demand
MAX_WAIT = 30       # zone is valid only if price returns within this many bars (else missed)
MAX_HOLD = 30       # max bars to hold a trade
R_MULT   = 3.0      # target = 3R (tight zone stop = good reward:risk)
STOP_ATR = 0.25     # stop = zone_low - this*ATR (small buffer below the zone)
SLIP     = 0.003    # slippage on exits
FEE      = 0.4

def find_trades(d):
    """One pass per ticker: detect fresh demand zones, simulate the first-pullback long."""
    hi, lo, cl = d["high"].values, d["low"].values, d["close"].values
    vol, vma   = d["volume"].values, d["volma"].values
    atr, turn  = d["atr"].values, d["turn20"].values
    t = d["time"].values
    n = len(d); out = []; i = 200
    while i < n - IMP_BARS - 2:
        a = atr[i]
        if np.isnan(a) or a <= 0 or np.isnan(turn[i]) or turn[i] < MIN_TURNOVER:
            i += 1; continue
        base_hi, base_lo = hi[i], lo[i]
        seg_hi = hi[i+1:i+1+IMP_BARS]
        seg_vol = vol[i+1:i+1+IMP_BARS]
        if len(seg_hi) == 0:
            i += 1; continue
        rally_ok = seg_hi.max() >= base_hi + IMP_ATR * a
        vol_ok   = (np.nanmax(seg_vol) >= VOL_X * vma[i]) if not np.isnan(vma[i]) else False
        if not (rally_ok and vol_ok):
            i += 1; continue
        imp_end = i + 1 + int(np.argmax(seg_hi))          # bar the rally peaked
        zlo, zhi = base_lo, base_hi                       # the demand zone
        stop = zlo - STOP_ATR * a
        # find FIRST pullback into the zone (fresh-zone, first touch only)
        entry_k = None
        for k in range(imp_end + 1, min(imp_end + 1 + MAX_WAIT, n)):
            if lo[k] <= zhi:                              # price re-entered the zone
                entry_k = k; break
        if entry_k is None:
            i = imp_end + 1; continue                     # zone never revisited — no trade
        entry = zhi                                       # limit fill at zone top
        risk = entry - stop
        if risk <= 0:
            i = imp_end + 1; continue
        target = entry + R_MULT * risk
        # simulate forward from the touch bar
        end = min(entry_k + MAX_HOLD, n - 1)
        pnl = None; xk = end
        for k in range(entry_k, end + 1):
            if lo[k] <= stop:    pnl = (stop*(1-SLIP)-entry)/entry*100; xk = k; break
            if hi[k] >= target:  pnl = (target*(1-SLIP)-entry)/entry*100; xk = k; break
        if pnl is None:
            pnl = (cl[end]*(1-SLIP)-entry)/entry*100; xk = end
        out.append({"ticker": None, "entry": pd.Timestamp(t[entry_k]),
                    "exit": pd.Timestamp(t[xk]), "pnl": pnl - FEE, "bars": xk-entry_k})
        i = xk + 1                                        # no overlapping trades per name
    return out

def main():
    print(f"DEMAND-ZONE pullback strategy · konglo universe · last {WINDOW_YEARS}y")
    print(f"Zone = base + rally>={IMP_ATR}ATR/{IMP_BARS}bars on >={VOL_X}x vol · buy 1st pullback · "
          f"stop below zone · target {R_MULT:.0f}R\n")
    tickers = K.all_tickers()
    data = yf.download(tickers, period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    trades = []
    for tk in tickers:
        try:
            d = build(tk, data[tk].copy())
        except Exception:
            d = None
        if d is None:
            print(f"  {tk}: no data"); continue
        for tr in find_trades(d):
            tr["ticker"] = tk.replace(".JK", ""); trades.append(tr)

    win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    print("\n" + "="*78 + f"\n  DEMAND-ZONE EDGE — konglo, realistic, last {WINDOW_YEARS}y\n" + "="*78)
    if not win:
        print("  no qualifying trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  Trades fired   : {len(df)}  across {df.ticker.nunique()} konglo names")
    print(f"  Win rate       : {wr:.0f}%")
    print(f"  Avg win / loss : +{aw:.1f}% / {al:.1f}%")
    print(f"  Expectancy     : {df.pnl.mean():+.2f}% / trade   ·   avg hold {df.bars.mean():.0f}d")
    print(f"  Most-traded    : {', '.join(df.ticker.value_counts().head(8).index)}")
    print("\n" + "="*78 + f"\n  $1,000 PORTFOLIO — demand-zone, {WINDOW_YEARS}y\n" + "="*78)
    for frac, mx, lab in [(0.25,4,"25% × max4 (live sizing)"), (0.10,8,"10% × max8 (defensive)")]:
        r = simulate(win, frac, mx)
        print(f"  {lab:28} ${r['final']:>9,.0f}  ({r['final']/START:5.2f}x)  "
              f"CAGR {r['cagr']:+6.1f}%  MaxDD {r['maxdd']:4.1f}%  took {r['taken']}/{len(win)}")
    print(f"\n  vs momentum konglo (4.83x, 27% win): is this edge ADDITIVE or redundant?")
    print("  ⚠️  Limit entry at zone top · slippage+fee on exits · long-only · no gap modeling.")

if __name__ == "__main__":
    main()
