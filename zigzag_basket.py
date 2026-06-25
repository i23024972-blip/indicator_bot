# zigzag_basket.py
# More TRADES via more markets. NOTE: result showed the full 10-coin basket DILUTES the edge to
# breakeven; only a subset of coins (ETH/BNB/DOGE/ADA/HYPE) stays profitable (see RESEARCH_NOTES.md).
# Config: 4H bias + 30M entry, %-deviation 5%, TP4/SL1.5, traded as spot. $1000 compounding.
import os
import pandas as pd
import numpy as np
from datetime import timedelta
from binance.client import Client

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".klines_cache")

# user's chosen set: BTC + HYPE (trusted) + DOGE (held up over 1000d)
SYMBOLS = [
    ("BTCUSDT", False), ("DOGEUSDT", False), ("HYPEUSDT", True),
]
DAYS = 1000
BIAS_IV  = Client.KLINE_INTERVAL_4HOUR
ENTRY_IV = Client.KLINE_INTERVAL_30MINUTE
DEVIATION = 5.0
ATR_TP, ATR_SL = 4.0, 1.5
FRESH_ONLY = True
SPOT_FEE = 0.20           # LONG legs on spot (round-trip)
FUT_FEE  = 0.10           # SHORT legs on futures 1x (round-trip, cheaper)
def fee_of(side): return SPOT_FEE if side == "LONG" else FUT_FEE
START_CAPITAL = 1000.0

try:
    client = Client()                  # pings Binance on init
except Exception as e:
    client = None                      # offline: fine as long as data is already cached
    print(f"  (offline — Binance unreachable, using pickle cache only: {e})")
BULL = ("HH+HL", "HL"); BEAR = ("LL+LH", "LH")

def get_historical(symbol, interval, is_futures=False, days=DAYS):
    os.makedirs(CACHE_DIR, exist_ok=True)
    # pickle cache: built into pandas, no pyarrow dependency (parquet was failing silently)
    fpath = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{'fut' if is_futures else 'spot'}_{days}d.pkl")
    if os.path.exists(fpath):
        try: return pd.read_pickle(fpath)
        except Exception: pass
    start_str = f"{days} days ago UTC"
    klines = None
    for attempt in range(3):                       # retry transient network timeouts
        try:
            klines = (client.futures_historical_klines(symbol, interval, start_str) if is_futures
                      else client.get_historical_klines(symbol, interval, start_str))
            break
        except Exception as e:
            print(f"  WARN {symbol} {interval} (try {attempt+1}/3): {e}")
    if not klines: return None
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume",
        "ct","qav","not","tbbav","tbqav","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    try: df.to_pickle(fpath)
    except Exception as e: print(f"  (cache write failed: {e})")
    return df

