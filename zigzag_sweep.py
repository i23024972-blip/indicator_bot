# zigzag_sweep.py
# Focus: 4H bias + 30M confirmation. Sweep ZigZag deviation, apply round-trip fees.
import pandas as pd
from binance.client import Client

SYMBOLS = [("BTCUSDT", False), ("HYPEUSDT", True)]    # HYPE candles pulled from futures feed,
                                                       # but traded as spot (spot fee, no leverage/funding)
BACKTEST_DAYS = 300

ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0

DEVIATIONS = [3.0, 5.0, 8.0]      # % reversal to confirm a pivot — swept
FEE_LEVELS = [0.0, 0.10, 0.20]    # round-trip cost % (0 = gross, 0.10 ~ futures, 0.20 ~ spot taker)
FRESH_ONLY = True

START_CAPITAL = 1000.0            # example account size in $
RISK_PCT      = 100.0             # % of equity deployed per trade (100 = full account, compounding)

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

# ─── 4H bias + 30M confirm ────────────────────────────
def backtest_symbol(symbol, bias_df, entry_df, deviation):
    entry_df = entry_df.copy()
    entry_df["atr"] = atr_series(entry_df)
    zz_bias  = compute_zigzag_pivots(bias_df, deviation)
    zz_entry = compute_zigzag_pivots(entry_df, deviation)

    trades = []
    prev_struct = None
    for i in range(50, len(entry_df)-1):
        if pd.isna(entry_df["atr"].iloc[i]):
            continue
        t = entry_df["time"].iloc[i]
        m_bias = bias_df[bias_df["time"] <= t]
        if len(m_bias) < 10:
            continue
        s_bias = structure_at(zz_bias, m_bias.index[-1])

        s_entry = structure_at(zz_entry, i)
        fresh = (s_entry != prev_struct)
        prev_struct = s_entry
        if FRESH_ONLY and not fresh:
            continue

        bull = (s_bias in BULL) and (s_entry in BULL)
        bear = (s_bias in BEAR) and (s_entry in BEAR)
        if bull or bear:
            is_buy = bull
            pnl, ex = simulate_trade(entry_df, i, is_buy, entry_df["atr"].iloc[i])
            if pnl is not None:
                trades.append({"symbol":symbol,"time":t,"side":"BUY" if is_buy else "SELL",
                               "pnl_pct":pnl,"exit":ex})
    return trades

def stats(trades, fee):
    if not trades:
        return None
    df = pd.DataFrame(trades).copy()
    df["net"] = df["pnl_pct"] - fee     # round-trip fee deducted per trade
    total = len(df)
    wins = df[df["net"]>0]
    wr = len(wins)/total*100
    exp = df["net"].mean()
    return {"total":total, "wr":wr, "exp":exp, "sum":df["net"].sum()}

def equity(trades, fee, start=START_CAPITAL, risk_pct=RISK_PCT):
    """Time-ordered compounding equity curve from a $start account.
       Each trade deploys risk_pct% of current equity; net = price move minus round-trip fee."""
    if not trades:
        return start, 0
    df = pd.DataFrame(trades).sort_values("time")
    bal = start
    peak = start
    max_dd = 0.0
    for pnl in df["pnl_pct"]:
        net = (pnl - fee) / 100.0
        bal *= (1 + net * risk_pct/100.0)
        if bal <= 0:
            bal = 0.0; break          # account blown
        peak = max(peak, bal)
        max_dd = max(max_dd, (peak - bal) / peak * 100)
    return bal, max_dd

# Timeframe pairs to test: (label, bias_interval, entry_interval)
TIMEFRAME_PAIRS = [
    ("1D bias + 1H confirm",  Client.KLINE_INTERVAL_1DAY,   Client.KLINE_INTERVAL_1HOUR),
    ("1H bias + 15M confirm", Client.KLINE_INTERVAL_1HOUR,   Client.KLINE_INTERVAL_15MINUTE),
    ("4H bias + 30M confirm", Client.KLINE_INTERVAL_4HOUR,   Client.KLINE_INTERVAL_30MINUTE),
]

SPOT_FEE = 0.20   # round-trip spot cost % used for the $ simulation

_CACHE = {}
def fetch(sym, interval, fut):
    key = (sym, interval, fut)
    if key not in _CACHE:
        _CACHE[key] = get_historical(sym, interval, fut)
    return _CACHE[key]

def run_pair(bias_iv, entry_iv):
    """Return {dev: trades_list} aggregated across symbols for one timeframe pair."""
    out = {}
    for dev in DEVIATIONS:
        trades = []
        for sym, fut in SYMBOLS:
            bias_df  = fetch(sym, bias_iv, fut)
            entry_df = fetch(sym, entry_iv, fut)
            if bias_df is None or entry_df is None:
                continue
            trades += backtest_symbol(sym, bias_df, entry_df, dev)
        out[dev] = trades
    return out

def main():
    print(f"ZigZag Timeframe Sweep | {BACKTEST_DAYS} days | BTC + HYPE (traded as spot)")
    print(f"R:R = {ATR_MULTIPLIER_TP}:{ATR_MULTIPLIER_SL} ATR | Fresh-only: {FRESH_ONLY} | spot fee {SPOT_FEE:.2f}%\n")

    for label, bias_iv, entry_iv in TIMEFRAME_PAIRS:
        print("=" * 72)
        print(f"  {label}")
        print("=" * 72)
        results = run_pair(bias_iv, entry_iv)

        header = (f"  {'Dev':>4} | {'Trades':>6} | {'WinRate':>7} | {'BEP/trade':>9} | "
                  f"{'exp@spot':>9} | {'$1000 spot':>13}")
        print(header)
        print("  " + "-" * (len(header) - 2))
        for dev in DEVIATIONS:
            trades = results[dev]
            n = len(trades)
            if n == 0:
                print(f"  {dev:>4.0f} | {0:>6} |     n/a |       n/a |       n/a |           n/a")
                continue
            gross = stats(trades, 0.0)        # gross expectancy == break-even fee per trade
            net   = stats(trades, SPOT_FEE)
            bal, dd = equity(trades, SPOT_FEE)
            print(f"  {dev:>4.0f} | {n:>6} | {gross['wr']:>6.1f}% | {gross['exp']:>+8.3f}% | "
                  f"{net['exp']:>+8.3f}% | {('$'+format(bal,',.0f')+' (-'+format(dd,'.0f')+'%)'):>13}")
        print()

    print("  BEP/trade = break-even round-trip fee per trade (the gross expectancy).")
    print("              You make money only if your real round-trip cost is BELOW this.")
    print("  exp@spot  = expectancy per trade after the 0.20% spot fee.")
    print(f"  $1000 spot = final balance from ${START_CAPITAL:,.0f}, compounding, after spot fees (max DD in parens).")

if __name__ == "__main__":
    main()
