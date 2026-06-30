# run_idx_loop.py — Fly.io supervisor for the IDX konglo scanner.
# Runs idx_scan.py once per weekday at 10:00 UTC (17:00 WIB, safely after the IDX close).
import subprocess, sys, time, datetime

RUN_HOUR_UTC = 10   # 17:00 WIB — after IDX close + EOD data settle
RUN_MIN_UTC  = 0

def seconds_until_next_run():
    now = datetime.datetime.utcnow()
    target = now.replace(hour=RUN_HOUR_UTC, minute=RUN_MIN_UTC, second=0, microsecond=0)
    if now >= target:
        target += datetime.timedelta(days=1)
    while target.weekday() >= 5:          # skip Sat(5)/Sun(6) — IDX closed
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()

print("[idx-loop] supervisor started", flush=True)
while True:
    s = seconds_until_next_run()
    print(f"[idx-loop] sleeping {s/3600:.1f}h until next weekday {RUN_HOUR_UTC:02d}:{RUN_MIN_UTC:02d} UTC", flush=True)
    time.sleep(s)
    print(f"[idx-loop] run @ {datetime.datetime.utcnow().isoformat()}Z", flush=True)
    try:
        subprocess.run([sys.executable, "idx_scan.py"], check=False)
    except Exception as e:
        print(f"[idx-loop] error: {e}", flush=True)
    time.sleep(90)   # avoid double-fire within the same minute
