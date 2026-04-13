use crate::types::LKS;

#[derive(Clone, Debug)]
pub struct Delta {
    pub raw: f32,
    pub pct: f32,
    pub q: i8,
    pub vec: &'static str,
}

pub fn compute(prev: &LKS, curr: &LKS) -> Delta {
    let raw = curr.dss - prev.dss;
    let pct = if prev.dss != 0.0 { raw / prev.dss } else { 0.0 };

    let q = match raw {
        x if x > 0.15 => 2,
        x if x > 0.05 => 1,
        x if x < -0.15 => -2,
        x if x < -0.05 => -1,
        _ => 0,
    };

    let vec = match q {
        2 => "↑↑",
        1 => "↑",
        0 => "→",
        -1 => "↓",
        -2 => "↓↓",
        _ => "?",
    };

    Delta { raw, pct, q, vec }
}
