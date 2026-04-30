#!/usr/bin/env python3
import os, time, subprocess

ROOT = subprocess.check_output(["git","rev-parse","--show-toplevel"]).decode().strip()
RESULTS = os.path.join(ROOT, ".ark_ci", "results")

while True:
    fails = []
    if os.path.exists(RESULTS):
        for f in os.listdir(RESULTS):
            if f.endswith(".json"):
                data = open(os.path.join(RESULTS,f)).read()
                if '"status":"fail"' in data:
                    fails.append(f)

    if not fails:
        print("[AI] no failures remaining, idle")
        time.sleep(5)
        continue

    print(f"[AI] processing {len(fails)} failures")
    os.system("python3 scripts/ai/autonomous_repair.py")

    time.sleep(2)
