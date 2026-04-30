#!/usr/bin/env python3
import json, os, subprocess, time, urllib.request

ROOT = subprocess.check_output(["git","rev-parse","--show-toplevel"]).decode().strip()
AI_DIR = os.path.join(ROOT, ".ark_ai")
QUEUE = os.path.join(AI_DIR, "queue")
PROPOSALS = os.path.join(AI_DIR, "proposals")

os.makedirs(PROPOSALS, exist_ok=True)

MODEL = os.getenv("ARK_AI_MODEL", "codellama:7b")
API = os.getenv("ARK_AI_API", "http://127.0.0.1:11434/api/generate")

def get_context():
    diff = subprocess.getoutput("git diff")
    return diff[:8000]

def call_model(prompt):
    data = json.dumps({"model": MODEL, "prompt": prompt}).encode()
    req = urllib.request.Request(API, data=data, headers={"Content-Type":"application/json"})
    return urllib.request.urlopen(req).read().decode()

while True:
    if os.path.exists(QUEUE):
        with open(QUEUE) as f:
            lines = f.readlines()
        if lines:
            task = json.loads(lines[0])
            with open(QUEUE, "w") as f:
                f.writelines(lines[1:])

            ctx = get_context()
            prompt = f"""
You are a local coding agent.
Task: {task['task']}
Context:
{ctx}

Return ONLY a unified diff patch.
"""

            out = call_model(prompt)
            patch_path = os.path.join(PROPOSALS, f"{task['id']}.patch")
            with open(patch_path, "w") as p:
                p.write(out)

            print(f"[ARK-AI] proposal written {patch_path}")
    time.sleep(2)
