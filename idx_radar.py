# idx_radar.py — "Waking up" radar. Scans the broad IDX universe daily for the BUVA-style
# pre-explosion tell: a quiet stock whose TURNOVER suddenly multiplies off its dormant base
# while price pushes up — i.e. the stock is "waking up" before the crowd notices.
#
# This is a DISCOVERY / watch-radar tool, NOT a buy signal. Most awakenings fizzle
# (survivorship bias is real). It surfaces names to add to the watchlist; the Combo
# (idx_scan.py) then decides the actual entry. Run occasionally; alerts top candidates.
import warnings; warnings.filterwarnings("ignore")
import os, sys, json
from datetime import datetime, timedelta
import pandas as pd, numpy as np, yfinance as yf
from idx_discover import UNIVERSE, flat
from idx_scan import WATCHLIST, notify

RADAR_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "radar_state.json")
REALERT_DAYS = 7        # don't re-alert the same waking-up stock within a week

def _load_seen():
    try:
        with open(RADAR_STATE) as f: return json.load(f)
    except Exception:
        return {}

def _save_seen(s):
    with open(RADAR_STATE, "w") as f: json.dump(s, f, indent=2)

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

WAKE_MIN     = 3.0      # recent turnover >= 3x its prior 3-month base = "waking up"
MIN_TURN_NOW = 5e9      # must now trade >= Rp 5bn/day (liquid enough to matter)
NOT_TOO_LATE = 1.00     # skip if already up >100% in 60d (the move's mostly done)

def analyse(d):
    d = flat(d).dropna()
    if len(d) < 130: return None
    c, v, h, l = d["close"], d["volume"], d["high"], d["low"]
    turn = c * v
    recent   = turn.iloc[-10:].mean()
    baseline = turn.iloc[-70:-10].median()
    if baseline <= 0: return None
    wake = recent / baseline
    hi120, lo120 = h.iloc[-120:].max(), l.iloc[-120:].min()
    rng_pos = (c.iloc[-1]-lo120)/(hi120-lo120) if hi120 > lo120 else np.nan
    prior60 = c.iloc[-1]/c.iloc[-61]-1
    up5     = c.iloc[-1]/c.iloc[-6]-1            # turning up recently?
    return dict(wake=wake, rng_pos=rng_pos, prior60=prior60*100,
                turn_now=recent, up5=up5*100, last=float(c.iloc[-1]))

def main():
    print(f"📡 Awakening radar — turnover surge >= {WAKE_MIN}x its 3-month base, still early.\n"
          f"   Scanning {len(UNIVERSE)} stocks...\n")
    rows = []
    tickers = [t+".JK" for t in UNIVERSE]
    for k in range(0, len(tickers), 25):
        data = yf.download(tickers[k:k+25], period="1y", interval="1d", progress=False,
                           auto_adjust=True, group_by="ticker")
        for t in tickers[k:k+25]:
            try:
                a = analyse(data[t].copy())
            except Exception:
                a = None
            if a: rows.append({"ticker": t.replace(".JK",""), **a})

    df = pd.DataFrame(rows)
    hits = df[(df["wake"] >= WAKE_MIN) & (df["turn_now"] >= MIN_TURN_NOW)
              & (df["prior60"] < NOT_TOO_LATE*100) & (df["up5"] > 0)
              & (df["rng_pos"] > 0.4)].sort_values("wake", ascending=False)

    def tn(x): return f"{x/1e9:,.0f}bn"
    print("="*72)
    print("  📡 STOCKS WAKING UP  (turnover multiplying off a quiet base, pushing up)")
    print("="*72)
    if not len(hits):
        print("  None today. (Common in a CRASH — awakenings cluster in healthy markets.)")
    else:
        print(f"  {'ticker':7}{'wake×':>7}{'turn/d':>9}{'rangePos':>9}{'60d':>7}{'5d':>7}  status")
        seen = _load_seen()
        cutoff = (datetime.now() - timedelta(days=REALERT_DAYS)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        lines = []
        for _, r in hits.head(15).iterrows():
            tag = "✓ in list" if r["ticker"] in WATCHLIST else "🆕 NEW"
            print(f"  {r['ticker']:7}{r['wake']:>6.1f}×{tn(r['turn_now']):>9}{r['rng_pos']:>9.2f}"
                  f"{r['prior60']:>+6.0f}%{r['up5']:>+6.0f}%  {tag}")
            # alert only NEW names not pinged in the last REALERT_DAYS
            if r["ticker"] not in WATCHLIST and seen.get(r["ticker"], "0000") < cutoff:
                lines.append(f"🆕 {r['ticker']}  turnover {r['wake']:.1f}× its base "
                             f"({tn(r['turn_now'])}/d), range {r['rng_pos']:.0%}, 60d {r['prior60']:+.0f}%")
                seen[r["ticker"]] = today
        _save_seen(seen)
        # Telegram: only the freshly-woken NEW names
        if lines:
            body = ("📡 WAKING-UP RADAR — possible early movers\n"
                    "(quiet stocks whose turnover just surged — like early BUVA/RAJA)\n\n"
                    + "\n".join(lines) +
                    "\n\n⚠️ Watch-radar only, NOT a buy. Add to watchlist & wait for a Combo signal.")
            print("\n" + body)
            notify(body)
    print(f"\n  Scanned {len(df)} · {len(hits)} waking up. Survivorship caveat: most fizzle.")

if __name__ == "__main__":
    main()
