# idx_watchlist.py — readiness watchlist: rank konglo names by how CLOSE each is to firing a
# Strategy A (DONCH50+200) signal. It triggers when price is BOTH above its 200MA AND breaks its
# 50-day high — so "distance to trigger" = the bigger of (rise to reach 200MA, rise to break 50d
# high). Smallest = next likely candidate. Also shows ADR% so you know how many days that is.
import sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
import idx_konglo as K

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MIN_TURN=10e9

def main():
    data=yf.download(K.all_tickers(),period="2y",interval="1d",progress=False,auto_adjust=True,group_by="ticker")
    rows=[]; asof=None
    for tk in K.all_tickers():
        try:
            d=data[tk].dropna().copy(); d.columns=[c.lower() for c in d.columns]
            if len(d)<210: continue
            close=float(d["close"].iloc[-1])
            sma200=float(d["close"].rolling(200).mean().iloc[-1])
            donch=float(d["high"].rolling(50).max().shift(1).iloc[-1])
            turn=float((d["close"]*d["volume"]).tail(20).median())
            adr=float(((d["high"]-d["low"])/d["close"]).tail(20).mean()*100)
            asof=d.index[-1].date()
            if turn<MIN_TURN: continue
            to200=max(0.0,(sma200-close)/close*100)        # % rise to reach 200MA
            to50h=max(0.0,(donch-close)/close*100)         # % rise to break 50d high
            trig=max(to200,to50h)                          # needs the bigger of the two
            rows.append(dict(tk=tk.replace(".JK",""),close=close,to200=to200,to50h=to50h,
                             trig=trig,adr=adr,above200=close>sma200))
        except Exception: pass
    df=pd.DataFrame(rows).sort_values("trig")
    print(f"📋 KONGLO WATCHLIST · readiness to trigger Strategy A · as of {asof}")
    print("━"*72)
    print(f"  {'#':>2} {'ticker':7}{'close':>9}{'needs':>8}{'(to 200MA':>11}{' / 50d-hi)':>10}{'ADR':>6}  ~days")
    print("  "+"-"*70)
    for n,(_,r) in enumerate(df.iterrows(),1):
        days = r["trig"]/r["adr"] if r["adr"]>0 else 0
        flag = "✅ above 200MA" if r["above200"] else ""
        print(f"  {n:>2} {r['tk']:7}{r['close']:>9,.0f}{('+'+format(r['trig'],'.0f')+'%'):>8}"
              f"{('+'+format(r['to200'],'.0f')+'%'):>11}{('+'+format(r['to50h'],'.0f')+'%'):>10}"
              f"{r['adr']:>5.1f}%{days:>5.0f}  {flag}")
    print("\n  'needs' = total % rise to fire (the bigger of: reach 200MA, or break 50d-high).")
    print("  '~days' = needs ÷ ADR = rough trading days of strong moves to get there.")
    print("  Top of list = closest to becoming a real candidate. None fire until 'needs' hits 0.")

if __name__=="__main__":
    main()
