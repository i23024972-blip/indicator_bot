# idx_paper_ride.py — LIVE PAPER-TRADING engine · DONCH50+200 (anti-manipulation, Eric's pick).
# Run once a day after the IDX close. Presents each day's signals as OPTIONS you can take,
# manages open positions, and tracks paper equity forward so you can prove execution.
#
# Strategy (validated, robust, hard to fake): konglo universe · SIGNAL = close breaks above
# the 50-day high WHILE above the 200-day MA (a real sustained-trend breakout an MM can't
# manufacture) → buy-stop 0.5% above the signal-day high (only fills if it confirms) · ride
# while above the 50 EMA · exit on a close below the 50 EMA OR a 4-ATR chandelier trail.
# Sizing: 20% per position, max 5 concurrent.
#
# State persists in idx_paper_state.json. Telegram optional (IDX_TG_*).
import os, sys, json, time
import pandas as pd
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

# ── config (matches the validated binary-ride backtest) ──
TRIG_BUF   = 0.005        # buy-stop sits 0.5% above the signal-day high
MAXGAP     = 0.04         # skip the fill if it gaps > 4% past the signal high
EMA_LEN    = 50           # ride while above this EMA; exit on a close below it
TRAIL_ATR  = 4.0          # chandelier trailing stop = peak - 4*ATR
INIT_ATR   = 2.5          # initial protective stop
DONCH      = 50           # signal = close breaks the prior 50-day high (while > 200MA)
MAX_POS    = 5
SIZE_FRAC  = 0.20         # 20% of equity per position
ACCOUNT    = 16_000_000   # Rp starting paper capital
PENDING_TTL= 3            # a buy-stop expires if not filled within N sessions
STATE_FILE = os.path.join(os.path.dirname(__file__), "idx_paper_state.json")

def notify(text):
    tok, chat = os.getenv("IDX_TG_TOKEN"), os.getenv("IDX_TG_CHAT")
    if not tok or not chat: return
    try: import requests
    except Exception: return
    for _ in range(4):
        try:
            if requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                             data={"chat_id": chat, "text": text}, timeout=30).ok:
                return
        except Exception: pass
        time.sleep(4)

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except Exception:
        return {"cash": ACCOUNT, "positions": {}, "pending": {}, "closed": [], "curve": []}

def save_state(s):
    with open(STATE_FILE, "w") as f: json.dump(s, f, indent=2, default=str)

