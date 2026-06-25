# bot_zigzag_paper.py
# PAPER-TRADING bot for the backtested ZigZag strategy (NO real orders, fake money).
#   Strategy : 4H bias + 30M entry, causal %-deviation ZigZag (dev 5%), structure HH/HL/LH/LL,
#              TP 4xATR / SL 1.5xATR, LONG (spot) + SHORT (futures 1x).
#   Sizing   : fires EVERY signal — up to one position per coin at once (BTC/DOGE/HYPE).
#   Goal     : run live on the real market with a virtual $1000 account to confirm the edge is
#              alive NOW before risking real money. Sends clean Telegram + PC alerts marked [PAPER].
#
# Run:  python bot_zigzag_paper.py     then press /start in Telegram.
import os, json, csv, asyncio, time
from dotenv import load_dotenv
load_dotenv()  # read secrets from a local .env file (never committed)
import pandas as pd
from datetime import datetime, timezone
from binance.client import Client
try:
    import winsound
except Exception:
    winsound = None
try:
    from plyer import notification
except Exception:
    notification = None
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ─── SETTINGS ────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]   # set in .env (see .env.example)
CHAT_ID        = os.environ["CHAT_ID"]

SYMBOLS = [("BTCUSDT", False), ("DOGEUSDT", False), ("HYPEUSDT", True)]  # (symbol, is_futures_feed)
BIAS_INTERVAL  = Client.KLINE_INTERVAL_4HOUR
ENTRY_INTERVAL = Client.KLINE_INTERVAL_30MINUTE
KLINE_LIMIT    = 1000          # candles pulled per scan (enough for ZigZag pivots + ATR)

DEVIATION      = 5.0           # ZigZag % reversal to confirm a pivot
ATR_TP, ATR_SL = 4.0, 1.5      # take-profit / stop-loss in ATR
FRESH_ONLY     = True          # only fire when structure label first flips (no re-firing)

LONG_FEE, SHORT_FEE = 0.20, 0.10   # round-trip % (spot long / futures-1x short)
PAPER_START    = 1000.0        # virtual account size $
POS_FRAC       = 1.0/len(SYMBOLS)   # share of account per position (3 coins -> ~33% each)
CHECK_EVERY    = 600           # seconds between scans (10 min; new 30m candle every 30 min)
HEARTBEAT_EVERY= 14400         # status ping every 4 hours (less notification spam)

STATE_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_state.json")
TRADES_CSV  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trades.csv")

client = Client()
bot    = Bot(token=TELEGRAM_TOKEN)
BULL = ("HH+HL", "HL"); BEAR = ("LL+LH", "LH")

is_running = False
last_heartbeat = 0
# positions = list of open paper trades (max one per symbol)
STATE = {"balance": PAPER_START, "positions": [], "prev_struct": {},
         "wins": 0, "losses": 0, "started": None, "active": False}

# ─── PERSISTENCE ─────────────────────────────────────
def load_state():
    global STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: STATE = json.load(f)
            STATE.setdefault("positions", []); STATE.setdefault("wins", 0)
            STATE.setdefault("losses", 0); STATE.setdefault("prev_struct", {})
            STATE.setdefault("active", False)
        except Exception as e: print(f"state load failed: {e}")

def save_state():
    try:
        with open(STATE_FILE, "w") as f: json.dump(STATE, f, indent=2, default=str)
    except Exception as e: print(f"state save failed: {e}")

def log_trade(row):
    new = not os.path.exists(TRADES_CSV)
    with open(TRADES_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["closed_at","symbol","side","entry","exit","reason",
                            "net_pct","balance_after"])
        w.writerow(row)

