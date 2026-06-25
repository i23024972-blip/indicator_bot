# zigzag_optimize.py
# Goal: push BEP/trade toward 0.5% on the winning setup (4H bias + 30M entry, deviation 5%).
#   Part A: sweep the R:R ratio (fixed ATR TP/SL).
#   Part B: structure-based exit (let winners run to the opposite ZigZag pivot) + breakeven trail.
# Symbols traded as SPOT (HYPE candles come from the futures feed, but economics are spot).
import pandas as pd
from binance.client import Client

SYMBOLS       = [("BTCUSDT", False), ("HYPEUSDT", True)]
BACKTEST_DAYS = 300
DEVIATION     = 4.0          # mid: more trades than 5%, smaller drawdown than 3%
FRESH_ONLY    = True
SPOT_FEE      = 0.20         # round-trip spot cost %
START_CAPITAL = 1000.0

BIAS_IV  = Client.KLINE_INTERVAL_4HOUR
ENTRY_IV = Client.KLINE_INTERVAL_30MINUTE

# Part A sweep grid
TP_MULTS = [3.0, 4.0, 5.0, 6.0]
SL_MULTS = [1.0, 1.5, 2.0]

# Part B params
BE_TRIGGER  = 0.0           # 0 = breakeven trail OFF (it stopped winners out at scratch)
DISASTER_SL = 1.5           # hard stop in ATR
EXIT_DEV    = 2.0           # smaller deviation for the EXIT pivots, so structure flips faster

client = Client()
BULL = ("HH+HL", "HL")
BEAR = ("LL+LH", "LH")

# ─── DATA ─────────────────────────────────────────────
_CACHE = {}
def get_historical(symbol, interval, is_futures=False, days=BACKTEST_DAYS):
    key = (symbol, interval, is_futures)
    if key in _CACHE:
        return _CACHE[key]
    start_str = f"{days} days ago UTC"
    try:
        if is_futures:
            klines = client.futures_historical_klines(symbol, interval, start_str)
        else:
            klines = client.get_historical_klines(symbol, interval, start_str)
    except Exception as e:
        print(f"  WARN could not fetch {symbol} {interval}: {e}")
        _CACHE[key] = None; return None
    if not klines:
        _CACHE[key] = None; return None
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    _CACHE[key] = df
    return df

