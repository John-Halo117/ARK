#!/usr/bin/env python3
import json, subprocess, sys, os

ROOT = subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip()
RULES = json.load(open(os.path.join(ROOT, "config/tiering_rules.json")))


def git_diff_files():
    out = subprocess.check_output(["git", "diff", "--name-only", "HEAD~1..HEAD"]).decode()
    return [l.strip() for l in out.splitlines() if l.strip()]


def git_diff_loc():
    out = subprocess.check_output(["git", "diff", "--numstat", "HEAD~1..HEAD"]).decode()
    total = 0
    for line in out.splitlines():
        parts = line.split()[:2]
        for p in parts:
            if p.isdigit():
                total += int(p)
    return total


def classify_scope(files):
    signals = RULES["signals"]

    if any(any(f.startswith(p) for p in signals["system_wide_paths"]) for f in files):
        return "S5"

    if any(any(f.startswith(p) for p in signals["cross_service_paths"]) for f in files):
        return "S4"

    if any(any(f.startswith(p) for p in signals["service_roots"]) for f in files):
        return "S3"

    if len(files) <= 5:
        return "S2"

    return "S1"


def classify_todo(loc):
    for tier, cfg in RULES["todo_tiers"].items():
        if loc <= cfg["max_loc"]:
            return tier
    return "T5"


def priority(scope, todo):
    return f"P{max(int(scope[1]), int(todo[1]))}"


def main():
    files = git_diff_files()
    loc = git_diff_loc()

    s = classify_scope(files)
    t = classify_todo(loc)
    p = priority(s, t)

    print(json.dumps({
        "scope": s,
        "todo": t,
        "priority": p,
        "files": files,
        "loc": loc
    }, indent=2))


if __name__ == "__main__":
    main()
