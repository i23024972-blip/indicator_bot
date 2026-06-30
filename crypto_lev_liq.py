# crypto_lev_liq.py — does leverage get you LIQUIDATED on this strategy? Take the cash-only (1x)
# equity curve of the regime long/short bot, then apply 1x/2x/3x leverage. Leverage multiplies BOTH
# returns AND drawdowns; you're liquidated the moment drawdown crosses ~1/leverage. The strategy's
# own drawdown (~45-58%) is the killer — this shows whether 2x/3x survive it. 1% risk, 2y. Read-only.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from crypto_capped import client, fetch, btc_regime, trades, MIN_VOL, TOPN, VOL_LO, VOL_HI, TEST_DAYS, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

RISK = 1.0
MMR = 0.005   # maintenance-margin rate (small); liquidation when drawdown >= 1/L - MMR


def base_curve(trs, maxpos):
    """Cash-only (1x) equity curve at the position count that fully deploys capital (~8)."""
    order = sorted(trs, key=lambda x: (x["entry"], x.get("sym", "")))
    eq = 1.0; openp = []; curve = [1.0]
    for tr in order:
        still = []
        for ex, R in openp:
            if ex <= tr["entry"]: eq *= (1 + RISK/100*R)
            else: still.append((ex, R))
        openp = still
        if len(openp) >= maxpos:
            curve.append(eq); continue
        openp.append((tr["exit"], tr["R"])); curve.append(eq)
    for ex, R in openp: eq *= (1 + RISK/100*R)
    curve.append(eq)
    return np.array(curve)


def apply_leverage(curve, L):
    rets = np.diff(curve) / curve[:-1]
    eq = 1.0; peak = 1.0; maxdd = 0.0
    liq_thresh = 1.0/L - MMR        # drawdown that wipes the margin
    liquidated = False
    for r in rets:
        eq *= (1 + L*r)
        if eq <= 0:
            liquidated = True; eq = 0.0; break
        peak = max(peak, eq); dd = (peak - eq)/peak
        maxdd = max(maxdd, dd)
        if dd >= liq_thresh:
            liquidated = True; eq = 0.0; break
    cagr = (eq**(365/TEST_DAYS)-1)*100 if eq > 0 else -100
    return eq, maxdd*100, liquidated, cagr


def main():
    print("LEVERAGE → LIQUIDATION TEST · regime long/short · 1% risk · 2y\n")
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

    curve = base_curve(allt, 8)   # ~8 positions = fully-deployed cash = 1x base
    base_dd = 0.0; peak = curve[0]
    for e in curve:
        peak = max(peak, e); base_dd = max(base_dd, (peak-e)/peak*100)
    print(f"  base (1x, ~8 positions, cash): {len(allt)} trades · final {curve[-1]:.2f}x · unlevered MaxDD {base_dd:.0f}%\n")

    print("="*66)
    print(f"  {'leverage':10}{'liq. line':>11}{'$200 →':>12}{'CAGR':>9}{'MaxDD':>9}{'  outcome':>13}")
    print("="*66)
    for L in [1.0, 1.5, 2.0, 2.5, 3.0]:
        eq, dd, liq, cagr = apply_leverage(curve, L)
        out = "LIQUIDATED ☠" if liq else "survives ✅"
        liqline = "~none" if L <= 1 else f"-{(1/L)*100:.0f}%"
        endbal = "$0" if liq else f"${START*eq*0.2:,.0f}"   # scale $1000-base to $200 (x0.2)
        cg = "—" if liq else f"{cagr:+.0f}%"
        print(f"  {L:>4.1f}x{liqline:>13}{endbal:>12}{cg:>9}{(f'{dd:.0f}%'):>9}{out:>13}")
    print("="*66)
    print("\n  liq.line = drawdown that wipes you at that leverage (~1/L). If the strategy's own")
    print("  drawdown exceeds it, you're liquidated BEFORE any recovery → permanent $0.")
    print("  $200 end-balance scales the $1k-base result ×0.2.")


if __name__ == "__main__":
    main()
