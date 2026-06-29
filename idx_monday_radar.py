# idx_monday_radar.py — what's on the radar for the next session.
# For each konglo name: is it in a real uptrend (>200MA), and how close is it to breaking its
# 50-day high (the DONCH50+200 trigger)? Ranks by closeness so you know what to watch.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MIN_TURN = 10e9

def main():
    data = yf.download(K.all_tickers(), period="2y", interval="1d",
                       progress=False, auto_adjust=True, group_by="ticker")
    rows = []
    asof = None
    for tk in K.all_tickers():
        try:
            d = data[tk].dropna().copy()
            if len(d) < 210: continue
            d.columns = [c.lower() for c in d.columns]
            close = float(d["close"].iloc[-1])
            sma200 = float(d["close"].rolling(200).mean().iloc[-1])
            donch50 = float(d["high"].rolling(50).max().shift(1).iloc[-1])
            turn = float((d["close"]*d["volume"]).tail(20).median())
            asof = d.index[-1].date()
            above200 = close > sma200
            to_break = (donch50 - close) / close * 100   # % move still needed to break 50d-high
            rows.append(dict(tk=tk.replace(".JK",""), close=close, donch=donch50,
                             above200=above200, to_break=to_break, turn=turn))
        except Exception:
            continue

    df = pd.DataFrame(rows)
    liquid = df[df["turn"] >= MIN_TURN].copy()

    def status(r):
        if not r["above200"]: return "⚪ below 200MA (no trade)"
        if r["to_break"] <= 0: return "🟢 SIGNAL — broke 50d-high!"
        if r["to_break"] <= 5: return "🟡 WATCH — close to breakout"
        return "🟠 uptrend, but far from high"

    liquid["status"] = liquid.apply(status, axis=1)
    # rank: signals first, then closest to breakout among uptrends, then the rest
    liquid["rank"] = liquid.apply(lambda r: (0 if (r["above200"] and r["to_break"]<=0)
                                             else (1 if r["above200"] else 2), r["to_break"]), axis=1)
    liquid = liquid.sort_values("rank")

    print(f"📡 MONDAY RADAR · DONCH50+200 · konglo · data as of {asof}")
    print("━"*64)
    print(f"  {'ticker':7}{'close':>9}{'50d-high':>10}{'to break':>10}  status")
    print("  "+"-"*60)
    for _, r in liquid.iterrows():
        tb = "—" if r["to_break"]<=0 else f"+{r['to_break']:.1f}%"
        print(f"  {r['tk']:7}{r['close']:>9,.0f}{r['donch']:>10,.0f}{tb:>10}  {r['status']}")
    sig = liquid[(liquid.above200)&(liquid.to_break<=0)]
    watch = liquid[(liquid.above200)&(liquid.to_break>0)&(liquid.to_break<=5)]
    print("\n  "+"━"*60)
    print(f"  🟢 Firing now : {len(sig)}   ·   🟡 Watch (<5% away): {len(watch)}   "
          f"·   ⚪ below 200MA: {(~liquid.above200).sum()}")
    if len(sig)==0:
        print("  No breakouts yet — most konglo names still below their 200MA (crash regime).")
        print("  The 🟡 WATCH names are the ones that could trigger first if the market turns.")

if __name__ == "__main__":
    main()