def atr_series(df, window=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()

# ─── ZIGZAG (causal) ──────────────────────────────────
def compute_zigzag_pivots(df, deviation_pct):
    highs = df["high"].values; lows = df["low"].values
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

def structure_label_array(df, pivots):
    """Per-bar structure label using only pivots confirmed up to that bar (causal)."""
    n = len(df); labels = ["neutral"]*n
    pj = 0; hs = []; ls = []
    def cur():
        if len(hs) >= 2 and len(ls) >= 2:
            hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
            ll, lh = ls[-1] < ls[-2], hs[-1] < hs[-2]
            if hh and hl: return "HH+HL"
            elif ll and lh: return "LL+LH"
            elif hl: return "HL"
            elif lh: return "LH"
        return "neutral"
    sp = sorted(pivots, key=lambda p: p[3])   # by confirm idx
    for i in range(n):
        while pj < len(sp) and sp[pj][3] <= i:
            p = sp[pj]
            (hs if p[2]=='high' else ls).append(p[1]); pj += 1
        labels[i] = cur()
    return labels

# ─── EXITS ────────────────────────────────────────────
def exit_fixed(df, entry_idx, is_buy, atr, tp_mult, sl_mult):
    entry = df["close"].iloc[entry_idx]
    sl = entry - atr*sl_mult if is_buy else entry + atr*sl_mult
    tp = entry + atr*tp_mult if is_buy else entry - atr*tp_mult
    for i in range(entry_idx+1, len(df)):
        hi, lo = df["high"].iloc[i], df["low"].iloc[i]
        if is_buy:
            if lo <= sl: return ((sl-entry)/entry)*100, "SL"
            if hi >= tp: return ((tp-entry)/entry)*100, "TP"
        else:
            if hi >= sl: return ((entry-sl)/entry)*100, "SL"
            if lo <= tp: return ((entry-tp)/entry)*100, "TP"
    return None, "OPEN"

def exit_structure(df, entry_idx, is_buy, atr, labels, be_trigger=BE_TRIGGER, disaster=DISASTER_SL):
    """No fixed TP. Exit when structure flips opposite, with breakeven trail + disaster stop."""
    entry = df["close"].iloc[entry_idx]
    sl = entry - atr*disaster if is_buy else entry + atr*disaster
    be_done = False
    h = df["high"].values; l = df["low"].values; c = df["close"].values
    for i in range(entry_idx+1, len(df)):
        hi, lo, cl = h[i], l[i], c[i]
        # disaster / breakeven stop
        if is_buy:
            if lo <= sl: return ((sl-entry)/entry)*100, "SL"
        else:
            if hi >= sl: return ((entry-sl)/entry)*100, "SL"
        if be_trigger > 0 and not be_done:
            if is_buy and hi >= entry + atr*be_trigger:
                sl = max(sl, entry); be_done = True
            elif (not is_buy) and lo <= entry - atr*be_trigger:
                sl = min(sl, entry); be_done = True
        # structure-flip exit on close
        s = labels[i]
        if is_buy and s in BEAR: return ((cl-entry)/entry)*100, "STRUCT"
        if (not is_buy) and s in BULL: return ((entry-cl)/entry)*100, "STRUCT"
    return None, "OPEN"

# ─── BACKTEST ─────────────────────────────────────────
def gen_signals(symbol, bias_df, entry_df, deviation):
    """Yield (entry_idx, is_buy, atr) for each fresh structure-aligned signal."""
    entry_df = entry_df.copy()
    entry_df["atr"] = atr_series(entry_df)
    zz_bias  = compute_zigzag_pivots(bias_df, deviation)
    zz_entry = compute_zigzag_pivots(entry_df, deviation)
    labels   = structure_label_array(entry_df, zz_entry)
    sigs = []; prev = None
    for i in range(50, len(entry_df)-1):
        if pd.isna(entry_df["atr"].iloc[i]): continue
        t = entry_df["time"].iloc[i]
        m_bias = bias_df[bias_df["time"] <= t]
        if len(m_bias) < 10: continue
        s_bias = structure_at(zz_bias, m_bias.index[-1])
        s_entry = labels[i]
        fresh = (s_entry != prev); prev = s_entry
        if FRESH_ONLY and not fresh: continue
        bull = (s_bias in BULL) and (s_entry in BULL)
        bear = (s_bias in BEAR) and (s_entry in BEAR)
        if bull or bear:
            sigs.append((i, bull, entry_df["atr"].iloc[i], t))
    return entry_df, labels, sigs

def run_fixed(tp_mult, sl_mult):
    trades = []
    for sym, fut in SYMBOLS:
        bias_df = get_historical(sym, BIAS_IV, fut); entry_df0 = get_historical(sym, ENTRY_IV, fut)
        if bias_df is None or entry_df0 is None: continue
        edf, labels, sigs = gen_signals(sym, bias_df, entry_df0, DEVIATION)
        for (i, is_buy, atr, t) in sigs:
            pnl, ex = exit_fixed(edf, i, is_buy, atr, tp_mult, sl_mult)
            if pnl is not None:
                trades.append({"time":t, "pnl_pct":pnl, "exit":ex})
    return trades

def run_structure():
    trades = []
    for sym, fut in SYMBOLS:
        bias_df = get_historical(sym, BIAS_IV, fut); entry_df0 = get_historical(sym, ENTRY_IV, fut)
        if bias_df is None or entry_df0 is None: continue
        edf, labels, sigs = gen_signals(sym, bias_df, entry_df0, DEVIATION)
        # faster exit pivots: smaller deviation so structure flips sooner
        zz_exit = compute_zigzag_pivots(edf, EXIT_DEV)
        exit_labels = structure_label_array(edf, zz_exit)
        for (i, is_buy, atr, t) in sigs:
            pnl, ex = exit_structure(edf, i, is_buy, atr, exit_labels)
            if pnl is not None:
                trades.append({"time":t, "pnl_pct":pnl, "exit":ex})
    return trades

# ─── METRICS ──────────────────────────────────────────
def metrics(trades):
    if not trades: return None
    df = pd.DataFrame(trades)
    n = len(df)
    gross = df["pnl_pct"].mean()                 # BEP per trade
    wr = (df["pnl_pct"] > 0).mean()*100
    net = (df["pnl_pct"] - SPOT_FEE).mean()
    return {"n":n, "wr":wr, "bep":gross, "net":net}

def equity(trades, fee=SPOT_FEE, start=START_CAPITAL):
    if not trades: return start, 0
    df = pd.DataFrame(trades).sort_values("time")
    bal = start; peak = start; dd = 0.0
    for pnl in df["pnl_pct"]:
        bal *= (1 + (pnl-fee)/100.0)
        if bal <= 0: bal = 0.0; break
        peak = max(peak, bal); dd = max(dd, (peak-bal)/peak*100)
    return bal, dd

def line(label, m, trades):
    if m is None:
        print(f"  {label:>16} |    n/a"); return
    bal, dd = equity(trades)
    flag = "  <-- BEP>=0.5%" if m["bep"] >= 0.5 else ""
    print(f"  {label:>16} | {m['n']:>5} | {m['wr']:>5.1f}% | {m['bep']:>+7.3f}% | "
          f"{m['net']:>+7.3f}% | {('$'+format(bal,',.0f')+' (-'+format(dd,'.0f')+'%)'):>14}{flag}")

def main():
    print(f"ZigZag Optimize | {BACKTEST_DAYS}d | 4H bias + 30M entry | dev {DEVIATION}% | BTC+HYPE spot")
    print(f"Target: BEP/trade >= 0.500%  (spot fee {SPOT_FEE:.2f}%)\n")
    hdr = f"  {'Setup':>16} | {'Trd':>5} | {'Win':>6} | {'BEP/trd':>8} | {'net@spot':>8} | {'$1000':>14}"

    print("="*78); print("  PART A — R:R sweep (fixed ATR TP/SL)"); print("="*78)
    print(hdr); print("  "+"-"*(len(hdr)-2))
    bestA = None
    for sl in SL_MULTS:
        for tp in TP_MULTS:
            tr = run_fixed(tp, sl); m = metrics(tr)
            line(f"TP{tp}/SL{sl}", m, tr)
            if m and (bestA is None or m["bep"] > bestA[0]): bestA = (m["bep"], tp, sl)
        print("  "+"-"*(len(hdr)-2))

    print("\n"+"="*78); print("  PART B — structure-based exit (run to opposite pivot + BE trail)"); print("="*78)
    print(hdr); print("  "+"-"*(len(hdr)-2))
    trB = run_structure(); mB = metrics(trB)
    line(f"struct/BE", mB, trB)
    if trB:
        ex = pd.DataFrame(trB)["exit"].value_counts().to_dict()
        print(f"\n  Exit mix: {ex}")

    print("\n  BEP/trd = gross expectancy = max round-trip fee before you stop earning.")
    print(f"  Best R:R sweep BEP: {bestA[0]:+.3f}% at TP{bestA[1]}/SL{bestA[2]}" if bestA else "")
    if mB: print(f"  Structure-exit BEP: {mB['bep']:+.3f}%")

if __name__ == "__main__":
    main()
