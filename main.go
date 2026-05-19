package main

import (
	"bytes"
	"flag"
	"fmt"
	"image"
	"image/jpeg"
	"io"
	"log"
	"math"
	"os"
	"runtime/debug"

	go_fourier "github.com/ardabasaran/go-fourier"
)

const blockSize = 8

type Config struct {
	Mode               string
	OriginalImagePath string
	ModifiedImagePath string
	WatermarkPath     string
	Quality           int
}

func IsValidFile(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

func InitializeApp() Config {
	// Define flags
	quality := flag.Int("quality", 90, "JPEG quality (1-100)")

	// Parse all flags (they can appear anywhere before positional args)
	flag.Parse()

	args := flag.Args()
	if len(args) < 1 {
		log.Fatalf("Usage:\n  %s [flags] insert <input_image> <output_image> [watermark_path]\n  %s [flags] extract <watermarked_image> <output_bin>\nFlags:\n  -quality int   JPEG quality 1-100 (default 90)\n", os.Args[0], os.Args[0])
	}

	mode := args[0]
	posArgs := args[1:]

	switch mode {
	case "insert":
		if len(posArgs) < 2 {
			log.Fatalf("insert: need <input_image> <output_image> [watermark_path]\n")
		}
		originalPath := posArgs[0]
		outputPath := posArgs[1]
		watermarkPath := "optimized_video.bin"
		if len(posArgs) >= 3 {
			watermarkPath = posArgs[2]
		}
		if !IsValidFile(originalPath) {
			log.Fatalf("%v is not a valid file\n", originalPath)
		}
		if !IsValidFile(watermarkPath) {
			log.Fatalf("%v is not a valid file\n", watermarkPath)
		}
		return Config{Mode: mode, OriginalImagePath: originalPath, ModifiedImagePath: outputPath, WatermarkPath: watermarkPath, Quality: *quality}
	case "extract":
		if len(posArgs) < 2 {
			log.Fatalf("extract: need <watermarked_image> <output_bin>\n")
		}
		inputPath := posArgs[0]
		outputPath := posArgs[1]
		if !IsValidFile(inputPath) {
			log.Fatalf("%v is not a valid file\n", inputPath)
		}
		return Config{Mode: mode, OriginalImagePath: inputPath, WatermarkPath: outputPath, Quality: *quality}
	default:
		log.Fatalf("Unknown mode: %s. Use 'insert' or 'extract'.\n", mode)
	}
	return Config{}
}

var luminanceQTable = [64]int{
	16, 11, 10, 16, 24, 40, 51, 61,
	12, 12, 14, 19, 26, 58, 60, 55,
	14, 13, 16, 24, 40, 57, 69, 56,
	14, 17, 22, 29, 51, 87, 80, 62,
	18, 22, 37, 56, 68, 109, 103, 77,
	24, 35, 55, 64, 81, 104, 113, 92,
	49, 64, 78, 87, 103, 121, 120, 101,
	72, 92, 95, 98, 112, 100, 103, 99,
}

var chrominanceQTable = [64]int{
	17, 18, 24, 47, 99, 99, 99, 99,
	18, 21, 26, 66, 99, 99, 99, 99,
	24, 26, 56, 99, 99, 99, 99, 99,
	47, 66, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
	99, 99, 99, 99, 99, 99, 99, 99,
}

func scaleQTable(base [64]int, quality int) [64]int {
	var scale int
	if quality <= 0 {
		quality = 1
	}
	if quality >= 100 {
		quality = 100
	}
	if quality < 50 {
		scale = 5000 / quality
	} else {
		scale = 200 - quality*2
	}
	var out [64]int
	for i, v := range base {
		s := (v*scale + 50) / 100
		if s < 1 {
			s = 1
		}
		if s > 255 {
			s = 255
		}
		out[i] = s
	}
	return out
}

func main() {
	Start()
}

func Start() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Printf("Recovered from: %v\n", r)
			debug.PrintStack()
		}
	}()

	cfg := InitializeApp()
	switch cfg.Mode {
	case "insert":
		insertWatermark(cfg)
	case "extract":
		extractWatermark(cfg)
	}
}

