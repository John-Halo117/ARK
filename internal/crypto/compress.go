package crypto

import (
	"bytes"

	"github.com/klauspost/compress/zstd"
	"github.com/pierrec/lz4/v4"
)

func ZstdCompress(data []byte) ([]byte, error) {
	var b bytes.Buffer
	enc, _ := zstd.NewWriter(&b)
	enc.Write(data)
	enc.Close()
	return b.Bytes(), nil
}

func ZstdDecompress(data []byte) ([]byte, error) {
	dec, _ := zstd.NewReader(bytes.NewReader(data))
	defer dec.Close()
	return dec.ReadAll(nil)
}

func LZ4Compress(data []byte) ([]byte, error) {
	var b bytes.Buffer
	w := lz4.NewWriter(&b)
	w.Write(data)
	w.Close()
	return b.Bytes(), nil
}

func LZ4Decompress(data []byte) ([]byte, error) {
	r := lz4.NewReader(bytes.NewReader(data))
	return io.ReadAll(r)
}
