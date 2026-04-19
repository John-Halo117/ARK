#!/usr/bin/env python3
import json, os, subprocess, urllib.request

ROOT = subprocess.check_output(["git","rev-parse","--show-toplevel"]).decode().strip()
POLICY = os.path.join(ROOT, "policy", "autonomy_rules.json")
RESULTS = os.path.join(ROOT, ".ark_ci", "results")
MODEL = os.getenv("ARK_AI_MODEL", "codellama:7b")
API = os.getenv("ARK_AI_API", "http://127.0.0.1:11434/api/generate")

with open(POLICY) as f:
    policy = json.load(f)

max_attempts = policy.get("max_repair_attempts", 3)

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

for attempt in range(max_attempts):
    wt = subprocess.getoutput(f"git worktree add --detach .ark_ci/repair_{attempt} {commit}")

    prompt = f"""
Fix the failure described below. Output ONLY a unified diff patch.
Failure:
{failure_detail}
"""

    req = urllib.request.Request(API, data=json.dumps({"model":MODEL,"prompt":prompt}).encode(), headers={"Content-Type":"application/json"})
    patch = urllib.request.urlopen(req).read().decode()

    patch_file = f".ark_ci/repair_{attempt}.patch"
    open(patch_file,"w").write(patch)

    os.system(f"cd .ark_ci/repair_{attempt} && git apply --3way ../repair_{attempt}.patch")
    os.system(f"cd .ark_ci/repair_{attempt} && git add -A && git commit -m 'auto-repair {attempt}'")

    new_commit = subprocess.getoutput(f"cd .ark_ci/repair_{attempt} && git rev-parse HEAD")

    # test
    test = os.system(f"cd .ark_ci/repair_{attempt} && go test ./... && pytest")

    if test == 0:
        print(f"[AI] repaired in attempt {attempt}: {new_commit}")
        exit(0)

print("[AI] repair failed after max attempts")
