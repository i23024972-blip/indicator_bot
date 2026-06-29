# idx_dividend_runup.py — the DIVIDEND RUN-UP trade on IDX blue chips.
# Thesis: dividend-hunters bid a stock UP into the cum-date, then dump after ex-date (the trap).
# So instead of collecting the dividend, we ride the run-up and SELL on the cum-date (1 day
# before ex) — out before the drop. Backtest: for every dividend over ~4y, buy N trading days
# before the ex-date, sell on the cum-date. Sweep N. Compare to the TRAP (holding through ex).
# Uses UNADJUSTED close (adjusted prices erase the ex-date drop we're studying).
import sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

# IDX blue-chip dividend payers (banks, telco, coal, consumer, industrial, cement, plantation)
TICKERS = ["BBCA","BBRI","BMRI","BBNI","BBTN","TLKM","ASII","UNTR","ITMG","PTBA",
           "ADRO","HMSP","GGRM","UNVR","INDF","ICBP","SMGR","INTP","KLBF","AALI",
           "ANTM","PGAS","JPFA","TINS"]
COST = 0.3            # % round-trip fee+slippage
N_LIST = [40,30,20,15,10,5]   # trading days before ex-date to buy
YEARS = 4

def main():
    print(f"DIVIDEND RUN-UP · IDX blue chips · last {YEARS}y · sell on cum-date (1d before ex)\n")
    # collect every (ticker, ex_date, run_up_for_each_N, yield, trap_return)
    recs = []
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=YEARS)
    for tk in TICKERS:
        try:
            t = yf.Ticker(tk + ".JK")
            hist = t.history(period=f"{YEARS+1}y", auto_adjust=False)
            divs = t.dividends
            if hist is None or len(hist) < 60 or divs is None or len(divs) == 0:
                print(f"  {tk}: no data"); continue
            close = hist["Close"].values
            dates = hist.index.tz_localize(None).normalize()
            for ex_date, amt in divs.items():
                ex = pd.Timestamp(ex_date).tz_localize(None).normalize()
                if ex < cutoff: continue
                pos = int(dates.searchsorted(ex))          # first trading day >= ex-date
                if pos < max(N_LIST)+1 or pos >= len(close)-6: continue
                cum_px = close[pos-1]                        # cum-date price (sell here)
                ups = {N: (cum_px-close[pos-N])/close[pos-N]*100 - COST for N in N_LIST}
                trap = (close[min(pos+5,len(close)-1)]-close[pos-20])/close[pos-20]*100 - COST  # buy 20d pre, hold 5d past ex
                recs.append(dict(tk=tk, ex=ex.date(), amt=amt, yld=amt/cum_px*100,
                                 trap=trap, **{f"N{N}":ups[N] for N in N_LIST}))
        except Exception as e:
            print(f"  {tk}: {e}")
    df = pd.DataFrame(recs)
    if df.empty:
        print("no dividend events found"); return
    print(f"  {len(df)} dividend events across {df.tk.nunique()} stocks.\n")

    print("="*60+"\n  RUN-UP by ENTRY TIMING (sell on cum-date, net cost)\n"+"="*60)
    print(f"  {'buy ___ days before ex':24}{'avg':>7}{'median':>8}{'win%':>6}")
    best=None
    for N in N_LIST:
        col=df[f"N{N}"]
        wr=(col>0).mean()*100
        print(f"  {('buy '+str(N)+'d before'):24}{col.mean():>+6.1f}%{col.median():>+7.1f}%{wr:>5.0f}%")
        if best is None or col.mean()>best[1]: best=(N,col.mean(),wr)

    print("\n"+"="*60+"\n  THE TRAP (buy 20d before, HOLD through ex-date +5d)\n"+"="*60)
    print(f"  Avg: {df.trap.mean():+.1f}%  ·  win {(df.trap>0).mean()*100:.0f}%  "
          f"← holding through ex-date {'LOSES' if df.trap.mean()<df[f'N{best[0]}'].mean() else 'beats run-up'}")

    print("\n"+"="*60+f"\n  BEST TIMING = buy {best[0]}d before ex · which stocks run up most?\n"+"="*60)
    g=df.groupby("tk")[f"N{best[0]}"].agg(["mean","count"]).sort_values("mean",ascending=False)
    for tk,row in g.iterrows():
        print(f"  {tk:6} {row['mean']:>+6.1f}% avg  ({int(row['count'])} dividends)")
    print(f"\n  Run-up avg yield of these dividends: {df.yld.mean():.1f}%")
    print("  Read: positive run-up + selling before ex = capture appreciation, dodge the trap.")

if __name__=="__main__":
    main()
