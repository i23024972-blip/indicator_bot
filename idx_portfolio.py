# idx_portfolio.py — "If I started with $1000, where did I end up?"
# Realistic compounding equity sim of the COMBO strategy (Volume-spike + ZigZag, spike 2.5x).
# Position-sizing matters enormously, so we show several sizing schemes side by side.
import sys
import pandas as pd
import idx_konglo as K
from idx_compare import prep, entries_combo, simulate_long, FEE

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

START   = 1000.0
SPIKE_X = 2.5     # sweet spot from the sweep

def build_trades(spike_x=SPIKE_X):
    """Chronological list of Combo trades with entry/exit dates and net % pnl."""
    trades = []
    for t in K.all_tickers():
        d = prep(t)
        if d is None:
            continue
        ents = entries_combo(d, K.group_of(t), spike_x)
        last_exit = -1
        for i in ents:
            if i <= last_exit:
                continue
            pnl, bars = simulate_long(d, i)
            last_exit = i + bars
            xi = min(i + bars, len(d) - 1)
            trades.append({"ticker": t, "entry": d["time"].iloc[i],
                           "exit": d["time"].iloc[xi], "pnl": pnl - FEE})
    return sorted(trades, key=lambda x: x["entry"])

def simulate(trades, alloc_frac, max_pos):
    """Event-driven: size each trade at alloc_frac of current equity, cap concurrent positions."""
    cash = START
    openp = []            # list of dict(exit, cost, pnl)
    curve = []            # (date, equity)
    taken = skipped = 0

    def equity():
        return cash + sum(p["cost"] for p in openp)

    def release(upto_date):
        nonlocal cash
        still = []
        for p in openp:
            if p["exit"] <= upto_date:
                cash += p["cost"] * (1 + p["pnl"] / 100.0)   # return capital + pnl
            else:
                still.append(p)
        openp[:] = still

    for tr in trades:
        release(tr["entry"])                 # free capital from anything already closed
        curve.append((tr["entry"], equity()))
        if len(openp) >= max_pos:
            skipped += 1; continue
        cost = alloc_frac * equity()
        if cost > cash:                      # not enough free cash for full size
            cost = cash
        if cost <= 1:
            skipped += 1; continue
        cash -= cost                          # commit capital — remove from cash
        openp.append({"exit": tr["exit"], "cost": cost, "pnl": tr["pnl"]})
        taken += 1

    # close everything remaining
    last_date = max(t["exit"] for t in trades)
    release(last_date)
    final = equity()
    curve.append((last_date, final))

    # max drawdown on the sampled equity curve
    peak = -1; maxdd = 0
    for _, e in curve:
        peak = max(peak, e)
        maxdd = max(maxdd, (peak - e) / peak * 100)

    years = (last_date - trades[0]["entry"]).days / 365.25
    cagr = (final / START) ** (1/years) - 1 if years > 0 and final > 0 else 0
    return dict(final=final, taken=taken, skipped=skipped, maxdd=maxdd, cagr=cagr*100, years=years)

def main():
    print("Building Combo trades (Volume-spike + ZigZag, spike 2.5x, net 0.5% fees)...")
    trades = build_trades()
    print(f"{len(trades)} candidate trades over the period.\n")
    print(f"  Start: ${START:,.0f}   |   strategy: COMBO   |   period ~3 years\n")
    print(f"  {'Sizing scheme':28} {'Final $':>12} {'x':>6} {'CAGR':>8} {'MaxDD':>7} {'Taken/Skip':>12}")
    print("  " + "-"*78)
    schemes = [
        ("10% per trade, max 8",  0.10, 8),
        ("20% per trade, max 5",  0.20, 5),
        ("25% per trade, max 4",  0.25, 4),
        ("33% per trade, max 3",  0.33, 3),
        ("50% per trade, max 2",  0.50, 2),
        ("100% all-in, max 1",    1.00, 1),
    ]
    for label, f, m in schemes:
        r = simulate(trades, f, m)
        print(f"  {label:28} ${r['final']:>10,.0f} {r['final']/START:>5.1f}x "
              f"{r['cagr']:>6.1f}% {r['maxdd']:>6.1f}% {r['taken']:>5}/{r['skipped']:<5}")
    print(f"\n  ⚠️  No fees beyond 0.5%/trade, no slippage on gaps, perfect fills assumed.")
    print(f"      These were 3 strong-trending years — real results will be lower.")

if __name__ == "__main__":
    main()
