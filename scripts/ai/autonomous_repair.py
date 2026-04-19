#!/usr/bin/env python3
import json, os, subprocess, urllib.request, hashlib

ROOT = subprocess.check_output(["git","rev-parse","--show-toplevel"]).decode().strip()
POLICY = os.path.join(ROOT, "policy", "autonomy_rules.json")
RESULTS = os.path.join(ROOT, ".ark_ci", "results")
OUT_DIR = os.path.join(ROOT, ".ark_ai", "batches")
SEEN = os.path.join(ROOT, ".ark_ai", "seen_patches.txt")
MODEL = os.getenv("ARK_AI_MODEL", "codellama:7b")
API = os.getenv("ARK_AI_API", "http://127.0.0.1:11434/api/generate")

os.makedirs(OUT_DIR, exist_ok=True)

with open(POLICY) as f:
    policy = json.load(f)

max_attempts = policy.get("max_repair_attempts", 3)
low_loc = policy.get("low_loc_batch_threshold", 40)
max_batch = policy.get("max_batched_candidates", 3)
max_failures = policy.get("max_failures_per_cycle", 3)
prefer_min = policy.get("prefer_minimal_passing_patch", True)
reject_factor = policy.get("reject_if_larger_than_best_loc_factor", 1.5)

seen = set()
if os.path.exists(SEEN):
    seen = set(open(SEEN).read().splitlines())

# multi-failure intake
fail_files = sorted([f for f in os.listdir(RESULTS) if f.endswith(".json")])[:max_failures]
failure_details = []
commits = []

for fpath in fail_files:
    with open(os.path.join(RESULTS, fpath)) as f:
        data = json.load(f)
        if data.get("status") == "fail":
            failure_details.append(json.dumps(data))
            commits.append(data.get("commit"))

if not failure_details:
    exit(0)

failure_blob = "\n".join(failure_details)
commit = commits[0]

candidates = []

def loc_count(patch):
    adds = len([l for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++')])
    dels = len([l for l in patch.splitlines() if l.startswith('-') and not l.startswith('---')])
    return adds + dels

for i in range(max_attempts):
    prompt = f"Fix the following failures. Output ONLY a unified diff.\n{failure_blob}"
    req = urllib.request.Request(API, data=json.dumps({"model":MODEL,"prompt":prompt}).encode(), headers={"Content-Type":"application/json"})
    patch = urllib.request.urlopen(req).read().decode()

    sig = hashlib.sha256(patch.encode()).hexdigest()
    if sig in seen:
        continue

    wt = f".ark_ci/batch_test_{i}"
    subprocess.run(f"git worktree add --detach {wt} {commit}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(f"{wt}.patch","w").write(patch)

    apply = os.system(f"cd {wt} && git apply --3way ../batch_test_{i}.patch")
    test = os.system(f"cd {wt} && go test ./... && pytest") if apply == 0 else 1

    loc = loc_count(patch)
    candidates.append({"patch":patch,"loc":loc,"pass": test == 0, "sig":sig})

# filter passing
passing = [c for c in candidates if c["pass"]]

if not passing:
    exit(0)

# minimal patch preference
passing.sort(key=lambda x: x["loc"])
best_loc = passing[0]["loc"]
filtered = [c for c in passing if c["loc"] <= best_loc * reject_factor]

batch = []
for c in filtered:
    if c["loc"] <= low_loc:
        batch.append(c)
    if len(batch) >= max_batch:
        break

if not batch:
    batch = [filtered[0]]

merged = "\n".join([c["patch"] for c in batch])
out = os.path.join(OUT_DIR, f"batch_{commit}.patch")
open(out,"w").write(merged)

# record signatures
with open(SEEN,"a") as f:
    for c in batch:
        f.write(c["sig"]+"\n")

print(f"[AI] batch ready: {out}")
