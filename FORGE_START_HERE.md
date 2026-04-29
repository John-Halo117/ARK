# Forge Start Here

If you want the self-coding part of ARK, start here and ignore the deeper docs.

## The easiest way to open Forge

- Browser app: `./forge-app`
- App status: `./forge-app --status`
- Stop the browser app: `./forge-app --stop`
- Remove stale launcher files: `./forge-app --cleanup`
- Terminal UI: `./forge`
- Browser app without launcher helper: `./forge --desktop`
- On Linux/Arch if you want a real app launcher: `./install-forge-arch.sh`
- In PowerShell: `.\forge.ps1`
- In Command Prompt: `forge.cmd`
- On Windows if you just want to click it: double-click `Forge App.cmd`
- On Linux if you want to click the repo-local launcher: run `./Forge\ App.sh`

That opens Forge. If you use the browser app, it should open a local page automatically.

Forge restores the last operator session automatically. Type a task, inspect the diff and risk panels, then run or step the pipeline.

## The safest first command

```bash
./forge --check
```

That tells you whether Forge can see Ollama and which model it will use.

## The normal everyday command

```bash
./forge
```

Inside the UI:

1. Type the task in the top input.
2. Add target files if you want to narrow the change.
3. Press `Run` or hit `Enter` for one step.
4. Watch the live panels for diff, tests, redteam, and logs.
5. If you stop a run, use `resume` to continue from the last queued task.

If you want the browser app instead of the terminal UI:

```bash
./forge --desktop
```

If you are on Arch Linux and want Forge in your app launcher without systemd:

```bash
./install-forge-arch.sh
```

That installs:

- a `forge-app` command in `~/.local/bin`
- a `Forge` desktop entry in `~/.local/share/applications`
- a user-local icon in `~/.local/share/icons`

It does **not** create any systemd unit or background service.
Forge starts only when you open it. Use the Forge `Shutdown` button or
`forge-app --stop` when you are done.

Quick controls:

- `:` opens the command palette
- `Space` toggles auto-loop
- `p` toggles planner
- `m` cycles mode
- `d` cycles diffs
- `q` opens quit confirmation
- `Ctrl+Q` exits the UI

Browser app legend:

- `Run` starts the bounded loop
- `Step` runs one iteration
- `Accept` applies the selected diff
- `Reject` drops the selected live candidate
- `resume` reruns the last queued task
- `tests fast` uses targeted test files when possible
- `expand` / `shrink` change context breadth
- `revert` previews the latest safe undo
- `revert apply` undoes the latest applied Forge delta
- `mode tri` switches to TRISECT
- `tau 0.25` lowers the risk threshold
- `export` writes the current Forge snapshot to `.forge/ui-export.json`

Forge keeps its shared UI session in `.forge/session.json`, including:

- task text and focused files
- controls like planner, mode, risk threshold, context level, and test mode
- live candidate selection
- session logs
- safe-revert lineage for applied Forge deltas

## One-line usage

```bash
./forge "fix the failing login test" app/auth.py tests/test_auth.py
```

If you want the old CLI flow instead of the TUI:

```bash
./forge --no-ui
```

## If Forge says Ollama is missing

Forge tries to wake Ollama and pull the coding model automatically. To check it
manually, run:

```bash
./forge --check
```

Use the AI health card or Nerd Stuff panel only if you want exact diagnostics.

## What Forge does

Forge is the bounded self-coding engine inside ARK. It asks Ollama for code-change proposals, then trusts tools instead of vibes:

- tests
- lint
- type checks
- red-team evaluation

If the candidate passes, Forge can apply it and write artifacts to `.forge/`.
