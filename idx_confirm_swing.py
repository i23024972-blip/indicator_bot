# idx_confirm_swing.py — SHORT-HOLD "confirmation bet" strategy (Eric's idea).
# Problem with EOD entry: the move often happens at the open, so "buy at open" chases gaps
# or buys fades. Fix: after an EOD candidate, place a BUY-STOP just above the signal-day
# high. You ONLY enter if next session trades UP through it (confirmation) — fades/gap-downs
# self-filter (no trade). Then: TIGHT stop, fast target (2R), short max-hold, and a
# FALSE-ALARM exit if it closes red on heavy selling volume. Holds days, not months.
# Honest limit: daily data only — confirmation/cut modeled at daily granularity (not intraday).
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF = 0.005    # buy-stop sits 0.5% above the signal-day high (must break out to fill)
MAXGAP   = 0.04     # skip if it gaps > 4% above signal high (too extended — chasing)
STOP_ATR = 1.0      # tight stop = entry - 1*ATR
R_MULT   = 2.0      # quick target at 2R
MAXHOLD  = 8        # short swing — out within 8 bars
FA_VOL   = 2.0      # false-alarm: red close on > this * avg volume = bail
SLIP     = 0.003
FEE      = 0.4

def find_trades(d):
    o, hi, lo, cl = d["open"].values, d["high"].values, d["low"].values, d["close"].values
    vol, vma = d["volume"].values, d["volma"].values
    atr, turn = d["atr"].values, d["turn20"].values
    t = d["time"].values
    n = len(d); out = []; i = 200; cand = conf = 0
    while i < n - 2:
        a = atr[i]
        if np.isnan(a) or a <= 0 or np.isnan(turn[i]) or turn[i] < MIN_TURNOVER:
            i += 1; continue
        if not fire_combo(d, i):
            i += 1; continue
        cand += 1
        trig = hi[i] * (1 + TRIG_BUF)
        k = i + 1
        # ── CONFIRMATION: only enter if next session trades up through the trigger ──
        if o[k] > hi[i] * (1 + MAXGAP):
            i += 1; continue                       # gapped too far — skip the chase
        if o[k] >= trig:
            entry = o[k] * (1 + SLIP)              # opened through trigger → take the open
        elif hi[k] >= trig:
            entry = trig * (1 + SLIP)              # broke out intraday → fill at trigger
        else:
            i += 1; continue                       # never confirmed → NO TRADE (false alarm filtered)
        conf += 1
        stop = entry - STOP_ATR * a
        if stop <= 0:
            i += 1; continue
        target = entry + R_MULT * (entry - stop)
        end = min(k + MAXHOLD, n - 1)
        pnl = None; xk = end
        for j in range(k, end + 1):
            if lo[j] <= stop:    pnl = (stop*(1-SLIP)-entry)/entry*100; xk = j; break
            if hi[j] >= target:  pnl = (target*(1-SLIP)-entry)/entry*100; xk = j; break
            if j > k and cl[j] < entry and not np.isnan(vma[j]) and vol[j] > FA_VOL*vma[j]:
                pnl = (cl[j]*(1-SLIP)-entry)/entry*100; xk = j; break     # false-alarm cut
        if pnl is None:
            pnl = (cl[end]*(1-SLIP)-entry)/entry*100; xk = end
        out.append({"ticker": None, "entry": pd.Timestamp(t[k]), "exit": pd.Timestamp(t[xk]),
                    "pnl": pnl - FEE, "bars": xk - k})
        i = xk + 1
    return out, cand, conf

def main():
    print(f"CONFIRMATION-SWING (short hold) · konglo · last {WINDOW_YEARS}y")
    print(f"Buy-stop {TRIG_BUF*100:.1f}% above signal high · stop {STOP_ATR}ATR · target {R_MULT:.0f}R · "
          f"max {MAXHOLD}d · false-alarm cut on >{FA_VOL}x red volume\n")
    tickers = K.all_tickers()
    data = yf.download(tickers, period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    trades = []; tot_cand = tot_conf = 0
    for tk in tickers:
        try:
            d = build(tk, data[tk].copy())
        except Exception:
            d = None
        if d is None: continue
        tr, c, cf = find_trades(d); tot_cand += c; tot_conf += cf
        for x in tr: x["ticker"] = tk.replace(".JK",""); trades.append(x)

    win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    print("="*80 + f"\n  CONFIRMATION-SWING EDGE — konglo, last {WINDOW_YEARS}y\n" + "="*80)
    if not win:
        print("  no trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  Candidates fired   : {tot_cand}   →   confirmed & entered: {tot_conf}  "
          f"({tot_conf/max(tot_cand,1)*100:.0f}%)   [rest self-filtered as fades]")
    print(f"  Trades (in window) : {len(df)}  across {df.ticker.nunique()} names")
    print(f"  Win rate           : {wr:.0f}%")
    print(f"  Avg win / loss     : +{aw:.1f}% / {al:.1f}%")
    print(f"  Expectancy         : {df.pnl.mean():+.2f}% / trade")
    print(f"  Avg hold           : {df.bars.mean():.1f} days  (vs ~16d combo / ~90d trend)")
    print("\n" + "="*80 + f"\n  $1,000 PORTFOLIO — confirmation-swing, {WINDOW_YEARS}y\n" + "="*80)
    print(f"  {'scheme':24}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}")
    for lab,f,m in [("10% × max8",0.10,8),("25% × max4 (live)",0.25,4),("33% × max3",0.33,3)]:
        r = simulate(win, f, m)
        print(f"  {lab:24}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%{r['maxdd']:>6.0f}%")
    print(f"\n  vs momentum-hold konglo: 4.8x (25%×4) but 16–90d holds.")
    print("  Key trade-off: short holds recycle capital fast but CAP the +200% monsters.")

if __name__ == "__main__":
    main()
