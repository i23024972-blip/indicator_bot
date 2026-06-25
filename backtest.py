# backtest.py - Test individual filter improvements on 1H/4H baseline (A-I)
import pandas as pd
from binance.client import Client
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volume import OnBalanceVolumeIndicator

# ─── SETTINGS ────────────────────────────────────────
SPOT_SYMBOLS    = ["BTCUSDT", "XAUTUSDT"]
FUTURES_SYMBOLS = ["HYPEUSDT"]

BACKTEST_DAYS   = 1000

ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0

client = Client()

TIMEFRAME_MODE = "1H_4H"
LTF_INTERVAL = Client.KLINE_INTERVAL_1HOUR
HTF_INTERVAL = Client.KLINE_INTERVAL_4HOUR

FILTER_MODE = "I_PURE"

# ─── GET HISTORICAL DATA ─────────────────────────────
def get_historical(symbol, interval, is_futures=False, days=BACKTEST_DAYS):
    start_str = f"{days} days ago UTC"
    try:
        if is_futures:
            klines = client.futures_historical_klines(symbol, interval, start_str)
        else:
            klines = client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        print(f"  ⚠️ Could not fetch {symbol}: {e}")
        return None

    if not klines:
        return None

    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"
    ])
    df["close"]  = df["close"].astype(float)
    df["high"]   = df["high"].astype(float)
    df["low"]    = df["low"].astype(float)
    df["open"]   = df["open"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["time"]   = pd.to_datetime(df["time"], unit="ms")
    return df

# ─── ADD ALL INDICATORS ──────────────────────────────
def add_indicators(df):
    df = df.copy()
    df["rsi"]      = RSIIndicator(df["close"], window=14).rsi()
    macd_obj        = MACD(df["close"])
    df["macd"]      = macd_obj.macd()
    df["macd_sig"]  = macd_obj.macd_signal()
    df["macd_hist"] = macd_obj.macd_diff()

    adx_obj         = ADXIndicator(df["high"], df["low"], df["close"], window=14)
    df["adx"]       = adx_obj.adx()
    df["plus_di"]   = adx_obj.adx_pos()
    df["minus_di"]  = adx_obj.adx_neg()

    df["obv"] = OnBalanceVolumeIndicator(df["close"], df["volume"]).on_balance_volume()
    df["atr"] = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

    bb = BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_width"]     = bb.bollinger_wband()
    df["bb_width_avg"] = df["bb_width"].rolling(20).mean()

    df["vol_avg20"] = df["volume"].rolling(20).mean()

    df["ema50"]       = EMAIndicator(df["close"], window=50).ema_indicator()
    df["ema50_slope"] = df["ema50"].diff(5)

    df["swing_low_recent"]  = df["low"].rolling(20).min().shift(1)
    df["swing_high_recent"] = df["high"].rolling(20).max().shift(1)

    stoch = StochasticOscillator(df["high"], df["low"], df["close"], window=10, smooth_window=5)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = df["stoch_k"].rolling(5).mean()

    return df

# ─── OBV DIVERGENCE HELPERS ───────────────────────────
def check_obv_divergence_bull(df, idx, lookback=10):
    if idx < lookback + 5:
        return False
    recent_price = df["low"].iloc[idx-lookback:idx+1]
    price_low_idx = recent_price.idxmin()
    if price_low_idx == recent_price.index[-1]:
        return False
    return df["low"].iloc[idx] < df["low"].loc[price_low_idx] and df["obv"].iloc[idx] > df["obv"].loc[price_low_idx]

def check_obv_divergence_bear(df, idx, lookback=10):
    if idx < lookback + 5:
        return False
    recent_price = df["high"].iloc[idx-lookback:idx+1]
    price_high_idx = recent_price.idxmax()
    if price_high_idx == recent_price.index[-1]:
        return False
    return df["high"].iloc[idx] > df["high"].loc[price_high_idx] and df["obv"].iloc[idx] < df["obv"].loc[price_high_idx]

# ─── MARKET STRUCTURE ─────────────────────────────────
def get_market_structure_at(df, idx, lookback=50):
    start = max(0, idx - lookback)
    window = df.iloc[start:idx+1]
    highs = window["high"].values
    lows  = window["low"].values
    n     = len(highs)
    swing_highs, swing_lows = [], []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            swing_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            swing_lows.append(lows[i])
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1]  > swing_lows[-2]
        ll = swing_lows[-1]  < swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        if hh and hl: return "HH+HL"
        elif ll and lh: return "LL+LH"
        elif hl: return "HL"
        elif lh: return "LH"
    return "neutral"

