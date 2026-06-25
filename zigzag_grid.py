# zigzag_grid.py
# 4H bias + 30M confirm, deviation 5%. Tune EXIT + STRUCTURE knobs (no new indicators).
# Grid: TP/SL ratio  x  strict/loose structure  x  ATR-stop / structure-stop.
# Each combo run through a $1000 account sim (2% risk, 0.10% fees, compounding).
import pandas as pd
from binance.client import Client

SYMBOLS = [("BTCUSDT", False), ("HYPEUSDT", True)]
BACKTEST_DAYS = 600
DEVIATION = 5.0
SL_ATR = 1.5                       # stop distance in ATR (ATR-stop mode)
RR_RATIOS = [1.0, 1.5, 2.0, 3.0]   # TP = ratio * SL distance
START_BALANCE = 1000.0
RISK = 0.02                        # 2% risk per trade
FEE = 0.10                         # round-trip fee %

client = Client()

def get_historical(symbol, interval, is_futures=False, days=BACKTEST_DAYS):
    start_str = f"{days} days ago UTC"
    try:
        if is_futures:
            klines = client.futures_historical_klines(symbol, interval, start_str)
        else:
            klines = client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        print(f"  WARN {symbol} {interval}: {e}"); return None
    if not klines: return None
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume",
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
    highs, lows = df["high"].values, df["low"].values
    n = len(df); pivots = []; trend = None
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

def structure_at(pivots, lim):
    conf = [p for p in pivots if p[3] <= lim]
    hs = [p[1] for p in conf if p[2]=='high']
    ls = [p[1] for p in conf if p[2]=='low']
    if len(hs) >= 2 and len(ls) >= 2:
        hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
        ll, lh = ls[-1] < ls[-2], hs[-1] < hs[-2]
        if hh and hl: return "HH+HL"
        elif ll and lh: return "LL+LH"
        elif hl: return "HL"
        elif lh: return "LH"
    return "neutral"

def last_pivot_price(pivots, lim, kind):
    conf = [p for p in pivots if p[3] <= lim and p[2]==kind]
    return conf[-1][1] if conf else None

def sim_exit(df, entry_idx, is_buy, sl_price, tp_price):
    entry = df["close"].iloc[entry_idx]
    for i in range(entry_idx+1, len(df)):
        hi, lo = df["high"].iloc[i], df["low"].iloc[i]
        if is_buy:
            if lo <= sl_price: return ((sl_price-entry)/entry)*100
            if hi >= tp_price: return ((tp_price-entry)/entry)*100
        else:
            if hi >= sl_price: return ((entry-sl_price)/entry)*100
            if lo <= tp_price: return ((entry-tp_price)/entry)*100
    return None

# bull/bear membership depending on strictness
def dir_match(struct, want_bull, strict):
    if strict:
        return struct == ("HH+HL" if want_bull else "LL+LH")
    return struct in (("HH+HL","HL") if want_bull else ("LL+LH","LH"))

def backtest_symbol(symbol, bias_df, entry_df, zz_bias, zz_entry, rr, strict, struct_stop):
    trades = []
    prev_struct = None
    atr = entry_df["atr"].values
    for i in range(50, len(entry_df)-1):
        if pd.isna(atr[i]): continue
        t = entry_df["time"].iloc[i]
        m_bias = bias_df[bias_df["time"] <= t]
        if len(m_bias) < 10: continue
        bias_lim = m_bias.index[-1]
        s_bias = structure_at(zz_bias, bias_lim)
        s_entry = structure_at(zz_entry, i)
        fresh = (s_entry != prev_struct); prev_struct = s_entry
        if not fresh: continue

        bull = dir_match(s_bias, True, strict) and dir_match(s_entry, True, strict)
        bear = dir_match(s_bias, False, strict) and dir_match(s_entry, False, strict)
        if not (bull or bear): continue
        is_buy = bull
        entry = entry_df["close"].iloc[i]

        # stop distance
        if struct_stop:
            piv = last_pivot_price(zz_entry, i, 'low' if is_buy else 'high')
            if piv is None: continue
            sl_dist = (entry - piv) if is_buy else (piv - entry)
            if sl_dist <= 0:  # pivot on wrong side, fall back to ATR
                sl_dist = atr[i] * SL_ATR
        else:
            sl_dist = atr[i] * SL_ATR
        if sl_dist <= 0: continue

        tp_dist = sl_dist * rr
        sl_price = entry - sl_dist if is_buy else entry + sl_dist
        tp_price = entry + tp_dist if is_buy else entry - tp_dist
        pnl = sim_exit(entry_df, i, is_buy, sl_price, tp_price)
        if pnl is None: continue
        trades.append({"time":t, "pnl_pct":pnl, "sl_dist_pct":sl_dist/entry})
    return trades

