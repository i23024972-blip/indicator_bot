# idx_ab_paper.py — A/B FORWARD paper-trade: run BOTH strategies live, let the real market decide.
#   Strategy A = DONCH50+200  : close breaks 50-day high above 200MA → confirm buy-stop →
#                               ride 50EMA + 4-ATR trail.        (anti-manipulation, current bot)
#   Strategy B = COMBO        : up-day + 2.5x volume + >50MA + bullish daily+weekly zigzag →
#                               next-open entry → 2-ATR stop / 6-ATR target / 20-day max.  (old scan)
# Same konglo universe, same Rp 16M each, same 20%×5 sizing — so we compare the SIGNAL LOGIC.
# Run daily after the close. Two portfolios in idx_ab_state.json; reports A vs B equity head-to-head.
import os, sys, json, time
import pandas as pd
import idx_konglo as K
from idx_hybrid_backtest import fire_combo

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception: pass

ACCOUNT=16_000_000; SIZE_FRAC=0.20; MAX_POS=5; SLIP=0.003
TRIG_BUF=0.005; MAXGAP=0.04
A_EMA=50; A_TRAIL=4.0; A_INIT=2.5                 # Strategy A exit
B_SL=2.0; B_TP=6.0; B_HOLD=20                      # Strategy B exit (COMBO)
SPIKE_X=2.5; DONCH=50
STATE=os.path.join(os.path.dirname(__file__),"idx_ab_state.json")

def notify(text):
    tok,chat=os.getenv("IDX_TG_TOKEN"),os.getenv("IDX_TG_CHAT")
    if not tok or not chat: return
    try: import requests
    except Exception: return
    for _ in range(4):
        try:
            if requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                             data={"chat_id":chat,"text":text},timeout=30).ok: return
        except Exception: pass
        time.sleep(4)

def load():
    try:
        with open(STATE) as f: return json.load(f)
    except Exception:
        blank=lambda:{"cash":ACCOUNT,"positions":{},"pending":{},"closed":[],"curve":[]}
        return {"A":blank(),"B":blank()}

def save(s):
    with open(STATE,"w") as f: json.dump(s,f,indent=2,default=str)

