# idx_tg_setgroup.py — point the bot at the group chat. Tries the raw ID and the -100 form,
# sends a confirmation, and updates IDX_TG_CHAT in .env to whichever works.
import os, sys, json, urllib.request, urllib.parse, urllib.error
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from dotenv import load_dotenv

ENV = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV)
tok = os.getenv("IDX_TG_TOKEN")
if not tok:
    print("No IDX_TG_TOKEN in .env"); sys.exit(1)

RAW = "-5471757696"
candidates = [RAW, "-100" + RAW.lstrip("-")]   # basic-group id, then supergroup form

def send(chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        r = json.loads(urllib.request.urlopen(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=20).read())
        return r.get("ok"), ""
    except urllib.error.HTTPError as e:
        return False, e.read().decode()[:160]
    except Exception as e:
        return False, str(e)[:160]

chosen = None
for c in candidates:
    ok, err = send(c, "✅ IDX A/B trading bot is connected to this group!\n"
                      "You'll get 🎯 signal and 🚪 sell alerts here — on every device in the group.\n"
                      "Status: CRASH regime, both strategies in cash. Patience.")
    print(f"  tried chat_id {c:>16} : {'✅ DELIVERED' if ok else 'fail — ' + err}")
    if ok:
        chosen = c; break

if chosen:
    lines = open(ENV, encoding="utf-8").read().splitlines()
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith("IDX_TG_CHAT"):
            out.append(f"IDX_TG_CHAT={chosen}"); found = True
        else:
            out.append(ln)
    if not found: out.append(f"IDX_TG_CHAT={chosen}")
    open(ENV, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"\n  ✅ Done — IDX_TG_CHAT set to {chosen}. All bot alerts now post to the group.")
else:
    print("\n  ❌ Neither ID worked. Likely: the bot isn't a member of the group, or the ID is off.")
    print("     Make sure your IDX bot (not @RawDataBot) is still IN the group.")
