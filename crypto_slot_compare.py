# crypto_slot_compare.py — for a SMALL account that can only hold a few positions, does it matter
# WHICH signals fill the scarce slots? Compares, at 1% risk over 2y, the same regime-directional
# trades under different slot-allocation rules:
#   UNCAPPED        — take every signal (reference; needs leverage, not reachable at $200)
#   CAP-N first-come — when slots full, skip; ties broken arbitrarily (what the live bot does now)
#   CAP-N conviction — scarce slots go to highest 30-bar momentum (long=strongest / short=weakest)
#   CAP-N anti-conv  — opposite ranking (sanity check: if conviction helps, this should hurt)
# Reuses crypto_capped's fetch/regime/trade logic. Read-only.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from crypto_capped import client, fetch, btc_regime, trades, MIN_VOL, TOPN, VOL_LO, VOL_HI, TEST_DAYS, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

RISK = 1.0


def sim(trs, maxpos, key):
    if key == "uncapped":
        order = sorted(trs, key=lambda x: x["entry"])
        takenR = [t["R"] for t in order]
        eq = 1.0; curve = []
        for R in takenR:
            eq *= (1 + RISK/100*R); curve.append(eq)
    else:
        if key == "conv":      order = sorted(trs, key=lambda x: (x["entry"], -x["conv"]))
        elif key == "anti":    order = sorted(trs, key=lambda x: (x["entry"],  x["conv"]))
        else:                  order = sorted(trs, key=lambda x: (x["entry"],  x["sym"]))   # first-come
        eq = 1.0; openp = []; curve = []; takenR = []
        for tr in order:
            still = []
            for ex, R in openp:
                if ex <= tr["entry"]: eq *= (1 + RISK/100*R)
                else: still.append((ex, R))
            openp = still; curve.append(eq)
            if len(openp) >= maxpos: continue
            openp.append((tr["exit"], tr["R"])); takenR.append(tr["R"])
        for ex, R in openp: eq *= (1 + RISK/100*R)
        curve.append(eq)
    peak = -1; dd = 0
    for e in curve:
        peak = max(peak, e); dd = max(dd, (peak-e)/peak*100)
    takenR = np.array(takenR)
    win = (takenR > 0).mean()*100 if len(takenR) else 0
    return eq, dd, len(takenR), win


def main():
    print("SLOT-ALLOCATION TEST · 1% risk · 2y · regime-directional · which signals fill scarce slots?\n")
    info = client.futures_exchange_info()
    syms = [s["symbol"] for s in info["symbols"] if s["symbol"].endswith("USDT")
            and s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"]
    vol = {t["symbol"]: float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid = sorted([s for s in syms if vol.get(s, 0) >= MIN_VOL], key=lambda s: -vol.get(s, 0))[:TOPN]
    cutoff = pd.Timestamp.now('UTC').tz_localize(None) - pd.Timedelta(days=TEST_DAYS)
    data = {}
    for s in liquid:
        try: data[s] = fetch(s)
        except Exception: pass
    reg = btc_regime(data["BTCUSDT"]); allt = []
    for s, df in data.items():
        if not (VOL_LO <= (df["atr"]/df["close"]).median()*100 <= VOL_HI): continue
        for tr in trades(df, reg, cutoff):
            tr["sym"] = s; allt.append(tr)
    print(f"  {len(allt)} raw signals across {len(set(t['sym'] for t in allt))} coins\n")

    # how often are slots actually contested? (signals sharing a 4h entry bar)
    bycnt = pd.Series([t["entry"] for t in allt]).value_counts()
    print(f"  bars with >1 simultaneous signal: {(bycnt>1).sum()} of {len(bycnt)} "
          f"({(bycnt>1).mean()*100:.0f}%) — conviction only matters when slots are contested\n")

    print("="*68)
    print(f"  {'policy':22}{'$1,000 →':>12}{'MaxDD':>8}{'trades':>8}{'win%':>7}")
    print("="*68)
    e, d, n, w = sim(allt, 999, "uncapped")
    print(f"  {'UNCAPPED (all)':22}${START*e:>9,.0f}{d:>7.0f}%{n:>8}{w:>6.0f}%")
    for cap in [6, 8]:
        print("  " + "-"*64)
        for key, label in [("first", f"CAP-{cap} first-come"), ("conv", f"CAP-{cap} conviction"), ("anti", f"CAP-{cap} anti-conv")]:
            e, d, n, w = sim(allt, cap, key)
            print(f"  {label:22}${START*e:>9,.0f}{d:>7.0f}%{n:>8}{w:>6.0f}%")
    print("="*68)
    print("\n  Read: if CAP-N conviction beats CAP-N first-come (and anti-conv is worst), ranking helps.")
    print("  If they're ~equal, the live bot's simpler first-come is fine — don't add conviction.")
    print("  $ shown for $1,000 base; scales linearly to your $200 (÷5).")


if __name__ == "__main__":
    main()