def lots(rp,px): return int(rp//(px*100))

def prep(t):
    d,w=K.get_eod(t+".JK",period="2y")
    if d is None or len(d)<260 or w is None or len(w)<20: return None
    d["atr"]=K.atr_series(d); d["volma"]=d["volume"].rolling(20).mean()
    d["sma50"]=d["close"].rolling(50).mean(); d["sma200"]=d["close"].rolling(200).mean()
    d["ema"]=d["close"].ewm(span=A_EMA,adjust=False).mean()
    d["donch"]=d["high"].rolling(DONCH).max().shift(1); d["ret1"]=d["close"].pct_change()
    zz=K.compute_zigzag_pivots(d); d["sd"]=[K.structure_at(zz,i) for i in range(len(d))]
    sw=[]
    for i in range(len(d)):
        wk=w[w["time"]<=d["time"].iloc[i]]; sw.append(K.structure_at(K.compute_zigzag_pivots(w),wk.index[-1]) if len(wk) else "neutral")
    d["sw"]=sw
    return d

def equity(p,lastpx):
    return p["cash"]+sum(v["shares"]*lastpx.get(tk,v["entry"]) for tk,v in p["positions"].items())

def fire_donch(d,i):
    r=d.iloc[i]
    if pd.isna(r["donch"]) or pd.isna(r["sma200"]): return False
    return r["close"]>r["donch"] and r["close"]>r["sma200"]

def main():
    st=load()
    data={t.replace(".JK",""):prep(t.replace(".JK","")) for t in K.all_tickers()}
    data={k:v for k,v in data.items() if v is not None}
    today=max(v["time"].iloc[-1] for v in data.values()).date()
    lastpx={k:float(v["close"].iloc[-1]) for k,v in data.items()}
    evA,evB=[],[]

    # ---- Strategy A (DONCH50+200) ----
    A=st["A"]
    for tk in list(A["positions"]):
        d=data.get(tk);
        if d is None: continue
        r=d.iloc[-1]; p=A["positions"][tk]; p["peak"]=max(p.get("peak",p["entry"]),float(r["high"]))
        stop=max(p["stop"],p["peak"]-A_TRAIL*float(r["atr"])); p["stop"]=stop
        if float(r["low"])<=stop or float(r["close"])<float(r["ema"]):
            px=stop if float(r["low"])<=stop else float(r["close"]); pnl=(px-p["entry"])/p["entry"]*100
            A["cash"]+=p["shares"]*px; A["closed"].append({"tk":tk,"pnl":round(pnl,1)})
            evA.append(f"🚪 SELL {tk} ({pnl:+.1f}%)"); del A["positions"][tk]
    for tk in list(A["pending"]):
        d=data.get(tk);
        if d is None: del A["pending"][tk]; continue
        r=d.iloc[-1]; pe=A["pending"][tk]; pe["age"]=pe.get("age",0)+1; trig=pe["trigger"]
        if float(r["open"])<=pe["sh"]*(1+MAXGAP) and (float(r["open"])>=trig or float(r["high"])>=trig):
            if len(A["positions"])<MAX_POS:
                entry=max(float(r["open"]),trig); sh=lots(min(SIZE_FRAC*equity(A,lastpx),A["cash"]),entry)*100
                if sh>0:
                    stp=entry-A_INIT*float(r["atr"])
                    A["cash"]-=sh*entry; A["positions"][tk]={"entry":entry,"shares":sh,"peak":entry,"stop":stp}
                    evA.append(f"✅ BUY {tk} @ {entry:,.0f}  →  set STOP-LOSS @ {stp:,.0f} in IPOT")
            del A["pending"][tk]
        elif pe["age"]>=3: del A["pending"][tk]
    for tk,d in data.items():
        if tk in A["positions"] or tk in A["pending"]: continue
        i=len(d)-1; r=d.iloc[i]
        if pd.isna(r["atr"]) or r["atr"]<=0 or pd.isna(r["sma200"]) or pd.isna(r["donch"]): continue
        if fire_donch(d,i):
            A["pending"][tk]={"trigger":float(r["high"])*(1+TRIG_BUF),"sh":float(r["high"]),"age":0}
            evA.append(f"🎯 [A] {tk} signal (50d-high breakout)")

    # ---- Strategy B (COMBO) ----
    B=st["B"]
    for tk in list(B["positions"]):
        d=data.get(tk);
        if d is None: continue
        r=d.iloc[-1]; p=B["positions"][tk]; p["age"]=p.get("age",0)+1
        ex=None
        if float(r["low"])<=p["stop"]: ex=("SL",p["stop"])
        elif float(r["high"])>=p["tp"]: ex=("TP",p["tp"])
        elif p["age"]>=B_HOLD: ex=("time",float(r["close"]))
        if ex:
            px=ex[1]; pnl=(px-p["entry"])/p["entry"]*100; B["cash"]+=p["shares"]*px
            B["closed"].append({"tk":tk,"pnl":round(pnl,1)}); evB.append(f"🚪 SELL {tk} ({pnl:+.1f}%, {ex[0]})"); del B["positions"][tk]
    for tk in list(B["pending"]):
        d=data.get(tk);
        if d is None: del B["pending"][tk]; continue
        r=d.iloc[-1]; pe=B["pending"][tk]
        if float(r["open"])<=pe["sh"]*(1+MAXGAP):                  # market-on-open (skip big gap)
            if len(B["positions"])<MAX_POS:
                entry=float(r["open"])*(1+SLIP); atr=float(r["atr"])
                sh=lots(min(SIZE_FRAC*equity(B,lastpx),B["cash"]),entry)*100
                if sh>0:
                    stp=entry-B_SL*atr; tgt=entry+B_TP*atr
                    B["cash"]-=sh*entry; B["positions"][tk]={"entry":entry,"shares":sh,"age":0,"stop":stp,"tp":tgt}
                    evB.append(f"✅ BUY {tk} @ {entry:,.0f}  →  set STOP @ {stp:,.0f} · TARGET @ {tgt:,.0f} in IPOT")
        del B["pending"][tk]
    for tk,d in data.items():
        if tk in B["positions"] or tk in B["pending"]: continue
        i=len(d)-1; r=d.iloc[i]
        if pd.isna(r["atr"]) or r["atr"]<=0 or pd.isna(r["sma200"]): continue
        if fire_combo(d,i):
            B["pending"][tk]={"sh":float(r["high"]),"age":0}; evB.append(f"🎯 [B] {tk} signal (combo)")

    eqA=equity(A,lastpx); eqB=equity(B,lastpx)
    A["curve"].append([str(today),round(eqA)]); B["curve"].append([str(today),round(eqB)])
    save(st)

    def line(name,p,eq,ev):
        wins=[c for c in p["closed"] if c["pnl"]>0]
        wr=f"{len(wins)/len(p['closed'])*100:.0f}%" if p["closed"] else "—"
        L=[f"  {name}: Rp {eq:,.0f} ({(eq/ACCOUNT-1)*100:+.1f}%) · open {len(p['positions'])} · closed {len(p['closed'])} (win {wr})"]
        for tk,v in p["positions"].items():            # open positions + current stop to set in IPOT
            cur=lastpx.get(tk,v["entry"]); upl=(cur-v["entry"])/v["entry"]*100
            tgt=f" · tgt {v['tp']:,.0f}" if "tp" in v else ""
            L.append(f"     • {tk}: now {cur:,.0f} ({upl:+.1f}%) · ➡️ STOP {v['stop']:,.0f}{tgt}  (set/update in IPOT)")
        L+= [f"     {e}" for e in ev]
        return "\n".join(L)
    tag = "🔔 ACTION" if (evA or evB) else "🟢 alive · no signals"
    rep=(f"⚔️ A/B PAPER · {today} · {tag}\n"+"━"*22+"\n"
         f"  Winner so far: {'A (DONCH)' if eqA>eqB else ('B (COMBO)' if eqB>eqA else 'tie')}\n"
         + line("A·DONCH",A,eqA,evA) + "\n" + line("B·COMBO",B,eqB,evB))
    print(rep)
    notify(rep)   # post EVERY run = daily heartbeat (see it daily = bot is on)

if __name__=="__main__":
    main()
