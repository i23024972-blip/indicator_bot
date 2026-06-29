# crypto_scanner.py — DYNAMIC universe scanner (no fixed list = no dead end). Pulls all liquid
# Binance perps, then finds the ones currently SET UP for the strategy right now:
#   SHORT-ready = downtrend (below 200-EMA) + broke/near previous-day LOW  + moderate vol
#   LONG-ready  = uptrend   (above 200-EMA) + broke/near previous-day HIGH + moderate vol
# Filters out the chaotic high-vol coins (the whipsaw losers) and dead low-vol ones.
import sys, time, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from binance.client import Client

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MIN_VOL=50e6        # $50M/24h minimum (liquid)
TOPN=70             # scan top-N by volume
VOL_LO, VOL_HI=0.8, 3.2   # keep moderate-volatility coins (skip dead & chaotic)
NEAR=2.0            # within 2% of the level = "watch"

def mkclient():
    for _ in range(6):
        try: return Client(requests_params={"timeout":30})
        except Exception: time.sleep(6)
    return Client(requests_params={"timeout":30})
client=mkclient()

def main():
    info=client.futures_exchange_info()
    syms=[s["symbol"] for s in info["symbols"]
          if s["symbol"].endswith("USDT") and s.get("contractType")=="PERPETUAL" and s["status"]=="TRADING"]
    vol={t["symbol"]:float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid=sorted([s for s in syms if vol.get(s,0)>=MIN_VOL], key=lambda s:-vol.get(s,0))[:TOPN]
    print(f"Scanning {len(liquid)} liquid perps (>${MIN_VOL/1e6:.0f}M/24h) for current setups...\n")

    shorts=[]; longs=[]
    for s in liquid:
        try:
            kl=client.futures_klines(symbol=s, interval="4h", limit=260)
            df=pd.DataFrame(kl,columns=["t","o","h","l","c","v","ct","q","n","tb","tq","ig"])
            for x in ["o","h","l","c"]: df[x]=df[x].astype(float)
            df["time"]=pd.to_datetime(df["t"],unit="ms")
            if len(df)<210: continue
            ema=df["c"].ewm(span=200,adjust=False).mean().iloc[-1]
            pc=df["c"].shift(1); tr=pd.concat([(df["h"]-df["l"]),(df["h"]-pc).abs(),(df["l"]-pc).abs()],axis=1).max(axis=1)
            atrp=(tr.rolling(14).mean()/df["c"]).iloc[-1]*100
            day=df["time"].dt.floor("D")
            pdh=df.groupby(day)["h"].max().shift(1).iloc[-1]
            pdl=df.groupby(day)["l"].min().shift(1).iloc[-1]
            c=df["c"].iloc[-1]
            if not (VOL_LO<=atrp<=VOL_HI): continue           # keep moderate-vol only
            name=s.replace("USDT","")
            if c<ema:                                          # downtrend → short side
                d=(c-pdl)/c*100                                # % above prev-day low (≤0 = broke)
                if d<=NEAR: shorts.append((name,c,atrp,d,vol[s]))
            else:                                              # uptrend → long side
                d=(pdh-c)/c*100
                if d<=NEAR: longs.append((name,c,atrp,d,vol[s]))
        except Exception: pass

    shorts.sort(key=lambda x:x[3]); longs.sort(key=lambda x:x[3])
    def show(rows,title,brk):
        print("="*60+f"\n  {title}  ({len(rows)})\n"+"="*60)
        if not rows: print("  none right now"); return
        print(f"  {'coin':9}{'price':>12}{'vol%':>6}{'vs level':>10}  status")
        for nm,c,v,d,vl in rows[:15]:
            st = brk if d<=0 else f"{d:.1f}% away"
            print(f"  {nm:9}{c:>12,.4f}{v:>5.1f}%{('broke' if d<=0 else f'+{d:.1f}%'):>10}  {st}")
    show(shorts,"🔴 SHORT-ready (downtrend + breaking/near prev-day LOW)","🔻 BROKE DOWN — short setup")
    print()
    show(longs,"🟢 LONG-ready (uptrend + breaking/near prev-day HIGH)","🔺 BROKE UP — long setup")
    print("\n  This is a LIVE scan of the whole liquid market — no fixed list. The bot would do")
    print("  this daily and trade whatever's set up (mostly shorts now = bearish crypto).")

if __name__=="__main__":
    main()
