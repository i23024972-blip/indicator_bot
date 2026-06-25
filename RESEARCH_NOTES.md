# ZigZag Strategy Research Notes

_Last updated: 2026-06-24. All tests: BTC + HYPE, traded as **spot** (HYPE candles pulled from
the futures feed but simulated as a spot buy — no leverage/funding). Compounding $1000 account,
full equity per trade, net of fees. "No fees/slippage" baseline shown as the 0% column.
Past results ≠ future._

## TL;DR
- **Only one config is honestly profitable:** 4H bias + 30M entry, %-deviation ZigZag **5%**,
  **TP 4×ATR / SL 1.5×ATR**. → ~135 trades / 300 days, BEP **+0.446%**, $1000 → **$1,272**, max DD −21%.
- Trading **more often loses money.** Every attempt to raise trade count (lower deviation, faster
  timeframe, matching the real ZigZag++ indicator) destroyed the edge after fees.
- **Target of 0.5% BEP/trade is not reachable** by tuning R:R or exit logic alone (caps at +0.446%).
  Only improving *entry quality* (trend/strong-structure filters) could close the gap — untested.

## Key term
- **BEP/trade** = gross expectancy per trade = the max round-trip fee you can pay before the edge
  disappears. Spot fee ≈ 0.20%, so you need BEP comfortably above 0.20% to make money.

## What was tested

### 1. Days / robustness (4H bias + 30M entry, dev 5%, TP3/SL1.5)
| Window | $1000 spot result |
|---|---|
| 600 days | $1,000 (break-even at spot fee) |
| 300 days | $1,224 (+22%) |

### 2. Deviation (more trades vs edge)
| Deviation | Trades/300d | Best BEP | Max DD | Verdict |
|---|---|---|---|---|
| 3% | ~305 | +0.268% | −54%+ | over-trades, loses after fees |
| **5%** | ~135 | **+0.446%** | −21% | **only profitable, smooth** |
| 8% | ~67 | negative | — | too few, poor quality |

### 3. Timeframe pairs (300d, dev 5%)
| Pair | Best BEP | Verdict |
|---|---|---|
| 1D bias + 1H confirm | −0.70% | fails badly (bias too slow) |
| 1H bias + 15M confirm | −0.12% | fails (15M = noise) |
| **4H bias + 30M confirm** | **+0.446%** | **winner** |

### 4. R:R sweep (4H/30M, dev 5%) — the optimum is a real peak
| TP/SL (×ATR) | Win% | BEP | $1000 |
|---|---|---|---|
| 3.0 / 1.5 | 40.0% | +0.398% | $1,224 |
| **4.0 / 1.5** | 33.6% | **+0.446%** | **$1,272 (−21%)** |
| 5.0 / 1.5 | 27.6% | +0.398% | $1,168 |
| 4.0 / 1.0 | 25.4% | +0.369% | $1,177 |
> SL 1.5 is the sweet spot; SL 2.0 row is negative everywhere. Pushing TP past 4 lowers BEP.

### 5. Structure-based exit (exit on opposite pivot + breakeven trail)
- Best version: 50.7% win rate but BEP only +0.162% — high win rate, small wins, ~breakeven
  after fees. Smoother but weaker than fixed TP4/SL1.5. Not adopted.

### 6. Causal ZigZag++ (matching the real "ZigZag++ [LD]" indicator, Depth≈12)
Built a non-repainting version that labels a new swing every ~5-6 candles like the TradingView
indicator. **Result: it loses money.**
| Pivot strength | Trades/300d | BEP | After spot fee | $1000 |
|---|---|---|---|---|
| 3 (~7 candles) | 858 | +0.091% | −0.109% | $315 (−86%) |
| 5 (~11 candles) | 557 | −0.040% | −0.240% | $229 (−85%) |
| 6 (~13 candles) | 473 | −0.001% | −0.201% | $340 (−72%) |
> **Conclusion:** the frequent swings of the real indicator are mostly noise. The %-deviation
> version makes money *because* it is selective. Matching the indicator removed the edge.
> ⚠️ The indicator **repaints** — backtesting its on-screen labels would secretly use future data.

### 7. Last 2 weeks (live-style, 4H/30M, dev5, TP4/SL1.5) — 2026-06-10 → 06-24
6 signals, 5 closed: **1 win / 4 losses (20%)**, $1000 → **$975 (−2.5%)**, 1 still open.
Normal variance for a ~33% win-rate system — red fortnights are expected (worst streak in the
600d run was 11 losses in a row).

### 8. More trades via MORE COINS (basket, 300d, dev5/TP4/SL1.5)
Goal: more activity without looser filters. 10-coin basket = 542 trades but edge **diluted to
breakeven** (BEP +0.209%, net ~0, $1000→$786 at full-equity compounding). More coins did NOT
preserve the edge — the BTC+HYPE result was partly coin-specific.
Per-coin (net after fee): HYPE +0.32%, DOGE +0.44%, ADA +0.14%, ETH +0.09%, BNB +0.08% = profitable;
BTC −0.06%, AVAX −0.01%, SOL −0.26%, XRP −0.34%, LINK −0.63% = dead weight.
**Profitable subset (ETH,BNB,DOGE,ADA,HYPE): 299 trades (~1/day), BEP +0.439%, $1000→$1,644 (+64%).**
⚠️ Cherry-picking past winners = OVERFITTING. ETH/BNB/HYPE defensible; DOGE/ADA may be luck. Real
forward edge will be lower. Sane takeaway: trade ~4-6 liquid coins, expect modest edge + ~1 trade/day.

### Live-bot strategy (RSI/MACD "Filter A+E") backtest — for comparison
| Timeframe | Trades/300d | Win% | BEP | $1000 |
|---|---|---|---|---|
| 1H entry + 4H EMA50 (bot default) | 3 | 67% (luck) | +0.869% | $1,020 |
| 30M entry + 4H EMA50 | 22 | 50% | +0.630% | $1,095 |
> Bot's strategy is GOOD quality per trade but fires very rarely on 1H (~3/yr) — effectively
> dormant. On 30M it wakes up (22 trades, +9.5%). Script: `backtest_rsi_macd.py`.

## ⚠️ IMPORTANT: live bot ≠ backtest
`bot.py` does **NOT** trade ZigZag. Its `get_signal()` uses RSI + MACD + OBV + ADX + MACD-hist
slope, filtered by EMA-50 HTF trend ("Filter A+E"). That signal logic has **never been
backtested**. The ZigZag research above is a separate line of work. Porting ZigZag into the bot
would replace its entire signal engine — a big decision, not yet made.

## Scripts
- `zigzag_sweep.py` — deviation sweep + $1000 sim (3 timeframe pairs, fee levels)
- `zigzag_optimize.py` — R:R sweep + structure-exit experiments
- `zigzag_pp.py` — causal ZigZag++ (Depth-based) detector, disk-cached klines (`.klines_cache/`)
- `zigzag_recent.py` — trade-by-trade ledger for the last N days
- `zigzag_backtest.py` / `zigzag_mtf_backtest.py` — earlier 1H/4H structure versions

## Caveats
Small sample (2 symbols, ~135 trades/300d). Treat the edge as *promising, not proven*.
Confirm any new config on the 600-day window before trusting it. No slippage modeled.
