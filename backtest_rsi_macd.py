# backtest_rsi_macd.py
# Faithful backtest of the LIVE bot's strategy (bot.py get_signal = "Filter A+E"):
#   RSI + MACD cross + OBV + ADX + MACD-hist slope, filtered by EMA-50 HTF trend,
#   exited with the bot's ATR stop/target + trailing stop.
# Same basis as the ZigZag tests: BTC + HYPE as spot, $1000 compounding, 0.20% spot fee.
import os
import pandas as pd
import numpy as np
from datetime import timedelta
from binance.client import Client
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange
from ta.momentum import RSIIndicator
from ta.volume import OnBalanceVolumeIndicator

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".klines_cache")
SYMBOLS   = [("BTCUSDT", False), ("HYPEUSDT", True)]   # traded as spot
DAYS      = 300
LTF = Client.KLINE_INTERVAL_1HOUR     # bot's backtested timeframe
HTF = Client.KLINE_INTERVAL_4HOUR

# bot.py constants (verbatim)
ADX_THRESHOLD = 20
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0
TRAILING_STOP_ACTIVATE = 0.02
TRAILING_STOP_DISTANCE = 0.015

SPOT_FEE = 0.20
START_CAPITAL = 1000.0

client = Client()

def get_historical(symbol, interval, is_futures=False, days=DAYS):
    os.makedirs(CACHE_DIR, exist_ok=True)
    fpath = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{'fut' if is_futures else 'spot'}_{days}d.parquet")
    if os.path.exists(fpath):
        return pd.read_parquet(fpath)
    start_str = f"{days} days ago UTC"
    klines = (client.futures_historical_klines(symbol, interval, start_str) if is_futures
              else client.get_historical_klines(symbol, interval, start_str))
    if not klines: return None
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    try: df.to_parquet(fpath)
    except Exception: pass
    return df

def compute_signals(df):
    """Replicate bot.get_signal() per-bar (causal). Returns arrays buy[i], sell[i], atr[i]."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    rsi  = RSIIndicator(close, 14).rsi()
    macd = MACD(close); macd_line = macd.macd(); macd_sig = macd.macd_signal(); macd_hist = macd.macd_diff()
    adx  = ADXIndicator(high, low, close, 14).adx()
    obv  = OnBalanceVolumeIndicator(close, vol).on_balance_volume()
    atr  = AverageTrueRange(high, low, close, 14).average_true_range()
    atr_pct = (atr/close)*100
    rsi_buy_t  = 40 + atr_pct
    rsi_sell_t = 60 - atr_pct
    base_buy  = (rsi < rsi_buy_t)  & (macd_line > macd_sig) & (obv > obv.shift(1)) & (adx > ADX_THRESHOLD)
    base_sell = (rsi > rsi_sell_t) & (macd_line < macd_sig) & (obv < obv.shift(1)) & (adx > ADX_THRESHOLD)
    hist_rising  = (macd_hist > macd_hist.shift(1)) & (macd_hist.shift(1) > macd_hist.shift(2))
    hist_falling = (macd_hist < macd_hist.shift(1)) & (macd_hist.shift(1) < macd_hist.shift(2))
    buy  = (base_buy  & hist_rising).values
    sell = (base_sell & hist_falling).values
    return buy, sell, atr.values

def simulate_exit(highs, lows, closes, entry_idx, is_buy, atr):
    """Bot's ATR SL/TP + trailing stop, bar-by-bar (causal). SL checked before TP if both hit."""
    entry = closes[entry_idx]
    sl_pct = (atr*ATR_MULTIPLIER_SL)/entry if atr else 0.03
    tp_pct = (atr*ATR_MULTIPLIER_TP)/entry if atr else 0.08
    if is_buy:
        sl = entry*(1-sl_pct); tp = entry*(1+tp_pct); best = entry
    else:
        sl = entry*(1+sl_pct); tp = entry*(1-tp_pct); best = entry
    activated = False
    for i in range(entry_idx+1, len(closes)):
        hi, lo, cl = highs[i], lows[i], closes[i]
        if is_buy:
            if lo <= sl: return ((sl-entry)/entry)*100, ("TRAIL" if activated else "SL"), i
            if hi >= tp: return ((tp-entry)/entry)*100, "TP", i
            pnl = (cl-entry)/entry
            if pnl >= TRAILING_STOP_ACTIVATE and not activated:
                activated = True; sl = max(sl, cl*(1-TRAILING_STOP_DISTANCE))
            if activated and cl > best:
                best = cl; sl = max(sl, best*(1-TRAILING_STOP_DISTANCE))
        else:
            if hi >= sl: return ((entry-sl)/entry)*100, ("TRAIL" if activated else "SL"), i
            if lo <= tp: return ((entry-tp)/entry)*100, "TP", i
            pnl = (entry-cl)/entry
            if pnl >= TRAILING_STOP_ACTIVATE and not activated:
                activated = True; sl = min(sl, cl*(1+TRAILING_STOP_DISTANCE))
            if activated and cl < best:
                best = cl; sl = min(sl, best*(1+TRAILING_STOP_DISTANCE))
    return None, "OPEN", None

