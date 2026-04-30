# external/

Optional connectivity and integration layer.

Everything that touches the outside world belongs here.

## Put code here if it:
- requires internet access
- integrates with third-party APIs
- performs sync, export, or notification
- is not required for offline operation

## Examples
- GitHub sync
- API adapters
- web fetchers
- external messaging (email, Matrix, etc)
- SaaS connectors

## Rules
- Must be callable but never required
- Must be gated by connectivity mode
- Must have a local fallback or safe failure
- Must be auditable and policy-checked

## Contract
internal/ must NEVER depend on external/.
external/ may depend on internal/.

## Principle
ARK is offline-default. external/ is an extension layer, not a dependency.
