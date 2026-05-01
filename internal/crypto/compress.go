package crypto

import (
	"bytes"
	"io"

	"github.com/klauspost/compress/zstd"
	"github.com/pierrec/lz4/v4"
)

func ZstdCompress(data []byte) ([]byte, error) {
	var b bytes.Buffer
	enc, err := zstd.NewWriter(&b)
	if err != nil {
		return nil, err
	}
	if _, err := enc.Write(data); err != nil {
		enc.Close()
		return nil, err
	}
	if err := enc.Close(); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

func ZstdDecompress(data []byte) ([]byte, error) {
	dec, err := zstd.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	defer dec.Close()
	return dec.DecodeAll(data, nil)
}

func LZ4Compress(data []byte) ([]byte, error) {
	var b bytes.Buffer
	w := lz4.NewWriter(&b)
	if _, err := w.Write(data); err != nil {
		w.Close()
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

func LZ4Decompress(data []byte) ([]byte, error) {
	r := lz4.NewReader(bytes.NewReader(data))
	return io.ReadAll(r)
}
