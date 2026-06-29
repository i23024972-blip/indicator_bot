# idx_trade_replay.py — narrated play-by-play of real past trades (binary ride, konglo).
# For 3 real winners and 3 real losers it tells the story the way the bot would coach you:
# candidate detected -> "place the bet" -> confirmed entry -> the price path while holding
# (with the trailing stop moving) -> the SELL signal (take profit / cut loss) -> the result.
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
import idx_konglo as K
from idx_walkforward import build, MIN_TURNOVER, CUTOFF, WINDOW_YEARS
from idx_hybrid_backtest import fire_combo

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

TRIG_BUF=0.005; MAXGAP=0.04; SLIP=0.003
EMA_LEN, TRAIL_ATR, INIT_ATR, MAXHOLD = 50, 4.0, 2.5, 250

def ride_paths(d, ticker):
    o,hi,lo,cl = d["open"].values,d["high"].values,d["low"].values,d["close"].values
    atr,turn = d["atr"].values,d["turn20"].values; t=d["time"].values
    ema = pd.Series(cl).ewm(span=EMA_LEN,adjust=False).mean().values
    n=len(d); out=[]; i=200
    while i<n-2:
        a=atr[i]
        if np.isnan(a) or a<=0 or np.isnan(turn[i]) or turn[i]<MIN_TURNOVER: i+=1; continue
        if not fire_combo(d,i): i+=1; continue
        sig_high=hi[i]; trig=sig_high*(1+TRIG_BUF); k=i+1
        if o[k]>sig_high*(1+MAXGAP): i+=1; continue
        if o[k]>=trig: entry=o[k]*(1+SLIP)
        elif hi[k]>=trig: entry=trig*(1+SLIP)
        else: i+=1; continue
        risk=INIT_ATR*a; stop=entry-risk; runmax=entry; end=min(k+MAXHOLD,n-1)
        path=[]; exitpx=None; reason=None; xk=end
        for j in range(k,end+1):
            runmax=max(runmax,hi[j]); aj=atr[j] if not np.isnan(atr[j]) else a
            stop=max(stop,runmax-TRAIL_ATR*aj)
            path.append((t[j],cl[j],hi[j],lo[j],stop,ema[j]))
            if lo[j]<=stop: exitpx=stop*(1-SLIP); reason="trailing stop hit"; xk=j; break
            if j>k and cl[j]<ema[j]: exitpx=cl[j]*(1-SLIP); reason="closed below 50 EMA"; xk=j; break
        if exitpx is None: exitpx=cl[end]*(1-SLIP); reason="still open at data end"; xk=end
        R=(exitpx-entry)/risk
        out.append(dict(ticker=ticker, sig_date=t[i], sig_high=sig_high, trig=trig,
                        entry_date=t[k], entry=entry, stop0=entry-risk, exit=exitpx,
                        exit_date=t[xk], reason=reason, R=R, pnl=(exitpx-entry)/entry*100,
                        bars=xk-k, path=path))
        i=xk+1
    return out

def rp(x): return f"{x:,.0f}"

def narrate(tr):
    win = tr["pnl"]>0
    tag = "🟢 WINNER" if win else "🔴 LOSER"
    print("\n" + "─"*70)
    print(f"{tag}  ·  {tr['ticker']}  ·  {str(pd.Timestamp(tr['entry_date']).date())} → "
          f"{str(pd.Timestamp(tr['exit_date']).date())}  ({tr['bars']}d)")
    print("─"*70)
    print(f"  📅 {str(pd.Timestamp(tr['sig_date']).date())}  🎯 CANDIDATE: {tr['ticker']} fired "
          f"(up-day + volume spike + uptrend). High {rp(tr['sig_high'])}.")
    print(f"      → BOT: \"Place a buy-stop at {rp(tr['trig'])}. Only buy IF it breaks out.\"")
    print(f"  📅 {str(pd.Timestamp(tr['entry_date']).date())}  ✅ CONFIRMED — it broke out.")
    print(f"      → BOT: \"BET ON. Bought at {rp(tr['entry'])}. Stop at {rp(tr['stop0'])} "
          f"(risk = your '1').\"")
    print(f"      {'date':10} {'close':>9} {'vs entry':>9} {'stop':>9}   note")
    # EVERY day, close-by-close
    path=tr["path"]; npath=len(path)
    peak_i=int(np.argmax([p[2] for p in path]))
    running_peak=tr["entry"]
    for idx in range(npath):
        dt,clz,h,l,stp,em = path[idx]
        pct=(clz-tr["entry"])/tr["entry"]*100
        running_peak=max(running_peak,h)
        note=""
        if idx==peak_i: note="📈 peak"
        elif idx==npath-1: note="🚪 EXIT"
        elif clz<em: note="⚠️ below 50EMA"
        dn = str(pd.Timestamp(dt).date())
        print(f"      {dn:10} {clz:>9,.0f} {pct:>+8.1f}% {stp:>9,.0f}   {note}")
    action = "💰 TAKE PROFIT — SELL" if win else "✂️ CUT THE LOSS — SELL"
    print(f"      → BOT: \"{action} at {rp(tr['exit'])}.\"   RESULT: {tr['pnl']:+.0f}%  =  {tr['R']:+.1f}R")

def main():
    print(f"TRADE REPLAY · konglo binary ride · real trades, last {WINDOW_YEARS}y")
    data=yf.download(K.all_tickers(),period="3y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    trades=[]
    for tk in K.all_tickers():
        try: d=build(tk,data[tk].copy())
        except Exception: d=None
        if d is None: continue
        for x in ride_paths(d, tk.replace(".JK","")):
            if pd.Timestamp(x["entry_date"])>=CUTOFF: trades.append(x)
    winners=sorted([t for t in trades if t["pnl"]>0], key=lambda x:-x["R"])[:3]
    losers =sorted([t for t in trades if t["pnl"]<=0], key=lambda x:x["R"])[:3]
    print(f"\n{'='*70}\n  3 WINNERS — when the bot says HOLD, then TAKE PROFIT\n{'='*70}")
    for t in winners: narrate(t)
    print(f"\n{'='*70}\n  3 LOSERS — when the bot says CUT IT (small, fast)\n{'='*70}")
    for t in losers: narrate(t)
    print(f"\n  Reminder: the 3 winners above are your fat tail. The losers are small & quick.")
    print("  Holding the winners for weeks/months is the ENTIRE game.")

if __name__=="__main__":
    main()
