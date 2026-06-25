# zigzag_order.py - does trade ORDER (oldest->newest vs reversed) change the result?
# Compounding is order-dependent; the per-trade edge is not. This shows by how much.
import numpy as np
import zigzag_risksize as zr

def equity_curve(trs, risk_pct):
    bal=1000.0; peak=1000.0; dd=0.0
    for t in trs:
        if risk_pct is None: frac=1.0
        else: frac=min((risk_pct/100.0)/(t["sl_dist_pct"]/100.0), 1.0)
        bal*=(1+frac*t["net"]/100.0)
        peak=max(peak,bal); dd=max(dd,(peak-bal)/peak*100)
    return bal, dd

def main():
    trs = zr.gen_trades()                       # sorted oldest->newest
    fwd = trs
    rev = list(reversed(trs))
    print("Order test | BTC+DOGE+HYPE | does day1->1000 vs 1000->day1 matter?\n")
    print(f"  Trades: {len(trs)} | first {trs[0]['time']:%Y-%m-%d}  ->  last {trs[-1]['time']:%Y-%m-%d}")
    print(f"  (My backtests all use FORWARD = oldest->newest = the realistic direction.)\n")
    hdr=f"  {'risk':>6} | {'FORWARD (real)':>22} | {'REVERSED':>22} | {'avg net/trade':>13}"
    print(hdr); print("  "+"-"*(len(hdr)-2))
    avgnet=np.mean([t["net"] for t in trs])
    for rp in (None, 1.0, 2.5):
        fb,fd=equity_curve(fwd,rp); rb,rd=equity_curve(rev,rp)
        lbl="FULL" if rp is None else f"{rp:.1f}%"
        print(f"  {lbl:>6} | ${fb:>9,.0f}  (-{fd:>2.0f}% DD) | ${rb:>9,.0f}  (-{rd:>2.0f}% DD) | {avgnet:>+11.3f}%")
    print(f"\n  avg net/trade is IDENTICAL both ways ({avgnet:+.3f}%) - the edge doesn't depend on order.")
    print("  Only the COMPOUNDED $ and drawdown differ, because gains/losses stack in a different")
    print("  sequence. FORWARD is the only one you could actually trade. The Monte Carlo (random")
    print("  orders) already showed FORWARD isn't a lucky sequence - its median matched closely.")

if __name__ == "__main__":
    main()
