# idx_walkforward_konglo.py — realistic-fills walk-forward, but ONLY the konglo universe
# (idx_konglo.KONGLO: Prajogo / Hapsoro / Bakrie / Salim groups — ~22 names, movers AND
# laggards). This is "what would 2y of trading MY actual konglo strategy have done?"
# Same fill realism as idx_walkforward_real: next-open entry, gap-skip >3%, slippage+fee.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_walkforward_real import sim_combo_real, sim_trend_real
from idx_hybrid_backtest import fire_combo, fire_trend, regime_at
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def collect_konglo():
    trades = []; done = 0
    tickers = K.all_tickers()                       # already ".JK"
    data = yf.download(tickers, period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    for t in tickers:
        try:
            d = build(t, data[t].copy())
        except Exception:
            d = None
        if d is None:
            print(f"  {t}: no data"); continue
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
            if res is None: continue
            pnl, bars = res
            last = i + bars; xi = min(i + bars, len(d)-1)
            trades.append({"ticker": t.replace(".JK",""), "entry": d["time"].iloc[i],
                           "exit": d["time"].iloc[xi], "pnl": pnl - 0.4, "bars": bars,
                           "group": K.group_of(t)})
    return trades, done

def main():
    print(f"KONGLO-ONLY realistic walk-forward · {len(K.all_tickers())} names · last {WINDOW_YEARS}y")
    print("Entry = next-day open · gap-skip >3% · 0.3% slippage/side · 0.4% fee\n")
    alltr, usable = collect_konglo()
    win = sorted([t for t in alltr if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    print("\n" + "="*78 + f"\n  SIGNAL EDGE — konglo only, realistic fills, last {WINDOW_YEARS}y\n" + "="*78)
    if not win:
        print("  no qualifying trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  Trades fired   : {len(df)}  across {df.ticker.nunique()} konglo names")
    print(f"  Win rate       : {wr:.0f}%")
    print(f"  Avg win / loss : +{aw:.1f}% / {al:.1f}%")
    print(f"  Expectancy     : {df.pnl.mean():+.2f}% / trade   ·   avg hold {df.bars.mean():.0f}d")
    print(f"  By group       : " +
          " · ".join(f"{g}:{(df[df.group==g].pnl.mean()):+.1f}%" for g in df.group.unique()))
    print(f"  Most-traded    : {', '.join(df.ticker.value_counts().head(8).index)}")
    print("\n" + "="*78 + f"\n  $1,000 PORTFOLIO — konglo only, realistic, {WINDOW_YEARS}y\n" + "="*78)
    for frac, mx, lab in [(0.25,4,"25% × max4 (live sizing)"), (0.10,8,"10% × max8 (defensive)")]:
        r = simulate(win, frac, mx)
        print(f"  {lab:28} ${r['final']:>9,.0f}  ({r['final']/START:5.2f}x)  "
              f"CAGR {r['cagr']:+6.1f}%  MaxDD {r['maxdd']:4.1f}%  took {r['taken']}/{len(win)}")
    print(f"\n  {usable}/{len(K.all_tickers())} konglo names had usable data.")
    print("  Compare vs broad-universe run: gap = how much edge is just 'trading the konglo names'.")

if __name__ == "__main__":
    main()
