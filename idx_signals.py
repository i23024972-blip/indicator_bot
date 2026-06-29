# idx_signals.py — shared store linking the daily scan and the Telegram journal.
# The scan writes BUY signals here (entry/stop/target). When price hits target or stop,
# the scan marks the signal "closed" and the journal asks you how many lots you bought,
# then computes the actual rupiah P&L (entry & exit prices are already known).
import os, json

HERE    = os.path.dirname(os.path.abspath(__file__))
SIGFILE = os.path.join(HERE, "signals.json")
LOT     = 100
FEE_BUY, FEE_SELL = 0.0015, 0.0025

def load():
    try:
        with open(SIGFILE) as f: return json.load(f)
    except Exception:
        return {}

def save(d):
    with open(SIGFILE, "w") as f: json.dump(d, f, indent=2)

def pnl(entry, exit_price, lots):
    """Return (rupiah_pnl, pct, cost, gross, fee) for `lots` lots, net of buy+sell fees."""
    shares = lots * LOT
    cost   = entry * shares
    gross  = exit_price * shares
    fee    = cost * FEE_BUY + gross * FEE_SELL
    p      = gross - cost - fee
    return p, (p / cost * 100 if cost else 0), cost, gross, fee
