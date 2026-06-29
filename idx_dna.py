# idx_dna.py — Find the common DNA of the explosive movers (BUVA, PTRO, RAJA, CUAN, BREN...)
# right BEFORE they launched. For each, locate the start of its biggest run and measure the
# pre-launch signature, so we can hunt new stocks showing the same early pattern.
import warnings; warnings.filterwarnings("ignore")
import sys
import pandas as pd, numpy as np
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# the stocks that had monster runs
MOVERS = ["BUVA", "PTRO", "RAJA", "CUAN", "BREN", "BRPT", "BUMI", "DEWA", "WIFI", "MDIA"]
RUN_WIN = 40        # look for the best 40-trading-day advance
MIN_RUN = 0.50      # only count it as a "launch" if the run was >= +50%

def measure(d, i):
    """Pre-launch features using only data up to day i."""
    c, v, h, l = d["close"], d["volume"], d["high"], d["low"]
    turn = c * v
    # volume awakening: last 10d turnover vs the prior 3-month median (dormant -> active)
    recent = turn.iloc[i-9:i+1].mean()
    baseline = turn.iloc[i-70:i-10].median()
    wake = recent / baseline if baseline > 0 else np.nan
    # where in its 6-month range (breaking out of a base?)
    hi120, lo120 = h.iloc[i-120:i+1].max(), l.iloc[i-120:i+1].min()
    rng_pos = (c.iloc[i] - lo120) / (hi120 - lo120) if hi120 > lo120 else np.nan
    # how long it was quiet before: days since it last moved >25% in any 20d window (rough base length)
    ret20 = c.iloc[max(0,i-90):i+1].pct_change(20).abs()
    base_len = (ret20 < 0.25).sum()
    # volatility: ATR% now vs 3 months ago (compression then expansion)
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_now = atr.iloc[i]/c.iloc[i]*100
    # prior 60d return (was it already running, or quiet?)
    prior60 = c.iloc[i]/c.iloc[i-60]-1 if i>=60 else np.nan
    return dict(wake=wake, rng_pos=rng_pos, base_len=base_len, atr_pct=atr_now, prior60=prior60*100)

def main():
    print("Finding each mover's biggest run and what it looked like at the START:\n")
    print(f"  {'stock':6}{'run%':>7}{'wake×':>8}{'rangePos':>9}{'baseLen':>8}{'ATR%':>7}{'prior60d':>9}")
    print("  " + "-"*56)
    feats = []
    for t in MOVERS:
        d, _ = K.get_eod(t+".JK", period="3y")
        if d is None or len(d) < 200:
            print(f"  {t:6}  insufficient data"); continue
        d = d.reset_index(drop=True)
        fwd = d["close"].shift(-RUN_WIN) / d["close"] - 1
        # candidate launch points: best run start, searched after day 130 (need history)
        valid = fwd.iloc[130:len(d)-RUN_WIN]
        if valid.empty or valid.max() < MIN_RUN:
            print(f"  {t:6}  no >50% run in window"); continue
        i = valid.idxmax()
        run = fwd.iloc[i]
        m = measure(d, i)
        feats.append(m)
        print(f"  {t:6}{run*100:>+6.0f}%{m['wake']:>7.1f}×{m['rng_pos']:>9.2f}{m['base_len']:>8.0f}"
              f"{m['atr_pct']:>6.1f}%{m['prior60']:>+8.0f}%")

    if feats:
        F = pd.DataFrame(feats)
        print("\n" + "="*60)
        print("  COMMON DNA AT LAUNCH (median across the movers)")
        print("="*60)
        print(f"  Volume awakening (10d vs prior 3mo) : {F['wake'].median():.1f}×  "
              f"← turnover surged vs its own dormant base")
        print(f"  Position in 6-month range          : {F['rng_pos'].median():.2f}  "
              f"(1.0 = breaking to new highs)")
        print(f"  Prior 60-day return                : {F['prior60'].median():+.0f}%  "
              f"(low = was quiet before launching)")
        print(f"  ATR% at launch                     : {F['atr_pct'].median():.1f}%")
        print("\n  → Hunt: a quiet stock whose TURNOVER suddenly multiplies while it")
        print("    pushes toward the top of its range. That's the pre-explosion tell.")

if __name__ == "__main__":
    main()
