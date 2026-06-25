# version 13 - Streamlined flow: Account -> Risk -> Timeframe -> Auto-start + Heartbeat
import os
from dotenv import load_dotenv
load_dotenv()  # read secrets from a local .env file (never committed)
import asyncio
import pandas as pd
import requests
import winsound
import time
from plyer import notification
from binance.client import Client
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import RSIIndicator
from ta.volume import OnBalanceVolumeIndicator
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                           CallbackQueryHandler, MessageHandler, filters)

# ─── SETTINGS ────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]   # set in .env (see .env.example)
CHAT_ID         = os.environ["CHAT_ID"]

SPOT_SYMBOLS    = ["BTCUSDT", "XAUTUSDT"]
FUTURES_SYMBOLS = ["HYPEUSDT"]

ADX_THRESHOLD = 20
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0
TRAILING_STOP_ACTIVATE = 0.02
TRAILING_STOP_DISTANCE = 0.015

HEARTBEAT_INTERVAL = 1800  # 30 minutes

client = Client()
bot    = Bot(token=TELEGRAM_TOKEN)
is_running = False
last_heartbeat = 0

# ─── STATE ────────────────────────────────────────────
ACCOUNT_SIZE = None
RISK_PER_TRADE = None
INTERVAL_LTF = None
INTERVAL_HTF = None
CHECK_EVERY = None
TIMEFRAME_LABEL = ""

# Conversation stage tracker
STAGE = "idle"   # idle -> awaiting_account -> awaiting_risk(handled by buttons) -> awaiting_timeframe(handled by buttons) -> running

