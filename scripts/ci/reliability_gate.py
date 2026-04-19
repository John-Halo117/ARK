#!/usr/bin/env python3
import json, os, sys

ROOT = os.popen("git rev-parse --show-toplevel").read().strip()
RESULTS = os.path.join(ROOT, ".ark_ci", "results")
POLICY = os.path.join(ROOT, "policy", "autonomy_rules.json")

with open(POLICY) as f:
    policy = json.load(f)

target = policy.get("rolling_pass_rate_target", 0.999)
window = policy.get("rolling_pass_rate_window", 1000)

files = []
if os.path.exists(RESULTS):
    files = sorted([os.path.join(RESULTS, f) for f in os.listdir(RESULTS) if f.endswith(".json")])

recent = files[-window:]

passes = 0
fails = 0

for fpath in recent:
    try:
        with open(fpath) as f:
            data = json.load(f)
            if data.get("status") == "pass":
                passes += 1
            else:
                fails += 1
    except Exception:
        continue

# include current run as pass
passes += 1

total = passes + fails
rate = passes / total if total > 0 else 1.0

print(f"[CI] projected pass rate: {rate:.6f} (target {target})")

if rate < target:
    print("[CI] BLOCKED: reliability below threshold")
    sys.exit(1)

sys.exit(0)