// ========================
// INSERT: embed watermark
// ========================

func insertWatermark(cfg Config) {
	rawImage := GetImage(ReadFile(cfg.OriginalImagePath))
	ycbcr := ImageToYCbCr(rawImage)
	img := NewImage(ycbcr)

	quality := float64(cfg.Quality)
	if quality < 1 {
		quality = 1
	}
	if quality > 100 {
		quality = 100
	}
	fmt.Printf("JPEG quality: %.0f\n", quality)

	// Process all three channels
	dctsY := BlocksToDCT(img.Y)
	dctsCb := BlocksToDCT(img.Cb)
	dctsCr := BlocksToDCT(img.Cr)

	// Quantize (Y -> luminance, Cb/Cr -> chrominance)
	for _, dct := range *dctsY {
		dct.Quantize(quality, true)
	}
	for _, dct := range *dctsCb {
		dct.Quantize(quality, false)
	}
	for _, dct := range *dctsCr {
		dct.Quantize(quality, false)
	}

	// Zigzag
	zzY := DCTsToZigZags(dctsY)
	zzCb := DCTsToZigZags(dctsCb)
	zzCr := DCTsToZigZags(dctsCr)

	// Insert watermark with 4-byte length prefix + triple redundancy
	payload := ReadFile(cfg.WatermarkPath)
	triplePayload := make([]byte, 4+3*len(payload))
	triplePayload[0] = byte(len(payload) >> 24)
	triplePayload[1] = byte(len(payload) >> 16)
	triplePayload[2] = byte(len(payload) >> 8)
	triplePayload[3] = byte(len(payload))
	// Store each byte 3 times for majority voting
	copy(triplePayload[4:4+len(payload)], payload)
	copy(triplePayload[4+len(payload):4+2*len(payload)], payload)
	copy(triplePayload[4+2*len(payload):4+3*len(payload)], payload)
	fmt.Printf("Watermark payload (3x redundancy): %d bytes (%d original x3 + 4 header)\n",
		len(triplePayload), len(payload))

	reader := NewBitReader(triplePayload)
	InsertBitsToZigZags(zzY, reader)
	InsertBitsToZigZags(zzCb, reader)
	InsertBitsToZigZags(zzCr, reader)

	// Inverse zigzag
	_ = ZigZagsToDCTs(zzY, dctsY)
	_ = ZigZagsToDCTs(zzCb, dctsCb)
	_ = ZigZagsToDCTs(zzCr, dctsCr)

	// Dequantize
	for _, dct := range *dctsY {
		dct.Dequantize(quality, true)
	}
	for _, dct := range *dctsCb {
		dct.Dequantize(quality, false)
	}
	for _, dct := range *dctsCr {
		dct.Dequantize(quality, false)
	}

	// Inverse DCT -> pixel blocks
	blocksY := DCTsToBlocks(dctsY, img.Y)
	blocksCb := DCTsToBlocks(dctsCb, img.Cb)
	blocksCr := DCTsToBlocks(dctsCr, img.Cr)

	bw, bh := img.BlockWidth, img.BlockHeight
	outputY := BlocksToPixels(blocksY, ycbcr.Bounds().Dx(), ycbcr.Bounds().Dy(), blockSize)
	outputCb := BlocksToPixels(blocksCb, bw, bh, blockSize)
	outputCr := BlocksToPixels(blocksCr, bw, bh, blockSize)

	outYCbCr := image.NewYCbCr(ycbcr.Bounds(), ycbcr.SubsampleRatio)
	copy(outYCbCr.Y, outputY)
	if len(outputCb) == len(outYCbCr.Cb) {
		copy(outYCbCr.Cb, outputCb)
	}
	if len(outputCr) == len(outYCbCr.Cr) {
		copy(outYCbCr.Cr, outputCr)
	}

	SaveJPEG(outYCbCr, cfg.ModifiedImagePath, cfg.Quality)
	fmt.Printf("Watermarked image saved to %s\n", cfg.ModifiedImagePath)
}

