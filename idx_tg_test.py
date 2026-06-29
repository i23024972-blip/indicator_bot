# idx_tg_test.py — verify Telegram alerts work (sends one test message to your IDX chat).
import os, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

tok, chat = os.getenv("IDX_TG_TOKEN"), os.getenv("IDX_TG_CHAT")
print("IDX_TG_TOKEN present:", bool(tok), "· IDX_TG_CHAT present:", bool(chat))
if not tok or not chat:
    print("❌ Missing IDX_TG_TOKEN / IDX_TG_CHAT in .env"); sys.exit(1)

import requests
msg = ("✅ IDX Paper-Ride connected.\n"
       "Strategy: DONCH50+200 (50-day-high breakout above 200MA).\n"
       "You'll get a 📋 SIGNAL OPTIONS message when a konglo name fires, and a 🚪 SELL "
       "alert when a position exits.\n"
       "Status now: CRASH regime — all names below 200MA, sitting in cash. Patience.")
try:
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": msg}, timeout=30)
    print("HTTP", r.status_code, "→", "✅ sent! check your Telegram." if r.ok else f"❌ {r.text[:300]}")
except Exception as e:
    print("❌ send failed:", e)
