# idx_konglo.py — Shared core for Indonesian konglomerat EOD zigzag strategy.
# Reuses the causal/non-repainting ZigZag structure logic from zigzag_backtest.py,
# but feeds it end-of-day (.JK) data from Yahoo Finance instead of Binance klines.
import warnings
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Conglomerate watchlist (validated against Yahoo Finance, .JK = IDX) ──
# Thin/illiquid names (avg 20d vol very low) are marked thin=True and skipped by default.
KONGLO = {
    "Prajogo": ["BRPT.JK", "TPIA.JK", "BREN.JK", "CUAN.JK", "PTRO.JK"],
    "Hapsoro": ["RATU.JK", "WIFI.JK", "BUVA.JK"],            # CBPE dropped (too thin)
    "Bakrie":  ["BNBR.JK", "BUMI.JK", "ENRG.JK", "BRMS.JK", "DEWA.JK", "ELTY.JK", "VKTR.JK"],
    "Salim":   ["INDF.JK", "ICBP.JK", "SIMP.JK", "LSIP.JK", "PANI.JK"],  # DNET/BISI/FAST thin
}

def all_tickers():
    return [t for ts in KONGLO.values() for t in ts]

def group_of(ticker):
    for g, ts in KONGLO.items():
        if ticker in ts:
            return g
    return "?"

# ── ZigZag tuning ──
ZIGZAG_DEVIATION  = 5.0   # % reversal to confirm a pivot (daily bars — try 4/5/8)
ATR_MULTIPLIER_SL = 1.5
ATR_MULTIPLIER_TP = 3.0
ATR_WINDOW        = 14

# ── Data fetch (end-of-day) ──
def get_eod(ticker, period="3y"):
    """Daily + weekly OHLC for one .JK ticker. Returns (df_daily, df_weekly) or (None, None)."""
    d = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    w = yf.download(ticker, period=period, interval="1wk", progress=False, auto_adjust=True)
    if d is None or len(d) == 0 or w is None or len(w) == 0:
        return None, None
    d, w = _flatten(d), _flatten(w)
    return d, w

def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy(); df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
    df = df.reset_index().rename(columns={df.reset_index().columns[0]: "time"})
    df["time"] = pd.to_datetime(df["time"])
    return df

def atr_series(df, window=ATR_WINDOW):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()

# ── ZigZag structure (ported verbatim from zigzag_backtest.py — causal, non-repainting) ──
def compute_zigzag_pivots(df, deviation_pct=ZIGZAG_DEVIATION):
    highs, lows = df["high"].values, df["low"].values
    n = len(df); pivots = []; trend = None
    eh_p, eh_i = highs[0], 0
    el_p, el_i = lows[0], 0
    for i in range(1, n):
        if highs[i] > eh_p: eh_p, eh_i = highs[i], i
        if lows[i]  < el_p: el_p, el_i = lows[i], i
        if trend is None:
            if (eh_p - lows[i]) / eh_p * 100 >= deviation_pct:
                pivots.append((eh_i, eh_p, 'high', i)); trend = 'down'; el_p, el_i = lows[i], i
            elif (highs[i] - el_p) / el_p * 100 >= deviation_pct:
                pivots.append((el_i, el_p, 'low', i)); trend = 'up'; eh_p, eh_i = highs[i], i
        elif trend == 'up':
            if (eh_p - lows[i]) / eh_p * 100 >= deviation_pct:
                pivots.append((eh_i, eh_p, 'high', i)); trend = 'down'; el_p, el_i = lows[i], i
        elif trend == 'down':
            if (highs[i] - el_p) / el_p * 100 >= deviation_pct:
                pivots.append((el_i, el_p, 'low', i)); trend = 'up'; eh_p, eh_i = highs[i], i
    return pivots

def structure_at(pivots, confirm_limit_idx):
    confirmed = [p for p in pivots if p[3] <= confirm_limit_idx]
    hs = [p[1] for p in confirmed if p[2] == 'high']
    ls = [p[1] for p in confirmed if p[2] == 'low']
    if len(hs) >= 2 and len(ls) >= 2:
        hh, hl = hs[-1] > hs[-2], ls[-1] > ls[-2]
        ll, lh = ls[-1] < ls[-2], hs[-1] < hs[-2]
        if hh and hl: return "HH+HL"
        elif ll and lh: return "LL+LH"
        elif hl: return "HL"
        elif lh: return "LH"
    return "neutral"

BULL = {"HH+HL", "HL"}
BEAR = {"LL+LH", "LH"}
