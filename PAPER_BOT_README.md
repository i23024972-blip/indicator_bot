# ZigZag Paper-Trading Bot

`bot_zigzag_paper.py` — runs the backtested **ZigZag** strategy LIVE on the real market with
**fake money**, so you can confirm the edge is alive *now* before risking real cash.

## What it does
- Strategy: **4H bias + 30M entry**, %-deviation ZigZag (dev **5%**), structure HH/HL/LH/LL,
  **TP 4×ATR / SL 1.5×ATR**, on **BTC + DOGE + HYPE**, **LONG + SHORT**, one position at a time.
- **No real orders.** It tracks a virtual $1,000 account and alerts you on Telegram + PC for every
  paper entry/exit, clearly marked `[PAPER]`.
- Non-repainting: only acts on **closed** candles, and waits for a genuine structure flip (won't fire
  on startup).

## How to run
```
python bot_zigzag_paper.py
```
Then in Telegram:
- `/start` — begin paper trading (auto-scans every 10 min)
- `/stats` — show current paper P&L, win rate, open position
- `/stop`  — pause (state is saved; `/start` resumes)
- `/reset` — wipe the paper account back to $1,000

## ⚠️ Important
- **Don't run `bot.py` and `bot_zigzag_paper.py` at the same time** — they share the same Telegram
  token and will conflict. Run only one.
- This is the **real strategy** you backtested (ZigZag), unlike `bot.py` which is the old RSI/MACD one.
- Output files: `paper_state.json` (current state, survives restarts) and `paper_trades.csv` (full
  trade log — open this to review every closed paper trade).

## Plan
Let it run ~2-4 weeks. Then compare the paper `/stats` result to the backtest:
- If paper roughly matches (modest edge, lumpy, ~30% win rate but wins bigger) → the edge is alive,
  you can consider going real (start small, e.g. 1% risk, not 100%).
- If paper bleeds steadily → the edge has faded; do NOT put real money in. You'll have lost $0 learning
  that — which is the entire point.