# ─── SIMULATE A SINGLE TRADE FORWARD ─────────────────
def simulate_trade(df, entry_idx, is_buy, atr_value):
    entry_price = df["close"].iloc[entry_idx]
    sl_dist = atr_value * ATR_MULTIPLIER_SL
    tp_dist = atr_value * ATR_MULTIPLIER_TP

    if is_buy:
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist

    for i in range(entry_idx + 1, len(df)):
        high = df["high"].iloc[i]
        low  = df["low"].iloc[i]

        if is_buy:
            if low <= sl_price:
                return ((sl_price - entry_price) / entry_price) * 100, "SL"
            if high >= tp_price:
                return ((tp_price - entry_price) / entry_price) * 100, "TP"
        else:
            if high >= sl_price:
                return ((entry_price - sl_price) / entry_price) * 100, "SL"
            if low <= tp_price:
                return ((entry_price - tp_price) / entry_price) * 100, "TP"

    return None, "OPEN"

# ─── RUN BACKTEST FOR ONE SYMBOL ─────────────────────
def backtest_symbol(symbol, is_futures):
    df_1h = get_historical(symbol, LTF_INTERVAL, is_futures)
    df_4h = get_historical(symbol, HTF_INTERVAL, is_futures)

    if df_1h is None or df_4h is None or len(df_1h) < 250 or len(df_4h) < 250:
        print(f"  ⚠️ Not enough data for {symbol}, skipping")
        return []

    df_1h = add_indicators(df_1h)
    df_4h = add_indicators(df_4h)

    trades = []
    adx_threshold = 20

    for i in range(200, len(df_1h) - 1):
        row = df_1h.iloc[i]

        if pd.isna(row["rsi"]) or pd.isna(row["adx"]) or pd.isna(row["atr"]):
            continue
        if FILTER_MODE == "H" and (pd.isna(row["stoch_k"]) or pd.isna(row["stoch_d"])):
            continue

        matching_4h = df_4h[df_4h["time"] <= row["time"]]
        if len(matching_4h) < 60:
            continue
        idx_4h = matching_4h.index[-1]
        row_4h = df_4h.loc[idx_4h]

        if pd.isna(row_4h["ema50"]):
            continue

        prev_obv_1h = df_1h["obv"].iloc[i-1]
        htf_trend_bull = row_4h["close"] > row_4h["ema50"]
        htf_trend_bear = row_4h["close"] < row_4h["ema50"]

        rsi_buy_thresh, rsi_sell_thresh = 45, 55
        if FILTER_MODE == "A":
            atr_pct = (row["atr"] / row["close"]) * 100
            rsi_buy_thresh  = 40 + atr_pct
            rsi_sell_thresh = 60 - atr_pct

        if FILTER_MODE == "I_PURE":
            base_buy  = True
            base_sell = True
        else:
            base_buy = (row["rsi"] < rsi_buy_thresh and row["macd"] > row["macd_sig"] and
                        row["obv"] > prev_obv_1h and row["adx"] > adx_threshold)
            base_sell = (row["rsi"] > rsi_sell_thresh and row["macd"] < row["macd_sig"] and
                         row["obv"] < prev_obv_1h and row["adx"] > adx_threshold)

        extra_buy_ok, extra_sell_ok = True, True

        if FILTER_MODE == "B":
            extra_buy_ok  = row["plus_di"] > row["minus_di"]
            extra_sell_ok = row["minus_di"] > row["plus_di"]

        elif FILTER_MODE == "C":
            vol_ok = row["volume"] > row["vol_avg20"]
            extra_buy_ok  = vol_ok and check_obv_divergence_bull(df_1h, i)
            extra_sell_ok = vol_ok and check_obv_divergence_bear(df_1h, i)

        elif FILTER_MODE == "D":
            widening = row["bb_width"] > row["bb_width_avg"]
            extra_buy_ok  = widening
            extra_sell_ok = widening

        elif FILTER_MODE == "E":
            h0 = df_1h["macd_hist"].iloc[i]
            h1 = df_1h["macd_hist"].iloc[i-1]
            h2 = df_1h["macd_hist"].iloc[i-2]
            extra_buy_ok  = h0 > h1 > h2
            extra_sell_ok = h0 < h1 < h2

        elif FILTER_MODE == "F":
            extra_buy_ok  = row["close"] > row["swing_low_recent"]
            extra_sell_ok = row["close"] < row["swing_high_recent"]

        elif FILTER_MODE == "G":
            extra_buy_ok  = row["ema50_slope"] > 0
            extra_sell_ok = row["ema50_slope"] < 0

        elif FILTER_MODE == "H":
            crossed_up, crossed_down = False, False
            was_oversold, was_overbought = False, False
            for j in range(max(0, i-5), i+1):
                k_now, d_now   = df_1h["stoch_k"].iloc[j], df_1h["stoch_d"].iloc[j]
                k_prev, d_prev = df_1h["stoch_k"].iloc[j-1], df_1h["stoch_d"].iloc[j-1]
                if pd.isna(k_now) or pd.isna(d_now) or pd.isna(k_prev) or pd.isna(d_prev):
                    continue
                if k_prev <= d_prev and k_now > d_now:
                    crossed_up = True
                if k_prev >= d_prev and k_now < d_now:
                    crossed_down = True
                if k_now < 20:
                    was_oversold = True
                if k_now > 80:
                    was_overbought = True
            extra_buy_ok  = crossed_up and was_oversold
            extra_sell_ok = crossed_down and was_overbought

        elif FILTER_MODE in ["I", "I_PURE"]:
            struct_1h = get_market_structure_at(df_1h, i)
            struct_4h = get_market_structure_at(df_4h, idx_4h)
            bull_1h = struct_1h in ["HH+HL", "HL"]
            bear_1h = struct_1h in ["LL+LH", "LH"]
            bull_4h = struct_4h in ["HH+HL", "HL"]
            bear_4h = struct_4h in ["LL+LH", "LH"]
            extra_buy_ok  = bull_1h and bull_4h
            extra_sell_ok = bear_1h and bear_4h

        buy_1h  = base_buy and extra_buy_ok
        sell_1h = base_sell and extra_sell_ok

        if FILTER_MODE == "I_PURE":
            confirmed_buy  = buy_1h
            confirmed_sell = sell_1h
        else:
            confirmed_buy  = buy_1h and htf_trend_bull
            confirmed_sell = sell_1h and htf_trend_bear

        if confirmed_buy or confirmed_sell:
            is_buy = confirmed_buy
            pnl_pct, exit_type = simulate_trade(df_1h, i, is_buy, row["atr"])
            if pnl_pct is not None:
                trades.append({
                    "symbol": symbol,
                    "time": row["time"],
                    "side": "BUY" if is_buy else "SELL",
                    "pnl_pct": pnl_pct,
                    "exit": exit_type
                })

    return trades