// ========================
// EXTRACT: recover watermark
// ========================

func extractWatermark(cfg Config) {
	rawImage := GetImage(ReadFile(cfg.OriginalImagePath))
	ycbcr := ImageToYCbCr(rawImage)

	// Extract bits from all channels
	quality := float64(cfg.Quality)
	if quality < 1 {
		quality = 1
	}
	if quality > 100 {
		quality = 100
	}
	extractedBytes := extractBitsAllChannels(ycbcr, quality, MIN_SAFE_DCT_FREQ_IDX, MAX_SAFE_DCT_FREQ_IDX)
	if len(extractedBytes) < 4 {
		log.Fatalf("Not enough data extracted (%d bytes)\n", len(extractedBytes))
	}

	payloadLen := int(extractedBytes[0])<<24 | int(extractedBytes[1])<<16 |
		int(extractedBytes[2])<<8 | int(extractedBytes[3])

	// With triple redundancy: expected size is 4 + 3*payloadLen
	expectedLen := 4 + 3*payloadLen
	if expectedLen > len(extractedBytes) {
		log.Fatalf("Watermark truncated: need %d bytes, have %d\n", expectedLen, len(extractedBytes))
	}

	// Triple majority voting: each byte appears 3 times,
	// recover by taking the value that appears at least twice
	actualPayload := make([]byte, payloadLen)
	for i := 0; i < payloadLen; i++ {
		a := extractedBytes[4+i]
		b := extractedBytes[4+payloadLen+i]
		c := extractedBytes[4+2*payloadLen+i]
		if a == b || a == c {
			actualPayload[i] = a
		} else {
			actualPayload[i] = b // b == c guaranteed if not a
		}
	}

	err := os.WriteFile(cfg.WatermarkPath, actualPayload, 0644)
	if err != nil {
		log.Fatalf("Failed to write extracted watermark: %v", err)
	}
	fmt.Printf("Extracted %d bytes to %s\n", len(actualPayload), cfg.WatermarkPath)
}

// ========================
// Quantization
// ========================

func (dct *DCT) Quantize(quality float64, isLuminance bool) {
	var base [64]int
	if isLuminance {
		base = luminanceQTable
	} else {
		base = chrominanceQTable
	}
	scaled := scaleQTable(base, int(quality))
	for i, row := range dct.at {
		for j := range row {
			q := float64(scaled[i*8+j])
			(*dct).at[i][j] = math.Round(dct.at[i][j] / q)
		}
	}
}

func (dct *DCT) Dequantize(quality float64, isLuminance bool) {
	var base [64]int
	if isLuminance {
		base = luminanceQTable
	} else {
		base = chrominanceQTable
	}
	scaled := scaleQTable(base, int(quality))
	for i, row := range dct.at {
		for j := range row {
			q := float64(scaled[i*8+j])
			(*dct).at[i][j] = dct.at[i][j] * q
		}
	}
}

// ========================
// LSB on quantized integers
// ========================

func SetLSBQuantized(val float64, bit int) float64 {
	intVal := int32(math.Round(val))
	if bit == 1 {
		intVal |= 1
	} else {
		intVal &^= 1
	}
	return float64(intVal)
}

func GetLSBInt(val float64) int {
	intVal := int32(math.Round(val))
	return int(intVal & 1)
}

// ========================
// Image I/O
// ========================

func ReadFile(path string) []byte {
	data, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	fmt.Printf("File read: %v\n", path)
	return data
}