def atr_series(df, window=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.rolling(window).mean()

def compute_zigzag_pivots(df, dev):
    highs=df["high"].values; lows=df["low"].values; n=len(df); pivots=[]; trend=None
    eh_p,eh_i=highs[0],0; el_p,el_i=lows[0],0
    for i in range(1,n):
        if highs[i]>eh_p: eh_p,eh_i=highs[i],i
        if lows[i]<el_p: el_p,el_i=lows[i],i
        if trend is None:
            if (eh_p-lows[i])/eh_p*100>=dev: pivots.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
            elif (highs[i]-el_p)/el_p*100>=dev: pivots.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
        elif trend=='up':
            if (eh_p-lows[i])/eh_p*100>=dev: pivots.append((eh_i,eh_p,'high',i)); trend='down'; el_p,el_i=lows[i],i
        elif trend=='down':
            if (highs[i]-el_p)/el_p*100>=dev: pivots.append((el_i,el_p,'low',i)); trend='up'; eh_p,eh_i=highs[i],i
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

def exit_fixed(h,l,c,e_idx,is_buy,atr):
    entry=c[e_idx]
    sl=entry-atr*ATR_SL if is_buy else entry+atr*ATR_SL
    tp=entry+atr*ATR_TP if is_buy else entry-atr*ATR_TP
    for i in range(e_idx+1,len(c)):
        if is_buy:
            if l[i]<=sl: return ((sl-entry)/entry)*100,i
            if h[i]>=tp: return ((tp-entry)/entry)*100,i
        else:
            if h[i]>=sl: return ((entry-sl)/entry)*100,i
            if l[i]<=tp: return ((entry-tp)/entry)*100,i
    return None,None

def trades_for(sym, fut):
    bias_df=get_historical(sym,BIAS_IV,fut); entry_df=get_historical(sym,ENTRY_IV,fut)
    if bias_df is None or entry_df is None or len(entry_df)<100: return []
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
        pnl,xi=exit_fixed(e_h,e_l,e_c,i,bull,atr_v[i])
        if pnl is None: continue
        side = "LONG" if bull else "SHORT"
        out.append({"symbol":sym,"time":pd.Timestamp(et[i]),"pnl_pct":pnl,
                    "side":side,"net":pnl-fee_of(side)})
    return out

def main():
    print(f"ZigZag BASKET | {len(SYMBOLS)} coins | {DAYS}d | 4H bias + 30M entry | dev {DEVIATION}% | TP{ATR_TP}/SL{ATR_SL} | spot")
    print(f"Goal: more trades by adding MARKETS (not looser filters). $1000 compounding, {SPOT_FEE}% fee.\n")
    print("  Downloading any missing coins (first run only, then cached)...")
    all_tr=[]; per_sym={}
    print(f"  {'coin':>10}: {'trades':>6} {'win%':>6} {'BEP':>8} {'net':>8}  {'$1000(this coin)':>16}")
    rows=[]
    for sym,fut in SYMBOLS:
        ts=trades_for(sym,fut)
        per_sym[sym]=ts; all_tr+=ts
        if ts:
            b=START_CAPITAL
            for t in sorted(ts,key=lambda x:x["time"]): b*=(1+t["net"]/100.0)
            bep=np.mean([t["pnl_pct"] for t in ts]); w=sum(1 for t in ts if t["net"]>0)
            net=np.mean([t["net"] for t in ts]); rows.append((sym,len(ts),w/len(ts)*100,bep,net,b))
        else:
            rows.append((sym,0,0,0,0,START_CAPITAL))
    for sym,nt,wr,bep,net,b in sorted(rows,key=lambda r:-r[5]):
        flag=" <- PROFIT" if b>START_CAPITAL else ""
        print(f"  {sym:>10}: {nt:>6} {wr:>5.0f}% {bep:>+7.3f}% {net:>+7.3f}%  {('$'+format(b,',.0f')):>16}{flag}")
    if not all_tr:
        print("  No trades."); return
    all_tr.sort(key=lambda x:x["time"])
    bal=START_CAPITAL; wins=0
    for t in all_tr:
        bal*=(1+t["net"]/100.0); wins+=1 if t["net"]>0 else 0
    n=len(all_tr); gross=np.mean([t["pnl_pct"] for t in all_tr]); netavg=np.mean([t["net"] for t in all_tr])
    # rough trade cadence
    span_days=(all_tr[-1]["time"]-all_tr[0]["time"]).days or 1
    print(f"\n  {'='*52}")
    print(f"  TOTAL trades   : {n}   (~1 every {span_days/n:.1f} days, ~{n/ (span_days/30.0):.0f}/month)")
    print(f"  Win rate       : {wins/n*100:.1f}%")
    print(f"  BEP/trade      : {gross:+.3f}%   net after fee: {netavg:+.3f}%  (long 0.20% / short 0.10% fee)")
    print(f"  $1000 -> ${bal:,.2f}   ({(bal-START_CAPITAL)/START_CAPITAL*100:+.1f}%)")
    print(f"  {'='*52}")
    # profitable subset = coins whose own net-after-fee expectancy is positive
    good = [sym for (sym,nt,wr,bep,net,b) in rows if net > 0]
    sub = sorted([t for t in all_tr if t["symbol"] in good], key=lambda x:x["time"])
    if sub:
        sb=START_CAPITAL; sw=0
        for t in sub: sb*=(1+t["net"]/100.0); sw+=1 if t["net"]>0 else 0
        sg=np.mean([t["pnl_pct"] for t in sub]); sn=np.mean([t["net"] for t in sub])
        sd=(sub[-1]["time"]-sub[0]["time"]).days or 1
        print(f"\n  PROFITABLE SUBSET ({', '.join(good)}):")
        print(f"    {len(sub)} trades (~{len(sub)/(sd/30.0):.0f}/month), win {sw/len(sub)*100:.1f}%, "
              f"BEP {sg:+.3f}% (net {sn:+.3f}%), $1000 -> ${sb:,.2f} ({(sb-START_CAPITAL)/10:.1f}%)")
        print(f"    ^ CAUTION: these are PAST winners. Cherry-picking them is overfitting -- no guarantee they repeat.")
    # LONG vs SHORT split + spot-realistic (long-only) result
    def equity_of(trs):
        b=START_CAPITAL; w=0
        for t in sorted(trs,key=lambda x:x['time']):
            b*=(1+t['net']/100.0); w+=1 if t['net']>0 else 0
        return b,(w/len(trs)*100 if trs else 0)
    longs =[t for t in all_tr if t['side']=="LONG"]
    shorts=[t for t in all_tr if t['side']=="SHORT"]
    lb,lw=equity_of(longs); sb,sw=equity_of(shorts)
    print(f"\n  {'='*52}")
    print(f"  LONG vs SHORT  (you can only do LONG on spot!):")
    print(f"    LONG  : {len(longs):>4} trades, {lw:.0f}% win -> $1000 = ${lb:,.0f}")
    print(f"    SHORT : {len(shorts):>4} trades, {sw:.0f}% win -> $1000 = ${sb:,.0f}   (futures 1x, 0.10% fee)")
    print(f"  LONG-ONLY (spot only):     $1000 -> ${lb:,.2f}  ({(lb-START_CAPITAL)/10:+.1f}%)")
    print(f"  {'='*52}")

    print(f"\n  vs 2-coin version: 135 trades, $1,272.")
    RECENT_DAYS = 60
    cut=pd.Timestamp.now(tz='UTC').tz_localize(None)-timedelta(days=RECENT_DAYS)
    rec=sorted([t for t in all_tr if t['time']>=cut], key=lambda x:x['time'])
    print(f"\n  LAST {RECENT_DAYS} DAYS (since {cut:%Y-%m-%d}) — trade-by-trade on $1000:")
    if rec:
        print(f"    {'#':>2} {'entry (UTC)':>12} {'coin':>9} {'net%':>8} {'equity$':>10}")
        rb=START_CAPITAL; rw=0
        for k,t in enumerate(rec,1):
            rb*=(1+t['net']/100.0); rw+=1 if t['net']>0 else 0
            print(f"    {k:>2} {t['time']:%m-%d %H:%M} {t['symbol']:>9} {t['side']:>5} {t['net']:>+7.2f}% {rb:>9,.2f}")
        print(f"    {'-'*44}")
        print(f"    {len(rec)} closed trades, {rw/len(rec)*100:.0f}% win  ->  $1000 became ${rb:,.2f}  ({(rb-START_CAPITAL)/10:+.1f}%)")
        print(f"    (still-open trades not shown)")
    else:
        print("    no closed trades in window")

if __name__ == "__main__":
    main()
