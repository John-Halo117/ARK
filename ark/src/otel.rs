use tracing_subscriber::{prelude::*, EnvFilter};

pub fn init() {
    tracing_subscriber::registry()
        .with(EnvFilter::from_default_env())
        .init();
}
