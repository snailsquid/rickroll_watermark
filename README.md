# rrwm — JPEG DCT Watermarking Tool

Embed and extract arbitrary binary payloads (video, files) inside JPEG images via LSB
manipulation of quantized DCT coefficients. Uses all three YCbCr channels with triple-byte
redundancy for robust extraction.

50MP JPEG capacity: **~1.7 MB usable payload** (~33 frames of 256×192 video at 10 fps).

> **Step-by-step documentation with visualisations:**
> [docs/watermarking.md](docs/watermarking.md)

## Architecture

Two binaries + a convenience script:

**`rrwm` (main.go)** — JPEG DCT embedder/extractor
- Decodes JPEG → YCbCr → 8×8 blocks → DCT → quantize → zigzag
- Embeds payload bits in LSB of mid-frequency DCT coefficients (zigzag indices 10–44)
- Operates on Y, Cb, and Cr channels (all three)
- Payload format: [4-byte big-endian length | byte₀×3 | byte₁×3 | ...]
- Triple redundancy enables majority-vote recovery on extraction
- Reconstructs JPEG with configurable quality (default 90)

**`converter` (converter/main.go)** — YCbCr video bitstream encoder/decoder
- Encodes video → raw YUV420p frames via FFmpeg → compact bitstream
- I-frame only encoding: Y stored at 6-bit precision, Cb/Cr at 5-bit
- 4:2:0 chroma subsampling for efficient chrominance representation
- No P-frame deltas — I-frame only is more efficient for high-motion content
- Header: width (16-bit), height (16-bit), frame count (16-bit)

**`run.sh`** — wrapper for the full pipeline (`input/original.jpeg`, `output/`, etc.)

## Requirements

- Go 1.26+
- FFmpeg (with libopenh264 for decode)
- `go-fourier` dependency (DCT/IDCT)

## Build

```bash
# Build the watermark tool
go build -o rrwm .

# Build the video converter
go build -o converter ./converter
```

## Usage

### Insert watermark

```bash
./rrwm insert <input_jpeg> <output_jpeg> [watermark_bin]
```

- `input_jpeg` — source JPEG image (any size)
- `output_jpeg` — watermarked JPEG output
- `watermark_bin` — optional, defaults to `optimized_video.bin`

With quality flag:

```bash
./rrwm -quality 95 insert input.jpeg output.jpeg payload.bin
```

Quality range: 1–100 (default 90). Higher = less visible distortion, lower = more data survives re-encoding.

### Extract watermark

```bash
./rrwm extract <watermarked_jpeg> <output_bin>
```

- `watermarked_jpeg` — JPEG with embedded payload
- `output_bin` — extracted raw binary

The extractor reads all three channels, runs DCT+quantize, extracts LSBs from mid-frequency
coefficients, groups bits into bytes, applies majority voting on the triple-redundant payload,
and writes the recovered data.

### Video pipeline

**Encode video to compact bitstream:**

```bash
./converter -mode encode -i input.mp4 -o optimized_video.bin
```

Flags:
- `-w` — target width (default 320)
- `-h` — target height (default 240)
- `-max-bytes` — stop encoding if bitstream exceeds this size (0 = unlimited)

**Decode bitstream back to video:**

```bash
./converter -mode decode -i optimized_video.bin -o secret.mp4
```

### Full pipeline via run.sh

```bash
# Encode video → insert → extract → decode (one shot)
./run.sh -w 256 -h 192 full input.mp4

# Step by step
./run.sh encode input.mp4                     # → output/optimized_video.bin
./run.sh insert                                # → output/modified.jpeg
./run.sh extract                               # → output/secret.mp4

# With quality override
./run.sh -quality 85 extract
```

## Technical details

**Embedding process:**
1. Decode input JPEG → `*image.YCbCr`
2. Split Y, Cb, Cr planes into 8×8 blocks
3. Shift pixel values by −128 (center around 0)
4. Forward 2D DCT on each block
5. Quantize using standard JPEG luminance/chrominance tables (scaled by quality)
6. Zigzag reorder DCT coefficients
7. For each payload bit: embed as LSB of quantized coefficient at zigzag index 10–44
8. Process channels in order: Y → Cb → Cr
9. Inverse zigzag, dequantize, inverse DCT, unshift (+128), re-encode JPEG

**Extraction process:**
1. Decode watermarked JPEG
2. Same DCT + quantize pipeline
3. Read LSB from coefficients at zigzag indices 10–44 across all three channels
4. Assemble bits into bytes
5. Read 4-byte payload length header
6. Apply majority voting: each payload byte appears 3 times, pick the value appearing ≥ 2 times

**Capacity** depends on image dimensions and channel subsampling. At 4:2:0 subsampling
on a 50MP JPEG (6144×8192):
- Y: 786,432 blocks × 35 coefficients = 27,525,120 bits
- Cb: 196,608 blocks × 35 coefficients = 6,881,280 bits
- Cr: 196,608 blocks × 35 coefficients = 6,881,280 bits
- Total raw: ~5.16 MB
- After 4-byte header + 3× redundancy: **~1.72 MB usable**

## Documentation

For a complete step-by-step walkthrough with visualisations of every pipeline stage — DCT
basis functions, quantization in action, zigzag ordering, LSB embedding, before/after
comparisons, and capacity breakdown — see:

**[docs/watermarking.md](docs/watermarking.md)**

## Notes

- The quality flag during extraction must match the quality used during insertion.
- Mid-frequency coefficients (indices 10–44) are used because low frequencies carry
  visible image data and high frequencies are destroyed by quantization.
- Triple redundancy with majority voting handles single-bit errors from quantization
  round-trip (3× copies, majority vote recovers the correct bit).
- The payload is embedded across Y+Cb+Cr channels — this triples capacity at the cost
  of more visible chroma artifacts at low quality settings.
