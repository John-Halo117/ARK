# ARK Internal Loop Contract

This file anchors the core loop stages enforced by `scripts/ci/policy_gate.sh`.

- sense: accept bounded observations and source events through strict contracts.
- compress: canonicalize, hash, and reduce payloads into verifiable state.
- judge: evaluate stability, policy, and budget gates before mutation.
- act: execute only bounded, explicit, observable actions.
- verify: validate outputs, signatures, health signals, and failure models.
- remember: append audit, state, and provenance records for replay.
