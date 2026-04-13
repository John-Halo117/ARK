pub fn extract(frames:&[Vec<u8>])->Vec<f32>{
    frames.iter().map(|f|{
        let b = f.iter().map(|&p|p as f32).sum::<f32>()/f.len() as f32;
        b*(f.len() as f32).sqrt()
    }).collect()
}
