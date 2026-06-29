# idx_replay.py — Replay the live scanner day-by-day over a past window, printing the
# exact Telegram messages it would have sent and tallying realised P&L. Fills at NEXT open.
import sys, argparse
import pandas as pd
import idx_konglo as K
from idx_regime import load_ihsg, SIZE_MULT
from idx_scan import WATCH, SPIKE_X, TREND_MA, SL_X, TP_X, BASE_SIZE, ACCOUNT, fmt, lots

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

def prep(t):
    d, w = K.get_eod(t + ".JK", period="2y")
    if d is None or len(d) < TREND_MA + 40 or w is None or len(w) < 20:
        return None
    d["atr"]   = K.atr_series(d)
    d["volma"] = d["volume"].rolling(20).mean()
    d["sma50"] = d["close"].rolling(TREND_MA).mean()
    zz_w = K.compute_zigzag_pivots(w)
    sw_by_day = []
    zz_d = K.compute_zigzag_pivots(d)
    sd_series = [K.structure_at(zz_d, i) for i in range(len(d))]
    for i in range(len(d)):
        wk = w[w["time"] <= d["time"].iloc[i]]
        sw_by_day.append(K.structure_at(zz_w, wk.index[-1]) if len(wk) else "neutral")
    d["sd"], d["sw"] = sd_series, sw_by_day
    return d, w

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-25")
    ap.add_argument("--end",   default="2026-06-25")
    args = ap.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)

    ix = load_ihsg()
    frames = {t: f for t in WATCH if (f := prep(t)) is not None}

    # union of trading dates in window
    dates = sorted({dt for _, (d, _) in frames.items()
                    for dt in d["time"] if start <= dt <= end})

    positions = {}      # ticker -> dict(entry, stop, target, lots, rupiah)
    messages = []       # (date, text)
    realised = []       # closed-trade pnl %
    prev_reg = None
    equity_note = ACCOUNT

    for dt in dates:
        reg_row = ix.loc[:dt]
        reg = str(reg_row["reg" + "ime"].iloc[-1]) if len(reg_row) else "HEALTHY"
        mult = SIZE_MULT[reg]; size_pct = BASE_SIZE * mult * 100
        rupiah = ACCOUNT * BASE_SIZE * mult

        # regime change message
        if prev_reg and reg != prev_reg:
            r = reg_row.iloc[-1]
            emoji = {"HEALTHY":"🟢","CAUTION":"⚠️","CRASH":"🔴"}[reg]
            messages.append((dt, f"{emoji} REGIME CHANGE — {dt.date()}\n"
                             f"IHSG {fmt(r['close'])} · {r['dd']:+.0f}% off highs · vol {r['vol20']:.0f}%\n"
                             f"{prev_reg} → {reg}  👉 size now {size_pct:.0f}% per trade"
                             + ("\n💀 2008/COVID structure — defensive." if reg=="CRASH" else "")))
        prev_reg = reg

        for t, (d, _) in frames.items():
            rows = d[d["time"] == dt]
            if rows.empty: continue
            i = rows.index[0]
            if i < TREND_MA or i + 1 >= len(d): continue
            r = d.iloc[i]
            if pd.isna(r["atr"]) or r["atr"] <= 0 or pd.isna(r["volma"]) or pd.isna(r["sma50"]):
                continue

            # manage open position using today's range
            if t in positions:
                p = positions[t]
                if r["high"] >= p["target"]:
                    pnl = (p["target"]-p["entry"])/p["entry"]*100; realised.append(pnl)
                    messages.append((dt, f"✅ SELL {t} — TARGET HIT @ {fmt(p['target'])} ({pnl:+.1f}%)"))
                    positions.pop(t); continue
                if r["low"] <= p["stop"]:
                    pnl = (p["stop"]-p["entry"])/p["entry"]*100; realised.append(pnl)
                    messages.append((dt, f"🛑 SELL {t} — STOP HIT @ {fmt(p['stop'])} ({pnl:+.1f}%)"))
                    positions.pop(t); continue

            # new buy signal
            up    = r["close"] > d["close"].iloc[i-1]
            volr  = r["volume"]/r["volma"]
            trend = r["close"] > r["sma50"]
            struct= r["sd"] in K.BULL and r["sw"] in K.BULL
            if up and volr>=SPIKE_X and trend and struct and t not in positions and len(positions) < 4:
                nxt = d.iloc[i+1]
                entry = nxt["open"]                          # realistic: fill next open
                gap = (entry/r["close"]-1)*100
                if gap > 3.0:
                    messages.append((dt, f"⏳ SKIP {t} — gapped +{gap:.1f}% at open (chase guard)"))
                    continue
                stop, target = entry - SL_X*r["atr"], entry + TP_X*r["atr"]
                nlots = lots(rupiah, entry)
                positions[t] = {"entry":entry,"stop":stop,"target":target}
                messages.append((dt, f"🔥 BUY SIGNAL — {t} — {dt.date()}\n"
                    f"Volume spike {volr:.1f}× · structure {r['sd']}/{r['sw']} · above 50MA\n"
                    f"Entry ~{fmt(entry)} (filled next open) · gap {gap:+.1f}%\n"
                    f"🛑 Stop {fmt(stop)} ({(stop/entry-1)*100:+.0f}%)  🎯 Target {fmt(target)} ({(target/entry-1)*100:+.0f}%)\n"
                    f"📊 Regime {reg} → size {size_pct:.0f}% ≈ Rp {rupiah:,.0f} ≈ {nlots} lots"))

    # output
    print(f"{'='*60}\n  TELEGRAM REPLAY  {start.date()} → {end.date()}\n{'='*60}")
    if not messages:
        print("  (No messages — strategy stayed flat. Expected in a CRASH regime:\n"
              "   no bullish structure = no buys, which is the defense working.)")
    for dt, m in messages:
        print("\n" + m)

    # P&L summary (close out opens at last close, mark-to-market)
    open_mtm = []
    for t, p in positions.items():
        d, _ = frames[t]
        last = d[d["time"] <= end].iloc[-1]["close"]
        open_mtm.append((last - p["entry"]) / p["entry"] * 100)
    print(f"\n{'='*60}\n  RESULT\n{'='*60}")
    print(f"  Closed trades : {len(realised)}  | sum {sum(realised):+.1f}%  "
          f"| wins {sum(1 for x in realised if x>0)}/{len(realised)}" if realised else "  Closed trades : 0")
    if open_mtm:
        print(f"  Still open    : {len(open_mtm)}  | unrealised {sum(open_mtm):+.1f}% (mark-to-market)")
    # rough capital effect at the regime size used
    total = sum(realised) + sum(open_mtm)
    print(f"  Net move (sum of trade %): {total:+.1f}%")

if __name__ == "__main__":
    main()
