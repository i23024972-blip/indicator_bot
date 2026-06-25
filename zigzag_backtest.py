# zigzag_structure_backtest.py - Pure ZigZag LL/LH/HL/HH structure (causal, non-repainting)
import pandas as pd
from binance.client import Client

SPOT_SYMBOLS    = ["BTCUSDT", "XAUTUSDT"]
FUTURES_SYMBOLS = ["HYPEUSDT"]
BACKTEST_DAYS   = 600

ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0

# ZigZag tuning (your Pine script used Depth=12, Dev=5, Backstep=2 — those are MT4-style point
# settings that don't map directly. This uses a % deviation, which is the standard causal equivalent.)
ZIGZAG_DEVIATION = 3.0     # % reversal to confirm a pivot — try 3, 5, 8
FRESH_ONLY       = True    # only fire when structure label FIRST changes (fixes re-firing problem)

client = Client()

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
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df

def atr_series(df, window=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()

def compute_zigzag_pivots(df, deviation_pct):
    """Causal ZigZag: a pivot confirms only after price reverses deviation_pct% from the extreme.
       Returns list of (pivot_idx, price, 'high'/'low', confirm_idx)."""
    highs = df["high"].values
    lows  = df["low"].values
    n = len(df)
    pivots = []
    trend = None
    eh_p, eh_i = highs[0], 0
    el_p, el_i = lows[0], 0
    for i in range(1, n):
        if highs[i] > eh_p: eh_p, eh_i = highs[i], i
        if lows[i]  < el_p: el_p, el_i = lows[i], i
        if trend is None:
            if (eh_p - lows[i]) / eh_p * 100 >= deviation_pct:
                pivots.append((eh_i, eh_p, 'high', i)); trend='down'; el_p, el_i = lows[i], i
            elif (highs[i] - el_p) / el_p * 100 >= deviation_pct:
                pivots.append((el_i, el_p, 'low', i)); trend='up'; eh_p, eh_i = highs[i], i
        elif trend == 'up':
            if (eh_p - lows[i]) / eh_p * 100 >= deviation_pct:
                pivots.append((eh_i, eh_p, 'high', i)); trend='down'; el_p, el_i = lows[i], i
        elif trend == 'down':
            if (highs[i] - el_p) / el_p * 100 >= deviation_pct:
                pivots.append((el_i, el_p, 'low', i)); trend='up'; eh_p, eh_i = highs[i], i
    return pivots

def structure_at(pivots, confirm_limit_idx):
    confirmed = [p for p in pivots if p[3] <= confirm_limit_idx]
    hs = [p[1] for p in confirmed if p[2]=='high']
    ls = [p[1] for p in confirmed if p[2]=='low']
    if len(hs) >= 2 and len(ls) >= 2:
        hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
        ll, lh = ls[-1] < ls[-2], hs[-1] < hs[-2]
        if hh and hl: return "HH+HL"
        elif ll and lh: return "LL+LH"
        elif hl: return "HL"
        elif lh: return "LH"
    return "neutral"

def simulate_trade(df, entry_idx, is_buy, atr_value):
    entry = df["close"].iloc[entry_idx]
    sl_d, tp_d = atr_value*ATR_MULTIPLIER_SL, atr_value*ATR_MULTIPLIER_TP
    sl = entry - sl_d if is_buy else entry + sl_d
    tp = entry + tp_d if is_buy else entry - tp_d
    for i in range(entry_idx+1, len(df)):
        hi, lo = df["high"].iloc[i], df["low"].iloc[i]
        if is_buy:
            if lo <= sl: return ((sl-entry)/entry)*100, "SL"
            if hi >= tp: return ((tp-entry)/entry)*100, "TP"
        else:
            if hi >= sl: return ((entry-sl)/entry)*100, "SL"
            if lo <= tp: return ((entry-tp)/entry)*100, "TP"
    return None, "OPEN"

def backtest_symbol(symbol, is_futures):
    df_1h = get_historical(symbol, Client.KLINE_INTERVAL_1HOUR, is_futures)
    df_4h = get_historical(symbol, Client.KLINE_INTERVAL_4HOUR, is_futures)
    if df_1h is None or df_4h is None or len(df_1h) < 250 or len(df_4h) < 250:
        print(f"  ⚠️ Not enough data for {symbol}, skipping"); return []

    df_1h["atr"] = atr_series(df_1h)
    zz_1h = compute_zigzag_pivots(df_1h, ZIGZAG_DEVIATION)
    zz_4h = compute_zigzag_pivots(df_4h, ZIGZAG_DEVIATION)

    trades = []
    prev_struct_1h = None

    for i in range(50, len(df_1h)-1):
        if pd.isna(df_1h["atr"].iloc[i]):
            continue
        matching_4h = df_4h[df_4h["time"] <= df_1h["time"].iloc[i]]
        if len(matching_4h) < 10:
            continue
        idx_4h = matching_4h.index[-1]

        s1h = structure_at(zz_1h, i)
        s4h = structure_at(zz_4h, idx_4h)

        bull = s1h in ["HH+HL","HL"] and s4h in ["HH+HL","HL"]
        bear = s1h in ["LL+LH","LH"] and s4h in ["LL+LH","LH"]

        # FRESH_ONLY: only fire when 1H structure label just changed this candle
        fresh = (s1h != prev_struct_1h)
        prev_struct_1h = s1h
        if FRESH_ONLY and not fresh:
            continue

        if bull or bear:
            is_buy = bull
            pnl, ex = simulate_trade(df_1h, i, is_buy, df_1h["atr"].iloc[i])
            if pnl is not None:
                trades.append({"symbol":symbol,"time":df_1h["time"].iloc[i],
                               "side":"BUY" if is_buy else "SELL","pnl_pct":pnl,"exit":ex})
    return trades

def analyze(trades, label):
    print(f"\n{'='*50}\n  {label}\n{'='*50}")
    if not trades:
        print("  No trades generated."); return
    df = pd.DataFrame(trades)
    total = len(df)
    wins = df[df["pnl_pct"]>0]; losses = df[df["pnl_pct"]<=0]
    wr = len(wins)/total*100
    aw = wins["pnl_pct"].mean() if len(wins) else 0
    al = losses["pnl_pct"].mean() if len(losses) else 0
    exp = (wr/100*aw) + ((1-wr/100)*al)
    ds = df.sort_values("time").reset_index(drop=True)
    streak=worst=0
    for p in ds["pnl_pct"]:
        if p<=0: streak+=1; worst=max(worst,streak)
        else: streak=0
    print(f"  Total Trades       : {total}")
    print(f"  Win Rate            : {wr:.1f}%")
    print(f"  Avg Win             : {aw:.2f}%")
    print(f"  Avg Loss            : {al:.2f}%")
    print(f"  Expectancy/Trade    : {exp:.3f}%")
    print(f"  Worst Losing Streak : {worst} in a row")
    print(f"\n  By Symbol:")
    for sym in df["symbol"].unique():
        sub = df[df["symbol"]==sym]
        print(f"    {sym}: {len(sub)} trades, {(sub['pnl_pct']>0).mean()*100:.1f}% win rate")
    print(f"\n  By Side:")
    for side in df["side"].unique():
        sub = df[df["side"]==side]
        print(f"    {side}: {len(sub)} trades, {(sub['pnl_pct']>0).mean()*100:.1f}% win rate")

def main():
    print(f"📊 ZigZag Structure Backtest | {BACKTEST_DAYS} days | Deviation {ZIGZAG_DEVIATION}% | Fresh-only: {FRESH_ONLY}\n")
    all_symbols = [(s,False) for s in SPOT_SYMBOLS] + [(s,True) for s in FUTURES_SYMBOLS]
    trades = []
    for sym, fut in all_symbols:
        print(f"  Processing {sym}...")
        trades += backtest_symbol(sym, fut)
    analyze(trades, "PURE ZIGZAG STRUCTURE (1H+4H agreement)")
    print(f"\n{'='*50}\n  ⚠️ No fees/slippage. Past results ≠ future.\n{'='*50}")

if __name__ == "__main__":
    main()