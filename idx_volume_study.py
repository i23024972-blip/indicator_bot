# idx_volume_study.py — Does a volume spike actually predict upside on konglo stocks?
# Hypothesis (user): spike+up -> keeps going up; quiet+down -> keeps falling;
# spike+down or quiet+up are "weird" divergences. Long-only, so we care about UPSIDE.
#
# Method: over the last ~300 trading days, label each day by (price direction, volume regime),
# then measure the AVERAGE forward return 5/10/20 days later. No trading rules yet — pure stats.
import sys
import numpy as np
import pandas as pd
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

LOOKBACK_DAYS = 300
VOL_MA        = 20      # baseline volume window
SPIKE_X       = 2.0     # vol >= 2x its 20d average = "spike"
QUIET_X       = 0.7     # vol <= 0.7x average    = "quiet/dry"
FWD = [5, 10, 20]       # forward horizons (trading days)

def label_rows(d):
    d = d.copy()
    d["ret1"]  = d["close"].pct_change()
    d["volma"] = d["volume"].rolling(VOL_MA).mean()
    d["volr"]  = d["volume"] / d["volma"]
    for h in FWD:
        d[f"fwd{h}"] = d["close"].shift(-h) / d["close"] - 1.0

    up   = d["ret1"] > 0
    down = d["ret1"] < 0
    spike = d["volr"] >= SPIKE_X
    quiet = d["volr"] <= QUIET_X

    d["bucket"] = "mid"                       # everything not in an extreme bucket
    d.loc[up   & spike, "bucket"] = "UP+SPIKE"     # conviction buying
    d.loc[up   & quiet, "bucket"] = "UP+QUIET"     # drifting up, no fuel (weird/weak)
    d.loc[down & spike, "bucket"] = "DOWN+SPIKE"   # heavy selling OR capitulation (weird)
    d.loc[down & quiet, "bucket"] = "DOWN+QUIET"   # quiet bleed
    return d

def main():
    print(f"Volume study | last {LOOKBACK_DAYS} trading days | spike>= {SPIKE_X}x, quiet<= {QUIET_X}x (20d avg)\n")
    rows = []
    for t in K.all_tickers():
        d, _ = K.get_eod(t, period="2y")
        if d is None or len(d) < LOOKBACK_DAYS + VOL_MA:
            continue
        d = label_rows(d).tail(LOOKBACK_DAYS)
        d["ticker"], d["group"] = t, K.group_of(t)
        rows.append(d)
    big = pd.concat(rows, ignore_index=True)

    order = ["UP+SPIKE", "UP+QUIET", "DOWN+SPIKE", "DOWN+QUIET"]
    def report(df, title):
        print(f"{'='*72}\n  {title}\n{'='*72}")
        print(f"  {'bucket':12} {'n':>5} " + " ".join(f"fwd{h}d  win%" for h in FWD))
        for b in order:
            s = df[df["bucket"] == b]
            if len(s) == 0:
                continue
            cells = []
            for h in FWD:
                col = s[f"fwd{h}"].dropna()
                cells.append(f"{col.mean()*100:+5.1f}% {(col>0).mean()*100:4.0f}%")
            print(f"  {b:12} {len(s):>5} " + "   ".join(cells))
        # baseline = any random day
        base = df["fwd10"].dropna()
        print(f"  {'(any day)':12} {len(base):>5}   baseline fwd10 {base.mean()*100:+.1f}%  win {(base>0).mean()*100:.0f}%")
        print()

    report(big, "ALL KONGLO STOCKS POOLED")
    for g in K.KONGLO:
        report(big[big["group"] == g], f"GROUP: {g}")

if __name__ == "__main__":
    main()
