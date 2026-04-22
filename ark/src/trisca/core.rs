use crate::types::LKS;
use super::system::{orthogonalize, preprocess, trisca, State, SystemConfig};

pub fn compute(data: &[f32]) -> LKS {
    compute_v41(data)
}

pub fn compute_legacy(data: &[f32]) -> LKS {
    if data.is_empty() {
        return LKS { qts:0.0,dsi:0.0,dss:0.0,dss_kalman:0.0,phase:"invalid".into() };
    }

    let mut sorted = data.to_vec();
    sorted.sort_by(|a,b| a.partial_cmp(b).unwrap());

    let n = sorted.len();
    let qs = n.div_ceil(5);

    let mean = |s:usize,c:usize| {
        let e = (s+c).min(n);
        let sl = &sorted[s..e];
        if sl.is_empty() {0.0} else {sl.iter().sum::<f32>()/sl.len() as f32}
    };

    let q1 = mean(0,qs);
    let q2 = mean(qs,qs);
    let q3 = mean(qs*2,qs);
    let q4 = mean(qs*3,qs);
    let q5 = mean(qs*4,n);

    let qts = (q1+q3+q5)/3.0;

    let total: f32 = data.iter().sum();
    let p: Vec<f32> = data.iter().map(|&x| if total>0.0 {x/total} else {0.0}).collect();

    let h = if n>1 {
        -p.iter().filter(|&&pi|pi>0.0).map(|&pi|pi*pi.ln()).sum::<f32>()/(n as f32).ln()
    } else {0.0};

    let mut sum_term=0.0;
    for (i,&v) in sorted.iter().enumerate() {
        sum_term += (n-i) as f32 * v;
    }
    let gini = if total>0.0 {
        ((n as f32 +1.0) -2.0*sum_term/total)/n as f32
    } else {0.0};

    let dsi = h*(1.0-gini.clamp(0.0,1.0));

    let b = (q2+q3+q4)/3.0;
    let eps = 1e-10;
    let s1 = q5/(b+eps);
    let s2 = b/(q1+eps);
    let s3 = (q5-q1)/(b+eps);
    let dss = (s1+s2+s3)/3.0;

    let phase = if dss>1.0 {"critical"} else if dss>0.7 {"unstable"} else if dss>0.4 {"drift"} else {"stable"};

    LKS {
        qts,
        dsi,
        dss,
        dss_kalman: dss*0.92,
        phase: phase.into(),
    }
}

pub fn compute_v41(data: &[f32]) -> LKS {
    let config = SystemConfig::default();
    let samples: Vec<f64> = data.iter().map(|value| f64::from(*value)).collect();

    let cleaned = match preprocess(&samples, &config) {
        Ok(values) => values,
        Err(_) => return invalid_lks(),
    };
    let orthogonalized = match orthogonalize(&cleaned, &config) {
        Ok(values) => values,
        Err(_) => return invalid_lks(),
    };
    let processed = match trisca(&orthogonalized, 0, None, &config) {
        Ok(result) => result,
        Err(_) => return invalid_lks(),
    };

    state_to_lks(&processed.state, processed.rejected)
}

fn invalid_lks() -> LKS {
    LKS {
        qts: 0.0,
        dsi: 0.0,
        dss: 0.0,
        dss_kalman: 0.0,
        phase: "invalid".into(),
    }
}

fn state_to_lks(state: &State, rejected: bool) -> LKS {
    let phase = if rejected {
        "fragile"
    } else if state.c < 0.45 {
        "unstable"
    } else if state.v < 0.25 {
        "drift"
    } else {
        "stable"
    };

    LKS {
        qts: state.v as f32,
        dsi: state.e as f32,
        dss: state.c as f32,
        dss_kalman: state.c as f32,
        phase: phase.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::{compute, compute_v41};

    #[test]
    fn compute_defaults_to_v41() {
        let data = [0.1_f32, 0.5_f32, 0.9_f32];
        let default_output = compute(&data);
        let v41_output = compute_v41(&data);
        assert_eq!(default_output.qts, v41_output.qts);
        assert_eq!(default_output.dsi, v41_output.dsi);
        assert_eq!(default_output.dss, v41_output.dss);
        assert_eq!(default_output.dss_kalman, v41_output.dss_kalman);
        assert_eq!(default_output.phase, v41_output.phase);
    }
}
