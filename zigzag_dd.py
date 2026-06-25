# zigzag_dd.py - anatomy of the worst drawdown: one big loss, or an accumulated bleed?
import pandas as pd
import numpy as np
import zigzag_risksize as zr   # reuse gen_trades()
import zigzag_basket as zb

START = zb.START_CAPITAL

def analyze(sizing):
    trs = zr.gen_trades()
    # build equity curve
    eq = [START]; times = [trs[0]["time"]]
    bal = START
    for t in trs:
        if sizing == "full":
            frac = 1.0
        else:  # risk 1%
            frac = min(0.01/(t["sl_dist_pct"]/100.0), 1.0)
        bal *= (1 + frac*t["net"]/100.0)
        eq.append(bal); times.append(t["time"])
    eq = np.array(eq)
    # find max drawdown trough, then its preceding peak
    running_peak = np.maximum.accumulate(eq)
    dd = (running_peak - eq)/running_peak
    trough = int(np.argmax(dd))
    peak = int(np.argmax(eq[:trough+1]))
    maxdd = dd[trough]*100
    n_trades = trough - peak
    span = (times[trough]-times[peak]).days
    # worst single trade (by net) and its share of the drop
    seg = trs[peak:trough]
    worst = min(seg, key=lambda x: x["net"]) if seg else None
    losers = sum(1 for t in seg if t["net"] < 0)
    print(f"\n  === {sizing.upper()} sizing — worst drawdown anatomy ===")
    print(f"  Max drawdown      : -{maxdd:.0f}%")
    print(f"  Peak  ${eq[peak]:,.0f} on {times[peak]:%Y-%m-%d}")
    print(f"  Trough ${eq[trough]:,.0f} on {times[trough]:%Y-%m-%d}")
    print(f"  It took           : {n_trades} trades over {span} days ({losers} of them losers)")
    if worst:
        print(f"  Worst SINGLE trade: {worst['net']:+.2f}% ({worst['symbol']} {worst['side']}) "
              f"on {worst['time']:%Y-%m-%d}")
        print(f"  -> So the -{maxdd:.0f}% is {'ONE big loss' if abs(worst['net'])>maxdd*0.6 else 'an ACCUMULATED bleed across many trades, not one shot'}.")

def main():
    print("Worst-drawdown anatomy | BTC+DOGE+HYPE | plain stops | long+short")
    analyze("full")
    analyze("risk1")

if __name__ == "__main__":
    main()
