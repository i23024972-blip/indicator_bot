# crypto_bot.py — LIVE paper-trade bot: regime-directional dynamic-universe crypto strategy.
#   Regime (BTC): BULL → take LONG breakouts · BEAR → take SHORT breakdowns · CRASH → CASH.
#   Universe   : scanned live (top liquid perps, moderate-vol only) — no fixed list.
#   Signal     : break prev-day high (long) / low (short), price on trend side of 200-EMA.
#   Exit       : ride a 4-ATR chandelier trail (let winners run). Risk 1%/trade, max 6 positions.
# Run on a schedule (e.g. every 4h). State in crypto_paper_state.json. Telegram → your group.
import os, sys, json, time
import numpy as np, pandas as pd
from binance.client import Client
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

START=1000.0; RISK=1.0; MAXPOS=6; SL_ATR=3.0; TRAIL_ATR=4.0
MIN_VOL=50e6; TOPN=45; VOL_LO,VOL_HI=0.8,3.2; INTERVAL="4h"
CAPITAL=float(os.getenv("CRYPTO_CAPITAL","0") or 0)   # your REAL $ — alerts show how much to put in (0 = hide)
STATE=os.path.join(os.path.dirname(__file__),"crypto_paper_state.json")

def mkclient():
    for _ in range(6):
        try: return Client(requests_params={"timeout":30})
        except Exception: time.sleep(5)
    return Client(requests_params={"timeout":30})
client=mkclient()

def notify(text):
    tok=os.getenv("CRYPTO_TG_TOKEN") or os.getenv("IDX_TG_TOKEN")   # own bot, or reuse IDX bot
    chat=os.getenv("CRYPTO_TG_CHAT")                                # SEPARATE crypto chat/group
    if not tok or not chat: return                                  # no crypto chat set = stays silent
    try: import requests
    except Exception: return
    for _ in range(4):
        try:
            if requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",data={"chat_id":chat,"text":text},timeout=30).ok: return
        except Exception: pass
        time.sleep(4)

def load():
    try:
        with open(STATE) as f: return json.load(f)
    except Exception: return {"cash":START,"positions":{},"closed":[],"curve":[]}
def save(s):
    with open(STATE,"w") as f: json.dump(s,f,indent=2,default=str)

