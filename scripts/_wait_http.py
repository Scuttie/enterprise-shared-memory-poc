"""Tiny readiness waiter: exit 0 when URL returns <500, else non-zero after the timeout. Used inside the
eval-image single-exec session to wait for the API before running a benchmark runner."""
import sys
import time
import urllib.request

url = sys.argv[1]
tries = int(sys.argv[2]) if len(sys.argv) > 2 else 90
for _ in range(tries):
    try:
        if urllib.request.urlopen(url, timeout=2).status < 500:
            sys.exit(0)
    except Exception:
        pass
    time.sleep(1)
sys.exit("not ready: " + url)
