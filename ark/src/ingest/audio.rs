pub fn extract(samples:&[f32])->Vec<f32>{
    samples.chunks(512).map(|c|{
        c.iter().map(|&x|x*x).sum::<f32>().sqrt()
    }).collect()
}
