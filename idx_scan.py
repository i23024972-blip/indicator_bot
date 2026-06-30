# idx_scan.py — LIVE daily scanner for the IDX konglo momentum strategy.
# Ties together everything we built and tested:
#   · Entry  = momentum COMBO: up-day + volume>=2.5x(20d) + close>50MA + bullish zigzag structure
#   · Sizing = REGIME-scaled: HEALTHY 25% / CAUTION 15% / CRASH 10%  (from IHSG structure)
#   · Fills  = tomorrow's OPEN (realistic); skip if it gaps >3%
#   · Exits  = stop 2xATR, target 6xATR; bot watches open trades and says when to sell
# Run ONCE a day after the IDX close (~16:15 WIB). Prints a table + pushes Telegram alerts.
#
# Telegram: set IDX_TG_TOKEN / IDX_TG_CHAT in .env (a NEW bot, separate from the crypto one).
import os, sys, json
import pandas as pd
import idx_konglo as K
import idx_signals as SIG
from idx_owners import backer_line, backer, STRENGTH_BONUS
from idx_regime import load_ihsg, SIZE_MULT

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

# ── Config ──
# Watchlist with liquidity tier (from idx_discover.py). Tier shown in signals so you know
# how big you can safely trade:  BIG >Rp100bn/day · MID 30–100bn · OKAY 10–30bn (size smaller).
WATCHLIST = {
    # 🟦 BIG liquidity — volatile movers, safe for full size
    "BREN": "BIG", "CUAN": "BIG", "PTRO": "BIG",
    "BRPT": "BIG", "DEWA": "BIG", "BUMI": "BIG", "ANTM": "BIG", "AMMN": "BIG",
    "RAJA": "BIG", "BNBR": "BIG", "TINS": "BIG", "INCO": "BIG", "BUVA": "BIG", "BIPI": "BIG",
    # 🟩 MID liquidity — solid
    "PANI": "MID", "WIFI": "MID", "NCKL": "MID", "JPFA": "MID", "VKTR": "MID", "INDY": "MID",
    # 🟨 OKAY liquidity — high conviction but trade smaller
    "NICL": "OKAY", "FORE": "OKAY", "MSIN": "OKAY", "ARKO": "OKAY", "EMTK": "OKAY",
    "MDIA": "OKAY",
    # (Banks BBCA/BMRI/BDMN removed — fired only ~2 signals in 3y; banks don't suit a
    #  momentum-spike strategy where the target assumes a 30%+ move.)
}
WATCH = list(WATCHLIST)
TIER_TAG = {"BIG": "🟦 big-liq", "MID": "🟩 mid-liq", "OKAY": "🟨 okay-liq"}
SPIKE_X   = 2.5
TREND_MA  = 50
SL_X, TP_X = 2.0, 6.0
T_STOP    = 3.0           # TREND-mode hard stop (×ATR); trend rides until 50MA break
STRATEGY  = "HYBRID"      # HYBRID = TREND in HEALTHY regime, COMBO in CAUTION/CRASH
BASE_SIZE = 0.25          # HEALTHY size; regime multiplier scales it down
ACCOUNT   = 16_000_000    # Rp — for position-size suggestions (edit to your capital)
GAP_SKIP  = 3.0           # skip a buy if tomorrow could gap > this % (advisory)
STATE_FILE = os.getenv("IDX_STATE_PATH") or os.path.join(os.path.dirname(__file__), "idx_scan_state.json")   # Fly: volume path

def notify(text):
    tok, chat = os.getenv("IDX_TG_TOKEN"), os.getenv("IDX_TG_CHAT")
    if not tok or not chat:
        return
    import time
    try:
        import requests
    except Exception as e:
        print(f"  (telegram skipped: {e})"); return
    # Telegram API can be flaky from some regions — retry a few times before giving up.
    for attempt in range(1, 5):
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              data={"chat_id": chat, "text": text}, timeout=30)
            if r.ok:
                return
            print(f"  (telegram HTTP {r.status_code} on try {attempt})")
        except Exception as e:
            print(f"  (telegram try {attempt} failed: {e})")
        time.sleep(5)
    print("  (telegram: gave up after 4 tries — signal is still in the log/console)")

