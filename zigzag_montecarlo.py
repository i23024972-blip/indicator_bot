# zigzag_montecarlo.py
# "Could it ever hit 90%?" Bootstrap the real trades into thousands of alternate histories
# and measure the distribution of MAX drawdown, for full-equity vs 1% risk sizing.
import numpy as np
import zigzag_risksize as zr

N_SIMS = 20000
RNG = np.random.default_rng(42)

def max_dd(path):
    peak = np.maximum.accumulate(path)
    return np.max((peak - path)/peak)

def simulate(nets, fracs):
    """nets, fracs: per-trade net% and sizing fraction. Returns (maxDDs, finalReturns%) over N_SIMS."""
    n = len(nets)
    dds = np.empty(N_SIMS); rets = np.empty(N_SIMS)
    for s in range(N_SIMS):
        idx = RNG.integers(0, n, n)                 # resample with replacement (worse-luck draws)
        r = fracs[idx]*nets[idx]/100.0
        eq = np.concatenate([[1.0], np.cumprod(1.0 + r)])
        dds[s] = max_dd(eq); rets[s] = (eq[-1]-1.0)*100
    return dds, rets

def report(name, res):
    dds, rets = res
    dds = np.sort(dds)*100
    print(f"\n  {name}")
    print(f"    median total return : {np.median(rets):+.0f}%   (5th pct {np.percentile(rets,5):+.0f}%)")
    print(f"    median max-DD : {np.median(dds):.0f}%   95th pct {np.percentile(dds,95):.0f}%   "
          f"99th pct {np.percentile(dds,99):.0f}%   worst {dds[-1]:.0f}%")
    for thr in (50, 60, 70, 80, 90):
        p = np.mean(dds >= thr)*100
        print(f"    P(max-DD >= {thr}%): {p:5.2f}%")

def main():
    print(f"Monte Carlo risk-of-ruin | BTC+DOGE+HYPE | {N_SIMS:,} bootstrapped histories")
    print("  Resamples your real trades with replacement (allows worse streaks than history).")
    trs = zr.gen_trades()
    nets  = np.array([t["net"] for t in trs])
    sldis = np.array([t["sl_dist_pct"] for t in trs])
    # FIXED-position sweep (best-fitting sizing for this strategy) -- find your spot on the frontier
    for pf in (0.25, 0.40, 0.50, 0.60, 0.75, 1.00):
        report(f"FIXED {pf*100:.0f}% position (no leverage)", simulate(nets, np.full(len(trs), pf)))
    print("\n  Caveat: bootstrap assumes trades are independent. Real losing streaks CLUSTER more")
    print("  than random, so true tail risk is a bit worse than these numbers. Stops + low risk %")
    print("  are what actually cap it; leverage or removing stops is what makes 90%+ real.")

if __name__ == "__main__":
    main()
