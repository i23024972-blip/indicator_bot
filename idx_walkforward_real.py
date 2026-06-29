# idx_walkforward_real.py — same blind 2y walk-forward, but REALISTIC FILLS.
# Changes vs idx_walkforward.py (which entered at the optimistic signal-day close):
#   · Entry  = NEXT DAY's open (you only know the signal after the close).
#   · Gap    = skip the trade if next open gaps > 3% above signal close (live GAP_SKIP).
#   · Slip   = pay 0.3% worse on entry AND exit (thin IDX names move on you).
# Everything else — universe, indicators, liquidity gate, sizing — is identical.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import (fire_combo, fire_trend, regime_at,
                                 C_SL, C_TP, C_HOLD, T_STOP, T_MAXHOLD)
from idx_discover import UNIVERSE
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

SLIP = 0.003        # 0.3% slippage each side
GAP_SKIP = 3.0      # skip if next open gaps > this % above signal close

def _entry(d, i):
    """Next-day open with gap-skip + buy slippage. Returns (entry_px, entry_idx) or None."""
    if i + 1 >= len(d): return None
    o, c = d["open"].iloc[i+1], d["close"].iloc[i]
    if (o - c) / c * 100 > GAP_SKIP:      # gapped away — would've skipped live
        return None
    return o * (1 + SLIP), i + 1

def sim_combo_real(d, i):
    ent = _entry(d, i)
    if ent is None: return None
    e, k = ent; atr = d["atr"].iloc[i]
    sl, tp = e - C_SL*atr, e + C_TP*atr
    end = min(k + C_HOLD, len(d)-1)
    for j in range(k+1, end+1):
        if d["low"].iloc[j]  <= sl: return (sl*(1-SLIP)-e)/e*100, j-i
        if d["high"].iloc[j] >= tp: return (tp*(1-SLIP)-e)/e*100, j-i
    return (d["close"].iloc[end]*(1-SLIP)-e)/e*100, end-i

def sim_trend_real(d, i):
    ent = _entry(d, i)
    if ent is None: return None
    e, k = ent; atr = d["atr"].iloc[i]
    stop = e - T_STOP*atr
    end = min(k + T_MAXHOLD, len(d)-1)
    for j in range(k+1, end+1):
        if d["low"].iloc[j] <= stop:                  return (stop*(1-SLIP)-e)/e*100, j-i
        if d["close"].iloc[j] < d["sma50"].iloc[j]:   return (d["close"].iloc[j]*(1-SLIP)-e)/e*100, j-i
    return (d["close"].iloc[end]*(1-SLIP)-e)/e*100, end-i

def collect_real():
    trades = []; done = 0
    tickers = [t + ".JK" for t in UNIVERSE]
    for kk in range(0, len(tickers), 25):
        chunk = tickers[kk:kk+25]
        try:
            data = yf.download(chunk, period="3y", interval="1d", progress=False,
                               auto_adjust=True, group_by="ticker")
        except Exception:
            continue
        for t in chunk:
            try:
                d = build(t, data[t].copy())
            except Exception:
                d = None
            if d is None: continue
            done += 1
            last = -1
            for i in range(200, len(d)-1):
                if i <= last: continue
                if pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i] <= 0: continue
                if pd.isna(d["sma200"].iloc[i]): continue
                if pd.isna(d["turn20"].iloc[i]) or d["turn20"].iloc[i] < MIN_TURNOVER: continue
                reg = regime_at(d["time"].iloc[i])
                if reg == "HEALTHY": fire, fn = fire_trend(d, i), sim_trend_real
                else:                fire, fn = fire_combo(d, i), sim_combo_real
                if not fire: continue
                res = fn(d, i)
                if res is None: continue        # gap-skipped — no trade taken
                pnl, bars = res
                last = i + bars; xi = min(i + bars, len(d)-1)
                trades.append({"ticker": t.replace(".JK",""), "entry": d["time"].iloc[i],
                               "exit": d["time"].iloc[xi], "pnl": pnl - 0.4, "bars": bars})
        print(f"  ...scanned {min(kk+25,len(tickers))}/{len(tickers)}  (usable: {done})", flush=True)
    return trades, done

def main():
    print(f"REALISTIC-FILLS walk-forward · broad IDX board · last {WINDOW_YEARS}y")
    print("Entry = next-day open · gap-skip >3% · 0.3% slippage/side · 0.4% fee\n")
    alltr, usable = collect_real()
    win = sorted([t for t in alltr if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    print("\n" + "="*78 + f"\n  SIGNAL EDGE — realistic fills, last {WINDOW_YEARS}y\n" + "="*78)
    if not win:
        print("  no qualifying trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  Trades fired   : {len(df)}  across {df.ticker.nunique()} stocks")
    print(f"  Win rate       : {wr:.0f}%")
    print(f"  Avg win / loss : +{aw:.1f}% / {al:.1f}%")
    print(f"  Expectancy     : {df.pnl.mean():+.2f}% / trade   ·   avg hold {df.bars.mean():.0f}d")
    print("\n" + "="*78 + f"\n  $1,000 PORTFOLIO — realistic fills, {WINDOW_YEARS}y\n" + "="*78)
    for frac, mx, lab in [(0.25,4,"25% × max4 (live sizing)"), (0.10,8,"10% × max8 (defensive)")]:
        r = simulate(win, frac, mx)
        print(f"  {lab:28} ${r['final']:>9,.0f}  ({r['final']/START:5.2f}x)  "
              f"CAGR {r['cagr']:+6.1f}%  MaxDD {r['maxdd']:4.1f}%  took {r['taken']}/{len(win)}")
    print(f"\n  Scanned {usable} stocks · next-open entry · gap-skip · slippage+fee modeled.")
    print("  THIS is the number to trust before risking real money.")

if __name__ == "__main__":
    main()
