# version 9 - with heartbeat monitoring
import os
from dotenv import load_dotenv
load_dotenv()  # read secrets from a local .env file (never committed)
import asyncio
import pandas as pd
import requests
import winsound
from plyer import notification
from binance.client import Client
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange, KeltnerChannel
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volume import OnBalanceVolumeIndicator
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import time

# ─── SETTINGS ────────────────────────────────────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]   # set in .env (see .env.example)
CHAT_ID         = os.environ["CHAT_ID"]

SPOT_SYMBOLS    = ["ETHUSDT", "BTCUSDT", "XAUTUSDT"]
FUTURES_SYMBOLS = ["HYPEUSDT"]

INTERVAL_LTF    = Client.KLINE_INTERVAL_1HOUR
INTERVAL_HTF    = Client.KLINE_INTERVAL_4HOUR
CHECK_EVERY     = 60 * 60

TAKE_PROFIT     = 0.05
STOP_LOSS       = 0.02

client          = Client()
bot             = Bot(token=TELEGRAM_TOKEN)
is_running      = False
last_heartbeat  = 0
HEARTBEAT_INTERVAL = 300  # 5 minutes in seconds
current_timeframe_label = "1 Hour"  # Track current timeframe

# ─── GET CANDLE DATA ─────────────────────────────────
def get_data(symbol, is_futures=False, interval=None, limit=200):
    if interval is None:
        interval = INTERVAL_LTF
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

# ─── FEAR & GREED ────────────────────────────────────
def get_fear_greed():
    try:
        r     = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        data  = r.json()
        value = int(data["data"][0]["value"])
        label = data["data"][0]["value_classification"]
        return value, label
    except:
        return None, "Unknown"

# ─── FUNDING RATE ────────────────────────────────────
def get_funding_rate(symbol):
    try:
        data = client.futures_funding_rate(symbol=symbol, limit=1)
        return float(data[-1]["fundingRate"]) * 100
    except:
        return None

# ─── LONG SHORT RATIO ────────────────────────────────
def get_long_short_ratio(symbol):
    try:
        data      = client.futures_global_longshort_ratio(symbol=symbol, period="1h", limit=1)
        long_pct  = float(data[0]["longAccount"]) * 100
        short_pct = float(data[0]["shortAccount"]) * 100
        return long_pct, short_pct
    except:
        return None, None

# ─── WEEKLY TREND ────────────────────────────────────
def get_weekly_trend(symbol, is_futures=False):
    try:
        df    = get_data(symbol, is_futures, interval=Client.KLINE_INTERVAL_1WEEK, limit=50)
        ema20 = EMAIndicator(df["close"], window=20).ema_indicator()
        return "bullish" if df["close"].iloc[-1] > ema20.iloc[-1] else "bearish"
    except:
        return "unknown"

# ─── HTF TREND ───────────────────────────────────────
def get_htf_trend(symbol, is_futures=False):
    try:
        df    = get_data(symbol, is_futures, interval=Client.KLINE_INTERVAL_4HOUR, limit=100)
        ema50 = EMAIndicator(df["close"], window=50).ema_indicator()
        return "bullish" if df["close"].iloc[-1] > ema50.iloc[-1] else "bearish"
    except:
        return "unknown"

# ─── MARKET STRUCTURE ────────────────────────────────
def get_market_structure(df):
    try:
        highs       = df["high"].values
        lows        = df["low"].values
        n           = len(highs)
        swing_highs = []
        swing_lows  = []
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(lows[i])
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_hh = swing_highs[-1] > swing_highs[-2]
            last_hl = swing_lows[-1]  > swing_lows[-2]
            last_ll = swing_lows[-1]  < swing_lows[-2]
            last_lh = swing_highs[-1] < swing_highs[-2]
            if last_hh and last_hl:
                return "HH+HL"
            elif last_ll and last_lh:
                return "LL+LH"
            elif last_hl:
                return "HL"
            elif last_lh:
                return "LH"
        return "neutral"
    except:
        return "neutral"

