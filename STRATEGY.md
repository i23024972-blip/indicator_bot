# IDX Konglo Strategy — Reference

End-of-day signal system for Indonesian (IDX) conglomerate / momentum stocks. Long-only,
Telegram-alerted, regime-aware. Built and validated through extensive backtesting.

---

## Core idea (one sentence)
**Buy confirmed strength (volume spike + uptrend structure) in tycoon-backed momentum stocks,
sized by how dangerous the market is, with a fixed stop — and in healthy markets, ride trends
for months instead of taking quick profits.**

---

## The strategy: HYBRID (regime-switched)
The live default is `STRATEGY = "HYBRID"` in `idx_scan.py`:

| Market regime (IHSG) | Mode | Entry | Exit |
|---|---|---|---|
| 🟢 HEALTHY | **TREND** (ride) | price reclaims 50MA while 50MA > 200MA | close below 50MA, or 3×ATR stop. No fixed target — let winners run |
| 🟡 CAUTION / 🔴 CRASH | **COMBO** (swing) | up-day + volume ≥ 2.5×(20d avg) + above 50MA + bullish daily & weekly zigzag structure | stop 2×ATR, target 6×ATR (1:3), 20-day time stop |

`COMBO` is also selectable standalone (steadier). Switch via the `STRATEGY` constant.

### Position sizing — regime-scaled (the crash defense)
The IHSG crash detector (`idx_regime.py`) reads price vs 200MA, 50/200 death cross, realized
vol, and 3-month momentum — the shared DNA of 2008 & COVID. It sets max size:

| Regime | Size of account / trade |
|---|---|
| 🟢 HEALTHY | 25% |
| 🟡 CAUTION | 15% |
| 🔴 CRASH | 10% (mostly sit in cash) |

Max ~4 positions. Fills assumed at **tomorrow's open**; skip if it gaps > 3%. Fees 0.4%
(0.15% buy / 0.25% sell). IDX lot = 100 shares.

---

## Conviction score (0–100, shown in every signal)
- Weekly structure bullish: +25
- Daily structure bullish: +25
- Above 50-day MA: +20
- Volume strength (3×+ = full): +30
- **Tycoon-backing bonus** (backtested: tycoon names averaged +7.5%/trade vs +5.5% overall):
  mega-tycoon +10, conglomerate +6, state/BUMN +4, none/unverified +0

---

## Watchlist (26 stocks, 3 liquidity tiers)
Tiers from `idx_discover.py` (turnover = price × volume per day):
- 🟦 **BIG** (>Rp100bn/day): BREN, CUAN, PTRO, BRPT, DEWA, BUMI, ANTM, AMMN, RAJA, BNBR, TINS, INCO, BUVA, BIPI
- 🟩 **MID** (30–100bn): PANI, WIFI, NCKL, JPFA, VKTR, INDY
- 🟨 **OKAY** (10–30bn, trade smaller): NICL, FORE, MSIN, ARKO, EMTK, MDIA

**Owner database** (`idx_owners.py`) tags the controlling tycoon/group — IDX monster-runs
cluster on stocks backed by powerful sponsors (Prajogo, Bakrie, Salim, Hapsoro, MNC,
Sinarmas). State-owned (BUMN) names are the laggards.

**Cut by data:** banks (BBCA/BMRI — fire ~2 signals in 3y, don't suit momentum), CDIA/AADI
(negative edge — IPO pump where the spike IS the dump), RATU (−3% edge, recent IPO),
ADRO/GEMS (no edge / too thin). "Famous + liquid" ≠ good; only validated responders kept.

---

## Backtest results (3 years, net 0.4% fees — BEST CASE, strong-trending years)
| Strategy | $1,000 → 3y | Drawdown | Through the crash (Aug'25→now) | Win rate |
|---|---|---|---|---|
| COMBO | ~$8,800 (8.8x) | 15% | 2.4x | 50% |
| TREND | ~$21,000 (21x) | 26% | 1.1x (dies in crash) | 22% |
| **HYBRID** | **~$36,000 (36x)** | 14% | **2.9x** | 32% |

HYBRID dominates: TREND's upside + COMBO's crash defense. But the 36x leans on a few monster
holds (BUVA +407%, WIFI +546%) and demands a 32% win rate (long losing streaks).

---

## Files
- `idx_scan.py` — live daily scanner (Hybrid) → Telegram. **Main file.**
- `idx_regime.py` — IHSG crash-regime detector (sizing governor)
- `idx_konglo.py` — data fetch (yfinance .JK) + zigzag structure
- `idx_owners.py` — ticker → controlling tycoon/group + conviction bonus
- `idx_signals.py` — shared store linking scan ↔ journal (entry/stop/target, ask-for-lots)
- `idx_journal.py` — Telegram trade journal (type lots → rupiah P&L), always-on listener
- `idx_discover.py` — broad-universe screener (liquidity + volume-spike edge)
- `idx_radar.py` — "awakening" radar (turnover surging off a quiet base = new movers)
- Backtests: `idx_watchlist_backtest`, `idx_compare`, `idx_portfolio`, `idx_trend_backtest`,
  `idx_hybrid_backtest`, `idx_accum_backtest`, `idx_crash_reversal`, `idx_alpha`, `idx_dna`

## Automation (Windows)
- Task `IDX_Konglo_Scan` — weekdays 17:30 local (16:30 WIB): the Hybrid scan
- Task `IDX_Awakening_Radar` — weekdays 18:00 local (17:00 WIB): the radar
- Startup `IDX_Journal.vbs` — always-on journal listener
- Telegram bot @ususkonglobot; creds in `.env` as `IDX_TG_TOKEN` / `IDX_TG_CHAT` (git-ignored)

---

## Things we TESTED and REJECTED (don't re-litigate)
All lost to the simple "buy confirmed strength" approach:
1. Conviction-based position sizing — slightly worse than flat
2. Filtering "junk" setups — no improvement
3. Accumulation / capitulation (bandarmology proxy) — earned less than momentum
4. Combining signals — diluted the winner
5. Early OBV-accumulation entry — lost money in crash (buys weakness)
6. Crash-reversal catching (RSI/hammer/capitulation) — all negative; falling-knife trap

**The deep lesson:** the edge is in *waiting for confirmation* (the spike / trend reclaim),
not in being clever or front-running it.

---

## Honest caveats (always remember)
- Backtest years were unusually strong; forward returns will be a FRACTION of the headline.
- No slippage modeled — real fills are worse, especially OKAY-tier names.
- Results lean on a few big winners; strip the top 3 and the multiple shrinks a lot.
- You MUST set the stop every time, and take every signal (or none) — cherry-picking breaks
  the math, especially for HYBRID's lower win rate.
- The crash-defense numbers (~2.4–2.9x) are the more believable, robust part.

## Manual checklist per BUY signal
1. Sanity-check (didn't already gap >3%? no obvious bad news?)
2. Size by the % shown, convert rupiah → whole lots (×100)
3. Buy near tomorrow's open
4. **Set the stop-loss order immediately** ← most important
5. When it closes (target/stop/trend-break), reply lots to the journal → logs your P&L
