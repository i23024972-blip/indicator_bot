# zigzag_recent.py
# Apply the PROFITABLE config (4H bias + 30M entry, %-deviation 5%, TP4/SL1.5, traded as spot)
# to the LAST 2 WEEKS only, and print a trade-by-trade ledger + $ result on a $1000 account.
import os
import pandas as pd
import numpy as np
from datetime import timedelta
from binance.client import Client

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".klines_cache")

SYMBOLS       = [("BTCUSDT", False), ("HYPEUSDT", True)]   # traded as spot
CONTEXT_DAYS  = 300      # history pulled to build structure (cached -> instant)
RECENT_DAYS   = 14       # only report trades ENTERED in this trailing window
BIAS_IV  = Client.KLINE_INTERVAL_4HOUR
ENTRY_IV = Client.KLINE_INTERVAL_30MINUTE

DEVIATION = 5.0
ATR_TP, ATR_SL = 4.0, 1.5
FRESH_ONLY = True
SPOT_FEE   = 0.20
START_CAPITAL = 1000.0

client = Client()
BULL = ("HH+HL", "HL"); BEAR = ("LL+LH", "LH")

def get_historical(symbol, interval, is_futures=False, days=CONTEXT_DAYS):
    os.makedirs(CACHE_DIR, exist_ok=True)
    fpath = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{'fut' if is_futures else 'spot'}_{days}d.parquet")
    if os.path.exists(fpath):
        return pd.read_parquet(fpath)
    start_str = f"{days} days ago UTC"
    klines = (client.futures_historical_klines(symbol, interval, start_str) if is_futures
              else client.get_historical_klines(symbol, interval, start_str))
    if not klines: return None
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    try: df.to_parquet(fpath)
    except Exception: pass
    return df

