use crate::types::Event;
use std::fs::OpenOptions;
use std::io::Write;

pub fn append(e:&Event){
    let mut f=OpenOptions::new().create(true).append(true).open("ark.wal").unwrap();
    let _=writeln!(f,"{}",serde_json::to_string(e).unwrap());
}
