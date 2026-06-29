# idx_trend_ride_quality.py — the PAYOFF test for Upgrade #1.
# Runs the exact validated trend-ride on the QUALITY-FILTERED universe (idx_universe.json:
# moveable ADR>=3% + tradeable turnover + not-junk) instead of the raw 395 board. Question:
# does the quality filter recover the konglo edge (4.1x) while adding more opportunity than
# the 20 konglo names — i.e., beat the diluted broad result (1.8x)?
import sys, json, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
from idx_trend_ride import ride
from idx_walkforward import build, CUTOFF, WINDOW_YEARS
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

EMA_LEN, TRAIL_ATR, INIT_ATR = 50, 4.0, 2.5

def main():
    uni = json.load(open("idx_universe.json"))["tickers"]
    print(f"PAYOFF TEST · trend-ride on QUALITY universe ({len(uni)} names) · last {WINDOW_YEARS}y\n")
    tickers = [t + ".JK" for t in uni]
    trades = []; usable = 0
    for k in range(0, len(tickers), 25):
        chunk = tickers[k:k+25]
        try:
            data = yf.download(chunk, period="3y", interval="1d", progress=False,
                               auto_adjust=True, group_by="ticker")
        except Exception:
            continue
        for t in chunk:
            try: d = build(t, data[t].copy())
            except Exception: d = None
            if d is None: continue
            usable += 1
            for x in ride(d, EMA_LEN, TRAIL_ATR, INIT_ATR):
                x["ticker"] = t.replace(".JK",""); trades.append(x)
        print(f"  ...{min(k+25,len(tickers))}/{len(tickers)}", flush=True)

    win = sorted([t for t in trades if t["entry"] >= CUTOFF], key=lambda x: x["entry"])
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean(); al = df[df.pnl<=0].pnl.mean()
    print("\n" + "="*78 + "\n  TREND-RIDE · QUALITY universe\n" + "="*78)
    print(f"  Signals     : {len(df)} across {df.ticker.nunique()} names")
    print(f"  Win rate    : {wr:.0f}%   ·   avg hold {df.bars.mean():.0f}d   ·   exp {df.pnl.mean():+.2f}%/trade")
    print(f"  Avg win/loss: +{aw:.1f}% / {al:.1f}%")
    print(f"  Top names   : {', '.join(df.ticker.value_counts().head(10).index)}")
    print("\n" + "="*78 + "\n  $1,000 PORTFOLIO — sizing × slots\n" + "="*78)
    print(f"  {'scheme':22}{'final $':>11}{'x':>6}{'CAGR':>8}{'MaxDD':>7}{'taken/skip':>13}")
    for lab,f,m in [("25% × max4",0.25,4),("15% × max6",0.15,6),("12% × max8",0.12,8),("10% × max10",0.10,10)]:
        r = simulate(win, f, m)
        print(f"  {lab:22}${r['final']:>9,.0f}{r['final']/START:>5.1f}x{r['cagr']:>+7.0f}%{r['maxdd']:>6.0f}%{r['taken']:>7}/{r['skipped']:<5}")
    print("\n  HEAD-TO-HEAD:  konglo-20 = 4.1x/60%win  ·  broad-395 = 1.8x/34%win  ·  quality = above")
    print("  Did filtering to quality recover the edge AND add opportunity?")

if __name__ == "__main__":
    main()
