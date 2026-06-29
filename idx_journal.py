# idx_journal.py — Telegram trade journal. You type trades in chat with @ususkonglobot;
# this logs them to an Excel-openable CSV and tracks open positions + realised P&L.
#
# Message format (forgiving, case-insensitive):
#   buy  BRPT 1580 22        -> bought 22 lots of BRPT @ 1580
#   sell BRPT 1750 22        -> sold 22 lots (FIFO-matched to open buys, computes P&L)
#   buy  BRPT 1580 22 swing entry on volume spike   -> trailing words = note
#   report        -> bot replies open positions + realised P&L so far
#   help          -> usage
#
# IDX lot = 100 shares. Fees: 0.15% buy / 0.25% sell (matches the strategy assumption).
# Runs as a long-poll loop; must be running to capture messages. Auto-restart-safe
# (persists the Telegram update offset + open positions).
import os, sys, csv, json, time
from datetime import datetime
import idx_signals as SIG

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

HERE   = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "trades_journal.csv")
STATE  = os.path.join(HERE, "journal_state.json")
TOKEN  = os.getenv("IDX_TG_TOKEN")
CHAT   = os.getenv("IDX_TG_CHAT")
LOT    = 100
FEE_BUY, FEE_SELL = 0.0015, 0.0025

LEDGER_COLS = ["time", "action", "ticker", "price", "lots", "shares",
               "gross_rupiah", "fee_rupiah", "realised_pnl", "pnl_pct", "note"]

# ── parsing (pure function, unit-testable) ──
def parse(text):
    """Return ('buy'|'sell', ticker, price, lots, note) or ('cmd', name,...) or ('error', msg)."""
    if not text or not text.strip():
        return ("error", "empty message")
    parts = text.strip().split()
    head = parts[0].lower().lstrip("/")
    if head in ("report", "r", "status"):   return ("cmd", "report")
    if head in ("help", "start", "h"):      return ("cmd", "help")
    if head in ("buy", "b", "sell", "s"):
        action = "buy" if head in ("buy", "b") else "sell"
        if len(parts) < 4:
            return ("error", f"need: {action} TICKER PRICE LOTS  (e.g. {action} BRPT 1580 22)")
        ticker = parts[1].upper().replace(".JK", "")
        try:
            price = float(parts[2].replace(",", ""))
            lots  = int(float(parts[3]))
        except ValueError:
            return ("error", "price/lots not a number. e.g. buy BRPT 1580 22")
        if price <= 0 or lots <= 0:
            return ("error", "price and lots must be positive")
        note = " ".join(parts[4:]) if len(parts) > 4 else ""
        return (action, ticker, price, lots, note)
    return ("error", "unknown. use: buy / sell / report / help")

# ── ledger + position state ──
def load_state():
    try:
        with open(STATE) as f: return json.load(f)
    except Exception:
        return {"offset": 0, "open": {}, "realised": 0.0}

def save_state(s):
    with open(STATE, "w") as f: json.dump(s, f, indent=2)

def append_ledger(row):
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        if new: w.writeheader()
        w.writerow(row)

def record_buy(st, ticker, price, lots, note):
    shares = lots * LOT
    gross  = price * shares
    fee    = gross * FEE_BUY
    st["open"].setdefault(ticker, []).append({"price": price, "lots": lots})
    append_ledger({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "BUY",
                   "ticker": ticker, "price": price, "lots": lots, "shares": shares,
                   "gross_rupiah": round(gross), "fee_rupiah": round(fee),
                   "realised_pnl": "", "pnl_pct": "", "note": note})
    return f"✅ Logged BUY {lots} lots {ticker} @ {price:,.0f}  (Rp {gross:,.0f} + fee {fee:,.0f})"

def record_sell(st, ticker, price, lots, note):
    queue = st["open"].get(ticker, [])
    if not queue:
        # log it anyway, but warn — no matching open position
        shares = lots * LOT; gross = price * shares; fee = gross * FEE_SELL
        append_ledger({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "SELL",
                       "ticker": ticker, "price": price, "lots": lots, "shares": shares,
                       "gross_rupiah": round(gross), "fee_rupiah": round(fee),
                       "realised_pnl": "", "pnl_pct": "", "note": note + " [no open buy matched]"})
        return f"⚠️ Logged SELL {lots} {ticker} @ {price:,.0f} but no open BUY on record — check it."
    remaining = lots; cost_basis = 0.0; matched = 0
    while remaining > 0 and queue:
        lot0 = queue[0]
        take = min(remaining, lot0["lots"])
        cost_basis += lot0["price"] * take * LOT
        lot0["lots"] -= take; remaining -= take; matched += take
        if lot0["lots"] == 0: queue.pop(0)
    if not queue: st["open"].pop(ticker, None)
    sold_shares = matched * LOT
    gross   = price * sold_shares
    buy_fee = cost_basis * FEE_BUY
    sell_fee= gross * FEE_SELL
    pnl     = gross - cost_basis - buy_fee - sell_fee
    pnl_pct = pnl / cost_basis * 100 if cost_basis else 0
    st["realised"] = st.get("realised", 0.0) + pnl
    append_ledger({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "SELL",
                   "ticker": ticker, "price": price, "lots": matched, "shares": sold_shares,
                   "gross_rupiah": round(gross), "fee_rupiah": round(sell_fee),
                   "realised_pnl": round(pnl), "pnl_pct": round(pnl_pct, 1), "note": note})
    emoji = "🟢" if pnl >= 0 else "🔴"
    extra = "" if remaining == 0 else f"  (only {matched} lots matched open buys; {remaining} extra)"
    return (f"{emoji} Logged SELL {matched} {ticker} @ {price:,.0f}\n"
            f"P&L: Rp {pnl:,.0f} ({pnl_pct:+.1f}%) net of fees{extra}")

