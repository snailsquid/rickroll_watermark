package main

import (
	"encoding/binary"
	"image/color"
	"io"
	"log"
	"os"
	"os/exec"
)

// BitWriter handles packing arbitrary bit widths sequentially into standard bytes
type BitWriter struct {
	bytes   []byte
	current byte
	numBits uint8
}

func (bw *BitWriter) WriteBits(value uint64, count uint8) {
	for i := int(count) - 1; i >= 0; i-- {
		bit := byte((value >> i) & 1)
		bw.current = (bw.current << 1) | bit
		bw.numBits++
		if bw.numBits == 8 {
			bw.bytes = append(bw.bytes, bw.current)
			bw.current = 0
			bw.numBits = 0
		}
	}
}

func (bw *BitWriter) Flush() {
	if bw.numBits > 0 {
		bw.current <<= (8 - bw.numBits)
		bw.bytes = append(bw.bytes, bw.current)
		bw.current = 0
		bw.numBits = 0
	}
}

// 16-color global palette for maximum structural density
var globalPalette = []color.RGBA{
	{0, 0, 0, 255}, {255, 255, 255, 255}, {128, 128, 128, 255}, {255, 0, 0, 255},
	{0, 255, 0, 255}, {0, 0, 255, 255}, {255, 255, 0, 255}, {255, 0, 255, 255},
	{0, 255, 255, 255}, {128, 0, 0, 255}, {0, 128, 0, 255}, {0, 0, 128, 255},
	{128, 128, 0, 255}, {128, 0, 128, 255}, {0, 128, 128, 255}, {64, 64, 64, 255},
}

func getPaletteIndex(r, g, b int) uint64 {
	bestIndex := 0
	minDist := 10000000
	for i, p := range globalPalette {
		dr := r - int(p.R)
		dg := g - int(p.G)
		db := b - int(p.B)
		dist := dr*dr + dg*dg + db*db
		if dist < minDist {
			minDist = dist
			bestIndex = i
		}
	}
	return uint64(bestIndex)
}

func main() {
	inputFile := "input.mp4"
	targetWidth := 128
	targetHeight := 128

	// Trigger FFmpeg to decode the MP4 on the fly and pipe raw RGB24 frames to stdout
	cmd := exec.Command("ffmpeg",
		"-i", inputFile,
		"-vf", "scale=128:128", // Rescale video down to 128x128
		"-f", "rawvideo",
		"-pix_fmt", "rgb24",
		"-",
	)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		log.Fatalf("Failed to create stdout pipe for FFmpeg: %v", err)
	}

	if err := cmd.Start(); err != nil {
		log.Fatalf("Failed to start FFmpeg process: %v. Is FFmpeg installed?", err)
	}

	bw := &BitWriter{}

	// Write basic global properties (Width, Height)
	bw.WriteBits(uint64(targetWidth), 8)
	bw.WriteBits(uint64(targetHeight), 8)

	// Placeholder slot for frame count (will overwrite this later once processing completes)
	frameCountOffset := len(bw.bytes)
	bw.bytes = append(bw.bytes, 0, 0) // 16-bit space holder

	// Write Palette mapping info (48 bytes total)
	for _, p := range globalPalette {
		bw.WriteBits(uint64(p.R), 8)
		bw.WriteBits(uint64(p.G), 8)
		bw.WriteBits(uint64(p.B), 8)
	}

	frameSize := targetWidth * targetHeight * 3 // 3 bytes per pixel (RGB)
	buf := make([]byte, frameSize)
	prevPixelIndices := make([]uint64, targetWidth*targetHeight)
	frameCount := 0

	for {
		// Read one complete uncompressed video frame from the FFmpeg stream pipe
		_, err := io.ReadFull(stdout, buf)
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			break // Video processing finished
		}

		currentPixelIndices := make([]uint64, targetWidth*targetHeight)
		idx := 0
		for i := 0; i < len(buf); i += 3 {
			currentPixelIndices[idx] = getPaletteIndex(int(buf[i]), int(buf[i+1]), int(buf[i+2]))
			idx++
		}

		if frameCount == 0 {
			// Frame 0 (I-Frame): Write all core pixel color identities sequentially
			for _, val := range currentPixelIndices {
				bw.WriteBits(val, 4)
			}
		} else {
			// Frames 1+ (P-Frames): Detect pixel changes vs previous state
			type DeltaPixel struct {
				index uint64
				color uint64
			}
			var deltas []DeltaPixel

			for i := 0; i < len(currentPixelIndices); i++ {
				if currentPixelIndices[i] != prevPixelIndices[i] {
					deltas = append(deltas, DeltaPixel{index: uint64(i), color: currentPixelIndices[i]})
				}
			}

			// Save block modifications: [16-bit Count][Repeated: 16-bit Position + 4-bit Color]
			bw.WriteBits(uint64(len(deltas)), 16)
			for _, d := range deltas {
				bw.WriteBits(d.index, 16)
				bw.WriteBits(d.color, 4)
			}
		}

		copy(prevPixelIndices, currentPixelIndices)
		frameCount++
	}

	_ = cmd.Wait() // Clean up background thread
	bw.Flush()

	// Update the frame count placeholder in our byte headers using Big Endian formatting
	binary.BigEndian.PutUint16(bw.bytes[frameCountOffset:frameCountOffset+2], uint16(frameCount))

	// Save the clean bitstream output to disk
	err = os.WriteFile("optimized_video.bin", bw.bytes, 0644)
	if err != nil {
		log.Fatalf("Failed saving bitstream target output file: %v", err)
	}

	log.Printf("Success! Processed %d frames from MP4 -> Saved %d bytes to optimized_video.bin", frameCount, len(bw.bytes))
}