def lots(rupiah, price):
    return int(rupiah // (price * 100))               # IDX lot = 100 shares

def prep(ticker):
    d, _ = K.get_eod(ticker + ".JK", period="2y")
    if d is None or len(d) < 260: return None
    d["atr"]    = K.atr_series(d)
    d["sma200"] = d["close"].rolling(200).mean()
    d["ema"]    = d["close"].ewm(span=EMA_LEN, adjust=False).mean()
    d["donch"]  = d["high"].rolling(DONCH).max().shift(1)   # prior 50-day high
    return d

def fire_donch(d, i):
    """DONCH50+200: close breaks the prior 50-day high while above the 200-day MA."""
    r = d.iloc[i]
    if pd.isna(r["donch"]) or pd.isna(r["sma200"]): return False
    return r["close"] > r["donch"] and r["close"] > r["sma200"]

def equity(state, lastpx):
    eq = state["cash"]
    for tk, p in state["positions"].items():
        eq += p["shares"] * lastpx.get(tk, p["entry"])
    return eq

def main():
    st = load_state()
    data = {t.replace(".JK",""): prep(t.replace(".JK","")) for t in K.all_tickers()}
    data = {k: v for k, v in data.items() if v is not None}
    today = max(v["time"].iloc[-1] for v in data.values()).date()
    lastpx = {k: float(v["close"].iloc[-1]) for k, v in data.items()}
    events = []

    # 1) MANAGE OPEN POSITIONS — trail + EMA-break exit
    for tk in list(st["positions"]):
        d = data.get(tk)
        if d is None: continue
        r = d.iloc[-1]; p = st["positions"][tk]
        p["peak"] = max(p.get("peak", p["entry"]), float(r["high"]))
        trail = p["peak"] - TRAIL_ATR * float(r["atr"])
        stop  = max(p["stop"], trail)
        p["stop"] = stop
        exit_now = float(r["low"]) <= stop or float(r["close"]) < float(r["ema"])
        if exit_now:
            px = stop if float(r["low"]) <= stop else float(r["close"])
            pnl = (px - p["entry"]) / p["entry"] * 100
            st["cash"] += p["shares"] * px
            st["closed"].append({"ticker": tk, "entry_date": p["entry_date"], "exit_date": str(today),
                                 "entry": p["entry"], "exit": px, "pnl_pct": round(pnl,1)})
            events.append(f"🚪 EXIT {tk} @ {px:,.0f}  ({pnl:+.1f}%)  — {'trail/stop' if float(r['low'])<=stop else 'EMA break'}")
            del st["positions"][tk]

    # 2) FILL PENDING BUY-STOPS — confirmation breakout
    for tk in list(st["pending"]):
        d = data.get(tk)
        if d is None: del st["pending"][tk]; continue
        r = d.iloc[-1]; pend = st["pending"][tk]; pend["age"] = pend.get("age",0) + 1
        trig = pend["trigger"]
        gapped = float(r["open"]) > pend["signal_high"] * (1 + MAXGAP)
        if not gapped and (float(r["open"]) >= trig or float(r["high"]) >= trig):
            if len(st["positions"]) >= MAX_POS:
                events.append(f"⏭️  {tk} broke out but all {MAX_POS} slots full — skipped")
                del st["pending"][tk]; continue
            entry = max(float(r["open"]), trig)
            eq = equity(st, lastpx)
            budget = min(SIZE_FRAC * eq, st["cash"])
            shares = lots(budget, entry) * 100
            if shares <= 0:
                del st["pending"][tk]; continue
            st["cash"] -= shares * entry
            st["positions"][tk] = {"entry": entry, "entry_date": str(today), "shares": shares,
                                   "peak": entry, "stop": entry - INIT_ATR*float(r["atr"])}
            events.append(f"✅ ENTER {tk} @ {entry:,.0f}  ({shares:,} sh ≈ Rp{shares*entry/1e6:.1f}M)")
            del st["pending"][tk]
        elif pend["age"] >= PENDING_TTL:
            events.append(f"⌛ {tk} buy-stop expired (never confirmed)")
            del st["pending"][tk]

    # 3) SCAN FOR NEW SIGNALS — present as OPTIONS (arm a buy-stop for next session)
    for tk, d in data.items():
        if tk in st["positions"] or tk in st["pending"]: continue
        i = len(d) - 1
        r = d.iloc[i]
        if pd.isna(r["atr"]) or r["atr"] <= 0 or pd.isna(r["sma200"]) or pd.isna(r["donch"]): continue
        if fire_donch(d, i):
            st["pending"][tk] = {"signal_date": str(today), "signal_high": float(r["high"]),
                                 "trigger": float(r["high"]) * (1+TRIG_BUF),
                                 "atr": float(r["atr"]), "age": 0}
            events.append(f"🎯 NEW SIGNAL {tk}: broke its 50-day high (above 200MA)")

    eq = equity(st, lastpx)
    st["curve"].append([str(today), round(eq)])
    save_state(st)

    # ── report ──
    L = [f"📒 PAPER RIDE · {today}", "━"*22]
    L.append(f"Equity: Rp {eq:,.0f}  ({(eq/ACCOUNT-1)*100:+.1f}% from Rp {ACCOUNT:,.0f})")
    L.append(f"Cash: Rp {st['cash']:,.0f}  ·  Open: {len(st['positions'])}/{MAX_POS}  ·  Armed: {len(st['pending'])}")
    if st["positions"]:
        L.append("\nOpen positions:")
        for tk, p in st["positions"].items():
            cur = lastpx.get(tk, p["entry"]); upl = (cur-p["entry"])/p["entry"]*100
            L.append(f"  {tk:6} entry {p['entry']:,.0f} · now {cur:,.0f} ({upl:+.1f}%) · stop {p['stop']:,.0f}")
    if events:
        L.append("\nToday:")
        L += [f"  {e}" for e in events]
    else:
        L.append("\nNo actions today.")

    # ── SIGNAL OPTIONS — the choices you can take next session ──
    if st["pending"]:
        free = MAX_POS - len(st["positions"])
        L.append(f"\n📋 SIGNAL OPTIONS  (place these buy-stops next session · {free} slot(s) free):")
        for n, (tk, pend) in enumerate(st["pending"].items(), 1):
            trig = pend["trigger"]; a = pend.get("atr", 0)
            stop = trig - INIT_ATR * a
            sh   = lots(SIZE_FRAC * eq, trig) * 100
            riskpct = (trig - stop) / trig * 100 if trig else 0
            L.append(f"  {n}) {tk:6} BUY-STOP @ {trig:,.0f} · stop {stop:,.0f} (−{riskpct:.0f}%) · "
                     f"size ~Rp {sh*trig/1e6:.1f}M ({sh:,} sh)")
        L.append("  → it only fills IF the stock trades up through the buy-stop (confirmation).")
    if st["closed"]:
        wins = [c for c in st["closed"] if c["pnl_pct"]>0]
        L.append(f"\nClosed: {len(st['closed'])} · win {len(wins)/len(st['closed'])*100:.0f}% "
                 f"· avg {sum(c['pnl_pct'] for c in st['closed'])/len(st['closed']):+.1f}%")
    report = "\n".join(L)
    print(report)
    if events:
        notify(report)

if __name__ == "__main__":
    main()
