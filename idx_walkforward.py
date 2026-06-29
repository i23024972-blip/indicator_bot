# idx_walkforward.py — THE HONEST TEST.
# Walk forward day-by-day through the last 2 years over the WHOLE liquid IDX board
# (~400 names, winners AND losers — NOT the hand-picked konglo watchlist). Each day the
# SAME hybrid indicators decide what to buy; we only buy names that were actually liquid
# AT THE SIGNAL DATE (trailing turnover, no hindsight), size by the live scheme, and
# compound. This answers: "if I'd run this blind for 2 years, where's my capital now?"
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, numpy as np, yfinance as yf
import idx_konglo as K
from idx_hybrid_backtest import fire_combo, fire_trend, sim_combo, sim_trend, regime_at
from idx_portfolio import simulate, START
from idx_discover import UNIVERSE

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MIN_TURNOVER = 10e9          # Rp 10bn/day TRAILING — point-in-time liquidity gate
WINDOW_YEARS = 2
CUTOFF = pd.Timestamp.now().normalize() - pd.DateOffset(years=WINDOW_YEARS)

def build(ticker, draw):
    """Replicate idx_hybrid_backtest.prep() from a batch-downloaded daily frame.
    Weekly structure is derived by RESAMPLING daily (no 2nd download)."""
    d = draw.dropna().copy()
    if len(d) < 300: return None
    d = d.rename(columns=str.lower)[["open","high","low","close","volume"]].reset_index()
    d = d.rename(columns={d.columns[0]: "time"}); d["time"] = pd.to_datetime(d["time"])
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(50).mean()
    d["sma200"]= d["close"].rolling(200).mean()
    d["ret1"]  = d["close"].pct_change()
    d["turn20"]= (d["close"]*d["volume"]).rolling(20).median()   # TRAILING liquidity
    # daily zigzag structure
    zz_d = K.compute_zigzag_pivots(d)
    d["sd"] = [K.structure_at(zz_d, i) for i in range(len(d))]
    # weekly structure via resample
    w = (d.set_index("time").resample("W")
           .agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
           .dropna().reset_index())
    if len(w) < 20: return None
    zz_w = K.compute_zigzag_pivots(w)
    sw = []
    for i in range(len(d)):
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw.append(K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral")
    d["sw"] = sw
    return d

def collect_universe():
    trades = []
    tickers = [t + ".JK" for t in UNIVERSE]
    done = 0
    for k in range(0, len(tickers), 25):
        chunk = tickers[k:k+25]
        try:
            data = yf.download(chunk, period="3y", interval="1d", progress=False,
                               auto_adjust=True, group_by="ticker")
        except Exception:
            continue
        for t in chunk:
            try:
                draw = data[t].copy()
                d = build(t, draw)
            except Exception:
                d = None
            if d is None: continue
            done += 1
            last = -1
            for i in range(200, len(d)-1):
                if i <= last: continue
                if pd.isna(d["atr"].iloc[i]) or d["atr"].iloc[i] <= 0: continue
                if pd.isna(d["sma200"].iloc[i]): continue
                # point-in-time liquidity gate — would this have been tradeable that day?
                if pd.isna(d["turn20"].iloc[i]) or d["turn20"].iloc[i] < MIN_TURNOVER: continue
                reg = regime_at(d["time"].iloc[i])
                if reg == "HEALTHY":
                    fire, fn = fire_trend(d, i), sim_trend
                else:
                    fire, fn = fire_combo(d, i), sim_combo
                if fire:
                    pnl, bars = fn(d, i)
                    last = i + bars; xi = min(i + bars, len(d)-1)
                    trades.append({"ticker": t.replace(".JK",""), "entry": d["time"].iloc[i],
                                   "exit": d["time"].iloc[xi], "pnl": pnl - 0.4, "bars": bars})
        print(f"  ...scanned {min(k+25,len(tickers))}/{len(tickers)}  (usable: {done})", flush=True)
    return trades, done

def main():
    print(f"WALK-FORWARD over the broad IDX board ({len(UNIVERSE)} names), last {WINDOW_YEARS} years.")
    print(f"Liquidity gate: trailing turnover >= Rp {MIN_TURNOVER/1e9:.0f}bn/day at signal date.")
    print("Downloading + scanning (a few minutes)...\n")
    alltr, usable = collect_universe()
    win = sorted([t for t in alltr if t["entry"] >= CUTOFF], key=lambda x: x["entry"])

    print("\n" + "="*78 + f"\n  SIGNAL EDGE — broad universe, last {WINDOW_YEARS}y (net 0.4% fee)\n" + "="*78)
    if not win:
        print("  no qualifying trades"); return
    df = pd.DataFrame(win); wr = (df.pnl>0).mean()*100
    aw = df[df.pnl>0].pnl.mean() if (df.pnl>0).any() else 0
    al = df[df.pnl<=0].pnl.mean() if (df.pnl<=0).any() else 0
    nstk = df.ticker.nunique()
    print(f"  Trades fired   : {len(df)}  across {nstk} different stocks")
    print(f"  Win rate       : {wr:.0f}%")
    print(f"  Avg win / loss : +{aw:.1f}% / {al:.1f}%")
    print(f"  Expectancy     : {df.pnl.mean():+.2f}% / trade   ·   avg hold {df.bars.mean():.0f}d")
    print(f"  Top stocks hit : {', '.join(df.ticker.value_counts().head(8).index)}")

    print("\n" + "="*78 + f"\n  $1,000 PORTFOLIO — bought blind for {WINDOW_YEARS}y (25% × max 4)\n" + "="*78)
    for frac, mx, lab in [(0.25,4,"25% × max4 (live sizing)"), (0.10,8,"10% × max8 (defensive)")]:
        r = simulate(win, frac, mx)
        print(f"  {lab:28} ${r['final']:>9,.0f}  ({r['final']/START:5.2f}x)  "
              f"CAGR {r['cagr']:+6.1f}%  MaxDD {r['maxdd']:4.1f}%  took {r['taken']}/{len(win)}")

    print(f"\n  Scanned {usable} stocks with usable data · only point-in-time-liquid names bought.")
    print("  ⚠️  Entry = signal-day close (real fills worse), 0.4% fee, no gap slippage, long-only.")
    print("  This is the closest thing to 'what would 2 years of trading it blind have done.'")

if __name__ == "__main__":
    main()
