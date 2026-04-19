/// Kalman filter for DSS smoothing.
///
/// Tuning:
///   q (process noise)     — higher = trust measurements more, lower = smoother output
///   r (measurement noise) — higher = smoother output, lower = more responsive
///
/// Defaults (q=0.01, r=0.1) suit moderate-frequency network/sensor telemetry.
/// Audio or high-frequency signals may need q≈0.001, r≈0.05.
#[derive(Clone)]
pub struct Kalman {
    pub x: f32,
    pub p: f32,
    q: f32,
    r: f32,
}

impl Kalman {
    pub fn new() -> Self {
        Self { x: 0.0, p: 1.0, q: 0.01, r: 0.1 }
    }

    /// Create a Kalman filter with custom noise parameters.
    pub fn with_params(q: f32, r: f32) -> Self {
        Self { x: 0.0, p: 1.0, q, r }
    }

    pub fn update(&mut self, measurement: f32) -> f32 {
        self.p += self.q;
        let k = self.p / (self.p + self.r);

        self.x += k * (measurement - self.x);
        self.p *= 1.0 - k;

        self.x
    }
}

impl Default for Kalman {
    fn default() -> Self {
        Self::new()
    }
}
