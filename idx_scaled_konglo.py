# idx_scaled_konglo.py — the marriage: Eric's SCALED-EXIT management on the KONGLO universe.
# Combines the two separately-validated edges: clean-trending konglo names (binary ride = 4.1x,
# 60% win) + scaled exits for comfort (banked profits, tiny drawdown). Same scaled logic as
# idx_scaled_exit.py, just on the ~20 konglo names instead of the diluted quality-89.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K
from idx_scaled_exit import find
from idx_walkforward import CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def main():
    tickers = K.all_tickers()
    print(f"SCALED-EXIT · KONGLO universe ({len(tickers)} names) · last {WINDOW_YEARS}y")
    print("TP1 +12%(⅓) · TP2 +30%(⅓) · runner rides · scale out ½ per weak EMA10 close\n")
    data = yf.download(tickers, period="3y", interval="1d", progress=False,
                       auto_adjust=True, group_by="ticker")
    from idx_walkforward import build
    trades = []
    for t in tickers:
        try: d = build(t, data[t].copy())
        except Exception: d = None
        if d is None: continue
        for x in find(d): x["ticker"] = t.replace(".JK",""); trades.append(x)

    win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean(); al = df[df.pnl<=0].pnl.mean()
    print("="*78 + "\n  SCALED-EXIT on KONGLO\n" + "="*78)
    print(f"  Trades      : {len(df)} across {df.ticker.nunique()} names")
    print(f"  Win rate    : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d   ·   exp {df.pnl.mean():+.2f}%/trade")
    print(f"  Avg win/loss: +{aw:.1f}% / {al:.1f}%")
    print(f"  Top names   : {', '.join(df.ticker.value_counts().head(8).index)}")
    print("\n" + "="*78 + "\n  $1,000 PORTFOLIO\n" + "="*78)
    print(f"  {'scheme':22}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}")
    for lab,f,m in [("25% × max4 (live)",0.25,4),("33% × max3",0.33,3),
                    ("15% × max6",0.15,6),("12% × max8",0.12,8)]:
        r = simulate(win, f, m)
        print(f"  {lab:22}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%{r['maxdd']:>6.0f}%")
    print("\n  BENCHMARKS:")
    print("    konglo BINARY ride : 4.1x · 60% win · 12% MaxDD   (max return, but gives back)")
    print("    quality SCALED     : 1.4x · 55% win ·  6% MaxDD   (smooth, but diluted universe)")
    print("    konglo SCALED      : ^^^ above ^^^   (clean trends + comfort — the sweet spot?)")

if __name__ == "__main__":
    main()
