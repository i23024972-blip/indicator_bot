# scenario_beplus.py
# A TRANSPARENT, hand-built scenario to show WHEN stop-loss-plus helps vs hurts.
# We send the SAME price paths through two exit rules and tally $ on $100 per trade.
#   PLAIN : fixed TP +4 ATR, SL -1.5 ATR.
#   BE+   : same, but once price runs +TRIGGER ATR in favor, move stop to entry+LOCK ATR
#           (LOCK chosen to COVER FEES -> a stopped trade nets ~breakeven, not a loss).
# All trades here are LONGs for clarity. ATR is treated as 1% of price.

STAKE   = 100.0     # $ per trade (no compounding, so the comparison is clean)
FEE     = 0.20      # round-trip fee % (spot long)
TP      = 4.0       # take-profit in ATR
SL      = 1.5       # stop-loss in ATR
TRIGGER = 1.0       # move stop after price runs this many ATR our way
LOCK    = 0.3       # lock this many ATR (0.3% > 0.20% fee, so it truly covers fees)

# Each scenario = ordered list of price levels (in ATR from entry, +up/-down) the price visits.
# Think of it as the path the candle prints, step by step.
SCENARIOS = [
    ("straight to SL (never went up)",        [-0.5, -1.0, -1.5]),
    ("up a bit, then reverses to SL",         [+1.2, +0.4, -0.5, -1.5]),
    ("dips, then runs straight to TP",        [-0.7, +1.5, +3.0, +4.0]),
    ("up to trigger, pulls back, THEN to TP", [+1.3, +0.2, +1.0, +2.5, +4.0]),
    ("up to trigger, pulls back, then to SL", [+1.4, +0.1, -0.8, -1.5]),
    ("chops up to +2, falls all the way back",[+0.8, +2.0, +0.5, -0.5, -1.5]),
    ("clean winner, no pullback",             [+1.5, +2.5, +4.0]),
    ("clean loser, small bounce only",        [-0.6, +0.3, -0.9, -1.5]),
]

def run_path(path, use_beplus):
    """Walk the price path; return realized P&L in ATR (before fee)."""
    sl = -SL; tp = +TP; moved = False
    for p in path:
        # stop check (price touches level p)
        if p <= sl:
            return sl
        if p >= tp:
            return tp
        if use_beplus and not moved and p >= TRIGGER:
            sl = +LOCK; moved = True   # stop-loss-plus: now locks a tiny profit
    # path ended without hitting TP/SL -> mark out at last price (open trade closed flat-ish)
    return path[-1]

def pnl_dollars(atr_result):
    # ATR = 1% of price; result is in ATR units -> % move = atr_result * 1.0%
    gross_pct = atr_result * 1.0
    return STAKE * (gross_pct - FEE) / 100.0

def main():
    print("SCENARIO: stop-loss-plus (covers fees) vs plain stop  |  $100/trade, long, ATR=1%")
    print(f"  TP +{TP} ATR | SL -{SL} ATR | BE+ trigger +{TRIGGER} ATR -> lock +{LOCK} ATR (>{FEE}% fee)\n")
    hdr = f"  {'scenario':<40} | {'PLAIN $':>9} | {'BE+ $':>9} | {'who wins':>9}"
    print(hdr); print("  "+"-"*(len(hdr)-2))
    tot_plain = tot_be = 0.0
    for name, path in SCENARIOS:
        rp = run_path(path, False); rb = run_path(path, True)
        dp = pnl_dollars(rp); db = pnl_dollars(rb)
        tot_plain += dp; tot_be += db
        who = "tie" if abs(dp-db) < 1e-9 else ("BE+ " if db > dp else "PLAIN")
        print(f"  {name:<40} | {dp:>+8.2f} | {db:>+8.2f} | {who:>9}")
    print("  "+"-"*(len(hdr)-2))
    print(f"  {'TOTAL (8 trades, $100 each)':<40} | {tot_plain:>+8.2f} | {tot_be:>+8.2f} | "
          f"{('BE+ ' if tot_be>tot_plain else 'PLAIN'):>9}")
    print(f"\n  Start $800 (8x$100)  ->  PLAIN ${800+tot_plain:,.2f}   |   BE+ ${800+tot_be:,.2f}")
    print("\n  Read it: BE+ WINS the 'went up then reversed' trades (saves them from a full loss),")
    print("  but LOSES the 'pulled back then ran to TP' trade (gets stopped at breakeven, misses +4).")
    print("  Which rule wins overall = how often each pattern happens in YOUR market.")

if __name__ == "__main__":
    main()
