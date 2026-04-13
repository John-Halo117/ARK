use ark::{
    otel,
    control::plane::process,
    ingest::{audio,video,text,image,net},
};

fn main(){
    otel::init();

    let audio_data = audio::extract(&vec![0.1,0.5,0.9,1.2]);
    process("audio",audio_data);

    let text_data = text::extract("ARK unified system processing multimodal streams");
    process("text",text_data);

    let net_data = net::extract(1200.0);
    process("network",net_data);

    let img_data = image::extract(&vec![0.2,0.4,0.6]);
    process("image",img_data);

    let vid_data = video::extract(&vec![vec![10,20,30],vec![40,50,60]]);
    process("video",vid_data);
}
