# idx_watchlist_backtest.py — Backtest the full compiled tiered watchlist with the
# momentum COMBO (volume spike + bullish daily/weekly structure + above 50MA). Long only.
# Breaks results down by liquidity tier and runs the $1,000 compounding portfolio.
import sys
import pandas as pd
import idx_konglo as K
from idx_scan import WATCHLIST
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SPIKE_X, TREND_MA, SL_X, TP_X, HOLD, FEE = 2.5, 50, 2.0, 6.0, 20, 0.4

def prep(t):
    d, w = K.get_eod(t + ".JK", period="3y")
    if d is None or len(d) < TREND_MA + 40 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(TREND_MA).mean()
    d["ret1"]  = d["close"].pct_change()
    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    d["sd"] = [K.structure_at(zz_d, i) for i in range(len(d))]
    sw = []
    for i in range(len(d)):
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw.append(K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral")
    d["sw"] = sw
    return d

def sim_long(d, i):
    atr = d["atr"].iloc[i]; entry = d["close"].iloc[i]
    sl, tp = entry - SL_X*atr, entry + TP_X*atr
    end = min(i + HOLD, len(d)-1)
    for j in range(i+1, end+1):
        if d["low"].iloc[j]  <= sl: return (sl-entry)/entry*100, j-i
        if d["high"].iloc[j] >= tp: return (tp-entry)/entry*100, j-i
    return (d["close"].iloc[end]-entry)/entry*100, end-i

def collect():
    trades = []
    for t, tier in WATCHLIST.items():
        d = prep(t)
        if d is None:
            print(f"  · {t:6} no data — skipped"); continue
        last = -1
        for i in range(TREND_MA, len(d)-1):
            if pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i] <= 0 or pd.isna(d["sma50"].iloc[i]) \
               or pd.isna(d["volma"].iloc[i]) or i <= last:
                continue
            up    = d["ret1"].iloc[i] > 0
            spike = d["volume"].iloc[i] >= SPIKE_X * d["volma"].iloc[i]
            trend = d["close"].iloc[i] > d["sma50"].iloc[i]
            struct= d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL
            if up and spike and trend and struct:
                pnl, bars = sim_long(d, i); last = i + bars
                xi = min(i+bars, len(d)-1)
                trades.append({"ticker": t, "tier": tier, "entry": d["time"].iloc[i],
                               "exit": d["time"].iloc[xi], "pnl": pnl - FEE})
    return trades

def stats(rows, label):
    if not rows: print(f"  {label:18} no trades"); return
    df = pd.DataFrame(rows); n=len(df); wr=(df.pnl>0).mean()*100
    aw=df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al=df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  {label:18} n={n:4} win={wr:4.0f}%  avgW/L=+{aw:4.1f}/{al:5.1f}  "
          f"exp={df.pnl.mean():+5.2f}%/trade  total={df.pnl.sum():+8.0f}%")

def main():
    print(f"Backtesting {len(WATCHLIST)} stocks (COMBO, 3y, net {FEE}% fees)...\n")
    trades = collect()
    print("\n" + "="*70 + "\n  RESULTS BY LIQUIDITY TIER\n" + "="*70)
    stats(trades, "ALL")
    for tg in ["BIG", "MID", "OKAY"]:
        stats([t for t in trades if t["tier"] == tg], f"{tg} liquidity")

    print("\n" + "="*70 + "\n  PER-STOCK BREAKDOWN (sorted by total return)\n" + "="*70)
    df = pd.DataFrame(trades)
    by = []
    for t in WATCHLIST:
        s = df[df["ticker"] == t]
        if not len(s): continue
        by.append((t, WATCHLIST[t], len(s), (s.pnl>0).mean()*100, s.pnl.mean(), s.pnl.sum()))
    by.sort(key=lambda x: x[5], reverse=True)
    print(f"  {'ticker':7}{'tier':6}{'trades':>7}{'win%':>7}{'exp/trade':>11}{'total':>10}")
    for t, tier, n, wr, exp, tot in by:
        print(f"  {t:7}{tier:6}{n:>7}{wr:>6.0f}%{exp:>+10.1f}%{tot:>+9.0f}%")

    print("\n" + "="*70 + "\n  $1,000 PORTFOLIO  (regime-style flat sizing, max positions)\n" + "="*70)
    crash = [t for t in trades if t["entry"] >= pd.Timestamp("2025-08-01")]
    for label, f, m in [("20% × max5", 0.20, 5), ("25% × max4", 0.25, 4)]:
        a = simulate(trades, f, m); b = simulate(crash, f, m)
        print(f"  {label:12}  full 3y: ${a['final']:>7,.0f} ({a['final']/START:.1f}x, DD {a['maxdd']:.0f}%)"
              f"   ·   since Aug'25: ${b['final']:>7,.0f} ({b['final']/START:.1f}x)")
    print("\n  ⚠️ No slippage; strong-trending years. Relative tier comparison is the signal.")

if __name__ == "__main__":
    main()
