import asyncio
import pandas as pd
from binance.client import Client
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volume import OnBalanceVolumeIndicator
from telegram import Bot

# ─── SETTINGS ───────────────────────────────────────
TELEGRAM_TOKEN = "8787350974:AAGWbEXMh4_j8vEIIzT2KajfhrfLucoVw-o"
CHAT_ID        = "6877313071"
SYMBOL         = "BTCUSDT"
INTERVAL       = Client.KLINE_INTERVAL_15MINUTE
CHECK_EVERY = 60  # check every 1 minute

# Binance (no API key needed for public data)
client = Client()
bot    = Bot(token=TELEGRAM_TOKEN)

# ─── GET CANDLE DATA ─────────────────────────────────
def get_data():
    klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=200)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"
    ])
    df["close"]  = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    return df

# ─── CALCULATE INDICATORS ────────────────────────────
def get_signal(df):
    close  = df["close"]
    volume = df["volume"]

    # EMA
    ema50  = EMAIndicator(close, window=50).ema_indicator()
    ema200 = EMAIndicator(close, window=200).ema_indicator()

    # RSI
    rsi = RSIIndicator(close, window=14).rsi()

    # MACD
    macd_obj  = MACD(close)
    macd_line = macd_obj.macd()
    macd_sig  = macd_obj.macd_signal()

    # OBV
    obv = OnBalanceVolumeIndicator(close, volume).on_balance_volume()

    # Get latest values
    last_close  = close.iloc[-1]
    last_rsi    = rsi.iloc[-1]
    last_ema50  = ema50.iloc[-1]
    last_ema200 = ema200.iloc[-1]
    last_macd   = macd_line.iloc[-1]
    last_sig    = macd_sig.iloc[-1]
    last_obv    = obv.iloc[-1]
    prev_obv    = obv.iloc[-2]

    # ─── BUY CONDITIONS (all must be true) ───
    buy = (
        last_close > last_ema200 and        # price above long trend
        last_ema50 > last_ema200 and        # short trend above long trend
        last_rsi < 35 and                   # oversold (stricter than normal)
        last_macd > last_sig and            # macd bullish crossover
        last_obv > prev_obv                 # volume confirming move
    )

    # ─── SELL CONDITIONS (all must be true) ──
    sell = (
        last_close < last_ema200 and        # price below long trend
        last_ema50 < last_ema200 and        # short trend below long trend
        last_rsi > 65 and                   # overbought (stricter than normal)
        last_macd < last_sig and            # macd bearish crossover
        last_obv < prev_obv                 # volume confirming move
    )

    return buy, sell, last_close, last_rsi

# ─── SEND TELEGRAM MESSAGE ───────────────────────────
async def send_message(text):
    await bot.send_message(chat_id=CHAT_ID, text=text)

# ─── MAIN LOOP ───────────────────────────────────────
async def main():
    print("✅ Bot started! Monitoring HYPEUSDT...")
    await send_message("🤖 Indicator Bot started!\nMonitoring HYPEUSDT every 15 minutes.")

    while True:
        try:
            df = get_data()
            buy, sell, price, rsi = get_signal(df)

            if buy:
                await send_message(
                    f"🟢 BUY SIGNAL — HYPEUSDT\n"
                    f"Price : {price:.4f}\n"
                    f"RSI   : {rsi:.2f}\n"
                    f"All indicators aligned ✅"
                )
            elif sell:
                await send_message(
                    f"🔴 SELL SIGNAL — HYPEUSDT\n"
                    f"Price : {price:.4f}\n"
                    f"RSI   : {rsi:.2f}\n"
                    f"All indicators aligned ✅"
                )
            else:
                print(f"No signal | Price: {price:.4f} | RSI: {rsi:.2f}")

        except Exception as e:
            print(f"Error: {e}")

        await asyncio.sleep(CHECK_EVERY)

asyncio.run(main())