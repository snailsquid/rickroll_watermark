#!/bin/bash
set -e

QUALITY=""
WIDTH="256"
HEIGHT="192"
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -quality)
      QUALITY="-quality $2"
      shift 2
      ;;
    -quality=*)
      QUALITY="-quality ${1#*=}"
      shift
      ;;
    -w|-width)
      WIDTH="$2"
      shift 2
      ;;
    -h|-height)
      HEIGHT="$2"
      shift 2
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

MODE="${POSITIONAL[0]:-insert}"

case "$MODE" in
  encode)
    INPUT="${POSITIONAL[1]:-converter/input.mp4}"
    OUTPUT="${POSITIONAL[2]:-output/optimized_video.bin}"
    echo "=== Encoding video to YCbCr bitstream ==="
    go run ./converter -mode encode -i "$INPUT" -o "$OUTPUT" -w "$WIDTH" -h "$HEIGHT"
    echo "Done: $OUTPUT ($(wc -c < "$OUTPUT") bytes)"
    ;;
  insert)
    VIDBIN="${POSITIONAL[1]:-output/optimized_video.bin}"
    echo "=== Embedding $VIDBIN ==="
    go run main.go $QUALITY insert input/original.jpeg output/modified.jpeg "$VIDBIN"
    echo "Done: output/modified.jpeg"
    ;;
  extract)
    echo "=== Extracting watermark ==="
    go run main.go $QUALITY extract output/modified.jpeg output/extracted.bin
    echo ""
    echo "=== Decoding video ==="
    go run ./converter -mode decode -i output/extracted.bin -o output/secret.mp4 -w "$WIDTH" -h "$HEIGHT"
    OUT="output/secret.mp4"
    DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT" 2>/dev/null || echo "?")
    echo "Done: $OUT (${DUR}s, $(wc -c < "$OUT") bytes, ${WIDTH}x${HEIGHT})"
    ;;
  full)
    INPUT="${POSITIONAL[1]:-converter/input.mp4}"
    echo "=== Full pipeline: encode → insert → extract → decode ==="
    go run ./converter -mode encode -i "$INPUT" -o output/optimized_video.bin -w "$WIDTH" -h "$HEIGHT"
    go run main.go $QUALITY insert input/original.jpeg output/modified.jpeg output/optimized_video.bin
    go run main.go $QUALITY extract output/modified.jpeg output/extracted.bin
    go run ./converter -mode decode -i output/extracted.bin -o output/secret.mp4 -w "$WIDTH" -h "$HEIGHT"
    echo ""
    OUT="output/secret.mp4"
    DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT" 2>/dev/null || echo "?")
    echo "=== Done ==="
    echo "  modified.jpeg: $(wc -c < output/modified.jpeg) bytes"
    echo "  extracted.bin: $(wc -c < output/extracted.bin) bytes"
    echo "  secret.mp4:    $(wc -c < output/secret.mp4) bytes (${DUR}s, ${WIDTH}x${HEIGHT})"
    ;;
  *)
    echo "Usage: $0 [-quality N] [-w width] [-h height] [encode|insert|extract|full]"
    echo ""
    echo "Commands:"
    echo "  encode [input.mp4] [output.bin]     Encode video to YCbCr bitstream"
    echo "  insert [video.bin]                   Embed bitstream into JPEG"
    echo "  extract                              Extract and decode video"
    echo "  full [input.mp4]                     Full pipeline (encode→insert→extract→decode)"
    echo ""
    echo "Options:"
    echo "  -quality N   JPEG quality (1-100, default 90)"
    echo "  -w W         Video width  (default 256)"
    echo "  -h H         Video height (default 192)"
    exit 1
    ;;
esac
