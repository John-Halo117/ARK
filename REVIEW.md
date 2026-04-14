# Review Guidelines

## Naming Conventions
- All NATS subjects, service names, capability names, and identifiers must
  follow the rules in [`GLOSSARY.md`](GLOSSARY.md).
- NATS subject strings must **never** be hard-coded — import constants and
  helpers from `ark/subjects.py`.
- Capability subscriptions must use the `>` (multi-token) wildcard, not `*`.

## Critical Areas
- Changes to `ark/security.py` validation regexes affect every module.
- Changes to `ark/subjects.py` constants affect every agent, emitter, and
  core service — verify all consumers still match.
- Any new NATS subject must be added to `ark/subjects.py` and documented in
  `GLOSSARY.md` §1.2.

## Performance
- Flag any NATS publish/subscribe inside a loop without rate limiting.
- Watch for unbounded dict growth (e.g. `RateLimiter._buckets`).

## Security
- No `str(e)` in HTTP error responses — use generic messages.
- All `subprocess.run` calls must validate arguments via `validate_docker_arg`.
- All SQL queries must use parameterized `?` placeholders — no f-strings.
