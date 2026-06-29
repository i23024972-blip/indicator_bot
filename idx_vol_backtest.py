# idx_vol_backtest.py — Long-only VOLUME-SPIKE momentum, backtested for side-by-side
# comparison with the zigzag strategy (idx_backtest.py). Same analyze() format.
#
# Entry  : up day  AND  volume >= SPIKE_X * 20d-avg-volume  AND  close > SMA(TREND_MA)
# Exit   : stop SL_X*ATR, target TP_X*ATR (longer R/R), or time-exit after MAX_HOLD days.
# Long only. One position per ticker at a time (non-overlapping).
import sys
import pandas as pd
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SPIKE_X   = 2.0
VOL_MA    = 20
TREND_MA  = 50
SL_X      = 2.0     # stop  = entry - 2*ATR
TP_X      = 6.0     # target= entry + 6*ATR  -> 1:3 reward:risk
MAX_HOLD  = 20      # trading-day time exit
SKIP_GROUPS = {"Salim"}   # study showed spike-momentum fails on Salim blue-chips

def simulate_long(d, i, atr):
    entry = d["close"].iloc[i]
    sl, tp = entry - SL_X * atr, entry + TP_X * atr
    end = min(i + MAX_HOLD, len(d) - 1)
    for j in range(i + 1, end + 1):
        lo, hi = d["low"].iloc[j], d["high"].iloc[j]
        if lo <= sl: return (sl - entry) / entry * 100, "SL", j - i
        if hi >= tp: return (tp - entry) / entry * 100, "TP", j - i
    return (d["close"].iloc[end] - entry) / entry * 100, "TIME", end - i

def backtest_ticker(ticker):
    if K.group_of(ticker) in SKIP_GROUPS:
        return []
    d, _ = K.get_eod(ticker, period="3y")
    if d is None or len(d) < TREND_MA + 30:
        return []
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(VOL_MA).mean()
    d["sma"]   = d["close"].rolling(TREND_MA).mean()
    d["ret1"]  = d["close"].pct_change()

    trades = []
    i = TREND_MA
    while i < len(d) - 1:
        atr = d["atr"].iloc[i]
        if pd.isna(atr) or pd.isna(d["sma"].iloc[i]) or pd.isna(d["volma"].iloc[i]) or atr <= 0:
            i += 1; continue
        up    = d["ret1"].iloc[i] > 0
        spike = d["volume"].iloc[i] >= SPIKE_X * d["volma"].iloc[i]
        trend = d["close"].iloc[i] > d["sma"].iloc[i]
        if up and spike and trend:
            pnl, ex, bars = simulate_long(d, i, atr)
            trades.append({"ticker": ticker, "group": K.group_of(ticker),
                           "time": d["time"].iloc[i].date(), "pnl_pct": pnl,
                           "exit": ex, "bars_held": bars})
            i += bars + 1            # non-overlapping: resume after the trade closes
        else:
            i += 1
    return trades

def analyze(trades, title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")
    if not trades:
        print("  No trades."); return
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
    print(f"  Total return (sum)  : {df.pnl_pct.sum():+.1f}%")
    print(f"  Exit mix            : " +
          ", ".join(f"{k} {v}" for k, v in df.exit.value_counts().items()))
    print(f"\n  By group:")
    for g in df.group.unique():
        s = df[df.group == g]
        print(f"    {g:9}: {len(s):3} trades  {(s.pnl_pct>0).mean()*100:5.1f}% win  {s.pnl_pct.sum():+7.1f}%")
    print(f"\n  By ticker:")
    for t in sorted(df.ticker.unique()):
        s = df[df.ticker == t]
        print(f"    {t:10}: {len(s):3} trades  {(s.pnl_pct>0).mean()*100:5.1f}% win  {s.pnl_pct.sum():+7.1f}%")

def main():
    print(f"Volume-spike momentum | spike>= {SPIKE_X}x, trend>SMA{TREND_MA} | "
          f"SL {SL_X}xATR / TP {TP_X}xATR (1:{TP_X/SL_X:.0f}) | hold<= {MAX_HOLD}d | skip {SKIP_GROUPS}")
    trades = []
    for t in K.all_tickers():
        trades += backtest_ticker(t)
    analyze(trades, "VOLUME-SPIKE MOMENTUM — LONG ONLY")
    print(f"\n{'='*60}\n  No fees/slippage. Past != future.\n{'='*60}")

if __name__ == "__main__":
    main()
