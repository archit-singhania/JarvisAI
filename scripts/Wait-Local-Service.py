"""Bounded readiness wait for the isolated acceptance service; never prints keys."""
import sys
import time
import urllib.request

target = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8006/health'
if not target.startswith(('http://127.0.0.1:','http://localhost:')):
    raise SystemExit('Acceptance readiness only targets a loopback service')
for attempt in range(30):
    try:
        with urllib.request.urlopen(target,timeout=1) as response:
            if response.status==200:
                print('Local acceptance service ready')
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('Local acceptance service did not become ready in 30 seconds')
