# crypto_leverage.py — INTERACTIVE margin/leverage + risk planner for the regime long/short bot.
#   Asks your capital, risk%, and max leverage you'll allow. Scans live signals and prints the
#   EXACT trade ticket for each: position size, leverage to set, margin used, stop, liquidation
#   price. Then a portfolio summary (effective leverage, total margin, total risk if all stop) and
#   a "what-if you fill N slots" table so you see how leverage+risk scale with # of positions.
#   SAFETY: per-trade leverage is auto-capped so the STOP always triggers BEFORE liquidation.
# Read-only — never touches paper state.  Run:  python crypto_leverage.py
import sys
import pandas as pd
from crypto_bot import client, klines, regime, MIN_VOL, TOPN, VOL_LO, VOL_HI, SL_ATR

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

MMR = 0.005         # ~maintenance-margin rate (Binance tiers vary; conservative)
STOP_BUFFER = 1.25  # require liquidation to sit >=25% beyond the stop
MIN_NOTIONAL = 5.0  # Binance USDT-perp min order size (~$5) — orders below this get rejected


def ask_float(prompt, default):
    try:
        raw = input(f"{prompt} [{default}]: ").strip().lstrip("﻿").replace(",", "").replace("$", "").replace("%", "").replace("x", "").replace("X", "")
    except EOFError:
        return default
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"  '{raw}' isn't a number — using {default}")
        return default


def safe_leverage(stop_frac, user_max):
    """Highest leverage that still keeps the stop inside the liquidation distance."""
    cap = 1.0 / (STOP_BUFFER * stop_frac + MMR)
    lev = min(user_max, cap)
    return max(1.0, float(int(lev)))   # whole-number leverage, never below 1x


def ticket(name, dir, entry, stop, risk_usd, user_max):
    stop_frac = abs(entry - stop) / entry
    notional = risk_usd / stop_frac
    units = notional / entry
    lev = safe_leverage(stop_frac, user_max)
    margin = notional / lev
    liq_move = 1.0 / lev - MMR
    liq = entry * (1 - dir * liq_move)
    capped = lev < user_max
    toosmall = notional < MIN_NOTIONAL
    print(f"  {'LONG' if dir == 1 else 'SHORT'} {name}" + ("   *** SKIP — below ~$5 min order ***" if toosmall else ""))
    print(f"     entry         {entry:,.6g}")
    print(f"     position size ${notional:,.2f}   ({units:,.4g} {name})  <- order quantity"
          + (f"  [<${MIN_NOTIONAL:.0f} min: skip, or use ${MIN_NOTIONAL:.0f} = risk ~${MIN_NOTIONAL*stop_frac:,.2f}]" if toosmall else ""))
    print(f"     leverage      {lev:.0f}x" + (f"   (capped from {user_max:.0f}x — stop {stop_frac*100:.0f}% too wide to lever more)" if capped else ""))
    print(f"     margin used   ${margin:,.2f}   <- cash this trade locks up")
    print(f"     stop-loss     {stop:,.6g}   (lose ~${risk_usd:,.2f} = your 1%)")
    print(f"     liquidation   {liq:,.6g}   {'OK — stop hits first' if (dir==1 and liq < stop) or (dir==-1 and liq > stop) else 'WARNING — liq before stop!'}")
    print()
    return notional, margin, stop_frac


def projection(risk_usd, capital, riskpct, med_stop, user_max):
    print("  " + "=" * 56)
    print("  WHAT-IF: how leverage + risk scale as you stack positions")
    print(f"  (avg position ~${risk_usd/med_stop:,.0f} notional at a {med_stop*100:.0f}% stop)")
    print("  " + "=" * 56)
    print(f"  {'# pos':>6}{'total notional':>16}{'eff.lev':>9}{'margin@'+format(user_max,'.0f')+'x':>11}{'risk if all stop':>18}")
    avg_notional = risk_usd / med_stop
    for n in [5, 10, 20, 30]:
        tot_notional = n * avg_notional
        eff_lev = tot_notional / capital
        margin = min(tot_notional / user_max, capital)
        tot_risk = n * risk_usd
        flag = "" if tot_risk <= 0.15 * capital else "  <- heavy"
        fits = "  (fits in cash, NO leverage)" if tot_notional <= capital else ""
        print(f"  {n:>6}{('$'+format(tot_notional,',.0f')):>16}{eff_lev:>8.1f}x{('$'+format(margin,',.0f')):>11}"
              f"{('$'+format(tot_risk,',.0f')+' ('+format(tot_risk/capital*100,'.0f')+'%)'):>18}{flag}{fits}")
    print("  " + "=" * 56)
    print(f"  Rule of thumb: keep TOTAL risk-if-all-stop under ~15% of capital (${0.15*capital:,.0f}).")
    print(f"  That's about {int(0.15/ (riskpct/100))} positions at {riskpct:g}% each — beyond that a")
    print("  correlated crash (everything dumps together) can gut the account fast.\n")


def main():
    print("=" * 58)
    print("  CRYPTO MARGIN / LEVERAGE PLANNER · regime long/short bot")
    print("=" * 58)
    capital = ask_float("Your capital (USD)", 1000.0)
    riskpct = ask_float("Risk per trade (%)", 1.0)
    user_max = ask_float("Max leverage you'll allow (x)", 3.0)
    risk_usd = capital * riskpct / 100.0

    print(f"\n  Capital ${capital:,.2f} · risk {riskpct:g}% = ${risk_usd:,.2f} max loss/trade · leverage cap {user_max:.0f}x\n")

    reg = regime()
    want = 1 if reg == "BULL" else (-1 if reg == "BEAR" else 0)
    arrow = "LONGS only" if want == 1 else ("SHORTS only" if want == -1 else "CASH — no trades")
    print(f"  BTC regime: {reg}  →  {arrow}\n")
    if want == 0:
        print("  Regime is CRASH — bot sits in cash. Nothing to size/lever.")
        return

    print("  scanning live universe...\n")
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

    stops = []
    if found:
        print(f"  {len(found)} LIVE signal(s) — exact trade tickets:\n")
        tot_notional = tot_margin = 0.0
        for name, dir, entry, stop in found:
            notional, margin, sf = ticket(name, dir, entry, stop, risk_usd, user_max)
            tot_notional += notional; tot_margin += margin; stops.append(sf)
        eff = tot_notional / capital
        tot_risk = len(found) * risk_usd
        print("  " + "-" * 50)
        print(f"  PORTFOLIO ({len(found)} open): total size ${tot_notional:,.2f} · margin used ${tot_margin:,.2f} "
              f"· free cash ${max(capital-tot_margin,0):,.2f}")
        print(f"  effective leverage {eff:.2f}x · total risk if all stop ${tot_risk:,.2f} ({tot_risk/capital*100:.1f}%)")
        if tot_notional <= capital:
            print("  -> total size fits inside your cash: NO leverage actually needed (spot, no liquidation risk).")
        print()
    else:
        print("  No live signals right now — showing the scaling math on a typical setup.\n")

    med_stop = float(pd.Series(stops).median()) if stops else 0.08
    if not (0.03 <= med_stop <= 0.15):          # ignore freak wide-stop coins (e.g. MANTA 61%)
        med_stop = 0.08                          # use a typical ~8% stop so the scaling is representative
    projection(risk_usd, capital, riskpct, med_stop, user_max)


if __name__ == "__main__":
    main()
