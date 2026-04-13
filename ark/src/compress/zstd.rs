use zstd::stream::{encode_all, decode_all};

pub fn compress(data: &[u8]) -> Vec<u8> {
    encode_all(data, 22).unwrap()
}

pub fn decompress(data: &[u8]) -> Vec<u8> {
    decode_all(data).unwrap()
}