func GetImage(data []byte) image.Image {
	img, err := jpeg.Decode(bytes.NewReader(data))
	if err != nil {
		panic(err)
	}
	fmt.Printf("bounds: %v\n", img.Bounds())
	return img
}

func ImageToYCbCr(input image.Image) *image.YCbCr {
	if img, ok := input.(*image.YCbCr); ok {
		return img
	}
	log.Fatalf("Failed to convert to YCbCr")
	return nil
}

func SaveJPEG(img image.Image, path string, quality int) {
	f, err := os.Create(path)
	if err != nil {
		panic(err)
	}
	defer f.Close()
	err = jpeg.Encode(f, img, &jpeg.Options{Quality: quality})
	if err != nil {
		panic(err)
	}
}

// ========================
// Block structures
// ========================

type Image struct {
	Y              *[]Block
	Cb             *[]Block
	Cr             *[]Block
	SubsampleRatio image.YCbCrSubsampleRatio
	BlockWidth     int
	BlockHeight    int
}

type Block struct {
	at    [blockSize * blockSize]uint8
	count int
}

type BlockShift struct {
	at    [blockSize * blockSize]int8
	count int
}

type DCT struct {
	at [][]float64
}

type ZigZag struct {
	at []*float64
}

func (b *Block) Append(pixel uint8) {
	b.at[b.count] = pixel
	b.count++
}

func (b *BlockShift) Append(pixel int8) {
	b.at[b.count] = pixel
	b.count++
}

func NewImage(input *image.YCbCr) *Image {
	bounds := input.Bounds()
	width := bounds.Dx()
	height := bounds.Dy()

	y := NewBlocks(input.Y, width, height)

	bw, bh := width, height
	switch input.SubsampleRatio {
	case image.YCbCrSubsampleRatio420:
		bw = (width + 1) / 2
		bh = (height + 1) / 2
	case image.YCbCrSubsampleRatio422:
		bw = (width + 1) / 2
	case image.YCbCrSubsampleRatio440:
		bh = (height + 1) / 2
	case image.YCbCrSubsampleRatio410:
		bw = (width + 3) / 4
	case image.YCbCrSubsampleRatio411:
		bw = (width + 3) / 4
	}

	cb := NewBlocks(input.Cb, bw, bh)
	cr := NewBlocks(input.Cr, bw, bh)

	return &Image{
		Y:              &y,
		Cb:            &cb,
		Cr:            &cr,
		SubsampleRatio: input.SubsampleRatio,
		BlockWidth:     bw,
		BlockHeight:    bh,
	}
}

func NewBlocks(pixels []uint8, width int, height int) []Block {
	blocks := make([]Block, len(pixels)/(blockSize*blockSize))
	for i, pixel := range pixels {
		n := getBlockIndex(i, width, blockSize)
		blocks[n].Append(pixel)
	}
	return blocks
}

func getBlockIndex(x, w, s int) int {
	blocksPerRow := w / s
	row := x / w
	col := x % w
	blockRow := row / s
	blockCol := col / s
	return (blockRow * blocksPerRow) + blockCol
}

// ========================
// Forward DCT pipeline
// ========================

func BlocksToDCT(blocks *[]Block) *[]*DCT {
	dataBuffer := make([]float64, 64)
	spine := make([][]float64, 8)
	for i := range spine {
		spine[i] = dataBuffer[i : (i+1)*blockSize]
	}

	var dcts []*DCT
	for i := range *blocks {
		shifted := (*blocks)[i].Shift()
		dcts = append(dcts, shifted.ToDCT(&dataBuffer, &spine))
	}
	return &dcts
}

func DCTsToZigZags(dcts *[]*DCT) *[]*ZigZag {
	var zz []*ZigZag
	for _, dct := range *dcts {
		zz = append(zz, dct.ToZigZag())
	}
	return &zz
}

