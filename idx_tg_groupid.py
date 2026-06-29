# idx_tg_groupid.py — find chat IDs the bot has seen (to grab your group's chat ID).
import os, sys, json, urllib.request
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

tok = os.getenv("IDX_TG_TOKEN")
if not tok:
    print("No IDX_TG_TOKEN in .env"); sys.exit(1)
# clear any stale webhook (blocks getUpdates with 409) — safe, we only sendMessage
try:
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/deleteWebhook?drop_pending_updates=false", timeout=15).read()
except Exception as e:
    print("(deleteWebhook note:", e, ")")
url = f"https://api.telegram.org/bot{tok}/getUpdates?timeout=5"
try:
    data = json.loads(urllib.request.urlopen(url, timeout=20).read())
except Exception as e:
    print("getUpdates failed:", e); sys.exit(1)

if not data.get("ok"):
    print("Telegram error:", data); sys.exit(1)

chats = {}
for u in data.get("result", []):
    for key in ("message","my_chat_member","channel_post","edited_message","chat_member"):
        node = u.get(key)
        if node and "chat" in node:
            c = node["chat"]
            chats[c["id"]] = (c.get("type"), c.get("title") or c.get("username") or c.get("first_name") or "")
print(f"{len(data.get('result',[]))} recent updates · {len(chats)} chats seen:\n")
if not chats:
    print("  (none — see notes below)")
for cid,(typ,title) in chats.items():
    tag = "  ← GROUP (use this)" if typ in ("group","supergroup") else ""
    print(f"  chat_id = {cid:>16}  type={typ:11} name='{title}'{tag}")
print("\n  Groups have NEGATIVE ids (supergroups start -100...). Private chats are positive.")
