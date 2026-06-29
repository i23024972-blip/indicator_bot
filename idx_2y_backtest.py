# idx_2y_backtest.py — the LIVE hybrid strategy, measured over the last 2 years only.
# Reuses the exact signal logic (idx_hybrid_backtest.collect) and the exact compounding
# portfolio sim (idx_portfolio.simulate) — this just windows trades to 2y and reports.
import sys
import pandas as pd
from idx_hybrid_backtest import collect, stats
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

CUTOFF = pd.Timestamp.now().normalize() - pd.DateOffset(years=2)

def window(trades):
    return [t for t in trades if t["entry"] >= CUTOFF]

def main():
    print(f"Backtesting LIVE hybrid strategy from {CUTOFF.date()} -> today")
    print("(scanning the watchlist — takes a minute)...\n")

    hybrid    = window(collect("hybrid"))
    hybrid_cx = window(collect("hybrid_cx"))

    print("="*78 + "\n  SIGNAL EDGE — last 2 years (net 0.4% fees/trade)\n" + "="*78)
    stats(hybrid,    "HYBRID")
    stats(hybrid_cx, "HYBRID+CX")

    print("\n" + "="*78 + f"\n  $1,000 PORTFOLIO — last 2 years (live sizing: 25% × max 4)\n" + "="*78)
    for rows, lab in [(hybrid, "HYBRID"), (hybrid_cx, "HYBRID+CX")]:
        if not rows:
            print(f"  {lab:11} no trades in window"); continue
        r = simulate(rows, 0.25, 4)
        print(f"  {lab:11} ${r['final']:>8,.0f}  ({r['final']/START:.2f}x)  "
              f"CAGR {r['cagr']:+5.1f}%  MaxDD {r['maxdd']:4.1f}%  "
              f"trades {r['taken']}/{r['taken']+r['skipped']}  over {r['years']:.1f}y")

    print("\n  HYBRID = TREND entries in HEALTHY regime / COMBO in CAUTION+CRASH.")
    print("  +CX also force-exits open trades the day the regime flips to CRASH.")
    print("  ⚠️  0.4% fee/trade only · perfect fills · no gap slippage · long-only.")

if __name__ == "__main__":
    main()