# ─── FAIR VALUE GAP ──────────────────────────────────
def get_fvg(df):
    try:
        fvg_bull = False
        fvg_bear = False
        for i in range(2, len(df)):
            if df["high"].iloc[i-2] < df["low"].iloc[i]:
                fvg_bull = True
            if df["low"].iloc[i-2] > df["high"].iloc[i]:
                fvg_bear = True
        return fvg_bull, fvg_bear
    except:
        return False, False

# ─── SQUEEZE MOMENTUM ────────────────────────────────
def get_squeeze(df):
    try:
        close    = df["close"]
        high     = df["high"]
        low      = df["low"]
        bb       = BollingerBands(close, window=20, window_dev=2)
        kc       = KeltnerChannel(high, low, close, window=20)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        kc_upper = kc.keltner_channel_hband().iloc[-1]
        kc_lower = kc.keltner_channel_lband().iloc[-1]
        return bb_upper < kc_upper and bb_lower > kc_lower
    except:
        return False

# ─── CALCULATE SIGNAL ────────────────────────────────
def get_signal(df):
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    ema50      = EMAIndicator(close, window=50).ema_indicator()
    ema200     = EMAIndicator(close, window=200).ema_indicator()
    rsi        = RSIIndicator(close, window=14).rsi()
    macd_obj   = MACD(close)
    macd_line  = macd_obj.macd()
    macd_sig   = macd_obj.macd_signal()
    bb         = BollingerBands(close, window=20, window_dev=2)
    bb_upper   = bb.bollinger_hband()
    bb_lower   = bb.bollinger_lband()
    stoch      = StochasticOscillator(high, low, close, window=14, smooth_window=3)
    stoch_k    = stoch.stoch()
    stoch_d    = stoch.stoch_signal()
    obv        = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    atr        = AverageTrueRange(high, low, close, window=14).average_true_range()
    adx        = ADXIndicator(high, low, close, window=14)

    last_close  = close.iloc[-1]
    prev_close  = close.iloc[-2]
    last_rsi    = rsi.iloc[-1]
    last_ema50  = ema50.iloc[-1]
    last_ema200 = ema200.iloc[-1]
    last_macd   = macd_line.iloc[-1]
    last_sig    = macd_sig.iloc[-1]
    last_bb_up  = bb_upper.iloc[-1]
    last_bb_low = bb_lower.iloc[-1]
    last_stk    = stoch_k.iloc[-1]
    last_std    = stoch_d.iloc[-1]
    last_obv    = obv.iloc[-1]
    prev_obv    = obv.iloc[-2]
    last_atr    = atr.iloc[-1]
    last_adx    = adx.adx().iloc[-1]
    atr_pct     = (last_atr / last_close) * 100
    vol_avg     = volume.rolling(window=20).mean()
    vol_ok      = volume.iloc[-1] > vol_avg.iloc[-1]
    atr_ok      = atr_pct < 5.0
    price_change = ((last_close - prev_close) / prev_close) * 100

    buy = (
        last_close > last_ema200 and
        last_ema50 > last_ema200 and
        last_rsi < 40 and
        last_macd > last_sig and
        last_close <= last_bb_low and
        last_stk < 20 and
        last_stk > last_std and
        last_obv > prev_obv and
        vol_ok and
        atr_ok and
        last_adx > 25
    )

    sell = (
        last_close < last_ema200 and
        last_ema50 < last_ema200 and
        last_rsi > 60 and
        last_macd < last_sig and
        last_close >= last_bb_up and
        last_stk > 80 and
        last_stk < last_std and
        last_obv < prev_obv and
        vol_ok and
        atr_ok and
        last_adx > 25
    )

    return (buy, sell, last_close, last_rsi,
            last_stk, last_bb_low, last_bb_up,
            price_change, last_adx, atr_pct)