func (block *Block) Shift() *BlockShift {
	var blockShift BlockShift
	for i := range (*block).at {
		(blockShift).at[i] = int8((*block).at[i] - 128)
	}
	return &blockShift
}

func (b *BlockShift) ToDCT(buffer *[]float64, spine *[][]float64) *DCT {
	for i := 0; i < blockSize; i++ {
		for j := 0; j < blockSize; j++ {
			(*buffer)[i*blockSize+j] = float64((*b).at[i*blockSize+j])
		}
	}
	result, err := go_fourier.DCT2D(*spine)
	if err != nil {
		panic(err)
	}
	return &DCT{at: result}
}

func (dct *DCT) ToZigZag() *ZigZag {
	return &ZigZag{at: ZigZagTraverse(dct.at)}
}

// ========================
// Inverse DCT pipeline
// ========================

func ZigZagsToDCTs(zigzags *[]*ZigZag, originalDCTs *[]*DCT) *[]*DCT {
	for idx, zz := range *zigzags {
		InverseZigZagTraverse((*originalDCTs)[idx].at, zz.at)
	}
	return originalDCTs
}

func InverseZigZagTraverse(matrix [][]float64, zigzag []*float64) {
	if len(matrix) == 0 || len(matrix[0]) == 0 {
		return
	}
	rows := len(matrix)
	cols := len(matrix[0])
	r, c := 0, 0
	movingUp := true
	for i := 0; i < len(zigzag); i++ {
		matrix[r][c] = *zigzag[i]
		if movingUp {
			if c == cols-1 {
				r++
				movingUp = false
			} else if r == 0 {
				c++
				movingUp = false
			} else {
				r--
				c++
			}
		} else {
			if r == rows-1 {
				c++
				movingUp = true
			} else if c == 0 {
				r++
				movingUp = true
			} else {
				r++
				c--
			}
		}
	}
}

func DCTsToBlocks(dcts *[]*DCT, originalBlocks *[]Block) *[]Block {
	blocks := make([]Block, len(*originalBlocks))
	for bi, dct := range *dcts {
		result, err := go_fourier.DCTInverse2D(dct.at)
		if err != nil {
			panic(err)
		}
		for row := 0; row < blockSize; row++ {
			for col := 0; col < blockSize; col++ {
				val := result[row][col] + 128
				if val < 0 {
					val = 0
				}
				if val > 255 {
					val = 255
				}
				blocks[bi].at[row*blockSize+col] = uint8(val)
			}
		}
	}
	return &blocks
}

func BlocksToPixels(blocks *[]Block, width, height, s int) []uint8 {
	pixels := make([]uint8, width*height)
	for i := range pixels {
		n := getBlockIndex(i, width, s)
		row := i / width
		col := i % width
		blockRow := row % s
		blockCol := col % s
		pixels[i] = (*blocks)[n].at[blockRow*s+blockCol]
	}
	return pixels
}

// ========================
// Bit insertion / extraction
// ========================

// Use mid-frequency AC coefficients for robustness
const MIN_SAFE_DCT_FREQ_IDX = 10
const MAX_SAFE_DCT_FREQ_IDX = 45