def run_account(trades):
    bal = START_BALANCE
    for tr in sorted(trades, key=lambda x: x["time"]):
        net = tr["pnl_pct"] - FEE          # price move % net of fees
        risk_amt = bal * RISK
        pos = min(risk_amt / tr["sl_dist_pct"], bal)   # bot's sizing rule (cap at balance)
        bal += pos * (net/100.0)
        if bal <= 0: return 0.0
    return bal

def metrics(trades):
    if not trades: return 0, 0.0, 0.0, START_BALANCE
    n = len(trades)
    wins = sum(1 for t in trades if (t["pnl_pct"]-FEE) > 0)
    wr = wins/n*100
    expR = sum((t["pnl_pct"]-FEE)/100.0 / t["sl_dist_pct"] for t in trades)/n
    return n, wr, expR, run_account(trades)

def main():
    print(f"4H bias + 30M confirm | dev {DEVIATION}% | {BACKTEST_DAYS}d | BTC+HYPE")
    print(f"Account sim: ${START_BALANCE:.0f} start, {RISK*100:.0f}% risk/trade, {FEE}% fees, compounding\n")
    data = {}
    for sym, fut in SYMBOLS:
        print(f"  Fetching {sym} (4H / 30M)...")
        b = get_historical(sym, Client.KLINE_INTERVAL_4HOUR, fut)
        e = get_historical(sym, Client.KLINE_INTERVAL_30MINUTE, fut)
        if e is not None: e = e.copy(); e["atr"] = atr_series(e)
        data[sym] = {"4h": b, "30m": e,
                     "zzb": compute_zigzag_pivots(b, DEVIATION) if b is not None else None,
                     "zze": compute_zigzag_pivots(e, DEVIATION) if e is not None else None}
    print()
    hdr = f"  {'R:R':>4} | {'Struct':>6} | {'Stop':>6} | {'Trades':>6} | {'Win%':>5} | {'ExpR':>7} | {'$1000 ->':>9}"
    print(hdr); print("  " + "-"*(len(hdr)-2))
    for strict in [False, True]:
        for struct_stop in [False, True]:
            for rr in RR_RATIOS:
                allt = []
                for sym, fut in SYMBOLS:
                    d = data[sym]
                    if d["4h"] is None or d["30m"] is None: continue
                    allt += backtest_symbol(sym, d["4h"], d["30m"], d["zzb"], d["zze"],
                                            rr, strict, struct_stop)
                n, wr, expR, bal = metrics(allt)
                s_lbl = "strict" if strict else "loose"
                st_lbl = "struct" if struct_stop else "ATR"
                print(f"  {rr:>4.1f} | {s_lbl:>6} | {st_lbl:>6} | {n:>6} | {wr:>4.1f}% | {expR:>+6.3f}R | ${bal:>8.0f}")
    print("\n  ExpR = avg profit per trade in units of risked amount (after fees)")
    print("  $1000 -> = ending balance after compounding all trades in time order")
    print("  Win% here counts a trade as a win only if it cleared the fee.")

if __name__ == "__main__":
    main()
