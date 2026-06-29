# idx_trend_ride_broad.py — UPGRADE #1: more opportunities.
# Exact same validated trend-ride strategy (confirmation entry + ride-while-above-50EMA +
# chandelier trail) — but on the BROAD liquid IDX universe (~395 names) instead of just ~20
# konglo names, with the point-in-time liquidity gate. Question: does deploying idle capital
# across more qualified bets compound faster, or does per-trade edge dilute? Also tests
# spreading across MORE concurrent slots (the real way to use the extra opportunities).
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from idx_trend_ride import ride                       # same EARLY entry + LOOSE-ride exit
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_discover import UNIVERSE
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

EMA_LEN, TRAIL_ATR, INIT_ATR = 50, 4.0, 2.5          # the proven LOOSE settings

def main():
    print(f"UPGRADE #1 · trend-ride on BROAD universe ({len(UNIVERSE)} names) · last {WINDOW_YEARS}y")
    print("Same strategy as konglo (4.1x) — only the opportunity set is wider.\n")
    tickers = [t + ".JK" for t in UNIVERSE]
    trades = []; usable = 0
    for k in range(0, len(tickers), 25):
        chunk = tickers[k:k+25]
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
            usable += 1
            for x in ride(d, EMA_LEN, TRAIL_ATR, INIT_ATR):
                x["ticker"] = t.replace(".JK", ""); trades.append(x)
        print(f"  ...scanned {min(k+25,len(tickers))}/{len(tickers)}  (usable {usable})", flush=True)

    win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    print("\n" + "="*80 + f"\n  TREND-RIDE · BROAD universe · last {WINDOW_YEARS}y\n" + "="*80)
    if not win:
        print("  no trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    print(f"  Signals fired  : {len(df)}  across {df.ticker.nunique()} names "
          f"(konglo had ~30 across ~16)")
    print(f"  Win rate       : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d")
    print(f"  Avg win / loss : +{aw:.1f}% / {al:.1f}%   ·   expectancy {df.pnl.mean():+.2f}%/trade")
    print(f"  Top names      : {', '.join(df.ticker.value_counts().head(10).index)}")

    print("\n" + "="*80 + "\n  DEPLOYING THE IDLE CAPITAL — sizing × concurrent slots\n" + "="*80)
    print(f"  {'scheme':22}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}{'taken/skipped':>16}")
    for lab, f, m in [("25% × max4",0.25,4), ("15% × max6",0.15,6),
                      ("12% × max8",0.12,8), ("10% × max10",0.10,10)]:
        r = simulate(win, f, m)
        print(f"  {lab:22}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%"
              f"{r['maxdd']:>6.0f}%{r['taken']:>8}/{r['skipped']:<6}")
    print(f"\n  Benchmark — konglo-only same strategy: 4.1x (25%×4, 30 trades, 60% win).")
    print("  'skipped' = signals you missed because all slots were full = unused opportunity.")
    print("  ⚠️  Broad universe = thinner names; real fills worse than konglo. Liquidity-gated.")

if __name__ == "__main__":
    main()
