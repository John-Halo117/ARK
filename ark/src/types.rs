use serde::{Serialize, Deserialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LKS {
    pub qts: f32,
    pub dsi: f32,
    pub dss: f32,
    pub dss_kalman: f32,
    pub phase: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Event {
    pub ts: u64,
    pub source: String,
    pub lks: LKS,
    pub decision: String,
}
