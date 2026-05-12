package main

import (
	"bytes"
	"fmt"
	"image"
	"image/jpeg"
	"log"
	"os"
	"runtime/debug"
)

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

func main() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Printf("Recovered from: %v\n", r)
			debug.PrintStack()
		}
	}()

	args := InitializeApp()

	GetImage(ReadFile(args.OriginalImagePath))
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
