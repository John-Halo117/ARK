#!/usr/bin/env python3
import json, os, subprocess, urllib.request, re

ROOT = subprocess.check_output(["git","rev-parse","--show-toplevel"]).decode().strip()
POLICY = os.path.join(ROOT, "policy", "autonomy_rules.json")
RESULTS = os.path.join(ROOT, ".ark_ci", "results")
OUT_DIR = os.path.join(ROOT, ".ark_ai", "batches")
MODEL = os.getenv("ARK_AI_MODEL", "codellama:7b")
API = os.getenv("ARK_AI_API", "http://127.0.0.1:11434/api/generate")

os.makedirs(OUT_DIR, exist_ok=True)

with open(POLICY) as f:
    policy = json.load(f)

max_attempts = policy.get("max_repair_attempts", 3)
low_loc = policy.get("low_loc_batch_threshold", 40)
max_batch = policy.get("max_batched_candidates", 3)

# get last failure
fails = sorted([f for f in os.listdir(RESULTS) if f.endswith(".json")])
if not fails:
    exit(0)

last = fails[-1]
with open(os.path.join(RESULTS, last)) as f:
    data = json.load(f)

if data.get("status") != "fail":
    exit(0)

failure_detail = json.dumps(data)
commit = data.get("commit")

candidates = []

def loc_count(patch):
    adds = len([l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++')])
    dels = len([l for l in patch.splitlines() if l.startswith('-') and not l.startswith('---')])
    return adds + dels

for i in range(max_attempts):
    prompt = f"""
Fix the failure. Output ONLY a unified diff.
Failure:\n{failure_detail}
"""
    req = urllib.request.Request(API, data=json.dumps({"model":MODEL,"prompt":prompt}).encode(), headers={"Content-Type":"application/json"})
    patch = urllib.request.urlopen(req).read().decode()

    wt = f".ark_ci/batch_test_{i}"
    subprocess.run(f"git worktree add --detach {wt} {commit}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(f"{wt}.patch","w").write(patch)

    apply = os.system(f"cd {wt} && git apply --3way ../batch_test_{i}.patch")
    test = os.system(f"cd {wt} && go test ./... && pytest") if apply == 0 else 1

    score = 1 if test == 0 else 0
    loc = loc_count(patch)

    candidates.append({
        "patch": patch,
        "score": score,
        "loc": loc
    })

# filter passing
passing = [c for c in candidates if c["score"] == 1]

# sort: low loc, high score
passing.sort(key=lambda x: (x["loc"]))

batch = []
for c in passing:
    if c["loc"] <= low_loc:
        batch.append(c["patch"])
    if len(batch) >= max_batch:
        break

if not batch and passing:
    batch = [passing[0]["patch"]]

if batch:
    merged = "\n".join(batch)
    out = os.path.join(OUT_DIR, f"batch_{commit}.patch")
    open(out,"w").write(merged)
    print(f"[AI] batch ready: {out}")
else:
    print("[AI] no viable repair batch")
