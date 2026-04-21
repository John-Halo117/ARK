# ARK Todo Tiers

`TODO_TIERS.md` is the canonical governance source for Scope/Todo/Priority
classification. Scripts and CI should read the machine version from
`config/tiering_rules.json`.

## Tier model

Scope = blast radius.

| Scope | Meaning |
| --- | --- |
| `S1` | Docs, comments, local scaffolding, no runtime behavior change |
| `S2` | Single module or service surface, bounded behavioral change |
| `S3` | Cross-file or cross-component slice, moderate coordination |
| `S4` | Multi-service, runtime, or data-path risk |
| `S5` | Security, trust, irreversible data, or public-contract risk |

Todo = delivery effort.

| Todo | Meaning |
| --- | --- |
| `T1` | Tiny edit or contract-preserving addition |
| `T2` | Small bounded implementation slice |
| `T3` | Multi-file but coherent feature slice |
| `T4` | Broad implementation or risky integration |
| `T5` | Architectural shift or high-risk irreversible work |

Priority:

```text
P = max(S, T)
```

## Rules

- batch by todo tier
- no mixed todo tiers in one promotion batch
- reject mixed scope escalation in a single automated batch
- `P1` through `P3` may auto-flow
- `P4` and `P5` require manual approval
- `P5` cannot auto-promote
- `S4` and `S5` cannot auto-promote
- avoid commit floods; prefer coherent batches

## Expected control flow

```text
generate -> classify -> batch -> test -> redteam -> promote
```

If a batch violates tier policy:

- stop promotion
- surface the violation
- queue manual review or repair