def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except Exception:
        return {"positions": {}, "regime": None}

def save_state(s):
    with open(STATE_FILE, "w") as f: json.dump(s, f, indent=2)

def fmt(x):
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.1f}"

def lots(rupiah, price):
    return int(rupiah // (price * 100))   # IDX lot = 100 shares

# ── analyse one ticker for a fresh COMBO buy + manage any open trade ──
def analyse(ticker):
    d, w = K.get_eod(ticker + ".JK", period="2y")
    if d is None or len(d) < TREND_MA + 30 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(TREND_MA).mean()
    d["sma200"]= d["close"].rolling(200).mean()
    i = len(d) - 1
    atr = d["atr"].iloc[i]
    if pd.isna(atr) or atr <= 0 or pd.isna(d["volma"].iloc[i]) or pd.isna(d["sma50"].iloc[i]):
        return None

    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    sd = K.structure_at(zz_d, i)
    sw = K.structure_at(zz_w, len(w) - 1)

    close = d["close"].iloc[i]
    up    = close > d["close"].iloc[i - 1]
    volr  = d["volume"].iloc[i] / d["volma"].iloc[i]
    spike = volr >= SPIKE_X
    trend = close > d["sma50"].iloc[i]
    struct = sd in K.BULL and sw in K.BULL
    buy_signal = up and spike and trend and struct

    # ── TREND entry (for HYBRID in healthy regime): reclaim 50MA while 50MA>200MA ──
    sma200 = d["sma200"].iloc[i]
    trend_buy = (not pd.isna(sma200)
                 and close > d["sma50"].iloc[i] and d["close"].iloc[i-1] <= d["sma50"].iloc[i-1]
                 and d["sma50"].iloc[i] > sma200)

    # ── conviction 0-100: how close to / how strong a setup (for ranking + display) ──
    abv = (close / d["sma50"].iloc[i] - 1) * 100
    c_wk    = 25 if sw in K.BULL else 0                       # weekly trend agrees
    c_dy    = 25 if sd in K.BULL else 0                       # daily structure bullish
    c_trend = 20 if trend else (10 if abv > -3 else 0)        # above (or just under) 50MA
    c_vol   = min(30.0, volr / 3.0 * 30)                      # volume conviction (3x -> full)
    _, _, strength = backer(ticker)                           # tycoon-backing bonus (backtested)
    c_backer = STRENGTH_BONUS.get(strength, 0)
    conviction = min(100, round(c_wk + c_dy + c_trend + c_vol + c_backer))

    return dict(ticker=ticker, date=str(d["time"].iloc[i].date()), close=float(close),
                today_low=float(d["low"].iloc[i]), today_high=float(d["high"].iloc[i]),
                atr=float(atr), volr=float(volr), sd=sd, sw=sw, buy=bool(buy_signal),
                trend_buy=bool(trend_buy), sma50=float(d["sma50"].iloc[i]),
                conviction=conviction, abv_sma=float(abv),
                stop=float(close - SL_X * atr), target=float(close + TP_X * atr),
                trend_stop=float(close - T_STOP * atr))

# ── regime banner + change alert ──
def check_regime(st):
    # IHSG fetch can occasionally come back short/empty (yfinance hiccup); retry, then
    # fall back to last known regime so the scan still runs and reports buy signals.
    ix = None
    for _ in range(3):
        try:
            cand = load_ihsg(period="2y")   # short range = far more reliable than "max"
            if cand is not None and len(cand) > 250:
                ix = cand; break
        except Exception:
            pass
    if ix is None:
        last = st.get("regime") or "CAUTION"      # safe default: trade cautiously
        print(f"  (IHSG data unavailable — using last known regime: {last})")
        return last, SIZE_MULT[last], BASE_SIZE*SIZE_MULT[last]*100, None, None
    r = ix.iloc[-1]
    reg = str(r["regime"]); mult = SIZE_MULT[reg]; size_pct = BASE_SIZE * mult * 100
    alert = None
    if st.get("regime") and st["regime"] != reg:
        prev = st["regime"]
        emoji = {"HEALTHY": "🟢", "CAUTION": "⚠️", "CRASH": "🔴"}[reg]
        alert = (f"{emoji} REGIME CHANGE — {ix.index[-1].date()}\n"
                 f"IHSG {fmt(r['close'])} · {r['dd']:+.0f}% off highs · vol {r['vol20']:.0f}%\n"
                 f"{prev} → {reg}\n"
                 f"👉 Position size now {size_pct:.0f}% per trade")
        if reg == "CRASH":
            alert += "\n💀 Structure matches 2008/COVID — defensive: fewer positions, more cash."
    st["regime"] = reg
    return reg, mult, size_pct, alert, r

def bar(pct):
    """5-block conviction bar, e.g. 72 -> ▓▓▓▓░"""
    filled = int(round(pct / 100 * 5))
    return "▓" * filled + "░" * (5 - filled)

REG_EMOJI = {"HEALTHY": "🟢", "CAUTION": "🟡", "CRASH": "🔴"}

def main():
    st = load_state()
    reg, mult, size_pct, reg_alert, ihsg = check_regime(st)
    date = pd.Timestamp.now().strftime("%d %b %Y")

    sigs = SIG.load()
    buys, closed, cands = [], [], []
    for t in WATCH:
        try:
            a = analyse(t)
        except Exception:
            continue
        if a is None:
            continue
        cands.append(a)

        # ── manage an OPEN signal: combo exits on target/stop; trend rides until 50MA break ──
        s = sigs.get(t)
        if s and s.get("status") == "open":
            stype = s.get("type", "combo")
            if stype == "trend":
                if a["today_low"] <= s["stop"]:
                    s["status"] = "hit_sl"; s["exit"] = s["stop"]; s["exit_date"] = a["date"]
                    pct = (s["stop"]/s["entry"]-1)*100
                    closed.append(f"🛑 {t} hit STOP {fmt(s['stop'])}  (entry {fmt(s['entry'])}, {pct:+.0f}%)\n"
                                  f"   👉 Reply:  {t} <lots>   (or  {t} 0)")
                elif a["close"] < a["sma50"]:        # trend break = exit
                    s["status"] = "hit_sl"; s["exit"] = a["close"]; s["exit_date"] = a["date"]
                    pct = (a["close"]/s["entry"]-1)*100
                    closed.append(f"📉 {t} TREND BROKE — closed below 50MA @ {fmt(a['close'])}  "
                                  f"(entry {fmt(s['entry'])}, {pct:+.0f}%)\n   👉 Reply:  {t} <lots>   (or  {t} 0)")
            else:                                     # combo
                if a["today_high"] >= s["target"]:
                    s["status"] = "hit_tp"; s["exit"] = s["target"]; s["exit_date"] = a["date"]
                    pct = (s["target"]/s["entry"]-1)*100
                    closed.append(f"✅ {t} hit TARGET {fmt(s['target'])}  (entry {fmt(s['entry'])}, {pct:+.0f}%)\n"
                                  f"   👉 Reply:  {t} <lots>   (or  {t} 0  if you skipped)")
                elif a["today_low"] <= s["stop"]:
                    s["status"] = "hit_sl"; s["exit"] = s["stop"]; s["exit_date"] = a["date"]
                    pct = (s["stop"]/s["entry"]-1)*100
                    closed.append(f"🛑 {t} hit STOP {fmt(s['stop'])}  (entry {fmt(s['entry'])}, {pct:+.0f}%)\n"
                                  f"   👉 Reply:  {t} <lots>   (or  {t} 0  if you skipped)")

        # ── fresh buy signal — HYBRID: TREND entry in HEALTHY regime, else COMBO ──
        mode = "trend" if (STRATEGY == "HYBRID" and reg == "HEALTHY") else "combo"
        fire = a["trend_buy"] if mode == "trend" else a["buy"]
        if fire and t not in sigs:
            entry = a["close"]
            liq = TIER_TAG.get(WATCHLIST.get(t, "MID"), "")
            bk = backer_line(t)
            backer_str = f"   Backer   : {bk}\n" if bk else ""
            if mode == "trend":
                buys.append(
                    f"🔥 BUY (TREND)  {t}   conviction {a['conviction']}%  {bar(a['conviction'])}  {liq}\n"
                    f"{backer_str}"
                    f"   Position : {size_pct:.0f}% of account  ({reg} regime — ride the trend)\n"
                    f"   Entry    : ~{fmt(entry)}  (buy at tomorrow's open)\n"
                    f"   Stop     : {fmt(a['trend_stop'])}  ({(a['trend_stop']/entry-1)*100:+.0f}%)\n"
                    f"   Exit     : when it closes below 50MA (ride winners — no fixed target)\n"
                    f"   ⏳ skip if gap >{GAP_SKIP:.0f}%")
                sigs[t] = {"entry": float(entry), "stop": a["trend_stop"], "target": 9e12,
                           "type": "trend", "date": a["date"], "status": "open"}
            else:
                buys.append(
                    f"🔥 BUY  {t}   conviction {a['conviction']}%  {bar(a['conviction'])}  {liq}\n"
                    f"{backer_str}"
                    f"   Position : {size_pct:.0f}% of account  ({reg} regime)\n"
                    f"   Entry    : ~{fmt(entry)}  (buy at tomorrow's open)\n"
                    f"   Stop     : {fmt(a['stop'])}  ({(a['stop']/entry-1)*100:+.0f}%)\n"
                    f"   Target   : {fmt(a['target'])}  ({(a['target']/entry-1)*100:+.0f}%)\n"
                    f"   Volume   : {a['volr']:.1f}× avg  ·  skip if gap >{GAP_SKIP:.0f}%")
                sigs[t] = {"entry": float(entry), "stop": a["stop"], "target": a["target"],
                           "type": "combo", "date": a["date"], "status": "open"}

    SIG.save(sigs)
    save_state(st)

    # ── build the tidy message ──
    top = sorted(cands, key=lambda x: x["conviction"], reverse=True)[:5]
    L = []
    L.append(f"📅  IDX KONGLO SCAN · {date}")
    L.append("━━━━━━━━━━━━━━━━━━━━")
    mode_now = "TREND (ride)" if (STRATEGY == "HYBRID" and reg == "HEALTHY") else "COMBO (swing)"
    if ihsg is not None:
        L.append(f"{REG_EMOJI[reg]} Regime: {reg}  ·  {STRATEGY} → {mode_now}  ·  size {size_pct:.0f}%")
        L.append(f"   IHSG {fmt(ihsg['close'])}  ({ihsg['dd']:+.0f}% off highs)")
    else:
        L.append(f"{REG_EMOJI[reg]} Regime: {reg} (last known)  ·  size {size_pct:.0f}%")
    L.append("━━━━━━━━━━━━━━━━━━━━")

    L.append("📊  Top candidates")
    for r in top:
        tag = ("🔥 BUY " if r["buy"] else
               ("👀 watch" if r["conviction"] >= 60 else "·  wait"))
        liq = TIER_TAG.get(WATCHLIST.get(r["ticker"], "MID"), "")
        L.append(f"{r['ticker']:5} {bar(r['conviction'])} {r['conviction']:>3}%  {tag}  {liq}")
    L.append("━━━━━━━━━━━━━━━━━━━━")

    if closed:
        L.append("🔔  Signal closed — tell me your lots")
        L += closed
        L.append("━━━━━━━━━━━━━━━━━━━━")
    if buys:
        L.append("🎯  BUY signals")
        L.append("")
        L.append("\n\n".join(buys))
    else:
        L.append("No buy signals today.")
        if reg == "CRASH":
            L.append("Defensive regime — sitting in cash is correct.")
    open_sigs = [t for t, s in sigs.items() if s.get("status") == "open"]
    if open_sigs:
        L.append("━━━━━━━━━━━━━━━━━━━━")
        L.append("Active signals: " + ", ".join(open_sigs))

    body = "\n".join(L)
    print(body)
    if reg_alert:
        notify(reg_alert)
    notify(body)

if __name__ == "__main__":
    main()
