# run_loop.py — Fly.io supervisor: runs crypto_bot.py every 4h, aligned to UTC boundaries.
# Fly machines are always-on, but Fly's native schedule can't do "every 4h", so we loop here.
import subprocess, sys, time, datetime

INTERVAL = 4 * 3600   # 4 hours

def next_boundary():
    now = time.time()
    return (now // INTERVAL + 1) * INTERVAL   # next 00/04/08/12/16/20 UTC

print("[loop] crypto bot supervisor started", flush=True)
while True:
    print(f"[loop] run @ {datetime.datetime.utcnow().isoformat()}Z", flush=True)
    try:
        subprocess.run([sys.executable, "crypto_bot.py"], check=False)
    except Exception as e:
        print(f"[loop] error: {e}", flush=True)
    sleep_s = max(60, next_boundary() - time.time())
    print(f"[loop] sleeping {sleep_s/3600:.2f}h until next 4h boundary", flush=True)
    time.sleep(sleep_s)