def atr_series(df, window=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(window).mean()

def compute_zigzag_pivots(df, deviation_pct):
    highs=df["high"].values; lows=df["low"].values; n=len(df); pivots=[]; trend=None
    eh_p,eh_i=highs[0],0; el_p,el_i=lows[0],0
    for i in range(1,n):
        if highs[i]>eh_p: eh_p,eh_i=highs[i],i
        if lows[i]<el_p: el_p,el_i=lows[i],i
        if trend is None:
            if (eh_p-lows[i])/eh_p*100>=deviation_pct:
                pivots.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
            elif (highs[i]-el_p)/el_p*100>=deviation_pct:
                pivots.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
        elif trend=='up':
            if (eh_p-lows[i])/eh_p*100>=deviation_pct:
                pivots.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
        elif trend=='down':
            if (highs[i]-el_p)/el_p*100>=deviation_pct:
                pivots.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
    return pivots

def structure_label_array(df, pivots):
    n=len(df); labels=["neutral"]*n; hs=[]; ls=[]; pj=0
    sp=sorted(pivots,key=lambda p:p[3])
    def cur():
        if len(hs)>=2 and len(ls)>=2:
            hh,hl=hs[-1]>hs[-2],ls[-1]>ls[-2]; ll,lh=ls[-1]<ls[-2],hs[-1]<hs[-2]
            if hh and hl: return "HH+HL"
            if ll and lh: return "LL+LH"
            if hl: return "HL"
            if lh: return "LH"
        return "neutral"
    for i in range(n):
        while pj<len(sp) and sp[pj][3]<=i:
            p=sp[pj]; (hs if p[2]=='high' else ls).append(p[1]); pj+=1
        labels[i]=cur()
    return labels

def exit_fixed(highs,lows,closes,entry_idx,is_buy,atr):
    entry=closes[entry_idx]
    sl=entry-atr*ATR_SL if is_buy else entry+atr*ATR_SL
    tp=entry+atr*ATR_TP if is_buy else entry-atr*ATR_TP
    for i in range(entry_idx+1,len(closes)):
        hi,lo=highs[i],lows[i]
        if is_buy:
            if lo<=sl: return ((sl-entry)/entry)*100,"SL",i
            if hi>=tp: return ((tp-entry)/entry)*100,"TP",i
        else:
            if hi>=sl: return ((entry-sl)/entry)*100,"SL",i
            if lo<=tp: return ((entry-tp)/entry)*100,"TP",i
    return None,"OPEN",None

def trades_for(sym, fut, cutoff):
    bias_df=get_historical(sym,BIAS_IV,fut); entry_df=get_historical(sym,ENTRY_IV,fut)
    if bias_df is None or entry_df is None: return []
    entry_df=entry_df.copy(); entry_df["atr"]=atr_series(entry_df)
    bias_lbl=structure_label_array(bias_df,compute_zigzag_pivots(bias_df,DEVIATION))
    entry_lbl=structure_label_array(entry_df,compute_zigzag_pivots(entry_df,DEVIATION))
    bt=bias_df["time"].values; et=entry_df["time"].values
    bidx_for=np.searchsorted(bt,et,side="right")-1
    atr_v=entry_df["atr"].values
    e_h=entry_df["high"].values; e_l=entry_df["low"].values; e_c=entry_df["close"].values
    out=[]; prev=None
    for i in range(50,len(entry_df)-1):
        if pd.isna(atr_v[i]): continue
        bidx=bidx_for[i]
        if bidx<10: continue
        s_bias=bias_lbl[bidx]; s_entry=entry_lbl[i]
        fresh=(s_entry!=prev); prev=s_entry
        if FRESH_ONLY and not fresh: continue
        bull=(s_bias in BULL) and (s_entry in BULL)
        bear=(s_bias in BEAR) and (s_entry in BEAR)
        if not (bull or bear): continue
        t=pd.Timestamp(et[i])
        if t < cutoff: continue                      # only last RECENT_DAYS
        pnl,ex,xi=exit_fixed(e_h,e_l,e_c,i,bull,atr_v[i])
        out.append({"symbol":sym,"time":t,"side":"BUY" if bull else "SELL",
                    "entry":e_c[i],"pnl_pct":pnl,"exit":ex,
                    "exit_time":pd.Timestamp(et[xi]) if xi is not None else None})
    return out

def main():
    end = pd.Timestamp.utcnow().tz_localize(None)
    cutoff = end - timedelta(days=RECENT_DAYS)
    print(f"Recent-window backtest | last {RECENT_DAYS} days (since {cutoff:%Y-%m-%d %H:%M} UTC)")
    print(f"Config: 4H bias + 30M entry | dev {DEVIATION}% | TP{ATR_TP}/SL{ATR_SL} | spot fee {SPOT_FEE}% | ${START_CAPITAL:,.0f} acct\n")

    trades=[]
    for sym,fut in SYMBOLS:
        trades += trades_for(sym,fut,cutoff)
    trades.sort(key=lambda x:x["time"])

    if not trades:
        print("  No trades triggered in the last 2 weeks."); return

    print(f"  {'#':>2} {'Entry time (UTC)':>16} {'Sym':>8} {'Side':>4} {'Exit':>5} {'PnL%':>8} {'Equity$':>10}")
    print("  "+"-"*64)
    bal=START_CAPITAL; closed=0; wins=0; open_n=0
    for k,t in enumerate(trades,1):
        if t["pnl_pct"] is None:
            print(f"  {k:>2} {t['time']:%m-%d %H:%M} {t['symbol']:>8} {t['side']:>4} {'OPEN':>5} {'--':>8} {'--':>10}")
            open_n+=1; continue
        net=t["pnl_pct"]-SPOT_FEE
        bal*=(1+net/100.0); closed+=1; wins+=1 if net>0 else 0
        print(f"  {k:>2} {t['time']:%m-%d %H:%M} {t['symbol']:>8} {t['side']:>4} {t['exit']:>5} {net:>+7.2f}% {bal:>9,.2f}")
    print("  "+"-"*64)
    pnl_dollar = bal-START_CAPITAL
    print(f"\n  Closed trades : {closed}   (still open: {open_n})")
    if closed:
        print(f"  Win rate      : {wins/closed*100:.1f}%  ({wins}W / {closed-wins}L)")
    print(f"  Start         : ${START_CAPITAL:,.2f}")
    print(f"  End           : ${bal:,.2f}")
    print(f"  Profit        : ${pnl_dollar:+,.2f}  ({pnl_dollar/START_CAPITAL*100:+.2f}%)")
    print(f"\n  Note: full equity per trade, compounding, net of {SPOT_FEE}% spot fee.")
    print("  Open trades aren't counted in profit (TP/SL not hit yet).")

if __name__ == "__main__":
    main()