def report(st):
    lines = ["📒 TRADE JOURNAL"]
    if st["open"]:
        lines.append("\nOpen positions:")
        for t, q in st["open"].items():
            tot = sum(l["lots"] for l in q)
            avg = sum(l["price"]*l["lots"] for l in q)/tot if tot else 0
            lines.append(f"  • {t}: {tot} lots @ avg {avg:,.0f}")
    else:
        lines.append("\nNo open positions.")
    lines.append(f"\nRealised P&L so far: Rp {st.get('realised',0):,.0f}")
    lines.append(f"Ledger: trades_journal.csv")
    return "\n".join(lines)

HELP = ("📝  TRADE JOURNAL\n"
        "━━━━━━━━━━━━━━━━\n"
        "Log a buy:\n"
        "   buy  BRPT 1580 22\n"
        "Log a sell:\n"
        "   sell BRPT 1750 22\n"
        "Add a note:\n"
        "   buy  DEWA 326 50 swing entry\n"
        "━━━━━━━━━━━━━━━━\n"
        "   report  ·  open positions + P&L\n"
        "   help    ·  this menu\n"
        "━━━━━━━━━━━━━━━━\n"
        "format:  action  ticker  price  lots\n"
        "1 lot = 100 shares · fees auto-applied")

def resolve_closed(text):
    """If text is '<TICKER> <lots>' and that ticker's scan signal has hit TP/SL,
    finalise it: compute rupiah P&L from the known entry & exit and log it.
    Returns a reply string, or None if this message isn't a lots-reply."""
    parts = text.strip().split()
    if len(parts) != 2:
        return None
    ticker = parts[0].upper().replace(".JK", "")
    try:
        n_lots = int(float(parts[1]))
    except ValueError:
        return None
    sigs = SIG.load()
    s = sigs.get(ticker)
    if not s or s.get("status") not in ("hit_tp", "hit_sl"):
        return None
    outcome = "TARGET" if s["status"] == "hit_tp" else "STOP"
    if n_lots <= 0:                                   # user skipped the trade
        sigs.pop(ticker, None); SIG.save(sigs)
        return f"👍 {ticker} {outcome} noted as not taken — nothing logged."
    p, pct, cost, gross, fee = SIG.pnl(s["entry"], s["exit"], n_lots)
    append_ledger({"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "action": "TRADE",
                   "ticker": ticker, "price": s["exit"], "lots": n_lots, "shares": n_lots*SIG.LOT,
                   "gross_rupiah": round(gross), "fee_rupiah": round(fee),
                   "realised_pnl": round(p), "pnl_pct": round(pct, 1),
                   "note": f"entry {s['entry']:.0f} -> exit {s['exit']:.0f} ({outcome})"})
    sigs.pop(ticker, None); SIG.save(sigs)
    emoji = "🟢" if p >= 0 else "🔴"
    return (f"{emoji} {ticker} closed at {outcome}  ({pct:+.1f}%)\n"
            f"Bought {n_lots} lots @ {s['entry']:,.0f} → exit {s['exit']:,.0f}\n"
            f"{'Profit' if p>=0 else 'Loss'}: Rp {p:,.0f}  (net of fees)")

def handle(text, st):
    closed = resolve_closed(text)        # check the ask-for-lots flow first
    if closed:
        return closed
    p = parse(text)
    kind = p[0]
    if kind == "buy":   return record_buy(st, p[1], p[2], p[3], p[4])
    if kind == "sell":  return record_sell(st, p[1], p[2], p[3], p[4])
    if kind == "cmd":
        return report(st) if p[1] == "report" else HELP
    return f"❓ {p[1]}\n\n{HELP}"

# ── Telegram long-poll loop ──
def send(text):
    import requests
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          data={"chat_id": CHAT, "text": text}, timeout=30); return
        except Exception:
            time.sleep(3)

def main():
    if not TOKEN or not CHAT:
        print("Missing IDX_TG_TOKEN / IDX_TG_CHAT in .env"); return
    import requests
    st = load_state()
    print(f"Trade journal listening… ledger: {LEDGER}")
    send("📝 Trade journal is ON. Type 'help' for commands.")
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                             params={"offset": st["offset"] + 1, "timeout": 30}, timeout=40)
            for upd in r.json().get("result", []):
                st["offset"] = upd["update_id"]
                msg = upd.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(CHAT):
                    continue
                text = msg.get("text", "")
                if not text: continue
                reply = handle(text, st)
                save_state(st)
                send(reply)
                print(f"  {text!r} -> logged")
        except Exception as e:
            print(f"  loop error: {e}; retrying in 10s")
            time.sleep(10)

if __name__ == "__main__":
    main()
