# lev_daily_backtest.py
# "One trade a day" leveraged perp backtest — EOD style.
# Question: can you win leverage trading with 1 trade/day + fixed 1% risk?
# It scans a basket each day, takes the SINGLE best setup, sizes by 1% risk,
# applies fees+slippage, compounds the account, and reports the truth about leverage.
import os, time, json, urllib.request
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange

# ─── SETTINGS ────────────────────────────────────────
UNIVERSE   = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
              "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","LTCUSDT"]
DAYS       = 900
START_EQ   = 1000.0      # USDT
RISK_PCT   = 0.01        # 1% of equity risked per trade
ATR_SL     = 1.5         # stop = 1.5 * ATR
R_TARGET   = 2.0         # take profit at 2R  (risk 1 to make 2)
DONCHIAN   = 20          # breakout lookback
EMA_TREND  = 50          # only trade with the trend
TAKER_FEE  = 0.0005      # 0.05% per side (perp taker)
SLIPPAGE   = 0.0005      # 0.05% slippage per side
LEV_CAP    = 50          # exchange leverage cap (for liquidation modeling)

CACHE = "/d/indicator_bot/.klines_cache" if os.path.exists("/d/indicator_bot/.klines_cache") else ".klines_cache"
os.makedirs(CACHE, exist_ok=True)

# ─── DATA ────────────────────────────────────────────
def fetch_daily(symbol, days=DAYS):
    path = os.path.join(CACHE, f"{symbol}_1d_{days}d.pkl")
    if os.path.exists(path) and (time.time() - os.path.getmtime(path) < 12*3600):
        return pd.read_pickle(path)
    url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
           f"&interval=1d&limit={min(days,1000)}")
    raw = json.loads(urllib.request.urlopen(url, timeout=20).read())
    df = pd.DataFrame(raw, columns=["time","open","high","low","close","volume",
                                    "ct","qav","n","tb","tq","ig"])
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    df = df[["time","open","high","low","close","volume"]]
    df.to_pickle(path)
    return df

def prep(df):
    df = df.copy()
    df["ema"]  = EMAIndicator(df["close"], EMA_TREND).ema_indicator()
    df["atr"]  = AverageTrueRange(df["high"], df["low"], df["close"], 14).average_true_range()
    df["hh"]   = df["high"].rolling(DONCHIAN).max().shift(1)   # prior N-day high
    df["ll"]   = df["low"].rolling(DONCHIAN).min().shift(1)
    return df

# ─── BUILD ALIGNED PANEL ─────────────────────────────
print(f"Fetching {len(UNIVERSE)} symbols, {DAYS}d daily candles...")
data = {}
for s in UNIVERSE:
    try:
        data[s] = prep(fetch_daily(s))
        print(f"  {s}: {len(data[s])} bars")
    except Exception as e:
        print(f"  ! {s} failed: {e}")

# common date index
dates = sorted(set.intersection(*[set(d["time"]) for d in data.values()]))
for s in data:
    data[s] = data[s].set_index("time").reindex(dates)

# ─── SIGNAL: each day score every coin, pick the single best ──
def day_signals(i):
    """Return list of candidate setups available at close of day i."""
    out = []
    for s, df in data.items():
        r = df.iloc[i]
        if any(pd.isna(r[c]) for c in ["ema","atr","hh","ll","close"]):
            continue
        atrp = r["atr"] / r["close"]
        if atrp <= 0:
            continue
        long_break  = r["close"] > r["hh"] and r["close"] > r["ema"]
        short_break = r["close"] < r["ll"] and r["close"] < r["ema"]
        if long_break:
            # momentum score = how far past the breakout level, in ATRs
            score = (r["close"] - r["hh"]) / r["atr"]
            out.append((score, s, "LONG", r["close"], r["atr"]))
        elif short_break:
            score = (r["ll"] - r["close"]) / r["atr"]
            out.append((score, s, "SHORT", r["close"], r["atr"]))
    out.sort(reverse=True)   # best momentum first
    return out

# ─── FORWARD SIMULATION OF ONE TRADE (next-day open entry) ──
TRAIL = True          # True = let winners run w/ chandelier trail; False = fixed 2R
TRAIL_ATR = 3.0       # trailing stop = 3*ATR off the running extreme

def sim_trade(s, i_signal, side, atr):
    df = data[s]
    if i_signal + 1 >= len(df):
        return None
    entry = df.iloc[i_signal+1]["open"]            # enter next day open (no lookahead)
    if pd.isna(entry):
        return None
    sl_dist = ATR_SL * atr

    if not TRAIL:
        # ── fixed 2R target ──
        if side == "LONG":
            sl, tp = entry - sl_dist, entry + R_TARGET*sl_dist
        else:
            sl, tp = entry + sl_dist, entry - R_TARGET*sl_dist
        for j in range(i_signal+1, len(df)):
            hi, lo = df.iloc[j]["high"], df.iloc[j]["low"]
            if pd.isna(hi): continue
            if side == "LONG":
                if lo <= sl: return entry, sl, "SL", j
                if hi >= tp: return entry, tp, "TP", j
            else:
                if hi >= sl: return entry, sl, "SL", j
                if lo <= tp: return entry, tp, "TP", j
        return entry, df.iloc[-1]["close"], "OPEN", len(df)-1

    # ── trailing chandelier stop: let winners run ──
    if side == "LONG":
        stop = entry - sl_dist
        extreme = entry
        for j in range(i_signal+1, len(df)):
            hi, lo = df.iloc[j]["high"], df.iloc[j]["low"]
            if pd.isna(hi): continue
            if lo <= stop: return entry, stop, "TRAIL", j
            extreme = max(extreme, hi)
            stop = max(stop, extreme - TRAIL_ATR*atr)   # ratchet up only
        return entry, df.iloc[-1]["close"], "OPEN", len(df)-1
    else:
        stop = entry + sl_dist
        extreme = entry
        for j in range(i_signal+1, len(df)):
            hi, lo = df.iloc[j]["high"], df.iloc[j]["low"]
            if pd.isna(hi): continue
            if hi >= stop: return entry, stop, "TRAIL", j
            extreme = min(extreme, lo)
            stop = min(stop, extreme + TRAIL_ATR*atr)
        return entry, df.iloc[-1]["close"], "OPEN", len(df)-1

