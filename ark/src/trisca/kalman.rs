use crate::types::LKS;

#[derive(Clone)]
pub struct Kalman {
    pub x: f32,
    pub p: f32,
}

impl Kalman {
    pub fn new() -> Self {
        Self { x: 0.0, p: 1.0 }
    }

    pub fn update(&mut self, measurement: f32) -> f32 {
        let q = 0.01;
        let r = 0.1;

        self.p += q;
        let k = self.p / (self.p + r);

        self.x += k * (measurement - self.x);
        self.p *= 1.0 - k;

        self.x
    }
}