def klines(sym,limit=300):
    kl=client.futures_klines(symbol=sym,interval=INTERVAL,limit=limit)
    df=pd.DataFrame(kl,columns=["t","open","high","low","close","v","ct","q","n","tb","tq","ig"])
    for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
    df["time"]=pd.to_datetime(df["t"],unit="ms")
    pc=df["close"].shift(1); tr=pd.concat([(df["high"]-df["low"]),(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
    df["atr"]=tr.rolling(14).mean(); df["ema"]=df["close"].ewm(span=200,adjust=False).mean()
    day=df["time"].dt.floor("D")
    df["pdh"]=day.map(df.groupby(day)["high"].max().shift(1)); df["pdl"]=day.map(df.groupby(day)["low"].min().shift(1))
    return df

def regime():
    d=klines("BTCUSDT",500)
    dd=d.set_index("time")["close"].resample("D").last()
    cur=dd.iloc[-1]; ma200=dd.rolling(200).mean().iloc[-1]; hi90=dd.rolling(90).max().iloc[-1]
    if cur/hi90-1<=-0.25: return "CRASH"
    return "BULL" if cur>ma200 else "BEAR"

def main():
    st=load(); reg=regime(); events=[]
    # universe
    syms=[s["symbol"] for s in client.futures_exchange_info()["symbols"]
          if s["symbol"].endswith("USDT") and s.get("contractType")=="PERPETUAL" and s["status"]=="TRADING"]
    vol={t["symbol"]:float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid=sorted([s for s in syms if vol.get(s,0)>=MIN_VOL],key=lambda s:-vol.get(s,0))[:TOPN]
    bars={}
    for s in liquid:
        try: bars[s]=klines(s)
        except Exception: pass

    # 1) manage open positions (trailing-stop exit, on latest bar)
    for sym in list(st["positions"]):
        d=bars.get(sym);
        if d is None or len(d)<2: continue
        r=d.iloc[-1]; p=st["positions"][sym]; dir=p["dir"]; a=float(r["atr"])
        p["peak"]=max(p.get("peak",p["entry"]),float(r["high"])) if dir==1 else min(p.get("peak",p["entry"]),float(r["low"]))
        trail=p["peak"]-TRAIL_ATR*a if dir==1 else p["peak"]+TRAIL_ATR*a
        p["stop"]=max(p["stop"],trail) if dir==1 else min(p["stop"],trail)
        hit=(dir==1 and float(r["low"])<=p["stop"]) or (dir==-1 and float(r["high"])>=p["stop"])
        if hit:
            px=p["stop"]; pnl=dir*(px-p["entry"])/p["entry"]*100
            st["cash"]+=p["units"]*p["entry"]+p["units"]*(px-p["entry"])*dir
            st["closed"].append({"sym":sym,"dir":"L" if dir==1 else "S","pnl":round(pnl,1)})
            events.append(f"🚪 CLOSE {sym.replace('USDT','')} {'L' if dir==1 else 'S'} @ {px:,.4g} ({pnl:+.1f}%)")
            del st["positions"][sym]

    # 2) new entries — only in regime direction (BULL→long, BEAR→short, CRASH→none)
    want = 1 if reg=="BULL" else (-1 if reg=="BEAR" else 0)
    if want!=0:
        for sym,d in bars.items():
            if sym in st["positions"] or len(st["positions"])>=MAXPOS: continue
            if len(d)<210: continue
            volp=(d["atr"]/d["close"]).median()*100
            if not (VOL_LO<=volp<=VOL_HI): continue
            r=d.iloc[-1]; pr=d.iloc[-2]; a=float(r["atr"])
            if pd.isna(a) or a<=0 or pd.isna(r["pdh"]) or pd.isna(r["ema"]): continue
            sig = (want==1 and r["close"]>r["pdh"] and pr["close"]<=r["pdh"] and r["close"]>r["ema"]) or \
                  (want==-1 and r["close"]<r["pdl"] and pr["close"]>=r["pdl"] and r["close"]<r["ema"])
            if not sig: continue
            entry=float(r["close"]); stop=entry-want*SL_ATR*a
            eq=st["cash"]+sum(pp["units"]*pp["entry"] for pp in st["positions"].values())
            risk_usd=RISK/100*eq; units=risk_usd/(SL_ATR*a)
            cost=units*entry
            if cost>st["cash"] or units<=0: continue
            st["cash"]-=cost
            st["positions"][sym]={"dir":want,"entry":entry,"units":units,"stop":stop,"peak":entry}
            R=SL_ATR*a; tp1=entry+want*2*R; tp2=entry+want*4*R   # 1R=3·ATR; scale-out at +2R/+4R
            msg=f"✅ {'LONG' if want==1 else 'SHORT'} {sym.replace('USDT','')} @ {entry:,.4g} → STOP {stop:,.4g}"
            if CAPITAL>0:
                rrisk=RISK/100*CAPITAL; rnotional=rrisk/(SL_ATR*a)*entry
                msg+=f"  ·  PUT IN ${rnotional:,.0f} (risk ${rrisk:,.0f})"
            else:
                msg+="  (set hard stop)"
            if tp1>0 and tp2>0:
                msg+=f"\n   TP1 {tp1:,.4g} (+2R → sell ⅓) · TP2 {tp2:,.4g} (+4R → sell ⅓) · runner rides trail"
            else:
                msg+=f"\n   TP n/a — stop {abs(stop/entry-1)*100:.0f}% wide (vol spike); ride 4·ATR trail only"
            events.append(msg)

    eq=st["cash"]+sum(p["units"]*p["entry"] for p in st["positions"].values())
    today=str(pd.Timestamp.now('UTC').date()); do_hb=st.get("hb_date")!=today
    st["curve"].append([str(pd.Timestamp.now('UTC'))[:16],round(eq,2)])
    if do_hb: st["hb_date"]=today
    save(st)

    tag="🟢 alive" if not events else "🔔 ACTION"
    L=[f"🤖 CRYPTO BOT · {str(pd.Timestamp.now('UTC'))[:16]}Z · {tag}","━"*22,
       f"Regime: {reg}  →  {'LONGS' if reg=='BULL' else ('SHORTS' if reg=='BEAR' else 'CASH (sit out)')}",
       f"Equity: ${eq:,.0f} ({(eq/START-1)*100:+.1f}%) · open {len(st['positions'])}/{MAXPOS} · closed {len(st['closed'])}"]
    for sym,p in st["positions"].items():
        cur=float(bars[sym]["close"].iloc[-1]) if sym in bars else p["entry"]; upl=p["dir"]*(cur-p["entry"])/p["entry"]*100
        L.append(f"  • {sym.replace('USDT','')} {'L' if p['dir']==1 else 'S'} {p['entry']:,.4g}→{cur:,.4g} ({upl:+.1f}%) · stop {p['stop']:,.4g}")
    L+=[f"  {e}" for e in events]
    rep="\n".join(L); print(rep)
    if events or do_hb: notify(rep)   # alert on every action; heartbeat only once/day (no 4h spam)

if __name__=="__main__":
    main()
