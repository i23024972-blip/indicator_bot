# crypto_sizer.py — INTERACTIVE position-size calculator for the regime long/short bot.
#   Asks your capital + risk%, then for every LIVE signal tells you EXACTLY how many $
#   to put in so that a stop-out costs only your chosen risk (default 1%).
#   Read-only: scans the same universe/signals as crypto_bot.py but NEVER touches paper state.
# Run by hand:  python crypto_sizer.py
import sys
import pandas as pd
# reuse the live bot's exact logic so sizing matches real trades
from crypto_bot import client, klines, regime, MIN_VOL, TOPN, VOL_LO, VOL_HI, SL_ATR, MAXPOS

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def ask_float(prompt, default):
    try:
        raw = input(f"{prompt} [{default}]: ").strip().lstrip("﻿").replace(",", "").replace("$", "").replace("%", "")
    except EOFError:
        return default
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"  '{raw}' isn't a number — using {default}")
        return default


def size_line(name, dir, entry, stop, risk_usd):
    units = risk_usd / abs(entry - stop)
    notional = units * entry
    print(f"  {'LONG' if dir == 1 else 'SHORT'} {name}")
    print(f"     entry   {entry:,.6g}")
    print(f"     stop    {stop:,.6g}   ({SL_ATR:g}·ATR away — set this as your hard stop)")
    print(f"     PUT IN  ${notional:,.2f}   ({units:,.4g} {name})")
    print(f"     max loss if stopped ≈ ${risk_usd:,.2f}\n")


def manual(want, risk_usd):
    while True:
        try:
            raw = input("  Size a coin manually? type symbol e.g. SOL (or blank to quit): ").strip().upper()
        except EOFError:
            return
        if not raw:
            return
        sym = raw if raw.endswith("USDT") else raw + "USDT"
        try:
            d = klines(sym)
        except Exception as e:
            print(f"  couldn't load {sym}: {e}\n")
            continue
        a = float(d["atr"].iloc[-1]); entry = float(d["close"].iloc[-1])
        stop = entry - want * SL_ATR * a
        size_line(sym.replace("USDT", ""), want, entry, stop, risk_usd)


def main():
    print("=" * 52)
    print("  CRYPTO POSITION SIZER · regime long/short bot")
    print("=" * 52)
    capital = ask_float("Your capital (USD)", 1000.0)
    riskpct = ask_float("Risk per trade (%)", 1.0)
    risk_usd = capital * riskpct / 100.0

    print(f"\n  Capital ${capital:,.2f} · risk {riskpct:g}% = ${risk_usd:,.2f} MAX LOSS per trade")
    print(f"  Bot holds up to {MAXPOS} at once → worst case ${risk_usd*MAXPOS:,.2f} "
          f"({riskpct*MAXPOS:g}% of account) at risk if all stop together\n")

    reg = regime()
    want = 1 if reg == "BULL" else (-1 if reg == "BEAR" else 0)
    arrow = "LONGS only" if want == 1 else ("SHORTS only" if want == -1 else "CASH — no new trades")
    print(f"  BTC regime: {reg}  →  {arrow}\n")
    if want == 0:
        print("  Regime is CRASH — the bot sits in cash, so there's nothing to size right now.")
        return

    print("  scanning live universe for breakout signals...\n")
    syms = [s["symbol"] for s in client.futures_exchange_info()["symbols"]
            if s["symbol"].endswith("USDT") and s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING"]
    vol = {t["symbol"]: float(t["quoteVolume"]) for t in client.futures_ticker()}
    liquid = sorted([s for s in syms if vol.get(s, 0) >= MIN_VOL], key=lambda s: -vol.get(s, 0))[:TOPN]

    found = []
    for sym in liquid:
        try:
            d = klines(sym)
        except Exception:
            continue
        if len(d) < 210:
            continue
        volp = (d["atr"] / d["close"]).median() * 100
        if not (VOL_LO <= volp <= VOL_HI):
            continue
        r = d.iloc[-1]; pr = d.iloc[-2]; a = float(r["atr"])
        if pd.isna(a) or a <= 0 or pd.isna(r["pdh"]) or pd.isna(r["ema"]):
            continue
        sig = (want == 1 and r["close"] > r["pdh"] and pr["close"] <= r["pdh"] and r["close"] > r["ema"]) or \
              (want == -1 and r["close"] < r["pdl"] and pr["close"] >= r["pdl"] and r["close"] < r["ema"])
        if not sig:
            continue
        entry = float(r["close"]); stop = entry - want * SL_ATR * a
        found.append((sym.replace("USDT", ""), want, entry, stop))

    if found:
        print(f"  {len(found)} LIVE signal(s) — here's how much to put in each:\n")
        for name, dir, entry, stop in found:
            size_line(name, dir, entry, stop, risk_usd)
    else:
        print("  No live breakout signals at this moment.\n")

    manual(want, risk_usd)


if __name__ == "__main__":
    main()
