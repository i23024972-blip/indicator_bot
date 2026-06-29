# idx_regime.py — Market crash-regime detector for the IHSG (Jakarta Composite).
# 2008 GFC and 2020 COVID shared the SAME structure: price below the 200-day MA,
# a 50/200 death cross, volatility spike, and deep negative momentum. We score those
# 4 conditions; a high score = bearish regime -> the strategy sizes DOWN.
import warnings; warnings.filterwarnings("ignore")
import sys, time, logging
import pandas as pd, numpy as np, yfinance as yf

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# yfinance prints a scary "possibly delisted; no price data found" banner on any
# transient empty response. We retry ourselves, so mute its logger to keep the scan clean.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

VOL_CRASH = 30     # annualized realized vol % above this = stress (normal IHSG ~12-18%)
MOM_CRASH = -10    # 3-month momentum below this % = bearish

# regime -> position-size multiplier (applied to your base 25%)
SIZE_MULT = {"HEALTHY": 1.00, "CAUTION": 0.60, "CRASH": 0.40}

def load_ihsg(period="max", tries=4):
    # ^JKSE via yfinance is flaky — retry with backoff before giving up. A short period
    # (the live scan uses "2y") is far more reliable than dragging the full 1927→ history.
    ix = None
    for attempt in range(tries):
        try:
            ix = yf.download("^JKSE", period=period, interval="1d",
                             progress=False, auto_adjust=True)
            if ix is not None and len(ix) > 250:
                break
        except Exception:
            ix = None
        time.sleep(1.5 * (attempt + 1))
    if ix is None or len(ix) <= 250:
        raise ValueError(f"^JKSE returned no usable data after {tries} attempts")
    if hasattr(ix.columns, "levels"): ix.columns = ix.columns.get_level_values(0)
    ix.columns = [c.lower() for c in ix.columns]; ix.index = pd.to_datetime(ix.index)
    c = ix["close"]
    ix["ma50"]  = c.rolling(50).mean()
    ix["ma200"] = c.rolling(200).mean()
    ix["dd"]    = (c / c.rolling(252, min_periods=60).max() - 1) * 100
    ix["vol20"] = c.pct_change().rolling(20).std() * 100 * np.sqrt(252)
    ix["ret63"] = (c / c.shift(63) - 1) * 100
    f_below = (c < ix["ma200"]).astype(int)
    f_death = (ix["ma50"] < ix["ma200"]).astype(int)
    f_vol   = (ix["vol20"] >= VOL_CRASH).astype(int)
    f_mom   = (ix["ret63"] <= MOM_CRASH).astype(int)
    ix["score"]  = f_below + f_death + f_vol + f_mom
    ix["regime"] = pd.cut(ix["score"], [-1, 1, 2, 4], labels=["HEALTHY", "CAUTION", "CRASH"])
    return ix

def regime_on(ix, date):
    """Causal lookup: regime as known on or before `date`."""
    sub = ix.loc[:pd.to_datetime(date)]
    return sub["regime"].iloc[-1] if len(sub) else "HEALTHY"

def main():
    ix = load_ihsg()
    print(f"IHSG {ix.index[0].date()} -> {ix.index[-1].date()}  | vol>={VOL_CRASH}%, mom<={MOM_CRASH}%\n")

    # Did it flag the big crashes EARLY (first CRASH day vs the eventual trough)?
    print("="*60 + "\n  DID THE DETECTOR CATCH IT — AND HOW EARLY?\n" + "="*60)
    for lbl, s, e in [("2008 GFC", "2008-06-01", "2009-03-31"),
                      ("2020 COVID", "2020-01-01", "2020-06-30")]:
        w = ix.loc[s:e]
        crash_days = w[w["regime"] == "CRASH"]
        trough = w["dd"].idxmin()
        if len(crash_days):
            first = crash_days.index[0]
            lead = (trough - first).days
            print(f"  {lbl:11}: first CRASH flag {first.date()} | trough {trough.date()} "
                  f"({lead:+d}d {'BEFORE' if lead>0 else 'after'} trough)")

    # Sanity: a calm year should read HEALTHY
    calm = ix.loc["2017-01-01":"2017-12-31"]
    print(f"\n  Sanity (calm 2017): {(calm['regime']=='HEALTHY').mean()*100:.0f}% of days HEALTHY")

    # Historical time spent in each regime
    print(f"\n  Time in each regime (all history):")
    for r in ["HEALTHY", "CAUTION", "CRASH"]:
        print(f"    {r:8}: {(ix['regime']==r).mean()*100:4.0f}%   -> size x{SIZE_MULT[r]:.2f}  (= {25*SIZE_MULT[r]:.0f}% per trade)")

    # Current state
    r = ix.iloc[-1]
    reg = r["regime"]
    print(f"\n{'='*60}\n  RIGHT NOW ({ix.index[-1].date()})\n{'='*60}")
    print(f"  IHSG {r['close']:.0f} | dd {r['dd']:+.0f}% | below200 {r['close']<r['ma200']} | "
          f"death-cross {r['ma50']<r['ma200']} | vol {r['vol20']:.0f}% | 3mo {r['ret63']:+.0f}%")
    print(f"  REGIME: {reg}  (score {int(r['score'])}/4)  ->  SIZE x{SIZE_MULT[reg]:.2f} = "
          f"{25*SIZE_MULT[reg]:.0f}% per trade")
    if reg == "CRASH":
        print(f"  ⚠️  Bearish structure active — trade smaller, fewer positions, more cash.")

if __name__ == "__main__":
    main()