# ─── DATA + INDICATORS ───────────────────────────────
def get_data(symbol, is_futures, interval, limit=KLINE_LIMIT):
    kl = (client.futures_klines(symbol=symbol, interval=interval, limit=limit) if is_futures
          else client.get_klines(symbol=symbol, interval=interval, limit=limit))
    df = pd.DataFrame(kl, columns=["time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]: df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.iloc[:-1].reset_index(drop=True)     # drop forming candle -> no repaint

def atr_series(df, window=14):
    h,l,c = df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(window).mean()

def compute_zigzag_pivots(df, dev):
    highs=df["high"].values; lows=df["low"].values; n=len(df); piv=[]; trend=None
    eh_p,eh_i=highs[0],0; el_p,el_i=lows[0],0
    for i in range(1,n):
        if highs[i]>eh_p: eh_p,eh_i=highs[i],i
        if lows[i]<el_p: el_p,el_i=lows[i],i
        if trend is None:
            if (eh_p-lows[i])/eh_p*100>=dev: piv.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
            elif (highs[i]-el_p)/el_p*100>=dev: piv.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
        elif trend=='up':
            if (eh_p-lows[i])/eh_p*100>=dev: piv.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
        elif trend=='down':
            if (highs[i]-el_p)/el_p*100>=dev: piv.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
    return piv

def structure_at(piv, limit_idx):
    conf=[p for p in piv if p[3]<=limit_idx]
    hs=[p[1] for p in conf if p[2]=='high']; ls=[p[1] for p in conf if p[2]=='low']
    if len(hs)>=2 and len(ls)>=2:
        hh,hl=hs[-1]>hs[-2],ls[-1]>ls[-2]; ll,lh=ls[-1]<ls[-2],hs[-1]<hs[-2]
        if hh and hl: return "HH+HL"
        if ll and lh: return "LL+LH"
        if hl: return "HL"
        if lh: return "LH"
    return "neutral"

def fee_of(side): return LONG_FEE if side=="LONG" else SHORT_FEE

def fp(x):   # pretty price: commas for big, more decimals for small
    return f"{x:,.2f}" if x >= 1 else f"{x:.6f}"

# ─── ALERTS ──────────────────────────────────────────
async def tg(text):
    try: await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e: print(f"telegram send failed: {e}")

def beep(kind):
    if winsound:
        try:
            if kind=="entry": winsound.Beep(1000,400); winsound.Beep(1200,400)
            elif kind=="win": winsound.Beep(1200,300); winsound.Beep(1500,500)
            elif kind=="loss": winsound.Beep(500,300); winsound.Beep(350,400)
        except Exception: pass
    if notification:
        try: notification.notify(title="ZigZag PAPER", message=kind, timeout=8)
        except Exception: pass

def wl_line():
    n = STATE["wins"] + STATE["losses"]
    wr = (STATE["wins"]/n*100) if n else 0
    return f"Wins {STATE['wins']}  ·  Losses {STATE['losses']}  ·  {wr:.0f}% win"

def bal_line():
    b = STATE["balance"]; pnl = b - PAPER_START
    return f"Balance  ${b:,.2f}  ({pnl:+,.2f} / {pnl/PAPER_START*100:+.1f}%)"

# ─── CORE: scan one symbol ───────────────────────────
def evaluate_symbol(symbol, is_futures):
    """Return (side, price, atr, sl, tp, s_entry) for a FRESH aligned signal, else side=None."""
    bias = get_data(symbol, is_futures, BIAS_INTERVAL)
    entry = get_data(symbol, is_futures, ENTRY_INTERVAL)
    if len(bias) < 60 or len(entry) < 60: return (None, None, None, None, None, None)
    entry["atr"] = atr_series(entry)
    s_bias  = structure_at(compute_zigzag_pivots(bias, DEVIATION),  len(bias)-1)
    s_entry = structure_at(compute_zigzag_pivots(entry, DEVIATION), len(entry)-1)
    price = entry["close"].iloc[-1]

    prev = STATE["prev_struct"].get(symbol)
    STATE["prev_struct"][symbol] = s_entry
    if prev is None: return (None, price, None, None, None, s_entry)     # warmup baseline
    if FRESH_ONLY and s_entry == prev: return (None, price, None, None, None, s_entry)

    bull = (s_bias in BULL) and (s_entry in BULL)
    bear = (s_bias in BEAR) and (s_entry in BEAR)
    if not (bull or bear): return (None, price, None, None, None, s_entry)

    atr = entry["atr"].iloc[-1]
    if pd.isna(atr) or atr<=0: return (None, price, None, None, None, s_entry)
    side = "LONG" if bull else "SHORT"
    if side=="LONG": sl, tp = price-atr*ATR_SL, price+atr*ATR_TP
    else:            sl, tp = price+atr*ATR_SL, price-atr*ATR_TP
    return side, price, atr, sl, tp, s_entry

def check_position(pos):
    """Return (closed?, net_pct, exit_price, reason)."""
    entry = get_data(pos["symbol"], pos["is_futures"], ENTRY_INTERVAL, limit=10)
    if entry.empty: return (False, None, None, None)
    hi = entry["high"].iloc[-1]; lo = entry["low"].iloc[-1]
    e, sl, tp, side = pos["entry"], pos["sl"], pos["tp"], pos["side"]
    if side=="LONG":
        if lo<=sl: return (True, (sl-e)/e*100 - fee_of(side), sl, "SL")
        if hi>=tp: return (True, (tp-e)/e*100 - fee_of(side), tp, "TP")
    else:
        if hi>=sl: return (True, (e-sl)/e*100 - fee_of(side), sl, "SL")
        if lo<=tp: return (True, (e-tp)/e*100 - fee_of(side), tp, "TP")
    return (False, None, None, None)

# ─── SCAN LOOP ───────────────────────────────────────
async def scan_loop():
    global is_running
    while is_running:
        try:
            # 1) close any open positions that hit TP/SL
            for pos in list(STATE["positions"]):
                closed, net, px, reason = check_position(pos)
                if not closed: continue
                STATE["balance"] += pos["stake"] * net / 100.0
                if net > 0: STATE["wins"] += 1
                else:       STATE["losses"] += 1
                STATE["positions"].remove(pos)
                log_trade([datetime.now(timezone.utc).isoformat(), pos["symbol"], pos["side"],
                           pos["entry"], px, reason, round(net,3), round(STATE["balance"],2)])
                head = "✅ PAPER WIN" if net>0 else "❌ PAPER LOSS"
                await tg(f"{head}  —  {pos['side']} {pos['symbol']}\n"
                         f"Result   {net:+.2f}%   ({reason})\n"
                         f"────────────────\n"
                         f"{bal_line()}\n{wl_line()}")
                beep("win" if net>0 else "loss")
                save_state()

            # 2) fire new signals — one position per coin, all coins independent
            open_syms = {p["symbol"] for p in STATE["positions"]}
            for symbol, fut in SYMBOLS:
                if not is_running: break
                side, price, atr, sl, tp, s_entry = evaluate_symbol(symbol, fut)
                if side and symbol not in open_syms:
                    stake = POS_FRAC * STATE["balance"]
                    STATE["positions"].append({"symbol":symbol, "is_futures":fut, "side":side,
                        "entry":price, "sl":sl, "tp":tp, "stake":stake,
                        "opened":datetime.now(timezone.utc).isoformat()})
                    open_syms.add(symbol)
                    venue = "futures 1x" if side=="SHORT" else "spot"
                    await tg(f"🚨 PAPER ENTRY  —  {side} {symbol}  ({venue})\n"
                             f"Entry    {fp(price)}\n"
                             f"🎯 TP    {fp(tp)}\n"
                             f"🛑 SL    {fp(sl)}\n"
                             f"────────────────\n"
                             f"{bal_line()}")
                    beep("entry")
                    save_state()
                await asyncio.sleep(1)

            await heartbeat()
        except Exception as e:
            print(f"scan error: {e}")
        await asyncio.sleep(CHECK_EVERY)

async def heartbeat():
    global last_heartbeat
    now = time.time()
    if now - last_heartbeat >= HEARTBEAT_EVERY:
        last_heartbeat = now
        if STATE["positions"]:
            opn = "\n".join(f"  • {p['side']} {p['symbol']} @ {fp(p['entry'])}" for p in STATE["positions"])
            opn = "Open trades:\n" + opn
        else:
            opn = "No open trades (waiting for a signal)"
        await tg(f"💓 PAPER bot alive  ·  {datetime.now().strftime('%H:%M')}\n"
                 f"────────────────\n{bal_line()}\n{wl_line()}\n{opn}")

# ─── TELEGRAM COMMANDS ───────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global is_running, last_heartbeat
    if is_running:
        await update.message.reply_text("Already running (paper). Use /stats.")
        return
    if not STATE.get("started"): STATE["started"] = datetime.now(timezone.utc).isoformat()
    is_running = True; last_heartbeat = 0; STATE["active"] = True; save_state()
    await update.message.reply_text(
        "📝 ZigZag PAPER bot STARTED  —  NO real money\n"
        f"Coins: {', '.join(s for s,_ in SYMBOLS)}   ·   4H+30M   ·   dev {DEVIATION}%   ·   TP{ATR_TP}/SL{ATR_SL}\n"
        "Fires LONG + SHORT on all coins (one position per coin).\n"
        "────────────────\n"
        f"{bal_line()}\n{wl_line()}\n\n"
        "/stats anytime  ·  /stop to pause  ·  /reset to wipe")
    asyncio.create_task(scan_loop())

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global is_running
    is_running = False; STATE["active"] = False; save_state()
    await update.message.reply_text("🛑 Paper bot paused. State saved. /start to resume.")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if STATE["positions"]:
        opn = "\n".join(f"  • {p['side']} {p['symbol']} @ {fp(p['entry'])}  "
                        f"(TP {fp(p['tp'])} / SL {fp(p['sl'])})" for p in STATE["positions"])
        opn = "Open trades:\n" + opn
    else:
        opn = "No open trades (waiting)."
    await update.message.reply_text(
        f"📊 PAPER ACCOUNT   (since {str(STATE.get('started'))[:10]})\n"
        f"────────────────\n"
        f"{bal_line()}\n{wl_line()}\n\n{opn}\n\nFull log: paper_trades.csv")

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    STATE.update({"balance":PAPER_START, "positions":[], "prev_struct":{},
                  "wins":0, "losses":0, "started":datetime.now(timezone.utc).isoformat()})
    save_state()
    await update.message.reply_text("♻️ Paper account reset to $1,000.  Wins 0 · Losses 0")

async def run():
    global is_running, last_heartbeat
    load_state()
    print("ZigZag PAPER bot ready. Press /start in Telegram.")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    async with app:
        await app.start(); await app.updater.start_polling()
        # auto-resume scanning if it was active before a crash/restart (no manual /start needed)
        if STATE.get("active"):
            is_running = True; last_heartbeat = 0
            asyncio.create_task(scan_loop())
            await tg(f"🔄 PAPER bot reconnected & resumed.\n────────────────\n{bal_line()}\n{wl_line()}")
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run())
