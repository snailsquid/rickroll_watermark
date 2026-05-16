package main

import (
	"bytes"
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

type Arg struct {
	OriginalImagePath string
	ModifiedImagePath string
}

func IsValidFile(path string) bool {
	info, err := os.Stat(path)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

func InitializeApp() Arg {
	if len(os.Args) != 3 {
		log.Fatalf("Usage: go run main.go <input_image> <output_image>\n")
	}

	if !IsValidFile(os.Args[1]) {
		log.Fatalf("%v is not a valid file\n", os.Args[1])
	}

	return Arg{
		OriginalImagePath: os.Args[1],
		ModifiedImagePath: os.Args[2],
	}
}

// AI Generated
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

// AI Generated
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

// AI Generated
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

const IMAGE_PATH = "optimized_video.bin"

func Start() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Printf("Recovered from: %v\n", r)
			debug.PrintStack()
		}
	}()

	args := InitializeApp()

	rawImage := GetImage(ReadFile(args.OriginalImagePath))
	image := NewImage(ImageToYCbCr(rawImage))

	y := BlocksToDCT(image.Y)
	println((*y)[0].at)

	zz := DCTsToZigZags(y)

	reader := LoadImage(IMAGE_PATH)
	InsertBitsToZigZags(zz, reader)

}

func ImageToYCbCr(input image.Image) *image.YCbCr {
	if img, ok := input.(*image.YCbCr); ok {
		return img
	}

	log.Fatalf("Failed to convert to YCbCr")
	return nil
}

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

type Image struct {
	Y  *[]Block
	Cb *[]Block
	Cr *[]Block
}

type Block struct {
	at    [blockSize * blockSize]uint8
	count int
}

type BlockShift struct {
	at    [blockSize * blockSize]int8
	count int
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
	cb := NewBlocks(input.Cb, width, height)
	cr := NewBlocks(input.Cr, width, height)

	image := Image{
		Y:  &y,
		Cb: &cb,
		Cr: &cr,
	}

	return &image
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

type DCT struct {
	at [][]float64
}

func BlocksToDCT(blocks *[]Block) *[]*DCT {
	dataBuffer := make([]float64, 64)
	spine := make([][]float64, 8)
	for i := range spine {
		spine[i] = dataBuffer[i : (i+1)*blockSize]
	}

	var dcts []*DCT

	for i, _ := range *blocks {
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

	dct := DCT{
		at: result,
	}

	return &dct
}

const MIN_SAFE_DCT_FREQ_IDX = 10
const MAX_SAFE_DCT_FREQ_IDX = 45

func InsertBitsToZigZags(zigzags *[]*ZigZag, bitReader *BitReader) {
	for _, zz := range *zigzags {
		finished := zz.InsertBits(bitReader)
		if finished {
			break
		}
	}
}

func (zz *ZigZag) InsertBits(bitReader *BitReader) bool {
	for i := MIN_SAFE_DCT_FREQ_IDX; i < MAX_SAFE_DCT_FREQ_IDX; i++ {
		current := zz.at[i]

		toInsertBit, err := bitReader.NextBit()
		if err == io.EOF {
			fmt.Println("Finished.")
			return true
		}
		*(zz.at[i]) = SetLSB32(*current, uint64(toInsertBit))
	}
	return false
}

type ZigZag struct {
	at []*float64
}

func SetLSB32(f float64, bit uint64) float64 {
	bits := math.Float64bits(f)

	bits = (bits &^ 1) | (bit & 1)

	return math.Float64frombits(bits)
}
func (dct *DCT) ToZigZag() *ZigZag {
	return &ZigZag{at: ZigZagTraverse(dct.at)}
}

// AI Generated
func ZigZagTraverse(matrix [][]float64) []*float64 {
	if len(matrix) == 0 || len(matrix[0]) == 0 {
		return nil
	}

	rows := len(matrix)
	cols := len(matrix[0])
	totalElements := rows * cols
	result := make([]*float64, totalElements)

	r, c := 0, 0
	// direction: true means moving UP-RIGHT, false means moving DOWN-LEFT
	movingUp := true

	for i := 0; i < totalElements; i++ {
		result[i] = &(matrix[r][c])

		if movingUp {
			// If we hit the right boundary, move down and change direction
			if c == cols-1 {
				r++
				movingUp = false
				// If we hit the top boundary, move right and change direction
			} else if r == 0 {
				c++
				movingUp = false
				// Otherwise, keep moving diagonally up-right
			} else {
				r--
				c++
			}
		} else {
			// If we hit the bottom boundary, move right and change direction
			if r == rows-1 {
				c++
				movingUp = true
				// If we hit the left boundary, move down and change direction
			} else if c == 0 {
				r++
				movingUp = true
				// Otherwise, keep moving diagonally down-left
			} else {
				r++
				c--
			}
		}
	}

	return result
}

func LoadImage(imagePath string) *BitReader {
	payloadBytes, err := os.ReadFile(imagePath)
	if err != nil {
		log.Fatalf("Cant load image\n")
	}

	BitReader := NewBitReader(payloadBytes)

	return BitReader
}

type BitReader struct {
	bytes   []byte
	byteIdx int
	bitIdx  int // Tracks the bit position (0 to 7) inside the current byte
}

func NewBitReader(data []byte) *BitReader {
	return &BitReader{bytes: data}
}

// NextBit returns the next bit (0 or 1). Returns io.EOF when out of data.
func (br *BitReader) NextBit() (int, error) {
	if br.byteIdx >= len(br.bytes) {
		return 0, io.EOF
	}

	// Extract the bit starting from the Most Significant Bit (MSB)
	shift := 7 - br.bitIdx
	bit := int((br.bytes[br.byteIdx] >> shift) & 1)

	// Move pointers forward
	br.bitIdx++
	if br.bitIdx == 8 {
		br.bitIdx = 0
		br.byteIdx++
	}

	return bit, nil
}