# ─── HEARTBEAT FUNCTION ───────────────────────────────
async def send_heartbeat():
    """Send heartbeat message every 5 minutes when on 1H timeframe"""
    global last_heartbeat, current_timeframe_label
    
    current_time = time.time()
    
    # Only send heartbeat if we're on 1H timeframe
    if current_timeframe_label == "1 Hour":
        if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
            last_heartbeat = current_time
            current_hour = time.strftime("%H:%M:%S")
            await send_message(
                f"💓 Heartbeat - Bot is Alive!\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Time: {current_hour}\n"
                f"📊 Timeframe: {current_timeframe_label}\n"
                f"🔄 Status: Actively Scanning\n"
                f"🎯 TP: +5% | SL: -2%\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"✅ All systems operational"
            )
            print(f"💓 Heartbeat sent at {current_hour}")

# ─── PC ALERT ────────────────────────────────────────
def alert_pc(title, message):
    try:
        notification.notify(
            title    = title,
            message  = message,
            app_name = "Indicator Bot V9",
            timeout  = 10
        )
        if "BUY" in title:
            winsound.Beep(1000, 500)
            winsound.Beep(1200, 500)
        elif "SELL" in title:
            winsound.Beep(600, 500)
            winsound.Beep(400, 500)
        elif "CUT LOSS" in title:
            for _ in range(3):
                winsound.Beep(800, 200)
                winsound.Beep(400, 200)
        elif "PROFIT" in title:
            winsound.Beep(1200, 300)
            winsound.Beep(1400, 300)
            winsound.Beep(1600, 500)
    except Exception as e:
        print(f"Alert error: {e}")

# ─── SEND MESSAGE ────────────────────────────────────
async def send_message(text):
    await bot.send_message(chat_id=CHAT_ID, text=text)

# ─── MONITOR CUT LOSS ────────────────────────────────
async def monitor_cutloss(symbol, entry_price, is_buy, is_futures=False):
    sl_pct = STOP_LOSS
    tp_pct = TAKE_PROFIT

    while is_running:
        try:
            df            = get_data(symbol, is_futures, interval=INTERVAL_LTF, limit=5)
            current_price = df["close"].iloc[-1]

            if is_buy:
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price * (1 + tp_pct)
                pnl_pct  = ((current_price - entry_price) / entry_price) * 100

                if current_price <= sl_price:
                    msg = (
                        f"🚨 CUT LOSS NOW!\n"
                        f"Symbol : {symbol}\n"
                        f"Entry  : {entry_price:.4f}\n"
                        f"Now    : {current_price:.4f}\n"
                        f"Loss   : {pnl_pct:.2f}%"
                    )
                    await send_message(msg)
                    alert_pc(f"🚨 CUT LOSS — {symbol}", f"Price: {current_price:.4f} | Loss: {pnl_pct:.2f}%")
                    break

                elif current_price >= tp_price:
                    msg = (
                        f"🎯 TAKE PROFIT HIT!\n"
                        f"Symbol : {symbol}\n"
                        f"Entry  : {entry_price:.4f}\n"
                        f"Now    : {current_price:.4f}\n"
                        f"Profit : +{pnl_pct:.2f}%"
                    )
                    await send_message(msg)
                    alert_pc(f"🎯 PROFIT — {symbol}", f"Price: {current_price:.4f} | Profit: +{pnl_pct:.2f}%")
                    break

            else:
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 - tp_pct)
                pnl_pct  = ((entry_price - current_price) / entry_price) * 100

                if current_price >= sl_price:
                    msg = (
                        f"🚨 CUT LOSS NOW!\n"
                        f"Symbol : {symbol}\n"
                        f"Entry  : {entry_price:.4f}\n"
                        f"Now    : {current_price:.4f}\n"
                        f"Loss   : {pnl_pct:.2f}%"
                    )
                    await send_message(msg)
                    alert_pc(f"🚨 CUT LOSS — {symbol}", f"Price: {current_price:.4f} | Loss: {pnl_pct:.2f}%")
                    break

                elif current_price <= tp_price:
                    msg = (
                        f"🎯 TAKE PROFIT HIT!\n"
                        f"Symbol : {symbol}\n"
                        f"Entry  : {entry_price:.4f}\n"
                        f"Now    : {current_price:.4f}\n"
                        f"Profit : +{pnl_pct:.2f}%"
                    )
                    await send_message(msg)
                    alert_pc(f"🎯 PROFIT — {symbol}", f"Price: {current_price:.4f} | Profit: +{pnl_pct:.2f}%")
                    break

        except Exception as e:
            print(f"Monitor error: {e}")

        await asyncio.sleep(60)

