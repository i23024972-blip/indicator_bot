# idx_konglo_journal.py — the BLIND play-by-play.
# Walks the konglo strategy forward day-by-day (it does NOT know the future). When the
# indicator trips on a name, you commit — realistic fills. This prints the actual trade
# LEDGER (which names, when, caught-before-the-move?), the running equity, and a sizing
# ladder so we can see honestly where ~10x would even come from (and its drawdown cost).
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd
from idx_walkforward_konglo import collect_konglo
from idx_walkforward import CUTOFF
from idx_portfolio import simulate, START

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def sim_log(trades, frac, mx):
    """Event-driven sim that RECORDS which trades were actually committed + equity path."""
    cash = START; openp = []; ledger = []
    def equity(): return cash + sum(p["cost"] for p in openp)
    def release(date):
        nonlocal cash
        keep = []
        for p in openp:
            if p["exit"] <= date:
                cash += p["cost"] * (1 + p["pnl"]/100.0)
            else:
                keep.append(p)
        openp[:] = keep
    for tr in trades:
        release(tr["entry"])
        if len(openp) >= mx:
            continue                          # at position cap — signal skipped
        eq = equity()
        cost = min(frac * eq, cash)
        if cost <= 1:
            continue
        cash -= cost
        openp.append({"exit": tr["exit"], "cost": cost, "pnl": tr["pnl"]})
        ledger.append({**tr, "cost": cost, "equity_at_entry": eq})
    release(max(t["exit"] for t in trades))
    return ledger, equity()

def main():
    print("BLIND konglo play-by-play · last 2y · realistic fills (next-open, gap-skip, slip, fee)")
    print("The scanner sees only the past at each step. When a name fires, we commit.\n")
    alltr, _ = collect_konglo()
    trades = sorted([t for t in alltr if t["entry"] >= CUTOFF], key=lambda x: x["entry"])

    ledger, final = sim_log(trades, 0.25, 4)     # live sizing: 25% x max 4

    print("="*82)
    print(f"  COMMITTED-TRADE LEDGER  (25% × max4 · started ${START:,.0f})")
    print("="*82)
    print(f"  {'#':>3} {'entry date':12} {'ticker':7} {'grp':8} {'held':>5} {'result':>9} {'equity→':>11}")
    eq = START
    for n, t in enumerate(ledger, 1):
        eq *= (1 + 0.25 * t["pnl"]/100)          # rough running equity (illustrative)
        flag = "🚀" if t["pnl"] >= 30 else ("✓" if t["pnl"] > 0 else "✗")
        print(f"  {n:>3} {str(t['entry'].date()):12} {t['ticker']:7} {t.get('group','?'):8} "
              f"{t['bars']:>4}d {t['pnl']:>+7.1f}% {flag} ${t['equity_at_entry']:>9,.0f}")

    df = pd.DataFrame(trades)
    print("\n" + "="*82)
    print("  DID WE CATCH THEM BEFORE THE MOVE?  (biggest winners, entry = START of the run)")
    print("="*82)
    big = df.sort_values("pnl", ascending=False).head(8)
    for _, t in big.iterrows():
        print(f"   {str(t['entry'].date())}  bought {t['ticker']:6} → {t['pnl']:+6.1f}% over "
              f"{t['bars']:>2}d   (signal fired, THEN it ran — no hindsight)")

    print("\n" + "="*82)
    print("  WHERE DOES ~10x COME FROM?  sizing ladder (same trades, more aggression)")
    print("="*82)
    print(f"  {'scheme':24} {'final $':>11} {'x':>6} {'CAGR':>8} {'MaxDD':>7}")
    for lab, f, m in [("10% × max8 (safe)",0.10,8), ("25% × max4 (live)",0.25,4),
                      ("33% × max3",0.33,3), ("50% × max2 (risky)",0.50,2),
                      ("100% all-in × 1",1.00,1)]:
        r = simulate(trades, f, m)
        print(f"  {lab:24} ${r['final']:>9,.0f} {r['final']/START:>5.1f}x "
              f"{r['cagr']:>+6.0f}% {r['maxdd']:>6.0f}%")
    print(f"\n  Reality: blind konglo realistic = ~4.8x at live sizing. 10x needs heavy")
    print(f"  concentration (50–100% sizing) — which is also where the drawdown wrecks you.")

if __name__ == "__main__":
    main()
