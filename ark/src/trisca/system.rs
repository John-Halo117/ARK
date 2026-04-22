use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::panic::{self, AssertUnwindSafe};

const PHI: f64 = 1.618_033_988_75;
const SQRT2: f64 = 1.414_213_562_37;
const E: f64 = 2.718_281_828_46;
const LN2: f64 = 0.693_147_180_56;
const MAX_STREAM_ID_LENGTH: usize = 128;

pub type NumericRecord = BTreeMap<String, f64>;
pub type ProcessResult = Result<ProcessOk, FailureModel>;
type Subscriber = Box<dyn Fn(&State) + Send + Sync + 'static>;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct FailureModel {
    pub status: String,
    pub error_code: String,
    pub reason: String,
    pub context: BTreeMap<String, String>,
    pub recoverable: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct State {
    pub v: f64,
    pub e: f64,
    pub i: f64,
    pub c: f64,
    pub t: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SystemConfig {
    pub max_records: usize,
    pub max_fields: usize,
    pub max_samples: usize,
    pub max_streams: usize,
    pub max_subscribers: usize,
    pub max_adjacency_pairs: usize,
    pub clamp_min: f64,
    pub clamp_max: f64,
    pub dedupe_eps: f64,
    pub epsilon: f64,
    pub noise_floor: f64,
    pub continuity_delta: f64,
    pub confidence_threshold: f64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub enum PublishStatus {
    Idle,
    Ok,
    Error,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct HealthSnapshot {
    pub record_count: usize,
    pub stream_count: usize,
    pub subscriber_count: usize,
    pub last_pair_count: usize,
    pub last_rejected_reason: Option<String>,
    pub last_budget_estimate: usize,
    pub last_output_timestamp: u64,
    pub last_publish_status: PublishStatus,
    pub last_publish_rejected: bool,
    pub last_error_code: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ProcessOk {
    pub status: String,
    pub state: State,
    pub rejected: bool,
    pub n: usize,
    pub health: HealthSnapshot,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub enum TriggerReason {
    ThresholdMet,
    BelowValue,
    BelowConfidence,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct TriggerResult {
    pub fired: bool,
    pub reason: TriggerReason,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SelfCheckOk {
    pub status: String,
    pub checks: usize,
}

impl Default for SystemConfig {
    fn default() -> Self {
        Self {
            max_records: 256,
            max_fields: 16,
            max_samples: 256,
            max_streams: 16,
            max_subscribers: 16,
            max_adjacency_pairs: 120,
            clamp_min: -1_000_000.0,
            clamp_max: 1_000_000.0,
            dedupe_eps: 1e-9,
            epsilon: 1e-9,
            noise_floor: 1e-9,
            continuity_delta: 0.25,
            confidence_threshold: 0.35,
        }
    }
}

impl Default for HealthSnapshot {
    fn default() -> Self {
        Self {
            record_count: 0,
            stream_count: 0,
            subscriber_count: 0,
            last_pair_count: 0,
            last_rejected_reason: None,
            last_budget_estimate: 0,
            last_output_timestamp: 0,
            last_publish_status: PublishStatus::Idle,
            last_publish_rejected: false,
            last_error_code: None,
        }
    }
}

fn failure(error_code: &str, reason: &str, context: BTreeMap<String, String>) -> FailureModel {
    FailureModel {
        status: "error".to_string(),
        error_code: error_code.to_string(),
        reason: reason.to_string(),
        context,
        recoverable: false,
    }
}

fn single_context(key: &str, value: impl ToString) -> BTreeMap<String, String> {
    let mut context = BTreeMap::new();
    context.insert(key.to_string(), value.to_string());
    context
}

fn ok_result(state: State, rejected: bool, n: usize, health: &HealthSnapshot) -> ProcessOk {
    ProcessOk {
        status: "ok".to_string(),
        state,
        rejected,
        n,
        health: health.clone(),
    }
}

fn is_positive(value: usize) -> bool {
    value > 0
}

fn clamp(value: f64, minimum: f64, maximum: f64) -> f64 {
    if value < minimum {
        minimum
    } else if value > maximum {
        maximum
    } else {
        value
    }
}

fn clamp_unit(value: f64) -> f64 {
    clamp(value, 0.0, 1.0)
}

fn zero_state(timestamp_ms: u64) -> State {
    State {
        v: 0.0,
        e: 0.0,
        i: 0.0,
        c: 0.0,
        t: timestamp_ms,
    }
}

fn max_entropy_bound(config: &SystemConfig) -> f64 {
    let max_abs = config.clamp_min.abs().max(config.clamp_max.abs());
    (max_abs * max_abs / PHI).max(config.noise_floor)
}

fn max_inequality_bound(config: &SystemConfig) -> f64 {
    ((config.clamp_max - config.clamp_min) / SQRT2).max(0.0)
}

fn normalize_state(state: &State, config: &SystemConfig) -> State {
    State {
        v: clamp(state.v, config.clamp_min, config.clamp_max),
        e: clamp(state.e, config.noise_floor, max_entropy_bound(config)),
        i: clamp(state.i, 0.0, max_inequality_bound(config)),
        c: clamp_unit(state.c),
        t: state.t,
    }
}

pub fn validate_config(config: &SystemConfig) -> Result<(), FailureModel> {
    if !is_positive(config.max_records) {
        return Err(failure("INVALID_CONFIG", "max_records must be > 0", single_context("max_records", config.max_records)));
    }
    if !is_positive(config.max_fields) {
        return Err(failure("INVALID_CONFIG", "max_fields must be > 0", single_context("max_fields", config.max_fields)));
    }
    if !is_positive(config.max_samples) {
        return Err(failure("INVALID_CONFIG", "max_samples must be > 0", single_context("max_samples", config.max_samples)));
    }
    if !is_positive(config.max_streams) {
        return Err(failure("INVALID_CONFIG", "max_streams must be > 0", single_context("max_streams", config.max_streams)));
    }
    if !is_positive(config.max_subscribers) {
        return Err(failure("INVALID_CONFIG", "max_subscribers must be > 0", single_context("max_subscribers", config.max_subscribers)));
    }
    if !is_positive(config.max_adjacency_pairs) {
        return Err(failure("INVALID_CONFIG", "max_adjacency_pairs must be > 0", single_context("max_adjacency_pairs", config.max_adjacency_pairs)));
    }
    if !config.clamp_min.is_finite() || !config.clamp_max.is_finite() || config.clamp_min >= config.clamp_max {
        let mut context = BTreeMap::new();
        context.insert("clamp_min".to_string(), config.clamp_min.to_string());
        context.insert("clamp_max".to_string(), config.clamp_max.to_string());
        return Err(failure("INVALID_CONFIG", "clamp_min must be finite and less than clamp_max", context));
    }
    if !config.dedupe_eps.is_finite() || config.dedupe_eps < 0.0 {
        return Err(failure("INVALID_CONFIG", "dedupe_eps must be finite and >= 0", single_context("dedupe_eps", config.dedupe_eps)));
    }
    if !config.epsilon.is_finite() || config.epsilon <= 0.0 {
        return Err(failure("INVALID_CONFIG", "epsilon must be finite and > 0", single_context("epsilon", config.epsilon)));
    }
    if !config.noise_floor.is_finite() || config.noise_floor <= 0.0 {
        return Err(failure("INVALID_CONFIG", "noise_floor must be finite and > 0", single_context("noise_floor", config.noise_floor)));
    }
    if !config.continuity_delta.is_finite() || config.continuity_delta < 0.0 {
        return Err(failure("INVALID_CONFIG", "continuity_delta must be finite and >= 0", single_context("continuity_delta", config.continuity_delta)));
    }
    if !config.confidence_threshold.is_finite()
        || config.confidence_threshold < 0.0
        || config.confidence_threshold > 1.0
    {
        return Err(failure("INVALID_CONFIG", "confidence_threshold must be within [0, 1]", single_context("confidence_threshold", config.confidence_threshold)));
    }

    let expected_pairs = (config.max_streams * (config.max_streams.saturating_sub(1))) / 2;
    if config.max_adjacency_pairs != expected_pairs {
        let mut context = BTreeMap::new();
        context.insert("max_streams".to_string(), config.max_streams.to_string());
        context.insert("max_adjacency_pairs".to_string(), config.max_adjacency_pairs.to_string());
        context.insert("expected_pairs".to_string(), expected_pairs.to_string());
        return Err(failure(
            "INCONSISTENT_CONFIG",
            "max_adjacency_pairs must exactly match the bounded pair count for max_streams",
            context,
        ));
    }

    Ok(())
}

pub fn validate_timestamp(timestamp_ms: u64) -> Result<(), FailureModel> {
    let _ = timestamp_ms;
    Ok(())
}

pub fn validate_field_list(fields: &[String], config: &SystemConfig) -> Result<(), FailureModel> {
    if fields.is_empty() {
        return Err(failure("EMPTY_FIELDS", "at least one field is required", BTreeMap::new()));
    }
    if fields.len() > config.max_fields {
        let mut context = BTreeMap::new();
        context.insert("field_count".to_string(), fields.len().to_string());
        context.insert("max_fields".to_string(), config.max_fields.to_string());
        return Err(failure("FIELD_CAP_EXCEEDED", "field count exceeds max_fields", context));
    }

    let mut seen = BTreeMap::new();
    for field in fields {
        if field.trim().is_empty() {
            return Err(failure("INVALID_FIELD_NAME", "field names must be non-empty", BTreeMap::new()));
        }
        if seen.insert(field.clone(), true).is_some() {
            return Err(failure("DUPLICATE_FIELD", "duplicate field names are not allowed", single_context("field", field)));
        }
    }

    Ok(())
}

pub fn validate_records(records: &[NumericRecord], config: &SystemConfig) -> Result<(), FailureModel> {
    if records.len() > config.max_records {
        let mut context = BTreeMap::new();
        context.insert("record_count".to_string(), records.len().to_string());
        context.insert("max_records".to_string(), config.max_records.to_string());
        return Err(failure("RECORD_CAP_EXCEEDED", "record count exceeds max_records", context));
    }
    Ok(())
}

pub fn validate_state(state: &State, config: &SystemConfig) -> Result<(), FailureModel> {
    validate_timestamp(state.t)?;
    if !state.v.is_finite() || !state.e.is_finite() || !state.i.is_finite() || !state.c.is_finite() {
        return Err(failure("INVALID_STATE", "state values must be finite", BTreeMap::new()));
    }
    if state.e < 0.0 || state.i < 0.0 {
        return Err(failure("INVALID_STATE", "entropy and inequality must be non-negative", BTreeMap::new()));
    }
    if state.c < 0.0 || state.c > 1.0 {
        return Err(failure("INVALID_STATE", "confidence must be within [0, 1]", single_context("confidence", state.c)));
    }
    if state.v < config.clamp_min || state.v > config.clamp_max {
        let mut context = BTreeMap::new();
        context.insert("value".to_string(), state.v.to_string());
        context.insert("clamp_min".to_string(), config.clamp_min.to_string());
        context.insert("clamp_max".to_string(), config.clamp_max.to_string());
        return Err(failure("VALUE_OUT_OF_RANGE", "state.v exceeds configured clamp range", context));
    }
    Ok(())
}

pub fn estimate_budget(
    record_count: usize,
    field_count: usize,
    sample_count: usize,
    stream_count: usize,
    config: &SystemConfig,
) -> usize {
    let bounded_records = record_count.min(config.max_records);
    let bounded_fields = field_count.min(config.max_fields);
    let bounded_samples = sample_count.min(config.max_samples);
    let bounded_streams = stream_count.min(config.max_streams);
    let pair_count = ((bounded_streams * bounded_streams.saturating_sub(1)) / 2)
        .min(config.max_adjacency_pairs);

    let ingest_ops = bounded_records * bounded_fields;
    let preprocess_ops = bounded_fields * bounded_samples * 3;
    let orthogonalize_ops = bounded_fields * bounded_samples * 4;
    let trisca_ops = bounded_fields * bounded_samples * 3;
    let pair_ops = pair_count * 6;
    let fusion_ops = bounded_streams * 6;

    ingest_ops + preprocess_ops + orthogonalize_ops + trisca_ops + pair_ops + fusion_ops
}

fn max_budget(config: &SystemConfig) -> usize {
    estimate_budget(
        config.max_records,
        config.max_fields,
        config.max_samples,
        config.max_streams,
        config,
    )
}

pub fn map_to_signals(
    records: &[NumericRecord],
    fields: &[String],
    config: &SystemConfig,
) -> Result<Vec<Vec<f64>>, FailureModel> {
    validate_records(records, config)?;
    validate_field_list(fields, config)?;

    let budget = estimate_budget(records.len(), fields.len(), config.max_samples, fields.len().min(config.max_streams), config);
    if budget > max_budget(config) {
        let mut context = BTreeMap::new();
        context.insert("estimated_budget".to_string(), budget.to_string());
        context.insert("max_budget".to_string(), max_budget(config).to_string());
        return Err(failure("BUDGET_EXCEEDED", "ingest request exceeds the configured budget", context));
    }

    let field_count = fields.len();
    let record_count = records.len();
    let mut output = vec![Vec::<f64>::new(); field_count];
    let mut counts = vec![0usize; field_count];

    for record_index in 0..record_count {
        let record = &records[record_index];
        for field_index in 0..field_count {
            let field = &fields[field_index];
            if let Some(value) = record.get(field) {
                if value.is_finite() {
                    if counts[field_index] >= config.max_samples {
                        let mut context = BTreeMap::new();
                        context.insert("field".to_string(), field.clone());
                        context.insert("max_samples".to_string(), config.max_samples.to_string());
                        return Err(failure("SAMPLE_CAP_EXCEEDED", "numeric samples for a field exceed max_samples", context));
                    }
                    output[field_index].push(*value);
                    counts[field_index] += 1;
                }
            }
        }
    }

    Ok(output)
}

pub fn preprocess(samples: &[f64], config: &SystemConfig) -> Result<Vec<f64>, FailureModel> {
    if samples.len() > config.max_samples {
        let mut context = BTreeMap::new();
        context.insert("sample_count".to_string(), samples.len().to_string());
        context.insert("max_samples".to_string(), config.max_samples.to_string());
        return Err(failure("SAMPLE_CAP_EXCEEDED", "sample count exceeds max_samples", context));
    }

    let mut cleaned = Vec::with_capacity(samples.len());
    let mut previous = 0.0f64;
    let mut has_previous = false;

    for sample in samples {
        if !sample.is_finite() {
            continue;
        }
        let clamped = clamp(*sample, config.clamp_min, config.clamp_max);
        if has_previous && (clamped - previous).abs() <= config.dedupe_eps {
            continue;
        }
        if cleaned.len() >= config.max_samples {
            return Err(failure("SAMPLE_CAP_EXCEEDED", "cleaned sample count exceeds max_samples", single_context("max_samples", config.max_samples)));
        }
        cleaned.push(clamped);
        previous = clamped;
        has_previous = true;
    }

    Ok(cleaned)
}

pub fn orthogonalize(samples: &[f64], config: &SystemConfig) -> Result<Vec<f64>, FailureModel> {
    if samples.len() > config.max_samples {
        let mut context = BTreeMap::new();
        context.insert("sample_count".to_string(), samples.len().to_string());
        context.insert("max_samples".to_string(), config.max_samples.to_string());
        return Err(failure("SAMPLE_CAP_EXCEEDED", "sample count exceeds max_samples", context));
    }
    if samples.is_empty() {
        return Ok(Vec::new());
    }

    let sample_count = samples.len();
    let mean_index = (sample_count.saturating_sub(1)) as f64 / 2.0;
    let mut sum_values = 0.0f64;
    for sample in samples {
        if !sample.is_finite() {
            return Err(failure("INVALID_SAMPLES", "samples must be finite", BTreeMap::new()));
        }
        sum_values += *sample;
    }
    let mean_value = sum_values / sample_count as f64;

    let mut numerator = 0.0f64;
    let mut denominator = 0.0f64;
    for (index, sample) in samples.iter().enumerate() {
        let centered_index = index as f64 - mean_index;
        let centered_value = *sample - mean_value;
        numerator += centered_index * centered_value;
        denominator += centered_index * centered_index;
    }

    let slope = if denominator <= config.epsilon { 0.0 } else { numerator / denominator };
    let mut output = vec![0.0f64; sample_count];
    for (index, sample) in samples.iter().enumerate() {
        let centered_index = index as f64 - mean_index;
        output[index] = *sample - mean_value - slope * centered_index;
    }

    Ok(output)
}

pub fn trisca(
    samples: &[f64],
    timestamp_ms: u64,
    previous: Option<&State>,
    config: &SystemConfig,
) -> ProcessResult {
    validate_timestamp(timestamp_ms)?;
    if samples.len() > config.max_samples {
        let mut context = BTreeMap::new();
        context.insert("sample_count".to_string(), samples.len().to_string());
        context.insert("max_samples".to_string(), config.max_samples.to_string());
        return Err(failure("SAMPLE_CAP_EXCEEDED", "sample count exceeds max_samples", context));
    }
    if let Some(prev) = previous {
        validate_state(prev, config)?;
        if timestamp_ms < prev.t {
            let mut context = BTreeMap::new();
            context.insert("timestamp_ms".to_string(), timestamp_ms.to_string());
            context.insert("prev_t".to_string(), prev.t.to_string());
            return Err(failure("TIMESTAMP_REGRESSION", "timestamp_ms cannot be earlier than previous state time", context));
        }
    }

    let mut health = HealthSnapshot::default();
    health.record_count = samples.len();
    health.last_budget_estimate = estimate_budget(0, 1, samples.len(), 1, config);
    health.last_output_timestamp = timestamp_ms;

    if samples.is_empty() {
        health.last_publish_status = PublishStatus::Ok;
        health.last_publish_rejected = true;
        health.last_rejected_reason = Some("empty_input".to_string());
        return Ok(ok_result(zero_state(timestamp_ms), true, 0, &health));
    }

    let mut sum_values = 0.0f64;
    let mut sum_squares = 0.0f64;
    let mut minimum = samples[0];
    let mut maximum = samples[0];

    for sample in samples {
        if !sample.is_finite() {
            return Err(failure("INVALID_SAMPLES", "samples must be finite", BTreeMap::new()));
        }
        sum_values += *sample;
        sum_squares += *sample * *sample;
        if *sample < minimum {
            minimum = *sample;
        }
        if *sample > maximum {
            maximum = *sample;
        }
    }

    let mean_value = sum_values / samples.len() as f64;
    let variance = ((sum_squares / samples.len() as f64) - mean_value * mean_value).max(0.0);
    let entropy = clamp((variance / PHI).max(config.noise_floor), config.noise_floor, max_entropy_bound(config));
    let range = maximum - minimum;
    let inequality = clamp(
        if range <= config.epsilon { 0.0 } else { (range / SQRT2).max(0.0) },
        0.0,
        max_inequality_bound(config),
    );

    let raw_value = (mean_value * PHI + entropy * SQRT2 + inequality) / (PHI + SQRT2 + 1.0);
    let normalized_raw = clamp(raw_value, config.clamp_min, config.clamp_max);

    let mut next_value = normalized_raw;
    if let Some(prev) = previous {
        let delta_time = timestamp_ms - prev.t;
        let decay_weight = clamp_unit((-(delta_time as f64) / (E * 1000.0)).exp());
        next_value = normalized_raw * (1.0 - decay_weight) + prev.v * decay_weight;
        let delta_value = next_value - prev.v;
        if delta_value.abs() > config.continuity_delta {
            next_value = prev.v + delta_value.signum() * config.continuity_delta;
        }
    }

    let raw_confidence = 1.0 / (1.0 + entropy + inequality);
    let confidence = clamp_unit(raw_confidence.max(LN2 * 0.5));
    let state = normalize_state(
        &State {
            v: next_value,
            e: entropy,
            i: inequality,
            c: confidence,
            t: timestamp_ms,
        },
        config,
    );

    if state.c < config.confidence_threshold {
        health.last_publish_status = PublishStatus::Ok;
        health.last_publish_rejected = true;
        health.last_rejected_reason = Some("low_confidence".to_string());
        let fallback = previous.cloned().unwrap_or_else(|| zero_state(timestamp_ms));
        return Ok(ok_result(normalize_state(&fallback, config), true, samples.len(), &health));
    }

    health.last_publish_status = PublishStatus::Ok;
    Ok(ok_result(state, false, samples.len(), &health))
}

fn similarity_weight(left: &State, right: &State) -> f64 {
    let distance = (left.v - right.v).abs() + 0.5 * (left.e - right.e).abs() + 0.5 * (left.i - right.i).abs();
    (1.0 - distance.min(1.0)).max(0.0)
}

fn fuse_signal_states(states: &[State], timestamp_ms: u64, config: &SystemConfig) -> State {
    if states.is_empty() {
        return zero_state(timestamp_ms);
    }

    let mut weight_sum = 0.0f64;
    let mut value_sum = 0.0f64;
    let mut entropy_sum = 0.0f64;
    let mut inequality_sum = 0.0f64;
    let mut confidence_sum = 0.0f64;

    for state in states {
        if state.c <= 0.0 {
            continue;
        }
        weight_sum += state.c;
        value_sum += state.v * state.c;
        entropy_sum += state.e * state.c;
        inequality_sum += state.i * state.c;
        confidence_sum += state.c * state.c;
    }

    if weight_sum <= config.epsilon {
        return zero_state(timestamp_ms);
    }

    normalize_state(
        &State {
            v: value_sum / weight_sum,
            e: entropy_sum / weight_sum,
            i: inequality_sum / weight_sum,
            c: clamp_unit(confidence_sum / weight_sum),
            t: timestamp_ms,
        },
        config,
    )
}

fn structural_kernel(
    states: &[State],
    timestamp_ms: u64,
    config: &SystemConfig,
) -> Result<(State, usize), FailureModel> {
    if states.is_empty() {
        return Ok((zero_state(timestamp_ms), 0));
    }
    if states.len() == 1 {
        return Ok((
            normalize_state(
                &State {
                    v: 1.0,
                    e: config.noise_floor,
                    i: 0.0,
                    c: 1.0,
                    t: timestamp_ms,
                },
                config,
            ),
            0,
        ));
    }

    let potential_pairs = (states.len() * (states.len().saturating_sub(1))) / 2;
    if potential_pairs > config.max_adjacency_pairs {
        let mut context = BTreeMap::new();
        context.insert("stream_count".to_string(), states.len().to_string());
        context.insert("potential_pairs".to_string(), potential_pairs.to_string());
        context.insert("max_adjacency_pairs".to_string(), config.max_adjacency_pairs.to_string());
        return Err(failure("ADJACENCY_CAP_EXCEEDED", "pairwise structural pass exceeds max_adjacency_pairs", context));
    }

    let mut pair_count = 0usize;
    let mut total_weight = 0.0f64;
    let mut minimum_weight = 1.0f64;
    let mut maximum_weight = 0.0f64;
    for left_index in 0..states.len() {
        for right_index in (left_index + 1)..states.len() {
            let weight = similarity_weight(&states[left_index], &states[right_index]);
            total_weight += weight;
            minimum_weight = minimum_weight.min(weight);
            maximum_weight = maximum_weight.max(weight);
            pair_count += 1;
        }
    }

    let pair_mean = if pair_count == 0 { 1.0 } else { total_weight / pair_count as f64 };
    let entropy = clamp(((1.0 - pair_mean) / PHI).max(config.noise_floor), config.noise_floor, 1.0);
    let inequality = clamp(if pair_count == 0 { 0.0 } else { (maximum_weight - minimum_weight).max(0.0) }, 0.0, 1.0);
    let confidence = clamp_unit((1.0 / (1.0 + entropy + inequality)).max(LN2 * 0.5));

    Ok((
        normalize_state(
            &State {
                v: clamp_unit(pair_mean),
                e: entropy,
                i: inequality,
                c: confidence,
                t: timestamp_ms,
            },
            config,
        ),
        pair_count,
    ))
}

fn fuse_global_state(signal_state: &State, structural_state: &State, timestamp_ms: u64, config: &SystemConfig) -> State {
    let signal_weight = signal_state.c;
    let structural_weight = structural_state.c;
    let total_weight = signal_weight + structural_weight;

    if total_weight <= config.epsilon {
        return zero_state(timestamp_ms);
    }

    normalize_state(
        &State {
            v: (signal_state.v * signal_weight + structural_state.v * structural_weight) / total_weight,
            e: (signal_state.e * signal_weight + structural_state.e * structural_weight) / total_weight,
            i: (signal_state.i * signal_weight + structural_state.i * structural_weight) / total_weight,
            c: clamp_unit((signal_state.c * signal_weight + structural_state.c * structural_weight) / total_weight),
            t: timestamp_ms,
        },
        config,
    )
}

pub fn evaluate_trigger(
    state: &State,
    value_threshold: f64,
    confidence_threshold: f64,
) -> Result<TriggerResult, FailureModel> {
    if !value_threshold.is_finite() || !(0.0..=1.0).contains(&value_threshold) {
        return Err(failure("INVALID_THRESHOLD", "value_threshold must be within [0, 1]", single_context("value_threshold", value_threshold)));
    }
    if !confidence_threshold.is_finite() || !(0.0..=1.0).contains(&confidence_threshold) {
        return Err(failure("INVALID_THRESHOLD", "confidence_threshold must be within [0, 1]", single_context("confidence_threshold", confidence_threshold)));
    }

    if state.v < value_threshold {
        return Ok(TriggerResult { fired: false, reason: TriggerReason::BelowValue });
    }
    if state.c < confidence_threshold {
        return Ok(TriggerResult { fired: false, reason: TriggerReason::BelowConfidence });
    }
    Ok(TriggerResult { fired: true, reason: TriggerReason::ThresholdMet })
}

pub struct ArkTriscaSystem {
    config: SystemConfig,
    stream_states: BTreeMap<String, State>,
    subscribers: Vec<Subscriber>,
    health: HealthSnapshot,
    global_state: Option<State>,
}

impl ArkTriscaSystem {
    pub fn new(config: SystemConfig) -> Result<Self, FailureModel> {
        validate_config(&config)?;
        run_deterministic_self_check(&config)?;
        Ok(Self {
            config,
            stream_states: BTreeMap::new(),
            subscribers: Vec::new(),
            health: HealthSnapshot::default(),
            global_state: None,
        })
    }

    pub fn health(&self) -> HealthSnapshot {
        let mut snapshot = self.health.clone();
        snapshot.stream_count = self.stream_states.len();
        snapshot.subscriber_count = self.subscribers.len();
        snapshot
    }

    pub fn subscribe<F>(&mut self, subscriber: F) -> Result<(), FailureModel>
    where
        F: Fn(&State) + Send + Sync + 'static,
    {
        if self.subscribers.len() >= self.config.max_subscribers {
            let mut context = BTreeMap::new();
            context.insert("subscriber_count".to_string(), self.subscribers.len().to_string());
            context.insert("max_subscribers".to_string(), self.config.max_subscribers.to_string());
            let error = failure("SUBSCRIBER_CAP_EXCEEDED", "subscriber count exceeds max_subscribers", context);
            self.record_error(&error);
            return Err(error);
        }

        self.subscribers.push(Box::new(subscriber));
        self.health.subscriber_count = self.subscribers.len();
        self.health.last_publish_status = PublishStatus::Ok;
        self.health.last_publish_rejected = false;
        self.health.last_error_code = None;
        Ok(())
    }

    pub fn publish(&mut self, stream_id: &str, state: State) -> ProcessResult {
        if stream_id.trim().is_empty() {
            let error = failure("INVALID_STREAM_ID", "stream_id must be a non-empty string", BTreeMap::new());
            self.record_error(&error);
            return Err(error);
        }
        if stream_id.len() > MAX_STREAM_ID_LENGTH {
            let mut context = BTreeMap::new();
            context.insert("stream_id_length".to_string(), stream_id.len().to_string());
            context.insert("max_length".to_string(), MAX_STREAM_ID_LENGTH.to_string());
            let error = failure("INVALID_STREAM_ID", "stream_id exceeds maximum length", context);
            self.record_error(&error);
            return Err(error);
        }

        validate_state(&state, &self.config)?;

        let had_existing = self.stream_states.contains_key(stream_id);
        if !had_existing && self.stream_states.len() >= self.config.max_streams {
            let mut context = BTreeMap::new();
            context.insert("stream_count".to_string(), self.stream_states.len().to_string());
            context.insert("max_streams".to_string(), self.config.max_streams.to_string());
            context.insert("rejected_stream_id".to_string(), stream_id.to_string());
            let error = failure("STREAM_CAP_EXCEEDED", "stream count exceeds max_streams", context);
            self.record_error(&error);
            return Err(error);
        }

        let previous_stream = self.stream_states.get(stream_id).cloned();
        let previous_global = self.global_state.clone();
        let normalized = normalize_state(&state, &self.config);
        self.stream_states.insert(stream_id.to_string(), normalized.clone());

        let states: Vec<State> = self.stream_states.values().cloned().collect();
        let stream_count = states.len();
        self.health.last_budget_estimate = estimate_budget(0, 0, 0, stream_count, &self.config);
        self.health.last_output_timestamp = normalized.t;
        self.health.stream_count = stream_count;

        let signal_state = fuse_signal_states(&states, normalized.t, &self.config);
        let (structural_state, pair_count) = match structural_kernel(&states, normalized.t, &self.config) {
            Ok(value) => value,
            Err(error) => {
                self.restore_state(stream_id, previous_stream, had_existing, previous_global);
                self.record_error(&error);
                return Err(error);
            }
        };

        self.health.last_pair_count = pair_count;
        let mut next_global = if stream_count <= 1 {
            signal_state
        } else {
            fuse_global_state(&signal_state, &structural_state, normalized.t, &self.config)
        };

        let mut rejected = false;
        if next_global.c < self.config.confidence_threshold {
            next_global = self.global_state.clone().unwrap_or_else(|| zero_state(normalized.t));
            rejected = true;
            self.health.last_rejected_reason = Some("low_confidence_global".to_string());
        } else {
            self.health.last_rejected_reason = None;
        }

        self.global_state = Some(normalize_state(&next_global, &self.config));
        let published_state = self.global_state.clone().unwrap_or_else(|| zero_state(normalized.t));

        for subscriber_index in 0..self.subscribers.len() {
            let subscriber = &self.subscribers[subscriber_index];
            let result = panic::catch_unwind(AssertUnwindSafe(|| subscriber(&published_state)));
            if result.is_err() {
                self.restore_state(stream_id, previous_stream, had_existing, previous_global);
                let mut context = BTreeMap::new();
                context.insert("subscriber_index".to_string(), subscriber_index.to_string());
                let error = failure("SUBSCRIBER_ERROR", "subscriber callback panicked during publish", context);
                self.record_error(&error);
                return Err(error);
            }
        }

        self.health.last_publish_status = PublishStatus::Ok;
        self.health.last_publish_rejected = rejected;
        self.health.last_error_code = None;
        self.health.stream_count = self.stream_states.len();
        self.health.subscriber_count = self.subscribers.len();
        self.health.last_output_timestamp = published_state.t;

        Ok(ok_result(published_state, rejected, self.stream_states.len(), &self.health))
    }

    pub fn ingest_and_process(
        &mut self,
        records: &[NumericRecord],
        fields: &[String],
        timestamp_ms: u64,
    ) -> ProcessResult {
        validate_timestamp(timestamp_ms)?;
        validate_records(records, &self.config)?;
        validate_field_list(fields, &self.config)?;

        let prospective_stream_count = self.stream_states.len().max(fields.len()).min(self.config.max_streams);
        let budget = estimate_budget(records.len(), fields.len(), self.config.max_samples, prospective_stream_count, &self.config);
        if budget > max_budget(&self.config) {
            let mut context = BTreeMap::new();
            context.insert("estimated_budget".to_string(), budget.to_string());
            context.insert("max_budget".to_string(), max_budget(&self.config).to_string());
            let error = failure("BUDGET_EXCEEDED", "request exceeds the configured budget", context);
            self.record_error(&error);
            return Err(error);
        }

        self.health.record_count = records.len();
        self.health.last_budget_estimate = budget;

        let mapped = map_to_signals(records, fields, &self.config)?;

        let mut final_result: Option<ProcessOk> = None;
        let mut any_rejected = false;
        for field_index in 0..fields.len() {
            let cleaned = preprocess(&mapped[field_index], &self.config)?;
            let orthogonalized = orthogonalize(&cleaned, &self.config)?;
            let previous = self.stream_states.get(&fields[field_index]);
            let stream_result = trisca(&orthogonalized, timestamp_ms, previous, &self.config)?;
            any_rejected |= stream_result.rejected;
            let publish_result = self.publish(&fields[field_index], stream_result.state.clone())?;
            any_rejected |= publish_result.rejected;
            final_result = Some(publish_result);
        }

        match final_result {
            Some(mut result) => {
                if any_rejected {
                    self.health.last_publish_rejected = true;
                    if self.health.last_rejected_reason.is_none() {
                        self.health.last_rejected_reason = Some("stream_rejected".to_string());
                    }
                    result.rejected = true;
                    result.health = self.health.clone();
                }
                Ok(result)
            }
            None => {
                self.health.last_publish_status = PublishStatus::Ok;
                self.health.last_publish_rejected = true;
                self.health.last_rejected_reason = Some("empty_processing_result".to_string());
                Ok(ok_result(zero_state(timestamp_ms), true, self.stream_states.len(), &self.health))
            }
        }
    }

    fn restore_state(
        &mut self,
        stream_id: &str,
        previous_stream: Option<State>,
        had_existing: bool,
        previous_global: Option<State>,
    ) {
        if had_existing {
            if let Some(state) = previous_stream {
                self.stream_states.insert(stream_id.to_string(), state);
            }
        } else {
            self.stream_states.remove(stream_id);
        }
        self.global_state = previous_global;
        self.health.stream_count = self.stream_states.len();
        self.health.last_pair_count = ((self.stream_states.len() * self.stream_states.len().saturating_sub(1)) / 2)
            .min(self.config.max_adjacency_pairs);
        self.health.last_output_timestamp = self.global_state.as_ref().map(|state| state.t).unwrap_or(0);
    }

    fn record_error(&mut self, error: &FailureModel) {
        self.health.last_publish_status = PublishStatus::Error;
        self.health.last_publish_rejected = true;
        self.health.last_rejected_reason = Some(error.reason.clone());
        self.health.last_error_code = Some(error.error_code.clone());
        self.health.stream_count = self.stream_states.len();
        self.health.subscriber_count = self.subscribers.len();
    }
}

pub fn create_system(config: SystemConfig) -> Result<ArkTriscaSystem, FailureModel> {
    ArkTriscaSystem::new(config)
}

pub fn run_deterministic_self_check(config: &SystemConfig) -> Result<SelfCheckOk, FailureModel> {
    validate_config(config)?;
    let orthogonalized = orthogonalize(&[1.0, 2.0, 3.0, 4.0], config)?;
    for value in &orthogonalized {
        if value.abs() > 1e-9 {
            return Err(failure("SELF_CHECK_ORTHOGONALIZE", "least-squares detrend should flatten a linear sequence", BTreeMap::new()));
        }
    }

    let previous = State { v: 0.8, e: 0.1, i: 0.1, c: 0.9, t: 10_000 };
    let decayed = trisca(&[0.25, 0.5, 0.75], 10_000, Some(&previous), config)?;
    if (decayed.state.v - previous.v).abs() > config.continuity_delta {
        return Err(failure("SELF_CHECK_DECAY", "identical timestamps must preserve the previous value", BTreeMap::new()));
    }

    let confidence_floor = LN2 * 0.5;
    let confident = trisca(&[0.01, 0.02], 11_000, None, config)?;
    if confident.state.c < confidence_floor {
        return Err(failure("SELF_CHECK_CONFIDENCE", "confidence floor must be applied as a floor", BTreeMap::new()));
    }

    let low_confidence = trisca(&[0.0, 10_000.0], 12_000, Some(&previous), config)?;
    if !low_confidence.rejected || (low_confidence.state.v - previous.v).abs() > config.epsilon {
        return Err(failure("SELF_CHECK_GATE", "low confidence output must preserve previous state", BTreeMap::new()));
    }

    let mut probe = ArkTriscaSystem {
        config: config.clone(),
        stream_states: BTreeMap::new(),
        subscribers: Vec::new(),
        health: HealthSnapshot::default(),
        global_state: None,
    };
    for index in 0..config.max_streams {
        let state = State { v: 0.5, e: 0.2, i: 0.1, c: 0.8, t: 20_000 };
        probe.publish(&format!("stream-{index}"), state)?;
    }
    let overflow = probe.publish(
        "stream-overflow",
        State { v: 0.5, e: 0.2, i: 0.1, c: 0.8, t: 20_000 },
    );
    match overflow {
        Err(error) if error.error_code == "STREAM_CAP_EXCEEDED" => Ok(SelfCheckOk {
            status: "ok".to_string(),
            checks: 5,
        }),
        Err(error) => Err(error),
        Ok(_) => Err(failure("SELF_CHECK_STREAM_CAP", "publish must reject newest streams at max_streams", BTreeMap::new())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn orthogonalize_flattens_linear_input() {
        let config = SystemConfig::default();
        let output = orthogonalize(&[1.0, 2.0, 3.0, 4.0], &config).expect("orthogonalize");
        assert!(output.iter().all(|value| value.abs() <= 1e-9));
    }

    #[test]
    fn trisca_empty_input_returns_zero_state() {
        let config = SystemConfig::default();
        let output = trisca(&[], 1_000, None, &config).expect("trisca");
        assert!(output.rejected);
        assert_eq!(output.state, zero_state(1_000));
    }

    #[test]
    fn publish_rejects_newest_stream_at_capacity() {
        let config = SystemConfig::default();
        let mut system = ArkTriscaSystem::new(config.clone()).expect("system");
        for index in 0..config.max_streams {
            let state = State { v: 0.5, e: 0.1, i: 0.1, c: 0.8, t: 1_000 };
            system.publish(&format!("stream-{index}"), state).expect("publish");
        }
        let overflow = system.publish(
            "overflow",
            State { v: 0.5, e: 0.1, i: 0.1, c: 0.8, t: 1_000 },
        );
        assert!(matches!(overflow, Err(FailureModel { error_code, .. }) if error_code == "STREAM_CAP_EXCEEDED"));
    }
}
