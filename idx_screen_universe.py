# idx_screen_universe.py — build a FAST, quality daily universe (run weekly, not daily).
# Screens the broad ~395 IDX board ONCE and writes idx_universe.json — the small set of
# "moveable + tradeable + not-junk" names. The daily scan then loads that file and runs in
# seconds instead of 6 minutes.
#   Hard filters (reliable, from OHLC):  price floor · turnover (tradeable) · ADR% (moveable)
#   Enrichment (yfinance, best-effort):  market cap + free-float %  (shown; soft cap ceiling)
import sys, json, time, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
from idx_discover import UNIVERSE

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MIN_PRICE = 50          # Rp — skip penny junk
MIN_TURN  = 10e9        # Rp 10bn/day median — tradeable
MIN_ADR   = 3.0         # % average daily range — "moveable" (your idea, measured from price)
CAP_MAX   = 300e12      # Rp 300T — exclude true mega-caps that can't move (soft; ADR also catches)
LOOKBACK  = 60          # days for turnover/ADR stats
OUT = "idx_universe.json"

def stat_block(df):
    df = df.rename(columns=str.lower).dropna()
    if len(df) < LOOKBACK + 5: return None
    tail = df.tail(LOOKBACK)
    price = float(tail["close"].iloc[-1])
    turn  = float((tail["close"] * tail["volume"]).median())
    adr   = float(((tail["high"] - tail["low"]) / tail["close"]).mean() * 100)
    return dict(price=price, turnover=turn, adr=adr)

def enrich(tk):
    """Best-effort market cap + free float via yfinance (often missing for IDX)."""
    cap = flt = None
    try:
        fi = yf.Ticker(tk).fast_info
        cap = getattr(fi, "market_cap", None)
    except Exception: pass
    try:
        info = yf.Ticker(tk).get_info()
        cap = cap or info.get("marketCap")
        fs, so = info.get("floatShares"), info.get("sharesOutstanding")
        if fs and so: flt = round(fs / so * 100, 1)
    except Exception: pass
    return cap, flt

def main():
    print(f"Screening {len(UNIVERSE)} IDX names → quality universe "
          f"(price>={MIN_PRICE}, turn>=Rp{MIN_TURN/1e9:.0f}bn, ADR>={MIN_ADR}%)\n")
    tickers = [t + ".JK" for t in UNIVERSE]
    rows = {}
    for k in range(0, len(tickers), 25):
        chunk = tickers[k:k+25]
        try:
            data = yf.download(chunk, period="6mo", interval="1d", progress=False,
                               auto_adjust=True, group_by="ticker")
        except Exception:
            continue
        for t in chunk:
            try:
                s = stat_block(data[t].copy())
            except Exception:
                s = None
            if s: rows[t] = s
        print(f"  ...{min(k+25,len(tickers))}/{len(tickers)}", flush=True)

    # hard filters
    passed = {t: s for t, s in rows.items()
              if s["price"] >= MIN_PRICE and s["turnover"] >= MIN_TURN and s["adr"] >= MIN_ADR}
    print(f"\n  {len(rows)} priced · {len(passed)} passed the moveable+tradeable filter.")
    print("  Enriching survivors with market cap / free float (best-effort)...\n")

    detail = {}
    for t, s in passed.items():
        cap, flt = enrich(t); time.sleep(0.05)
        if cap and cap > CAP_MAX:                 # soft ceiling — drop true mega-caps
            continue
        s = {**s, "cap": cap, "float_pct": flt}
        detail[t.replace(".JK", "")] = s

    ranked = sorted(detail.items(), key=lambda kv: kv[1]["adr"], reverse=True)
    print("="*82)
    print(f"  QUALITY UNIVERSE — {len(ranked)} names  (sorted by moveability / ADR%)")
    print("="*82)
    print(f"  {'ticker':7}{'price':>9}{'turnover/d':>13}{'ADR%':>7}{'mktcap':>11}{'float%':>8}")
    def b(x): return "—" if x is None else (f"{x/1e12:.1f}T" if x>=1e12 else f"{x/1e9:.0f}bn")
    for t, s in ranked:
        fl = "—" if s["float_pct"] is None else f"{s['float_pct']:.0f}"
        print(f"  {t:7}{s['price']:>9,.0f}{s['turnover']/1e9:>10,.0f}bn{s['adr']:>6.1f}%"
              f"{b(s['cap']):>11}{fl:>8}")

    out = {"generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
           "filters": {"min_price": MIN_PRICE, "min_turnover": MIN_TURN, "min_adr": MIN_ADR,
                       "cap_max": CAP_MAX},
           "tickers": [t for t, _ in ranked], "detail": dict(ranked)}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  ✅ Wrote {OUT} — {len(ranked)} names. Daily scan can load this (fast).")
    print("  Re-run weekly to refresh. Free float blank = yfinance didn't have it (common on IDX).")

if __name__ == "__main__":
    main()