# ─── RUN ─────────────────────────────────────────────
def run(risk_pct=RISK_PCT, lev_cap=LEV_CAP, label=""):
    eq = START_EQ
    peak = eq
    maxdd = 0.0
    trades = []
    eq_curve = []
    for i in range(EMA_TREND + DONCHIAN, len(dates) - 1):
        cands = day_signals(i)
        if not cands:
            continue
        score, s, side, px, atr = cands[0]      # ONE trade per day: the best
        res = sim_trade(s, i, side, atr)
        if res is None:
            continue
        entry, exit_px, how, jexit = res

        stop_dist_pct = (ATR_SL * atr) / entry
        # position sized so a stop-out loses exactly risk_pct of equity
        risk_usd = eq * risk_pct
        pos_usd  = risk_usd / stop_dist_pct       # notional
        eff_lev  = pos_usd / eq                   # ACTUAL leverage on the account

        # liquidation guard: if you used the exchange max leverage, would you be
        # liquidated before your stop? (isolated margin, ~maintenance ignored)
        liq_dist_pct = 1.0 / lev_cap
        liquidated   = stop_dist_pct > liq_dist_pct  # stop further than liq = dead first

        # raw move %
        if side == "LONG":
            move = (exit_px - entry) / entry
        else:
            move = (entry - exit_px) / entry

        gross_usd = pos_usd * move
        fees_usd  = pos_usd * (TAKER_FEE + SLIPPAGE) * 2   # entry + exit
        pnl_usd   = gross_usd - fees_usd

        eq += pnl_usd
        peak = max(peak, eq)
        maxdd = max(maxdd, (peak - eq) / peak)
        eq_curve.append(eq)
        trades.append(dict(date=dates[i], sym=s, side=side, how=how,
                           move=move*100, pnl=pnl_usd, eq=eq,
                           eff_lev=eff_lev, stop_pct=stop_dist_pct*100,
                           liq_if_maxlev=liquidated))
        if eq <= 0:
            print("  ACCOUNT BLOWN OUT")
            break

    return pd.DataFrame(trades), eq, maxdd

def report(tr, eq, maxdd, label):
    print(f"\n{'='*58}\n  {label}\n{'='*58}")
    if tr.empty:
        print("  no trades"); return
    n = len(tr)
    wins = tr[tr.pnl > 0]; losses = tr[tr.pnl <= 0]
    wr = len(wins)/n*100
    aw = wins.move.mean() if len(wins) else 0
    al = losses.move.mean() if len(losses) else 0
    # worst losing streak
    s=w=0
    for p in tr.pnl:
        if p<=0: s+=1; w=max(w,s)
        else: s=0
    yrs = (tr.date.iloc[-1]-tr.date.iloc[0]).days/365.25
    cagr = ((eq/START_EQ)**(1/yrs)-1)*100 if yrs>0 else 0
    print(f"  Period             : {tr.date.iloc[0].date()} -> {tr.date.iloc[-1].date()}  ({yrs:.1f}y)")
    print(f"  Trades             : {n}  (~{n/max(yrs*252,1):.2f} per trading day)")
    print(f"  Win rate           : {wr:.1f}%")
    print(f"  Avg win / avg loss : +{aw:.2f}% / {al:.2f}%   (R:R target {R_TARGET}:1)")
    print(f"  Worst losing streak: {w} in a row")
    print(f"  Start -> End equity: ${START_EQ:,.0f} -> ${eq:,.0f}")
    print(f"  Total return       : {(eq/START_EQ-1)*100:,.1f}%")
    print(f"  CAGR               : {cagr:.1f}% / yr")
    print(f"  Max drawdown       : {maxdd*100:.1f}%")
    print(f"  Median EFFECTIVE leverage actually used : {tr.eff_lev.median():.2f}x")
    print(f"  Trades that WOULD liquidate at {LEV_CAP}x max-lev: "
          f"{tr.liq_if_maxlev.mean()*100:.0f}%")

if __name__ == "__main__":
    tr, eq, dd = run(label="proper")
    report(tr, eq, dd, f"1 TRADE/DAY  |  {RISK_PCT*100:.0f}% risk  |  {ATR_SL}xATR stop  |  {R_TARGET}R target")
    print(f"\n{'='*58}\n  THE LEVERAGE TRUTH\n{'='*58}")
    print(f"  To risk only {RISK_PCT*100:.0f}% with a {tr.stop_pct.median():.1f}% stop, the math forces")
    print(f"  ~{tr.eff_lev.median():.1f}x effective leverage. The '50x/100x' is the exchange")
    print(f"  MAX, not what a 1%-risk trader uses. Crank real leverage to")
    print(f"  hit those numbers and the liquidation column above eats you.")
    print(f"\n  NOTE: fees+slippage {(TAKER_FEE+SLIPPAGE)*2*100:.1f}%/round-trip included.")
    print(f"  No funding costs, no lookahead. Daily candles, next-open entry.")
