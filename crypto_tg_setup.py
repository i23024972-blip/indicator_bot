# crypto_tg_setup.py — find the crypto bot's chat and wire CRYPTO_TG_CHAT into .env.
import os, sys, json, urllib.request, urllib.parse, urllib.error
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from dotenv import load_dotenv
ENV=os.path.join(os.path.dirname(__file__),".env"); load_dotenv(ENV)
tok=os.getenv("CRYPTO_TG_TOKEN")
if not tok: print("No CRYPTO_TG_TOKEN in .env"); sys.exit(1)
try: urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/deleteWebhook",timeout=15).read()
except Exception: pass
try:
    data=json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates?timeout=5",timeout=20).read())
except Exception as e:
    print("getUpdates failed:",e); sys.exit(1)
chats={}
for u in data.get("result",[]):
    for k in ("message","my_chat_member","channel_post","edited_message"):
        node=u.get(k)
        if node and "chat" in node:
            c=node["chat"]; chats[c["id"]]=(c.get("type"),c.get("title") or c.get("username") or c.get("first_name") or "")
if not chats:
    print("NO_CHAT_YET")
    print("  → Open your new crypto bot in Telegram and send it a message (e.g. /start),")
    print("    OR add it to your crypto group and send any message there. Then I'll retry.")
    sys.exit(0)
for cid,(typ,title) in chats.items(): print(f"  found chat_id={cid} type={typ} name='{title}'")
grp=[cid for cid,(t,_) in chats.items() if t in ("group","supergroup")]
chosen=grp[0] if grp else list(chats)[0]
lines=open(ENV,encoding="utf-8").read().splitlines()
out=[l for l in lines if not l.startswith("CRYPTO_TG_CHAT")]+[f"CRYPTO_TG_CHAT={chosen}"]
open(ENV,"w",encoding="utf-8").write("\n".join(out)+"\n")
msg=("✅ Crypto bot connected to this chat!\nRegime-directional alerts post here: LONG in bull · "
     "SHORT in bear · CASH in crash. Currently: BEAR → hunting shorts.")
try:
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage",
        data=urllib.parse.urlencode({"chat_id":chosen,"text":msg}).encode(),timeout=20).read()
    print(f"  ✅ Set CRYPTO_TG_CHAT={chosen} and sent a test message — check Telegram.")
except Exception as e:
    print(f"  set CRYPTO_TG_CHAT={chosen} but test send failed: {e}")
