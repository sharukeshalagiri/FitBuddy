"""Start uvicorn (demo mode), sample its CPU/memory every 1 s while Locust runs, write CSV.

Run from the project root with the venv active:  python tests/resource_monitor.py
Writes reports/resource_usage.csv plus the usual Locust reports/perf* files.
"""
import csv, os, subprocess, sys, threading, time, urllib.request
from datetime import datetime
from pathlib import Path
import psutil

ROOT = str(Path(__file__).resolve().parents[1])
PY = sys.executable
env = dict(os.environ, DEMO_MODE="true")

log = open(os.path.join(ROOT, "reports", "server-perf.log"), "w")
server = subprocess.Popen([PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                          cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
for _ in range(60):
    try:
        print(urllib.request.urlopen("http://127.0.0.1:8000/api/health").read().decode()); break
    except Exception:
        time.sleep(0.5)
else:
    server.kill(); sys.exit("server did not start")

proc = psutil.Process(server.pid)
ncpu = psutil.cpu_count()
total_mb = psutil.virtual_memory().total / 2**20
samples, stop = [], threading.Event()

_cache = {}
def procs():
    # Reuse Process objects: cpu_percent() is measured since the previous call on the same object.
    try:
        live = [proc] + proc.children(recursive=True)
    except psutil.NoSuchProcess:
        return []
    for p in live:
        _cache.setdefault(p.pid, p)
    return [_cache[p.pid] for p in live]

def sample():
    for p in procs():
        p.cpu_percent(None)  # prime
    t0 = time.time()
    while not stop.wait(1.0):
        cpu = rss = 0.0
        for p in procs():
            try:
                cpu += p.cpu_percent(None); rss += p.memory_info().rss
            except psutil.NoSuchProcess:
                pass
        mb = rss / 2**20
        if not samples: print("tree:", [(p.pid, p.name()) for p in procs()])
        samples.append({"timestamp": datetime.now().isoformat(timespec="seconds"),
                        "elapsed_s": round(time.time() - t0, 1),
                        "cpu_percent": round(cpu, 1),                 # 100 = one full core
                        "cpu_percent_of_system": round(cpu / ncpu, 2),
                        "rss_mb": round(mb, 1),
                        "mem_percent_of_system": round(mb / total_mb * 100, 3)})

th = threading.Thread(target=sample); th.start()
cmd = [PY, "-m", "locust", "-f", "tests/locustfile.py", "--headless",
       "-u", "50", "-r", "10", "-t", "60s", "--host", "http://127.0.0.1:8000",
       "--csv", "reports/perf", "--html", "reports/perf.html"]
rc = subprocess.run(cmd, cwd=ROOT, env=env).returncode
stop.set(); th.join()
server.terminate(); server.wait(10); log.close()

with open(os.path.join(ROOT, "reports", "resource_usage.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(samples[0])); w.writeheader(); w.writerows(samples)

def stats(k):
    v = [s[k] for s in samples]; return sum(v) / len(v), max(v)
print(f"\nlocust rc={rc} samples={len(samples)} cores={ncpu} ram_total_mb={total_mb:.0f}")
for k in ("cpu_percent", "cpu_percent_of_system", "rss_mb", "mem_percent_of_system"):
    a, m = stats(k); print(f"{k}: avg={a:.2f} peak={m:.2f}")
