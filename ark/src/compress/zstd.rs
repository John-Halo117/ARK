use std::io;
use zstd::stream::{encode_all, decode_all};

/// Compress data using zstd.
/// Level 3 is appropriate for real-time event streams (good ratio, low CPU).
/// Level 22 (previous) is meant for offline archival and is far too expensive.
pub fn compress(data: &[u8]) -> io::Result<Vec<u8>> {
    encode_all(data, 3)
}

pub fn decompress(data: &[u8]) -> io::Result<Vec<u8>> {
    decode_all(data)
}
