# internal/state/

Materialized state layer.

Provides the current truth snapshot of ARK without replaying the full event log.

## Tracks
- current promoted commit
- current deployed commit
- system health vector
- active anomalies
- connectivity mode

## Rule
State must be derived from events but stored locally for fast access.
