use std::fs::File;
use std::io::{BufRead,BufReader};

pub fn replay(){
    let f=File::open("ark.wal").unwrap();
    for l in BufReader::new(f).lines(){
        println!("{}",l.unwrap());
    }
}
