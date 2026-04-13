pub fn extract(text:&str)->Vec<f32>{
    text.split_whitespace().map(|w|w.len() as f32).collect()
}