func extractBitsAllChannels(ycbcr *image.YCbCr, quality float64, minFreq, maxFreq int) []byte {
	bounds := ycbcr.Bounds()
	w := bounds.Dx()
	bw := (w + 1) / 2

	chPixels := [][]uint8{ycbcr.Y, ycbcr.Cb, ycbcr.Cr}
	chWidths := []int{w, bw, bw}
	isLum := []bool{true, false, false}

	var result []byte
	var cb byte
	bc := 0

	for ch := 0; ch < len(chPixels); ch++ {
		pixels := chPixels[ch]
		cw := chWidths[ch]
		lum := isLum[ch]
		nBlocks := len(pixels) / 64
		blocks := make([][64]float64, nBlocks)

		for i, p := range pixels {
			bi := getBlockIndex(i, cw, 8)
			row := i / cw
			col := i % cw
			br := (row % 8) * 8 + (col % 8)
			blocks[bi][br] = float64(int(p) - 128)
		}

		for _, blk := range blocks {
			mat := make([][]float64, 8)
			for r := 0; r < 8; r++ {
				mat[r] = blk[r*8 : (r+1)*8]
			}
			dct, err := go_fourier.DCT2D(mat)
			if err != nil {
				panic(err)
			}

			var base [64]int
			if lum {
				base = luminanceQTable
			} else {
				base = chrominanceQTable
			}
			scaled := scaleQTable(base, int(quality))
			for r := 0; r < 8; r++ {
				for c2 := 0; c2 < 8; c2++ {
					dct[r][c2] = math.Round(dct[r][c2] / float64(scaled[r*8+c2]))
				}
			}

			zz := ZigZagTraverse(dct)

			for idx := minFreq; idx < maxFreq && idx < 64; idx++ {
				bit := GetLSBInt(*zz[idx])
				cb = (cb << 1) | byte(bit)
				bc++
				if bc == 8 {
					result = append(result, cb)
					cb = 0
					bc = 0
				}
			}
		}
	}
	if bc > 0 {
		cb <<= (8 - bc)
		result = append(result, cb)
	}
	return result
}

func InsertBitsToZigZags(zigzags *[]*ZigZag, bitReader *BitReader) {
	for _, zz := range *zigzags {
		finished := zz.InsertBits(bitReader)
		if finished {
			return
		}
	}
}

func (zz *ZigZag) InsertBits(bitReader *BitReader) bool {
	for i := MIN_SAFE_DCT_FREQ_IDX; i < MAX_SAFE_DCT_FREQ_IDX; i++ {
		if zz.at[i] == nil {
			continue
		}
		toInsertBit, err := bitReader.NextBit()
		if err == io.EOF {
			fmt.Println("Finished embedding watermark.")
			return true
		}
		*zz.at[i] = SetLSBQuantized(*zz.at[i], toInsertBit)
	}
	return false
}

// ========================
// Zigzag traversal
// ========================

func ZigZagTraverse(matrix [][]float64) []*float64 {
	if len(matrix) == 0 || len(matrix[0]) == 0 {
		return nil
	}
	rows := len(matrix)
	cols := len(matrix[0])
	totalElements := rows * cols
	result := make([]*float64, totalElements)
	r, c := 0, 0
	movingUp := true
	for i := 0; i < totalElements; i++ {
		result[i] = &(matrix[r][c])
		if movingUp {
			if c == cols-1 {
				r++
				movingUp = false
			} else if r == 0 {
				c++
				movingUp = false
			} else {
				r--
				c++
			}
		} else {
			if r == rows-1 {
				c++
				movingUp = true
			} else if c == 0 {
				r++
				movingUp = true
			} else {
				r++
				c--
			}
		}
	}
	return result
}

// ========================
// Bit reader
// ========================

func LoadWatermark(imagePath string) *BitReader {
	payloadBytes, err := os.ReadFile(imagePath)
	if err != nil {
		log.Fatalf("Cannot load watermark: %v\n", err)
	}
	fmt.Printf("Watermark loaded: %d bytes\n", len(payloadBytes))
	return NewBitReader(payloadBytes)
}

type BitReader struct {
	bytes   []byte
	byteIdx int
	bitIdx  int
}

func NewBitReader(data []byte) *BitReader {
	return &BitReader{bytes: data}
}

func (br *BitReader) NextBit() (int, error) {
	if br.byteIdx >= len(br.bytes) {
		return 0, io.EOF
	}
	shift := 7 - br.bitIdx
	bit := int((br.bytes[br.byteIdx] >> shift) & 1)
	br.bitIdx++
	if br.bitIdx == 8 {
		br.bitIdx = 0
		br.byteIdx++
	}
	return bit, nil
}
