use ark::{
    otel,
    control::plane::Engine,
    ingest::{audio, text, net},
};

fn main() {
    otel::init();

    let mut engine = Engine::new();

    for i in 0..100 {
        let audio_data = audio::extract(&[0.1 * i as f32, 0.5, 0.9]);
        engine.process("audio", audio_data);

        let text_data = text::extract("ark system evolving state");
        engine.process("text", text_data);

        let net_data = net::extract((i * 50) as f32);
        engine.process("network", net_data);
    }

    println!("ARK v1.0 core + Δ + DuckDB + Kalman running");
}
