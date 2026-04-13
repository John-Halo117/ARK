use crate::{
    trisca::core::compute,
    trisca::kalman::Kalman,
    policy::engine::decide,
    event::wal::append,
    delta::compute::{compute as delta_compute, Delta},
    storage::duck::DuckStore,
    types::{Event, LKS},
};

pub struct Engine {
    prev: Option<LKS>,
    kalman: Kalman,
    store: DuckStore,
}

impl Engine {
    pub fn new() -> Self {
        Self {
            prev: None,
            kalman: Kalman::new(),
            store: DuckStore::new("ark.db"),
        }
    }

    pub fn process(&mut self, source: &str, data: Vec<f32>) {
        let mut lks = compute(&data);

        // Kalman smoothing
        lks.dss_kalman = self.kalman.update(lks.dss);

        let ts = chrono::Utc::now().timestamp() as u64;

        let delta: Option<Delta> = if let Some(prev) = &self.prev {
            Some(delta_compute(prev, &lks))
        } else {
            None
        };

        let decision = decide(&lks);

        // Store
        self.store.insert_lks(ts, &lks);
        if let Some(d) = &delta {
            self.store.insert_delta(ts, d);
        }

        // WAL
        let e = Event {
            ts,
            source: source.into(),
            lks: lks.clone(),
            decision: decision.into(),
        };

        append(&e);

        self.prev = Some(lks);
    }
}
