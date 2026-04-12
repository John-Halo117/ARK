BEGIN;

CREATE TABLE IF NOT EXISTS ark_event_delta (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL CHECK (length(trim(source)) > 0),
  source_event_id TEXT,
  entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
  signal_key TEXT NOT NULL CHECK (length(trim(signal_key)) > 0),
  started_at TIMESTAMPTZ NOT NULL,
  ended_at TIMESTAMPTZ NOT NULL,
  value JSONB NOT NULL DEFAULT 'null'::jsonb,
  value_kind TEXT NOT NULL DEFAULT 'json',
  unit TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  event_fingerprint TEXT NOT NULL,
  classifier_status TEXT NOT NULL DEFAULT 'known' CHECK (classifier_status IN ('known', 'inferred', 'fallback', 'error')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (ended_at >= started_at)
);

CREATE INDEX IF NOT EXISTS ark_event_delta_source_entity_signal_time_idx
  ON ark_event_delta (source, entity_id, signal_key, started_at DESC);

CREATE INDEX IF NOT EXISTS ark_event_delta_signal_time_idx
  ON ark_event_delta (signal_key, started_at DESC);

CREATE INDEX IF NOT EXISTS ark_event_delta_status_time_idx
  ON ark_event_delta (classifier_status, started_at DESC);

CREATE INDEX IF NOT EXISTS ark_event_delta_source_event_idx
  ON ark_event_delta (source, source_event_id);

CREATE INDEX IF NOT EXISTS ark_event_delta_metadata_gin_idx
  ON ark_event_delta USING GIN (metadata jsonb_path_ops);

CREATE INDEX IF NOT EXISTS ark_event_delta_value_gin_idx
  ON ark_event_delta USING GIN (value jsonb_path_ops);

CREATE TABLE IF NOT EXISTS ark_event_receipt (
  event_fingerprint TEXT PRIMARY KEY,
  delta_id BIGINT NOT NULL REFERENCES ark_event_delta(id) ON DELETE CASCADE,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ark_event_receipt_delta_idx
  ON ark_event_receipt (delta_id);

CREATE TABLE IF NOT EXISTS ark_entity_snapshot (
  source TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  signal_key TEXT NOT NULL,
  current_value JSONB NOT NULL DEFAULT 'null'::jsonb,
  value_kind TEXT NOT NULL DEFAULT 'json',
  unit TEXT,
  latest_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ NOT NULL,
  delta_id BIGINT NOT NULL REFERENCES ark_event_delta(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source, entity_id, signal_key)
);

CREATE INDEX IF NOT EXISTS ark_entity_snapshot_observed_idx
  ON ark_entity_snapshot (observed_at DESC);

CREATE INDEX IF NOT EXISTS ark_entity_snapshot_signal_idx
  ON ark_entity_snapshot (signal_key, observed_at DESC);

CREATE TABLE IF NOT EXISTS ark_ingest_anomaly (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  signal_key TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  reason TEXT NOT NULL,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ark_ingest_anomaly_observed_idx
  ON ark_ingest_anomaly (observed_at DESC);

CREATE INDEX IF NOT EXISTS ark_ingest_anomaly_source_signal_idx
  ON ark_ingest_anomaly (source, signal_key, observed_at DESC);

CREATE OR REPLACE FUNCTION update_snapshots()
RETURNS TABLE (snapshots_upserted BIGINT)
LANGUAGE plpgsql
AS $$
DECLARE
  v_count BIGINT := 0;
BEGIN
  WITH ranked AS (
    SELECT
      d.id,
      d.source,
      d.entity_id,
      d.signal_key,
      d.value,
      d.value_kind,
      d.unit,
      d.metadata,
      d.ended_at,
      ROW_NUMBER() OVER (
        PARTITION BY d.source, d.entity_id, d.signal_key
        ORDER BY d.ended_at DESC, d.id DESC
      ) AS rn
    FROM ark_event_delta AS d
  )
  INSERT INTO ark_entity_snapshot (
    source,
    entity_id,
    signal_key,
    current_value,
    value_kind,
    unit,
    latest_metadata,
    observed_at,
    delta_id,
    created_at,
    updated_at
  )
  SELECT
    ranked.source,
    ranked.entity_id,
    ranked.signal_key,
    ranked.value,
    ranked.value_kind,
    ranked.unit,
    ranked.metadata,
    ranked.ended_at,
    ranked.id,
    now(),
    now()
  FROM ranked
  WHERE ranked.rn = 1
  ON CONFLICT (source, entity_id, signal_key) DO UPDATE
  SET
    current_value = EXCLUDED.current_value,
    value_kind = EXCLUDED.value_kind,
    unit = EXCLUDED.unit,
    latest_metadata = EXCLUDED.latest_metadata,
    observed_at = EXCLUDED.observed_at,
    delta_id = EXCLUDED.delta_id,
    updated_at = now()
  WHERE
    ark_entity_snapshot.delta_id IS DISTINCT FROM EXCLUDED.delta_id
    OR ark_entity_snapshot.current_value IS DISTINCT FROM EXCLUDED.current_value
    OR ark_entity_snapshot.latest_metadata IS DISTINCT FROM EXCLUDED.latest_metadata
    OR ark_entity_snapshot.observed_at IS DISTINCT FROM EXCLUDED.observed_at
    OR ark_entity_snapshot.unit IS DISTINCT FROM EXCLUDED.unit
    OR ark_entity_snapshot.value_kind IS DISTINCT FROM EXCLUDED.value_kind;

  GET DIAGNOSTICS v_count = ROW_COUNT;

  RETURN QUERY
  SELECT v_count;
END;
$$;

CREATE OR REPLACE FUNCTION upsert_delta(
  p_source TEXT,
  p_entity_id TEXT,
  p_signal_key TEXT,
  p_started_at TIMESTAMPTZ,
  p_ended_at TIMESTAMPTZ,
  p_value JSONB,
  p_metadata JSONB DEFAULT '{}'::jsonb,
  p_event_fingerprint TEXT DEFAULT NULL,
  p_value_kind TEXT DEFAULT 'json',
  p_unit TEXT DEFAULT NULL,
  p_raw_payload JSONB DEFAULT NULL,
  p_classifier_status TEXT DEFAULT 'known',
  p_source_event_id TEXT DEFAULT NULL
)
RETURNS TABLE (
  action TEXT,
  delta_id BIGINT,
  event_fingerprint TEXT,
  merged BOOLEAN,
  snapshot_rows BIGINT
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_started_at TIMESTAMPTZ := COALESCE(p_started_at, p_ended_at, now());
  v_ended_at TIMESTAMPTZ := GREATEST(COALESCE(p_started_at, p_ended_at, now()), COALESCE(p_ended_at, p_started_at, now()));
  v_value JSONB := COALESCE(p_value, 'null'::jsonb);
  v_metadata JSONB := COALESCE(p_metadata, '{}'::jsonb);
  v_raw_payload JSONB := COALESCE(p_raw_payload, '{}'::jsonb);
  v_fingerprint TEXT;
  v_existing_delta_id BIGINT;
  v_candidate_id BIGINT;
  v_candidate_started_at TIMESTAMPTZ;
  v_candidate_ended_at TIMESTAMPTZ;
  v_snapshot_rows BIGINT := 0;
BEGIN
  IF p_source IS NULL OR length(trim(p_source)) = 0 THEN
    RAISE EXCEPTION 'p_source is required';
  END IF;

  IF p_entity_id IS NULL OR length(trim(p_entity_id)) = 0 THEN
    RAISE EXCEPTION 'p_entity_id is required';
  END IF;

  IF p_signal_key IS NULL OR length(trim(p_signal_key)) = 0 THEN
    RAISE EXCEPTION 'p_signal_key is required';
  END IF;

  v_fingerprint := COALESCE(
    NULLIF(trim(p_event_fingerprint), ''),
    md5(
      concat_ws(
        '|',
        p_source,
        COALESCE(p_source_event_id, ''),
        p_entity_id,
        p_signal_key,
        to_char(v_started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
        COALESCE(v_value::text, 'null'),
        COALESCE(v_raw_payload::text, '{}')
      )
    )
  );

  SELECT r.delta_id
  INTO v_existing_delta_id
  FROM ark_event_receipt AS r
  WHERE r.event_fingerprint = v_fingerprint;

  IF FOUND THEN
    SELECT snapshots_upserted
    INTO v_snapshot_rows
    FROM update_snapshots();

    RETURN QUERY
    SELECT 'duplicate'::TEXT, v_existing_delta_id, v_fingerprint, false, COALESCE(v_snapshot_rows, 0);
    RETURN;
  END IF;

  SELECT
    d.id,
    d.started_at,
    d.ended_at
  INTO
    v_candidate_id,
    v_candidate_started_at,
    v_candidate_ended_at
  FROM ark_event_delta AS d
  WHERE
    d.source = p_source
    AND d.entity_id = p_entity_id
    AND d.signal_key = p_signal_key
    AND d.value = v_value
    AND d.metadata = v_metadata
    AND COALESCE(d.unit, '') = COALESCE(p_unit, '')
    AND COALESCE(d.value_kind, 'json') = COALESCE(p_value_kind, 'json')
    AND d.ended_at >= v_started_at
    AND v_ended_at >= d.started_at
  ORDER BY d.ended_at DESC, d.id DESC
  LIMIT 1;

  IF FOUND THEN
    UPDATE ark_event_delta
    SET
      started_at = LEAST(v_candidate_started_at, v_started_at),
      ended_at = GREATEST(v_candidate_ended_at, v_ended_at),
      source_event_id = COALESCE(ark_event_delta.source_event_id, p_source_event_id),
      raw_payload = CASE
        WHEN ark_event_delta.raw_payload = '{}'::jsonb THEN v_raw_payload
        ELSE ark_event_delta.raw_payload
      END,
      updated_at = now()
    WHERE ark_event_delta.id = v_candidate_id;

    INSERT INTO ark_event_receipt (event_fingerprint, delta_id)
    VALUES (v_fingerprint, v_candidate_id)
    ON CONFLICT ON CONSTRAINT ark_event_receipt_pkey DO NOTHING;

    SELECT snapshots_upserted
    INTO v_snapshot_rows
    FROM update_snapshots();

    RETURN QUERY
    SELECT 'merged'::TEXT, v_candidate_id, v_fingerprint, true, COALESCE(v_snapshot_rows, 0);
    RETURN;
  END IF;

  INSERT INTO ark_event_delta (
    source,
    source_event_id,
    entity_id,
    signal_key,
    started_at,
    ended_at,
    value,
    value_kind,
    unit,
    metadata,
    raw_payload,
    event_fingerprint,
    classifier_status,
    created_at,
    updated_at
  )
  VALUES (
    p_source,
    p_source_event_id,
    p_entity_id,
    p_signal_key,
    v_started_at,
    v_ended_at,
    v_value,
    COALESCE(p_value_kind, 'json'),
    p_unit,
    v_metadata,
    v_raw_payload,
    v_fingerprint,
    COALESCE(p_classifier_status, 'known'),
    now(),
    now()
  )
  RETURNING id
  INTO v_existing_delta_id;

  INSERT INTO ark_event_receipt (event_fingerprint, delta_id)
  VALUES (v_fingerprint, v_existing_delta_id)
  ON CONFLICT ON CONSTRAINT ark_event_receipt_pkey DO NOTHING;

  SELECT snapshots_upserted
  INTO v_snapshot_rows
  FROM update_snapshots();

  RETURN QUERY
  SELECT 'inserted'::TEXT, v_existing_delta_id, v_fingerprint, false, COALESCE(v_snapshot_rows, 0);
END;
$$;

COMMIT;
