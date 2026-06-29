# idx_trend_ride.py — Eric's refined idea: confirmation entry, then RIDE while the trend
# still checks out, exit only when an indicator says it's TURNING AROUND. No fixed timer,
# no tight stop. Adaptive hold = as long as the move lasts.
#   Entry : buy-stop above signal high (confirmed breakout only; fades self-filter).
#   Stay  : wide initial stop (room to breathe) + chandelier trail that ratchets up.
#   Exit  : trailing stop hit, OR close breaks below the trend EMA (momentum rolled over).
# Tested at 3 tightness settings to show the hold-length vs monster-capture trade-off.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF = 0.005; MAXGAP = 0.04; SLIP = 0.003; FEE = 0.4; MAXHOLD = 250

def ride(d, ema_len, trail_atr, init_atr):
    o, hi, lo, cl = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    atr, turn = d["atr"].values, d["turn20"].values; t = d["time"].values
    ema = pd.Series(cl).ewm(span=ema_len, adjust=False).mean().values
    n = len(d); out = []; i = 200
    while i < n - 2:
        a = atr[i]
        if np.isnan(a) or a <= 0 or np.isnan(turn[i]) or turn[i] < MIN_TURNOVER:
            i += 1; continue
        if not fire_combo(d, i): i += 1; continue
        trig = hi[i] * (1 + TRIG_BUF); k = i + 1
        if o[k] > hi[i] * (1 + MAXGAP): i += 1; continue        # gapped too far — skip chase
        if o[k] >= trig:   entry = o[k] * (1 + SLIP)
        elif hi[k] >= trig: entry = trig * (1 + SLIP)
        else: i += 1; continue                                  # never confirmed — no trade
        stop = entry - init_atr * a                             # WIDE initial stop
        runmax = entry; end = min(k + MAXHOLD, n - 1)
        pnl = None; xk = end
        for j in range(k, end + 1):
            runmax = max(runmax, hi[j])
            aj = atr[j] if not np.isnan(atr[j]) else a
            stop = max(stop, runmax - trail_atr * aj)           # chandelier ratchets up
            if lo[j] <= stop:
                pnl = (stop*(1-SLIP)-entry)/entry*100; xk = j; break
            if j > k and cl[j] < ema[j]:                        # trend EMA broken = turning
                pnl = (cl[j]*(1-SLIP)-entry)/entry*100; xk = j; break
        if pnl is None:
            pnl = (cl[end]*(1-SLIP)-entry)/entry*100; xk = end
        out.append({"ticker": None, "entry": pd.Timestamp(t[k]), "exit": pd.Timestamp(t[xk]),
                    "pnl": pnl - FEE, "bars": xk - k})
        i = xk + 1
    return out

def main():
    print(f"TREND-RIDE (confirm entry + ride-till-it-turns) · konglo · last {WINDOW_YEARS}y\n")
    tickers = K.all_tickers()
    data = yf.download(tickers, period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    built = {}
    for tk in tickers:
        try: built[tk] = build(tk, data[tk].copy())
        except Exception: built[tk] = None

    configs = [("TIGHT  (EMA10, trail2.0)", 10, 2.0, 1.5),
               ("MEDIUM (EMA20, trail3.0)", 20, 3.0, 2.0),
               ("LOOSE  (EMA50, trail4.0)", 50, 4.0, 2.5)]
    print(f"  {'config':26}{'trades':>7}{'win%':>6}{'avgHold':>9}{'exp%':>7}{'  $1k→ (25%x4)':>16}{'MaxDD':>7}")
    print("  " + "-"*78)
    for lab, el, tr_atr, in_atr in configs:
        trades = []
        for tk in tickers:
            d = built[tk]
            if d is None: continue
            for x in ride(d, el, tr_atr, in_atr):
                x["ticker"] = tk; trades.append(x)
        win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
        if not win:
            print(f"  {lab:26} no trades"); continue
        df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
        r = simulate(win, 0.25, 4)
        print(f"  {lab:26}{len(df):>7}{wr:>5.0f}%{df.bars.mean():>7.0f}d{df.pnl.mean():>+6.1f}%"
              f"   ${r['final']:>8,.0f} ({r['final']/START:.1f}x){r['maxdd']:>6.0f}%")

    print(f"\n  Benchmarks: momentum-hold 4.8x (16–90d) · short-scalp 0.8x (1d) · demand-zone 0.95x")
    print("  This rides while healthy, exits on the turn — the middle path you described.")

if __name__ == "__main__":
    main()