# ─── GET CANDLE DATA ─────────────────────────────────
def get_data(symbol, is_futures=False, interval=None, limit=200):
    if is_futures:
        klines = client.futures_klines(symbol=symbol, interval=interval, limit=limit)
    else:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"
    ])
    df["close"]  = df["close"].astype(float)
    df["high"]   = df["high"].astype(float)
    df["low"]    = df["low"].astype(float)
    df["open"]   = df["open"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df

# ─── SENTIMENT (display only) ────────────────────────
def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        data = r.json()
        return int(data["data"][0]["value"]), data["data"][0]["value_classification"]
    except:
        return None, "Unknown"

def get_funding_rate(symbol):
    try:
        data = client.futures_funding_rate(symbol=symbol, limit=1)
        return float(data[-1]["fundingRate"]) * 100
    except:
        return None

def get_htf_trend_ema(df_htf):
    ema50 = EMAIndicator(df_htf["close"], window=50).ema_indicator()
    return df_htf["close"].iloc[-1] > ema50.iloc[-1]

# ─── SIGNAL LOGIC: BASELINE + FILTER A + FILTER E ────
def get_signal(df):
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    rsi       = RSIIndicator(close, window=14).rsi()
    macd_obj  = MACD(close)
    macd_line = macd_obj.macd()
    macd_sig  = macd_obj.macd_signal()
    macd_hist = macd_obj.macd_diff()
    adx       = ADXIndicator(high, low, close, window=14).adx()
    obv       = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    atr       = AverageTrueRange(high, low, close, window=14).average_true_range()

    last_close = close.iloc[-1]
    last_rsi   = rsi.iloc[-1]
    last_macd  = macd_line.iloc[-1]
    last_sig   = macd_sig.iloc[-1]
    last_adx   = adx.iloc[-1]
    last_obv   = obv.iloc[-1]
    prev_obv   = obv.iloc[-2]
    last_atr   = atr.iloc[-1]
    atr_pct    = (last_atr / last_close) * 100

    rsi_buy_thresh  = 40 + atr_pct
    rsi_sell_thresh = 60 - atr_pct

    base_buy = (last_rsi < rsi_buy_thresh and last_macd > last_sig and
                last_obv > prev_obv and last_adx > ADX_THRESHOLD)
    base_sell = (last_rsi > rsi_sell_thresh and last_macd < last_sig and
                 last_obv < prev_obv and last_adx > ADX_THRESHOLD)

    h0, h1, h2 = macd_hist.iloc[-1], macd_hist.iloc[-2], macd_hist.iloc[-3]
    hist_rising  = h0 > h1 > h2
    hist_falling = h0 < h1 < h2

    buy  = base_buy and hist_rising
    sell = base_sell and hist_falling

    return (buy, sell, last_close, last_rsi, last_adx, atr_pct, last_atr)

# ─── POSITION SIZE CALCULATOR ────────────────────────
def calculate_position_size(entry_price, stop_loss_price):
    if ACCOUNT_SIZE is None or RISK_PER_TRADE is None:
        return None, None, None
    risk_amount = ACCOUNT_SIZE * RISK_PER_TRADE
    sl_distance_pct = abs(entry_price - stop_loss_price) / entry_price
    if sl_distance_pct == 0:
        return None, None, None
    position_size_usd = min(risk_amount / sl_distance_pct, ACCOUNT_SIZE)
    qty = position_size_usd / entry_price
    return risk_amount, position_size_usd, qty

# ─── PC ALERT ────────────────────────────────────────
def alert_pc(title, message):
    try:
        notification.notify(title=title, message=message, app_name="Indicator Bot V13", timeout=10)
        if "BUY" in title:
            winsound.Beep(1000, 500); winsound.Beep(1200, 500)
        elif "SELL" in title:
            winsound.Beep(600, 500); winsound.Beep(400, 500)
        elif "STOP LOSS" in title:
            for _ in range(3):
                winsound.Beep(800, 200); winsound.Beep(400, 200)
        elif "PROFIT" in title:
            winsound.Beep(1200, 300); winsound.Beep(1400, 300); winsound.Beep(1600, 500)
        elif "TRAILING" in title:
            winsound.Beep(900, 200); winsound.Beep(1100, 200)
    except Exception as e:
        print(f"Alert error: {e}")

# ─── SEND MESSAGE ────────────────────────────────────
async def send_message(text):
    await bot.send_message(chat_id=CHAT_ID, text=text)

# ─── HEARTBEAT ────────────────────────────────────────
async def heartbeat_loop():
    global last_heartbeat
    while is_running:
        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            last_heartbeat = now
            await send_message(
                f"💓 Heartbeat — Bot is Alive\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Time: {time.strftime('%H:%M:%S')}\n"
                f"📊 Timeframe: {TIMEFRAME_LABEL}\n"
                f"💰 Account: ${ACCOUNT_SIZE:.2f} | Risk: {RISK_PER_TRADE*100:.0f}%\n"
                f"✅ Actively scanning"
            )
            print(f"💓 Heartbeat sent at {time.strftime('%H:%M:%S')}")
        await asyncio.sleep(60)

# ─── MONITOR WITH TRAILING STOP ─────────────────────
async def monitor_cutloss(symbol, entry_price, is_buy, is_futures, atr_value):
    sl_pct = (atr_value * ATR_MULTIPLIER_SL) / entry_price if atr_value else 0.03
    tp_pct = (atr_value * ATR_MULTIPLIER_TP) / entry_price if atr_value else 0.08

    if is_buy:
        sl_price = entry_price * (1 - sl_pct)
        tp_price = entry_price * (1 + tp_pct)
        best_price = entry_price
    else:
        sl_price = entry_price * (1 + sl_pct)
        tp_price = entry_price * (1 - tp_pct)
        best_price = entry_price

    trailing_activated = False

    while is_running:
        try:
            df = get_data(symbol, is_futures, interval=INTERVAL_LTF, limit=5)
            current_price = df["close"].iloc[-1]

            if is_buy:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100
                if pnl_pct >= TRAILING_STOP_ACTIVATE * 100 and not trailing_activated:
                    trailing_activated = True
                    sl_price = current_price * (1 - TRAILING_STOP_DISTANCE)
                    await send_message(f"🔒 TRAILING ACTIVATED — {symbol}\nProfit: {pnl_pct:.2f}%")
                    alert_pc(f"🔒 TRAILING — {symbol}", f"Profit: {pnl_pct:.2f}%")
                if trailing_activated and current_price > best_price:
                    best_price = current_price
                    sl_price = max(sl_price, best_price * (1 - TRAILING_STOP_DISTANCE))

                if current_price <= sl_price:
                    await send_message(f"❌ STOP LOSS — {symbol}\nResult: {pnl_pct:.2f}%")
                    alert_pc(f"❌ STOP LOSS — {symbol}", f"Loss: {pnl_pct:.2f}%")
                    break
                elif current_price >= tp_price:
                    await send_message(f"✅ TAKE PROFIT — {symbol}\nProfit: +{pnl_pct:.2f}%")
                    alert_pc(f"✅ PROFIT — {symbol}", f"Profit: +{pnl_pct:.2f}%")
                    break
            else:
                pnl_pct = ((entry_price - current_price) / entry_price) * 100
                if pnl_pct >= TRAILING_STOP_ACTIVATE * 100 and not trailing_activated:
                    trailing_activated = True
                    sl_price = current_price * (1 + TRAILING_STOP_DISTANCE)
                    await send_message(f"🔒 TRAILING ACTIVATED — {symbol}\nProfit: {pnl_pct:.2f}%")
                    alert_pc(f"🔒 TRAILING — {symbol}", f"Profit: {pnl_pct:.2f}%")
                if trailing_activated and current_price < best_price:
                    best_price = current_price
                    sl_price = min(sl_price, best_price * (1 + TRAILING_STOP_DISTANCE))

                if current_price >= sl_price:
                    await send_message(f"❌ STOP LOSS — {symbol}\nResult: {pnl_pct:.2f}%")
                    alert_pc(f"❌ STOP LOSS — {symbol}", f"Loss: {pnl_pct:.2f}%")
                    break
                elif current_price <= tp_price:
                    await send_message(f"✅ TAKE PROFIT — {symbol}\nProfit: +{pnl_pct:.2f}%")
                    alert_pc(f"✅ PROFIT — {symbol}", f"Profit: +{pnl_pct:.2f}%")
                    break

        except Exception as e:
            print(f"Monitor error: {e}")

        await asyncio.sleep(30)

# ─── SCAN ONE SYMBOL ─────────────────────────────────
async def scan_symbol(symbol, is_futures=False):
    try:
        df_1h = get_data(symbol, is_futures, interval=INTERVAL_LTF)
        df_4h = get_data(symbol, is_futures, interval=INTERVAL_HTF)

        (buy, sell, price, rsi, adx, atr_pct, atr_val) = get_signal(df_1h)
        htf_bull = get_htf_trend_ema(df_4h)
        htf_bear = not htf_bull

        confirmed_buy  = buy and htf_bull
        confirmed_sell = sell and htf_bear

        label = "FUTURES" if is_futures else "SPOT"
        fg_value, fg_label = get_fear_greed()
        funding = get_funding_rate(symbol) if is_futures else None
        fg_line = f"Fear & Greed: {fg_value} ({fg_label})\n" if fg_value else ""
        fund_line = f"Funding Rate: {funding:+.4f}%\n" if funding is not None else ""

        if confirmed_buy or confirmed_sell:
            is_buy = confirmed_buy
            if is_buy:
                sl_price = price - (atr_val * ATR_MULTIPLIER_SL)
                tp_price = price + (atr_val * ATR_MULTIPLIER_TP)
                trend_txt = "BULLISH"
            else:
                sl_price = price + (atr_val * ATR_MULTIPLIER_SL)
                tp_price = price - (atr_val * ATR_MULTIPLIER_TP)
                trend_txt = "BEARISH"

            risk_amt, pos_usd, qty = calculate_position_size(price, sl_price)
            pos_lines = (
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 Position Sizing ({RISK_PER_TRADE*100:.0f}% risk):\n"
                f"Risk Amount : ${risk_amt:.2f}\n"
                f"Position    : ${pos_usd:.2f}\n"
                f"Quantity    : {qty:.4f}\n"
            ) if risk_amt is not None else ""

            side_word = "BUY" if is_buy else "SELL"
            await send_message(
                f"🚨 {side_word} SIGNAL — {symbol} ({label})\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Price : {price:.4f}\n"
                f"RSI   : {rsi:.2f} | ADX: {adx:.2f} | ATR: {atr_pct:.2f}%\n"
                f"📅 HTF Trend: {trend_txt}\n"
                f"{fg_line}{fund_line}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 TP: {tp_price:.4f}\n"
                f"🛑 SL: {sl_price:.4f}\n"
                f"{pos_lines}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔥 Filter A+E confirmed"
            )
            alert_pc(f"🚨 {side_word} — {symbol}", f"Price: {price:.4f}")
            asyncio.create_task(monitor_cutloss(symbol, price, is_buy, is_futures, atr_val))
        else:
            print(f"⏳ No signal | {symbol} | Price: {price:.4f} | RSI: {rsi:.2f} | ADX: {adx:.2f}")

    except Exception as e:
        print(f"❌ Error scanning {symbol}: {e}")

# ─── SCAN LOOP ───────────────────────────────────────
async def scan_loop():
    global is_running
    while is_running:
        print(f"\n🔍 Scanning all symbols...")
        for symbol in SPOT_SYMBOLS:
            if not is_running: break
            await scan_symbol(symbol, is_futures=False)
            await asyncio.sleep(2)
        for symbol in FUTURES_SYMBOLS:
            if not is_running: break
            await scan_symbol(symbol, is_futures=True)
            await asyncio.sleep(2)
        if is_running:
            await asyncio.sleep(CHECK_EVERY)

# ─── TELEGRAM: /start asks for account size FIRST ────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global STAGE
    STAGE = "awaiting_account"
    await update.message.reply_text(
        "🤖 Indicator Bot V13\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Let's set up your bot.\n\n"
        "💰 Step 1: Type your account size (just the number, e.g. 1000)"
    )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running, STAGE
    if not is_running:
        await update.message.reply_text("⚠️ Bot is not running!")
        return
    is_running = False
    STAGE = "idle"
    await update.message.reply_text("🛑 Bot Stopped! Type /start to set up again.")

# ─── TEXT HANDLER: catches account size input ────────
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ACCOUNT_SIZE, STAGE
    if STAGE == "awaiting_account":
        try:
            ACCOUNT_SIZE = float(update.message.text.strip())
            STAGE = "awaiting_risk"
            keyboard = [[
                InlineKeyboardButton("1% Risk", callback_data="risk_1"),
                InlineKeyboardButton("2% Risk", callback_data="risk_2")
            ]]
            await update.message.reply_text(
                f"✅ Account set to ${ACCOUNT_SIZE:.2f}\n\n"
                f"📊 Step 2: Choose risk per trade",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except ValueError:
            await update.message.reply_text("⚠️ Please type a number only, e.g. 1000")

# ─── BUTTON HANDLER: risk % then timeframe ───────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global RISK_PER_TRADE, STAGE, is_running
    global INTERVAL_LTF, INTERVAL_HTF, CHECK_EVERY, TIMEFRAME_LABEL, last_heartbeat

    query = update.callback_query
    await query.answer()

    if query.data in ["risk_1", "risk_2"]:
        RISK_PER_TRADE = 0.01 if query.data == "risk_1" else 0.02
        STAGE = "awaiting_timeframe"
        keyboard = [
            [InlineKeyboardButton("⚡ 15 Min (UNTESTED with these filters)", callback_data="tf_15m")],
            [InlineKeyboardButton("🕐 1 Hour (✅ Backtested)", callback_data="tf_1h")],
            [InlineKeyboardButton("📅 1 Day (UNTESTED with these filters)", callback_data="tf_1d")],
        ]
        await query.edit_message_text(
            f"✅ Risk set to {RISK_PER_TRADE*100:.0f}%\n\n"
            f"⏰ Step 3: Choose timeframe\n"
            f"(Only 1 Hour has been backtested with the current filter combo — others are untested)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data in ["tf_15m", "tf_1h", "tf_1d"]:
        if query.data == "tf_15m":
            INTERVAL_LTF, INTERVAL_HTF, CHECK_EVERY = Client.KLINE_INTERVAL_15MINUTE, Client.KLINE_INTERVAL_1HOUR, 60*15
            TIMEFRAME_LABEL = "15 Min (untested)"
        elif query.data == "tf_1h":
            INTERVAL_LTF, INTERVAL_HTF, CHECK_EVERY = Client.KLINE_INTERVAL_1HOUR, Client.KLINE_INTERVAL_4HOUR, 60*60
            TIMEFRAME_LABEL = "1 Hour (backtested)"
        elif query.data == "tf_1d":
            INTERVAL_LTF, INTERVAL_HTF, CHECK_EVERY = Client.KLINE_INTERVAL_1DAY, Client.KLINE_INTERVAL_1WEEK, 60*60*24
            TIMEFRAME_LABEL = "1 Day (untested)"

        STAGE = "running"
        is_running = True
        last_heartbeat = time.time()

        await query.edit_message_text(
            f"🤖 Bot Started!\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Account: ${ACCOUNT_SIZE:.2f} | Risk: {RISK_PER_TRADE*100:.0f}%\n"
            f"⏰ Timeframe: {TIMEFRAME_LABEL}\n"
            f"📊 Symbols: {', '.join(SPOT_SYMBOLS + FUTURES_SYMBOLS)}\n"
            f"💓 Heartbeat every 30 min\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Type /stop to stop"
        )
        asyncio.create_task(scan_loop())
        asyncio.create_task(heartbeat_loop())

# ─── RUN BOT ─────────────────────────────────────────
async def run_all():
    print("✅ V13 Bot ready! Press /start in Telegram.")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()

asyncio.run(run_all())