# ─── SCAN ONE SYMBOL ─────────────────────────────────
async def scan_symbol(symbol, is_futures=False):
    try:
        df_1h = get_data(symbol, is_futures, interval=INTERVAL_LTF)
        df_4h = get_data(symbol, is_futures, interval=INTERVAL_HTF)

        (buy_1h, sell_1h, price, rsi_1h,
         stoch_1h, bb_low_1h, bb_up_1h,
         price_change, adx_1h, atr_pct) = get_signal(df_1h)

        (buy_4h, sell_4h, _, rsi_4h,
         stoch_4h, _, _,
         _, adx_4h, _) = get_signal(df_4h)

        structure          = get_market_structure(df_4h)
        fvg_bull, fvg_bear = get_fvg(df_4h)
        squeeze            = get_squeeze(df_1h)
        weekly_trend       = get_weekly_trend(symbol, is_futures)
        htf_trend          = get_htf_trend(symbol, is_futures)
        fg_value, fg_label = get_fear_greed()

        change_emoji        = "📈" if price_change > 0 else "📉"
        label               = "FUTURES" if is_futures else "SPOT"
        funding             = get_funding_rate(symbol) if is_futures else None
        long_pct, short_pct = get_long_short_ratio(symbol) if is_futures else (None, None)

        structure_bull      = structure in ["HH+HL", "HL"]
        structure_bear      = structure in ["LL+LH", "LH"]
        trends_aligned_bull = weekly_trend == "bullish" and htf_trend == "bullish"
        trends_aligned_bear = weekly_trend == "bearish" and htf_trend == "bearish"
        fear_ok             = fg_value is not None and fg_value < 30
        greed_ok            = fg_value is not None and fg_value > 70
        funding_bull        = funding is not None and funding < -0.01
        funding_bear        = funding is not None and funding > 0.01
        shorts_heavy        = short_pct is not None and short_pct > 65
        longs_heavy         = long_pct  is not None and long_pct  > 65

        confirmed_buy = (
            buy_1h and
            buy_4h and
            structure_bull and
            trends_aligned_bull and
            fvg_bull
        )

        confirmed_sell = (
            sell_1h and
            sell_4h and
            structure_bear and
            trends_aligned_bear and
            fvg_bear
        )

        squeeze_msg = "⚠️ SQUEEZE DETECTED - Big move incoming!\n" if squeeze else ""

        if confirmed_buy:
            tp_price     = price * (1 + TAKE_PROFIT)
            sl_price     = price * (1 - STOP_LOSS)
            funding_line = f"Funding Rate : {funding:+.4f}% {'🔥 Shorts paying!' if funding_bull else ''}\n" if funding is not None else ""
            ls_line      = f"Long/Short   : {long_pct:.1f}% / {short_pct:.1f}% {'👀 Shorts heavy!' if shorts_heavy else ''}\n" if long_pct is not None else ""
            fg_line      = f"Fear & Greed : {fg_value} ({fg_label}) {'😱 Extreme Fear!' if fear_ok else ''}\n" if fg_value is not None else ""

            await send_message(
                f"🚨 HIGH PROB BUY — {symbol} ({label})\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{squeeze_msg}"
                f"Price        : {price:.4f}\n"
                f"Change       : {price_change:+.2f}% {change_emoji}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 1H Indicators:\n"
                f"RSI (1H)     : {rsi_1h:.2f}\n"
                f"Stoch (1H)   : {stoch_1h:.2f}\n"
                f"ADX (1H)     : {adx_1h:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 4H Indicators:\n"
                f"RSI (4H)     : {rsi_4h:.2f}\n"
                f"Stoch (4H)   : {stoch_4h:.2f}\n"
                f"ADX (4H)     : {adx_4h:.2f}\n"
                f"ATR          : {atr_pct:.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏗️ Structure    : {structure} ✅\n"
                f"📐 FVG Bull     : ✅\n"
                f"📅 Weekly       : {weekly_trend.upper()}\n"
                f"⏰ 4H Trend     : {htf_trend.upper()}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"😱 Sentiment:\n"
                f"{fg_line}"
                f"{funding_line}"
                f"{ls_line}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Take Profit : {tp_price:.4f} (+5%)\n"
                f"🛑 Stop Loss   : {sl_price:.4f} (-2%)\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔥 1H + 4H Confirmed!"
            )
            alert_pc(f"🚨 BUY — {symbol}", f"Price: {price:.4f} | TP: {tp_price:.4f} | SL: {sl_price:.4f}")
            asyncio.create_task(monitor_cutloss(symbol, price, is_buy=True, is_futures=is_futures))

        elif confirmed_sell:
            tp_price     = price * (1 - TAKE_PROFIT)
            sl_price     = price * (1 + STOP_LOSS)
            funding_line = f"Funding Rate : {funding:+.4f}% {'🔥 Longs paying!' if funding_bear else ''}\n" if funding is not None else ""
            ls_line      = f"Long/Short   : {long_pct:.1f}% / {short_pct:.1f}% {'👀 Longs heavy!' if longs_heavy else ''}\n" if long_pct is not None else ""
            fg_line      = f"Fear & Greed : {fg_value} ({fg_label}) {'🤑 Extreme Greed!' if greed_ok else ''}\n" if fg_value is not None else ""

            await send_message(
                f"🚨 HIGH PROB SELL — {symbol} ({label})\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{squeeze_msg}"
                f"Price        : {price:.4f}\n"
                f"Change       : {price_change:+.2f}% {change_emoji}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 1H Indicators:\n"
                f"RSI (1H)     : {rsi_1h:.2f}\n"
                f"Stoch (1H)   : {stoch_1h:.2f}\n"
                f"ADX (1H)     : {adx_1h:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📊 4H Indicators:\n"
                f"RSI (4H)     : {rsi_4h:.2f}\n"
                f"Stoch (4H)   : {stoch_4h:.2f}\n"
                f"ADX (4H)     : {adx_4h:.2f}\n"
                f"ATR          : {atr_pct:.2f}%\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🏗️ Structure    : {structure} ✅\n"
                f"📐 FVG Bear     : ✅\n"
                f"📅 Weekly       : {weekly_trend.upper()}\n"
                f"⏰ 4H Trend     : {htf_trend.upper()}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"😱 Sentiment:\n"
                f"{fg_line}"
                f"{funding_line}"
                f"{ls_line}"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎯 Take Profit : {tp_price:.4f} (-5%)\n"
                f"🛑 Stop Loss   : {sl_price:.4f} (+2%)\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔥 1H + 4H Confirmed!"
            )
            alert_pc(f"🚨 SELL — {symbol}", f"Price: {price:.4f} | TP: {tp_price:.4f} | SL: {sl_price:.4f}")
            asyncio.create_task(monitor_cutloss(symbol, price, is_buy=False, is_futures=is_futures))

        else:
            print(
                f"⏳ No signal | {symbol} | "
                f"Price: {price:.4f} | "
                f"1H RSI: {rsi_1h:.2f} | "
                f"4H RSI: {rsi_4h:.2f} | "
                f"Structure: {structure} | "
                f"Weekly: {weekly_trend} | "
                f"4H: {htf_trend}"
            )

    except Exception as e:
        print(f"❌ Error scanning {symbol}: {e}")

