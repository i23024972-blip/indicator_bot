# idx_compare.py — Bake-off: ZigZag vs Volume-spike vs Combo (confluence).
# Fair test: identical exit engine + fee haircut for all three, so only the ENTRY differs.
# Reports full 3y AND last ~12 months (out-of-sample reality check), plus a volume sweep.
import sys
import pandas as pd
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# Shared exit + costs (1:3 reward:risk, 20d time stop)
SL_X, TP_X, MAX_HOLD = 2.0, 6.0, 20
FEE        = 0.4     # % round-trip: 0.15% buy + 0.25% sell (IDX)
SPIKE_X    = 2.0
VOL_MA, TREND_MA = 20, 50
SKIP_GROUPS = {"Salim"}     # volume-spike fails on Salim blue-chips
RECENT_DAYS = 252

def simulate_long(d, i, sl_x=SL_X, tp_x=TP_X, hold=MAX_HOLD):
    atr = d["atr"].iloc[i]; entry = d["close"].iloc[i]
    sl, tp = entry - sl_x*atr, entry + tp_x*atr
    end = min(i + hold, len(d) - 1)
    for j in range(i + 1, end + 1):
        if d["low"].iloc[j]  <= sl: return (sl-entry)/entry*100, j-i
        if d["high"].iloc[j] >= tp: return (tp-entry)/entry*100, j-i
    return (d["close"].iloc[end]-entry)/entry*100, end-i

# ── precompute per-ticker frame with all indicators + zigzag structure series ──
def prep(t):
    d, w = K.get_eod(t, period="3y")
    if d is None or len(d) < TREND_MA + 40 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(VOL_MA).mean()
    d["sma"]   = d["close"].rolling(TREND_MA).mean()
    d["ret1"]  = d["close"].pct_change()
    zz_d, zz_w = K.compute_zigzag_pivots(d), K.compute_zigzag_pivots(w)
    # daily + weekly structure label aligned to each daily bar
    sd_series, sw_series, prev, fresh_series = [], [], None, []
    for i in range(len(d)):
        sd = K.structure_at(zz_d, i)
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw = K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral"
        sd_series.append(sd); sw_series.append(sw)
        fresh_series.append(sd != prev); prev = sd
    d["sd"], d["sw"], d["fresh"] = sd_series, sw_series, fresh_series
    return d

def valid(d, i):
    return not (pd.isna(d["atr"].iloc[i]) or pd.isna(d["sma"].iloc[i])
                or pd.isna(d["volma"].iloc[i]) or d["atr"].iloc[i] <= 0)

# ── entry signals (return list of entry indices) ──
def entries_zigzag(d, group, spike_x=SPIKE_X):
    out = []
    for i in range(TREND_MA, len(d)-1):
        if not valid(d, i): continue
        if d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL and d["fresh"].iloc[i]:
            out.append(i)
    return out

def entries_volume(d, group, spike_x=SPIKE_X):
    if group in SKIP_GROUPS: return []
    out = []
    for i in range(TREND_MA, len(d)-1):
        if not valid(d, i): continue
        if (d["ret1"].iloc[i] > 0 and d["volume"].iloc[i] >= spike_x*d["volma"].iloc[i]
                and d["close"].iloc[i] > d["sma"].iloc[i]):
            out.append(i)
    return out

def entries_combo(d, group, spike_x=SPIKE_X):
    if group in SKIP_GROUPS: return []
    out = []
    for i in range(TREND_MA, len(d)-1):
        if not valid(d, i): continue
        vol = (d["ret1"].iloc[i] > 0 and d["volume"].iloc[i] >= spike_x*d["volma"].iloc[i]
               and d["close"].iloc[i] > d["sma"].iloc[i])
        struct = d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL
        if vol and struct:
            out.append(i)
    return out

def collect(entry_fn, data, spike_x=SPIKE_X):
    trades = []
    for t, d in data.items():
        ents = entry_fn(d, K.group_of(t), spike_x)
        last_exit = -1
        for i in ents:
            if i <= last_exit: continue
            pnl, bars = simulate_long(d, i)
            last_exit = i + bars
            trades.append({"ticker": t, "group": K.group_of(t),
                           "date": d["time"].iloc[i], "pnl": pnl - FEE, "bars": bars})
    return pd.DataFrame(trades)

def summarize(df, label):
    if len(df) == 0:
        print(f"  {label:16} no trades"); return
    n = len(df); wr = (df.pnl > 0).mean()*100
    aw = df[df.pnl > 0].pnl.mean() if (df.pnl > 0).any() else 0
    al = df[df.pnl <= 0].pnl.mean() if (df.pnl <= 0).any() else 0
    exp = df.pnl.mean()
    print(f"  {label:16} n={n:4}  win={wr:4.1f}%  avgW/L=+{aw:5.1f}/{al:6.1f}  "
          f"exp={exp:+5.2f}%  total={df.pnl.sum():+8.1f}%  hold={df.bars.mean():3.0f}d")

def window(df, data, recent=False):
    if not recent or len(df) == 0: return df
    cutoff = max(d["time"].iloc[-1] for d in data.values()) - pd.Timedelta(days=int(RECENT_DAYS*1.5))
    return df[df["date"] >= cutoff]

def main():
    print("Loading data + indicators for all tickers...")
    data = {}
    for t in K.all_tickers():
        d = prep(t)
        if d is not None: data[t] = d
    print(f"Loaded {len(data)} tickers. Exit: SL{SL_X}/TP{TP_X}xATR (1:3), {MAX_HOLD}d stop, "
          f"fee {FEE}%/trade.\n")

    strats = {"ZigZag": entries_zigzag, "Volume-spike": entries_volume, "Combo(V+Z)": entries_combo}
    runs = {name: collect(fn, data) for name, fn in strats.items()}

    print(f"{'='*92}\n  FULL 3 YEARS  (net of {FEE}% fees)\n{'='*92}")
    for name, df in runs.items(): summarize(df, name)

    print(f"\n{'='*92}\n  LAST ~12 MONTHS  (out-of-sample reality check)\n{'='*92}")
    for name, df in runs.items(): summarize(window(df, data, recent=True), name)

    print(f"\n{'='*92}\n  VOLUME-SPIKE SWEEP — spike threshold (full 3y, net fees)\n{'='*92}")
    for sx in [1.5, 2.0, 2.5, 3.0]:
        summarize(collect(entries_volume, data, spike_x=sx), f"spike>= {sx}x")

if __name__ == "__main__":
    main()