def backtest_symbol(sym, fut, ltf_iv=LTF, htf_iv=HTF):
    ltf = get_historical(sym, ltf_iv, fut); htf = get_historical(sym, htf_iv, fut)
    if ltf is None or htf is None: return []
    buy, sell, atr = compute_signals(ltf)
    ema50 = EMAIndicator(htf["close"], 50).ema_indicator().values
    htf_close = htf["close"].values
    htf_bull = htf_close > ema50           # bot.get_htf_trend_ema
    lt = ltf["time"].values; ht = htf["time"].values
    hidx_for = np.searchsorted(ht, lt, side="right") - 1
    highs = ltf["high"].values; lows = ltf["low"].values; closes = ltf["close"].values
    times = ltf["time"].values
    trades = []; in_trade_until = -1
    for i in range(60, len(ltf)-1):
        if i <= in_trade_until: continue          # one position at a time per symbol
        if np.isnan(atr[i]): continue
        hidx = hidx_for[i]
        if hidx < 50: continue
        bull = bool(htf_bull[hidx]); bear = not bull
        cbuy  = buy[i]  and bull
        csell = sell[i] and bear
        if not (cbuy or csell): continue
        pnl, ex, xi = simulate_exit(highs, lows, closes, i, cbuy, atr[i])
        trades.append({"symbol":sym, "time":pd.Timestamp(times[i]), "side":"BUY" if cbuy else "SELL",
                       "pnl_pct":pnl, "exit":ex})
        if xi is not None: in_trade_until = xi
        else: break                                # open trade to end of data
    return trades

def report(trades, label):
    print(f"\n{'='*60}\n  {label}\n{'='*60}")
    closed = [t for t in trades if t["pnl_pct"] is not None]
    open_n = len(trades) - len(closed)
    if not closed:
        print(f"  No closed trades. (open: {open_n})"); return
    bal = START_CAPITAL; wins = 0
    pnls = []
    for t in sorted(closed, key=lambda x:x["time"]):
        net = t["pnl_pct"] - SPOT_FEE
        bal *= (1+net/100.0); pnls.append(net); wins += 1 if net>0 else 0
    n = len(closed)
    gross = np.mean([t["pnl_pct"] for t in closed])
    print(f"  Closed trades : {n}   (still open: {open_n})")
    print(f"  Win rate      : {wins/n*100:.1f}%  ({wins}W / {n-wins}L)")
    print(f"  BEP/trade     : {gross:+.3f}%   (gross expectancy = break-even fee)")
    print(f"  Net/trade     : {np.mean(pnls):+.3f}%  (after {SPOT_FEE}% spot fee)")
    print(f"  $1000 -> ${bal:,.2f}   ({(bal-START_CAPITAL)/START_CAPITAL*100:+.2f}%)")
    by = {}
    for t in closed: by.setdefault(t["symbol"], []).append(t)
    for s, ts in by.items():
        w = sum(1 for t in ts if t["pnl_pct"]>SPOT_FEE)
        print(f"    {s}: {len(ts)} trades, {w/len(ts)*100:.1f}% win")

def main():
    print(f"LIVE BOT STRATEGY backtest (RSI+MACD+OBV+ADX 'Filter A+E') | {DAYS}d")
    print(f"BTC + HYPE as spot | $1000 compounding | {SPOT_FEE}% spot fee | exit: ATR SL{ATR_MULTIPLIER_SL}/TP{ATR_MULTIPLIER_TP} + trailing")

    runs = [
        ("1H entry + 4H EMA50 (bot default)", Client.KLINE_INTERVAL_1HOUR,     Client.KLINE_INTERVAL_4HOUR),
        ("30M entry + 4H EMA50 (matches ZigZag)", Client.KLINE_INTERVAL_30MINUTE, Client.KLINE_INTERVAL_4HOUR),
    ]
    for label, ltf_iv, htf_iv in runs:
        all_trades = []
        for sym, fut in SYMBOLS:
            all_trades += backtest_symbol(sym, fut, ltf_iv, htf_iv)
        report(all_trades, f"{label}  —  FULL 300 DAYS")
        cutoff = pd.Timestamp.now(tz="UTC").tz_localize(None) - timedelta(days=14)
        recent = [t for t in all_trades if t["time"] >= cutoff]
        report(recent, f"{label}  —  LAST 14 DAYS")

if __name__ == "__main__":
    main()