# ─── SCAN LOOP ───────────────────────────────────────
async def scan_loop():
    global is_running
    while is_running:
        print(f"\n🔍 Scanning all symbols...")
        
        # Send heartbeat before scanning
        await send_heartbeat()
        
        for symbol in SPOT_SYMBOLS:
            if not is_running:
                break
            await scan_symbol(symbol, is_futures=False)
            await asyncio.sleep(2)
        for symbol in FUTURES_SYMBOLS:
            if not is_running:
                break
            await scan_symbol(symbol, is_futures=True)
            await asyncio.sleep(2)
        if is_running:
            await asyncio.sleep(CHECK_EVERY)

# ─── TELEGRAM COMMANDS ───────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🧪 1 Min (Test)", callback_data="tf_1min"),
            InlineKeyboardButton("⚡ 15 Min", callback_data="tf_15m"),
        ],
        [
            InlineKeyboardButton("🕐 1 Hour", callback_data="tf_1h"),
            InlineKeyboardButton("🕓 4 Hours", callback_data="tf_4h"),
        ],
        [
            InlineKeyboardButton("📅 1 Day", callback_data="tf_1d"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 Indicator Bot V9\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Select your timeframe:",
        reply_markup=reply_markup
    )

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running
    if not is_running:
        await update.message.reply_text("⚠️ Bot is not running!")
        return
    is_running = False
    await update.message.reply_text(
        "🛑 Bot Stopped!\n"
        "Type /start to start again."
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_running, INTERVAL_LTF, INTERVAL_HTF, CHECK_EVERY, last_heartbeat, current_timeframe_label
    query = update.callback_query
    await query.answer()

    if query.data == "tf_1min":
        INTERVAL_LTF = Client.KLINE_INTERVAL_1MINUTE
        INTERVAL_HTF = Client.KLINE_INTERVAL_15MINUTE
        CHECK_EVERY  = 60
        tf_label     = "1 Min (Test)"
        current_timeframe_label = "1 Min"
    elif query.data == "tf_15m":
        INTERVAL_LTF = Client.KLINE_INTERVAL_15MINUTE
        INTERVAL_HTF = Client.KLINE_INTERVAL_1HOUR
        CHECK_EVERY  = 60 * 15
        tf_label     = "15 Min"
        current_timeframe_label = "15 Min"
    elif query.data == "tf_1h":
        INTERVAL_LTF = Client.KLINE_INTERVAL_1HOUR
        INTERVAL_HTF = Client.KLINE_INTERVAL_4HOUR
        CHECK_EVERY  = 60 * 60
        tf_label     = "1 Hour"
        current_timeframe_label = "1 Hour"
    elif query.data == "tf_4h":
        INTERVAL_LTF = Client.KLINE_INTERVAL_4HOUR
        INTERVAL_HTF = Client.KLINE_INTERVAL_1DAY
        CHECK_EVERY  = 60 * 60 * 4
        tf_label     = "4 Hours"
        current_timeframe_label = "4 Hours"
    elif query.data == "tf_1d":
        INTERVAL_LTF = Client.KLINE_INTERVAL_1DAY
        INTERVAL_HTF = Client.KLINE_INTERVAL_1WEEK
        CHECK_EVERY  = 60 * 60 * 24
        tf_label     = "1 Day"
        current_timeframe_label = "1 Day"

    is_running = False
    await asyncio.sleep(1)
    is_running = True
    last_heartbeat = time.time()  # Reset heartbeat timer

    heartbeat_notice = ""
    if current_timeframe_label == "1 Hour":
        heartbeat_notice = "\n💓 Heartbeat active: You'll receive 'still alive' messages every 5 minutes!"

    await query.edit_message_text(
        f"🤖 Indicator Bot V9 Started!\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 Monitoring:\n"
        f"• HYPEUSDT (Futures)\n"
        f"• ETHUSDT (Spot)\n"
        f"• BTCUSDT (Spot)\n"
        f"• XAUTUSDT (Spot)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ Timeframe  : {tf_label}\n"
        f"🎯 Take Profit: +5%\n"
        f"🛑 Stop Loss  : -2%\n"
        f"{heartbeat_notice}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Smart Money Mode ON\n"
        f"Type /stop to stop the bot"
    )
    asyncio.create_task(scan_loop())

# ─── RUN BOT ─────────────────────────────────────────
async def run_all():
    print("✅ V9 Bot ready! Press /start in Telegram to begin.")
    print("💓 Heartbeat monitoring active for 1H timeframe (every 5 minutes)")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    async with app:
        await app.start()
        await app.updater.start_polling()
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()

asyncio.run(run_all())