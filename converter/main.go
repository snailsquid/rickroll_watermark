package main

import (
	"bytes"
	"encoding/binary"
	"flag"
	"fmt"
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

// BitReader for decode
type BitReader struct {
	data    []byte
	byteIdx int
	bitIdx  int
}

func NewBitReader(data []byte) *BitReader {
	return &BitReader{data: data}
}

func (br *BitReader) ReadBit() (int, error) {
	if br.byteIdx >= len(br.data) {
		return 0, io.EOF
	}
	shift := 7 - br.bitIdx
	bit := int((br.data[br.byteIdx] >> shift) & 1)
	br.bitIdx++
	if br.bitIdx == 8 {
		br.bitIdx = 0
		br.byteIdx++
	}
	return bit, nil
}

func (br *BitReader) ReadBits(count int) (uint64, error) {
	var val uint64
	for i := 0; i < count; i++ {
		bit, err := br.ReadBit()
		if err != nil {
			return 0, err
		}
		val = (val << 1) | uint64(bit)
	}
	return val, nil
}

// Color bit depths: Y 6-bit (64 levels), Cb/Cr 5-bit (32 levels)
const (
	yBits       = 6
	cbBits      = 5
	crBits      = 5
	yPosBits    = 20 // position bits for Y plane (up to ~1M pixels)
	chromaPosBits = 18 // position bits for Cb/Cr planes (up to ~262K positions)
)

func main() {
	mode := flag.String("mode", "encode", "encode or decode")
	inputFile := flag.String("i", "input.mp4", "input file")
	outputFile := flag.String("o", "optimized_video.bin", "output file")
	targetWidth := flag.Int("w", 320, "target width")
	targetHeight := flag.Int("h", 240, "target height")
	maxBytes := flag.Int("max-bytes", 0, "max output file size (0 = unlimited)")
	flag.Parse()

	switch *mode {
	case "encode":
		encode(*inputFile, *outputFile, *targetWidth, *targetHeight, *maxBytes)
	case "decode":
		decode(*inputFile, *outputFile, *targetWidth, *targetHeight)
	default:
		log.Fatalf("Unknown mode: %s. Use 'encode' or 'decode'.\n", *mode)
	}
}

func encode(inputFile, outputFile string, targetWidth, targetHeight int, maxBytes int) {
	cmd := exec.Command("ffmpeg",
		"-i", inputFile,
		"-vf", fmt.Sprintf("scale=%d:%d:flags=lanczos", targetWidth, targetHeight),
		"-f", "rawvideo",
		"-pix_fmt", "yuv420p",
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

	// Header: width (16), height (16), frame count placeholder (16)
	bw.WriteBits(uint64(targetWidth), 16)
	bw.WriteBits(uint64(targetHeight), 16)

	frameCountOffset := len(bw.bytes)
	bw.bytes = append(bw.bytes, 0, 0)

	yPlaneSize := targetWidth * targetHeight
	cbPlaneW := (targetWidth + 1) / 2
	cbPlaneH := (targetHeight + 1) / 2
	cbPlaneSize := cbPlaneW * cbPlaneH
	crPlaneSize := cbPlaneSize
	frameSize := yPlaneSize + cbPlaneSize + crPlaneSize

	buf := make([]byte, frameSize)
	frameCount := 0

	for {
		_, err := io.ReadFull(stdout, buf)
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			break
		}
		if err != nil {
			log.Printf("Error reading frame: %v", err)
			break
		}

		if maxBytes > 0 && len(bw.bytes)+yPlaneSize+cbPlaneSize+crPlaneSize+100 > maxBytes {
			log.Printf("Frame %d would exceed limit, stopping", frameCount)
			break
		}

		yPlane := buf[:yPlaneSize]
		cbPlane := buf[yPlaneSize : yPlaneSize+cbPlaneSize]
		crPlane := buf[yPlaneSize+cbPlaneSize : yPlaneSize+cbPlaneSize+crPlaneSize]

		// I-frame only: store Y (6-bit), Cb (5-bit), Cr (5-bit)
		// Using I-frames for all frames avoids position overhead of deltas,
		// which is actually more efficient for high-motion content.
		for _, y := range yPlane {
			bw.WriteBits(uint64(y>>2), yBits)
		}
		for _, cb := range cbPlane {
			bw.WriteBits(uint64(cb>>3), cbBits)
		}
		for _, cr := range crPlane {
			bw.WriteBits(uint64(cr>>3), crBits)
		}

		frameCount++
	}

	_ = cmd.Process.Kill()
	_ = cmd.Wait()
	bw.Flush()

	binary.BigEndian.PutUint16(bw.bytes[frameCountOffset:frameCountOffset+2], uint16(frameCount))

	err = os.WriteFile(outputFile, bw.bytes, 0644)
	if err != nil {
		log.Fatalf("Failed saving bitstream: %v", err)
	}
	log.Printf("Encoded %d frames (%dx%d) -> %d bytes to %s", frameCount, targetWidth, targetHeight, len(bw.bytes), outputFile)
}

func decode(inputFile, outputFile string, targetWidth, targetHeight int) {
	data, err := os.ReadFile(inputFile)
	if err != nil {
		log.Fatalf("Failed to read bitstream: %v", err)
	}

	br := NewBitReader(data)

	// Read header
	w, err := br.ReadBits(16)
	if err != nil {
		log.Fatalf("Failed to read width: %v", err)
	}
	h, err := br.ReadBits(16)
	if err != nil {
		log.Fatalf("Failed to read height: %v", err)
	}
	frameCount, err := br.ReadBits(16)
	if err != nil {
		log.Fatalf("Failed to read frame count: %v", err)
	}

	log.Printf("Bitstream: %dx%d, %d frames", w, h, frameCount)

	yPlaneSize := int(w) * int(h)
	cbPlaneW := (int(w) + 1) / 2
	cbPlaneH := (int(h) + 1) / 2
	cbPlaneSize := cbPlaneW * cbPlaneH
	crPlaneSize := cbPlaneSize

	// Start FFmpeg to encode video
	cmd := exec.Command("ffmpeg",
		"-y",
		"-f", "rawvideo",
		"-pix_fmt", "yuv420p",
		"-s", fmt.Sprintf("%dx%d", w, h),
		"-r", "10",
		"-an",
		"-i", "-",
		"-c:v", "libopenh264",
		"-pix_fmt", "yuv420p",
		outputFile,
	)

	var stderrBuf bytes.Buffer
	cmd.Stderr = &stderrBuf

	stdin, err := cmd.StdinPipe()
	if err != nil {
		log.Fatalf("Failed to create stdin pipe: %v", err)
	}

	if err := cmd.Start(); err != nil {
		log.Fatalf("Failed to start FFmpeg: %v", err)
	}

	// Allocate per-plane buffers
	yPlane := make([]byte, yPlaneSize)
	cbPlane := make([]byte, cbPlaneSize)
	crPlane := make([]byte, crPlaneSize)

	// Frame buffer: Y + Cb + Cr interleaved for FFmpeg
	frameBuf := make([]byte, yPlaneSize+cbPlaneSize+crPlaneSize)

	for f := 0; f < int(frameCount); f++ {
		// I-frame only: read Y (6-bit), Cb (5-bit), Cr (5-bit)
		for i := 0; i < yPlaneSize; i++ {
			val, err := br.ReadBits(yBits)
			if err != nil {
				log.Fatalf("Failed to read Y pixel %d frame %d: %v", i, f, err)
			}
			yPlane[i] = uint8(val<<2) | uint8(val>>4)
		}
		for i := 0; i < cbPlaneSize; i++ {
			val, err := br.ReadBits(cbBits)
			if err != nil {
				log.Fatalf("Failed to read Cb pixel %d frame %d: %v", i, f, err)
			}
			cbPlane[i] = uint8(val<<3) | uint8(val>>2)
		}
		for i := 0; i < crPlaneSize; i++ {
			val, err := br.ReadBits(crBits)
			if err != nil {
				log.Fatalf("Failed to read Cr pixel %d frame %d: %v", i, f, err)
			}
			crPlane[i] = uint8(val<<3) | uint8(val>>2)
		}

		// Pack frame: Y plane (w*h bytes), Cb plane (w*h/4 bytes), Cr plane (w*h/4 bytes)
		copy(frameBuf, yPlane)
		copy(frameBuf[yPlaneSize:], cbPlane)
		copy(frameBuf[yPlaneSize+cbPlaneSize:], crPlane)

		if _, err := stdin.Write(frameBuf); err != nil {
			log.Fatalf("Failed to write frame %d: %v", f, err)
		}
	}

	stdin.Close()
	if err := cmd.Wait(); err != nil {
		log.Printf("FFmpeg stderr:\n%s\n", stderrBuf.String())
		log.Fatalf("FFmpeg encoding failed: %v", err)
	}

	log.Printf("Decoded %d frames (%dx%d) -> %s", frameCount, w, h, outputFile)
}
