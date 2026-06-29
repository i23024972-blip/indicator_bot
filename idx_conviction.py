# idx_conviction.py — Which Combo setups actually win MORE? Test features so we can
# size by conviction instead of a flat 25%. Records features at entry, then the outcome.
import sys
import pandas as pd
import idx_konglo as K
from idx_compare import prep, simulate_long, FEE, SPIKE_X, TREND_MA, VOL_MA

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def combo_trades_with_features(spike_x=2.5):
    rows = []
    for t in K.all_tickers():
        if K.group_of(t) in {"Salim"}:
            continue
        d = prep(t)
        if d is None:
            continue
        last_exit = -1
        for i in range(TREND_MA, len(d) - 1):
            if pd.isna(d["atr"].iloc[i]) or pd.isna(d["sma"].iloc[i]) or pd.isna(d["volma"].iloc[i]) or d["atr"].iloc[i] <= 0:
                continue
            vol = (d["ret1"].iloc[i] > 0 and d["volume"].iloc[i] >= spike_x * d["volma"].iloc[i]
                   and d["close"].iloc[i] > d["sma"].iloc[i])
            struct = d["sd"].iloc[i] in K.BULL and d["sw"].iloc[i] in K.BULL
            if not (vol and struct) or i <= last_exit:
                continue
            pnl, bars = simulate_long(d, i); last_exit = i + bars
            xi = min(i + bars, len(d) - 1)
            rows.append({
                "ticker": t, "group": K.group_of(t), "pnl": pnl - FEE,
                "entry": d["time"].iloc[i], "exit": d["time"].iloc[xi],
                "volr": d["volume"].iloc[i] / d["volma"].iloc[i],        # spike magnitude
                "above_sma": (d["close"].iloc[i] / d["sma"].iloc[i] - 1) * 100,  # trend strength
                "atr_pct": d["atr"].iloc[i] / d["close"].iloc[i] * 100,  # volatility
                "both_strong": d["sd"].iloc[i] == "HH+HL" and d["sw"].iloc[i] == "HH+HL",
            })
    return pd.DataFrame(rows)

def bucket(df, col, edges, labels):
    df = df.copy()
    df["b"] = pd.cut(df[col], bins=edges, labels=labels)
    print(f"\n  By {col}:")
    print(f"    {'bucket':14}{'n':>5}{'win%':>7}{'avg pnl':>10}")
    for lab in labels:
        s = df[df["b"] == lab]
        if len(s) == 0: continue
        print(f"    {str(lab):14}{len(s):>5}{(s.pnl>0).mean()*100:>6.0f}%{s.pnl.mean():>+9.1f}%")

def main():
    df = combo_trades_with_features()
    print(f"COMBO trades with features | {len(df)} trades | "
          f"overall win {(df.pnl>0).mean()*100:.0f}%  avg pnl {df.pnl.mean():+.1f}%")

    bucket(df, "volr", [0, 4, 6, 10, 1e9], ["2.5-4x", "4-6x", "6-10x", "10x+"])
    bucket(df, "above_sma", [-1, 5, 15, 30, 1e9], ["0-5%", "5-15%", "15-30%", "30%+"])
    bucket(df, "atr_pct", [0, 4, 6, 1e9], ["calm <4%", "4-6%", "wild 6%+"])

    print(f"\n  By structure quality:")
    print(f"    {'bucket':14}{'n':>5}{'win%':>7}{'avg pnl':>10}")
    for lab, s in [("both HH+HL", df[df.both_strong]), ("weaker bull", df[~df.both_strong])]:
        if len(s): print(f"    {lab:14}{len(s):>5}{(s.pnl>0).mean()*100:>6.0f}%{s.pnl.mean():>+9.1f}%")

    print(f"\n  By group:")
    print(f"    {'bucket':14}{'n':>5}{'win%':>7}{'avg pnl':>10}")
    for g in df.group.unique():
        s = df[df.group == g]
        print(f"    {g:14}{len(s):>5}{(s.pnl>0).mean()*100:>6.0f}%{s.pnl.mean():>+9.1f}%")

if __name__ == "__main__":
    main()
