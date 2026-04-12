CREATE OR REPLACE VIEW ark_current AS
SELECT
  source,
  entity_id,
  signal_key,
  current_value,
  value_kind,
  unit,
  latest_metadata,
  observed_at,
  updated_at
FROM ark_entity_snapshot;
