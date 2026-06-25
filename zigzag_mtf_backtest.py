# zigzag_mtf_backtest.py
# Multi-timeframe ZigZag: 4H sets the BIAS, a lower TF (15M / 30M / both) CONFIRMS the entry.
# Causal, non-repainting. BTC + HYPE only.
import pandas as pd
from binance.client import Client

SYMBOLS = [("BTCUSDT", False), ("HYPEUSDT", True)]
BACKTEST_DAYS = 300

ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0

ZIGZAG_DEVIATION = 3.0     # % reversal to confirm a pivot
FRESH_ONLY = True          # only fire the candle the entry-TF structure label first changes

client = Client()

# ─── DATA ─────────────────────────────────────────────
def get_historical(symbol, interval, is_futures=False, days=BACKTEST_DAYS):
    start_str = f"{days} days ago UTC"
    try:
        if is_futures:
            klines = client.futures_historical_klines(symbol, interval, start_str)
        else:
            klines = client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        print(f"  WARN could not fetch {symbol} {interval}: {e}")
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

# ─── ZIGZAG (causal) ──────────────────────────────────
def compute_zigzag_pivots(df, deviation_pct):
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

BULL = ("HH+HL", "HL")
BEAR = ("LL+LH", "LH")

# ─── TRADE SIM (on the entry/confirmation TF) ─────────
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

# ─── MTF BACKTEST ─────────────────────────────────────
# bias_df  = 4H (direction filter)
# entry_df = finest confirm TF (where we enter & the "fresh" trigger lives)
# also_df  = optional second confirm TF that must agree (for the "15M+30M together" mode)
def backtest_symbol(symbol, bias_df, entry_df, also_df=None):
    entry_df = entry_df.copy()
    entry_df["atr"] = atr_series(entry_df)

    zz_bias  = compute_zigzag_pivots(bias_df, ZIGZAG_DEVIATION)
    zz_entry = compute_zigzag_pivots(entry_df, ZIGZAG_DEVIATION)
    zz_also  = compute_zigzag_pivots(also_df, ZIGZAG_DEVIATION) if also_df is not None else None

    trades = []
    prev_struct = None

    for i in range(50, len(entry_df)-1):
        if pd.isna(entry_df["atr"].iloc[i]):
            continue
        t = entry_df["time"].iloc[i]

        # most-recent CLOSED higher-TF candle at this moment (causal)
        m_bias = bias_df[bias_df["time"] <= t]
        if len(m_bias) < 10:
            continue
        s_bias = structure_at(zz_bias, m_bias.index[-1])

        s_entry = structure_at(zz_entry, i)
        fresh = (s_entry != prev_struct)
        prev_struct = s_entry
        if FRESH_ONLY and not fresh:
            continue

        # second confirm TF (optional)
        s_also = None
        if also_df is not None:
            m_also = also_df[also_df["time"] <= t]
            if len(m_also) < 10:
                continue
            s_also = structure_at(zz_also, m_also.index[-1])

        bull = (s_bias in BULL) and (s_entry in BULL) and (s_also in BULL if also_df is not None else True)
        bear = (s_bias in BEAR) and (s_entry in BEAR) and (s_also in BEAR if also_df is not None else True)

        if bull or bear:
            is_buy = bull
            pnl, ex = simulate_trade(entry_df, i, is_buy, entry_df["atr"].iloc[i])
            if pnl is not None:
                trades.append({"symbol":symbol,"time":t,
                               "side":"BUY" if is_buy else "SELL","pnl_pct":pnl,"exit":ex})
    return trades

# ─── ANALYZE ──────────────────────────────────────────
def analyze(trades, label):
    print(f"\n{'='*54}\n  {label}\n{'='*54}")
    if not trades:
        print("  No trades generated."); return
    df = pd.DataFrame(trades)
    total = len(df)
    wins = df[df["pnl_pct"]>0]; losses = df[df["pnl_pct"]<=0]
    wr = len(wins)/total*100
    aw = wins["pnl_pct"].mean() if len(wins) else 0
    al = losses["pnl_pct"].mean() if len(losses) else 0
    exp = (wr/100*aw) + ((1-wr/100)*al)
    bep = (-al)/(aw-al)*100 if (aw-al) != 0 else 0   # breakeven win-rate for this R:R
    ds = df.sort_values("time").reset_index(drop=True)
    streak=worst=0
    for p in ds["pnl_pct"]:
        if p<=0: streak+=1; worst=max(worst,streak)
        else: streak=0
    print(f"  Total Trades        : {total}")
    print(f"  Win Rate            : {wr:.1f}%")
    print(f"  Breakeven Win Rate  : {bep:.1f}%   (margin: {wr-bep:+.1f} pts)")
    print(f"  Avg Win             : {aw:.2f}%")
    print(f"  Avg Loss            : {al:.2f}%")
    print(f"  Expectancy/Trade    : {exp:.3f}%")
    print(f"  Total (raw sum)     : {df['pnl_pct'].sum():+.1f}%")
    print(f"  Worst Losing Streak : {worst} in a row")
    print(f"  By Symbol:")
    for sym in df["symbol"].unique():
        sub = df[df["symbol"]==sym]
        print(f"    {sym}: {len(sub)} trades, {(sub['pnl_pct']>0).mean()*100:.1f}% win rate")
    print(f"  By Side:")
    for side in df["side"].unique():
        sub = df[df["side"]==side]
        print(f"    {side}: {len(sub)} trades, {(sub['pnl_pct']>0).mean()*100:.1f}% win rate")

# ─── MAIN ─────────────────────────────────────────────
def main():
    print(f"ZigZag MTF Backtest | {BACKTEST_DAYS} days | Dev {ZIGZAG_DEVIATION}% | Fresh-only: {FRESH_ONLY}")
    print("Bias = 4H structure | Confirmation = lower TF structure\n")

    # fetch once per symbol
    data = {}
    for sym, fut in SYMBOLS:
        print(f"  Fetching {sym} (4H / 30M / 15M)...")
        data[sym] = {
            "fut":  fut,
            "4h":   get_historical(sym, Client.KLINE_INTERVAL_4HOUR,   fut),
            "30m":  get_historical(sym, Client.KLINE_INTERVAL_30MINUTE, fut),
            "15m":  get_historical(sym, Client.KLINE_INTERVAL_15MINUTE, fut),
        }

    configs = [
        ("4H bias + 15M confirm",        "15m", None),
        ("4H bias + 30M confirm",        "30m", None),
        ("4H bias + 15M AND 30M confirm","15m", "30m"),
    ]

    for label, entry_key, also_key in configs:
        trades = []
        for sym, fut in SYMBOLS:
            d = data[sym]
            if d["4h"] is None or d[entry_key] is None or (also_key and d[also_key] is None):
                print(f"  skip {sym} ({label}) - missing data"); continue
            if len(d[entry_key]) < 100:
                print(f"  skip {sym} ({label}) - too few entry candles"); continue
            trades += backtest_symbol(sym, d["4h"], d[entry_key],
                                      d[also_key] if also_key else None)
        analyze(trades, label)

    print(f"\n{'='*54}\n  NOTE: no fees/slippage. Past results != future.\n{'='*54}")

if __name__ == "__main__":
    main()
