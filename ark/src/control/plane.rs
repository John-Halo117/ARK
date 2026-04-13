use crate::{
    trisca::core::compute,
    policy::engine::decide,
    event::wal::append,
    types::Event,
};

pub fn process(source:&str,data:Vec<f32>){
    let lks=compute(&data);
    let decision=decide(&lks);

    let e=Event{
        ts:chrono::Utc::now().timestamp() as u64,
        source:source.into(),
        lks,
        decision:decision.into(),
    };

    append(&e);
}
