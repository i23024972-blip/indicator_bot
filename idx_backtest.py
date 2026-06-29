# idx_backtest.py — Backtest the konglomerat EOD ZigZag-structure strategy.
# Long-only. Entry on Daily structure when it AGREES with Weekly bias and the
# Daily label JUST turned bullish (fresh). ATR-based SL/TP. No fees/slippage modelled.
import sys
import pandas as pd
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

FRESH_ONLY = True

def simulate_long(df, entry_idx, atr_value):
    entry = df["close"].iloc[entry_idx]
    sl = entry - atr_value * K.ATR_MULTIPLIER_SL
    tp = entry + atr_value * K.ATR_MULTIPLIER_TP
    for i in range(entry_idx + 1, len(df)):
        lo, hi = df["low"].iloc[i], df["high"].iloc[i]
        if lo <= sl: return (sl - entry) / entry * 100, "SL", i - entry_idx
        if hi >= tp: return (tp - entry) / entry * 100, "TP", i - entry_idx
    return None, "OPEN", len(df) - 1 - entry_idx

def backtest_ticker(ticker):
    d, w = K.get_eod(ticker)
    if d is None or len(d) < 120 or len(w) < 30:
        print(f"  ⚠️ not enough data for {ticker}"); return []
    d["atr"] = K.atr_series(d)
    zz_d = K.compute_zigzag_pivots(d)
    zz_w = K.compute_zigzag_pivots(w)

    trades, prev_sd = [], None
    for i in range(30, len(d) - 1):
        if pd.isna(d["atr"].iloc[i]):
            continue
        wk = w[w["time"] <= d["time"].iloc[i]]
        if len(wk) < 5:
            continue
        idx_w = wk.index[-1]

        sd = K.structure_at(zz_d, i)
        sw = K.structure_at(zz_w, idx_w)
        bull = sd in K.BULL and sw in K.BULL

        fresh = (sd != prev_sd); prev_sd = sd
        if FRESH_ONLY and not fresh:
            continue
        if bull:
            pnl, ex, bars = simulate_long(d, i, d["atr"].iloc[i])
            if pnl is not None:
                trades.append({"ticker": ticker, "group": K.group_of(ticker),
                               "time": d["time"].iloc[i].date(), "pnl_pct": pnl,
                               "exit": ex, "bars_held": bars})
    return trades

def analyze(trades):
    print(f"\n{'='*58}\n  KONGLO EOD ZIGZAG — LONG ONLY (Daily+Weekly agree)\n{'='*58}")
    if not trades:
        print("  No trades generated."); return
    df = pd.DataFrame(trades)
    total = len(df); wins = df[df.pnl_pct > 0]
    wr = len(wins) / total * 100
    aw = wins.pnl_pct.mean() if len(wins) else 0
    al = df[df.pnl_pct <= 0].pnl_pct.mean() if (total - len(wins)) else 0
    exp = wr/100*aw + (1-wr/100)*al
    print(f"  Total trades        : {total}")
    print(f"  Win rate            : {wr:.1f}%")
    print(f"  Avg win / avg loss  : +{aw:.2f}% / {al:.2f}%")
    print(f"  Expectancy / trade  : {exp:+.2f}%")
    print(f"  Avg bars held       : {df.bars_held.mean():.0f} days")
    print(f"  Total return (sum)  : {df.pnl_pct.sum():+.1f}%  (1 unit/trade, no compounding)")
    print(f"\n  By group:")
    for g in df.group.unique():
        s = df[df.group == g]
        print(f"    {g:9}: {len(s):3} trades  {(s.pnl_pct>0).mean()*100:5.1f}% win  {s.pnl_pct.sum():+7.1f}%")
    print(f"\n  By ticker:")
    for t in sorted(df.ticker.unique()):
        s = df[df.ticker == t]
        print(f"    {t:10}: {len(s):3} trades  {(s.pnl_pct>0).mean()*100:5.1f}% win  {s.pnl_pct.sum():+7.1f}%")

def main():
    print(f"📊 Konglo EOD ZigZag backtest | dev {K.ZIGZAG_DEVIATION}% | "
          f"SL {K.ATR_MULTIPLIER_SL}xATR / TP {K.ATR_MULTIPLIER_TP}xATR | fresh-only {FRESH_ONLY}")
    all_trades = []
    for t in K.all_tickers():
        print(f"  · {t} ({K.group_of(t)})")
        all_trades += backtest_ticker(t)
    analyze(all_trades)
    print(f"\n{'='*58}\n  ⚠️  No fees/slippage. EOD fills assumed at close. Past ≠ future.\n{'='*58}")

if __name__ == "__main__":
    main()