# ─── ANALYZE RESULTS ─────────────────────────────────
def analyze(trades, label):
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")

    if not trades:
        print("  No trades generated.")
        return

    df = pd.DataFrame(trades)
    total = len(df)
    wins  = df[df["pnl_pct"] > 0]
    losses = df[df["pnl_pct"] <= 0]

    win_rate = len(wins) / total * 100
    avg_win  = wins["pnl_pct"].mean() if len(wins) > 0 else 0
    avg_loss = losses["pnl_pct"].mean() if len(losses) > 0 else 0

    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

    df_sorted = df.sort_values("time").reset_index(drop=True)
    streak = 0
    worst_streak = 0
    for pnl in df_sorted["pnl_pct"]:
        if pnl <= 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0

    print(f"  Total Trades       : {total}")
    print(f"  Win Rate            : {win_rate:.1f}%")
    print(f"  Avg Win             : {avg_win:.2f}%")
    print(f"  Avg Loss            : {avg_loss:.2f}%")
    print(f"  Expectancy/Trade    : {expectancy:.3f}%")
    print(f"  Worst Losing Streak : {worst_streak} in a row")

    print(f"\n  By Symbol:")
    for sym in df["symbol"].unique():
        sub = df[df["symbol"] == sym]
        sub_wr = (sub["pnl_pct"] > 0).mean() * 100
        print(f"    {sym}: {len(sub)} trades, {sub_wr:.1f}% win rate")

    print(f"\n  By Side (Long vs Short):")
    for side in df["side"].unique():
        sub = df[df["side"] == side]
        sub_wr = (sub["pnl_pct"] > 0).mean() * 100
        print(f"    {side}: {len(sub)} trades, {sub_wr:.1f}% win rate")

# ─── MAIN ─────────────────────────────────────────────
def main():
    print(f"📊 Backtesting over last {BACKTEST_DAYS} days...")
    print(f"⏱️  Timeframe Mode: {TIMEFRAME_MODE}")
    print(f"🔍 Filter Mode: {FILTER_MODE}")
    print(f"📡 Fetching historical data (this may take a minute)...\n")

    all_symbols = [(s, False) for s in SPOT_SYMBOLS] + [(s, True) for s in FUTURES_SYMBOLS]

    trades = []
    for symbol, is_futures in all_symbols:
        print(f"  Processing {symbol}...")
        trades += backtest_symbol(symbol, is_futures)

    analyze(trades, f"RESULTS [{TIMEFRAME_MODE}] [Filter: {FILTER_MODE}]")

    print(f"\n{'='*50}")
    print("  ⚠️ IMPORTANT NOTES")
    print(f"{'='*50}")
    print("  - No trading fees or slippage simulated")
    print("  - Trailing stop logic NOT included here (simplified)")
    print("  - Past performance does not guarantee future results")

if __name__ == "__main__":
    main()