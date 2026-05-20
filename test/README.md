# rrwm Watermark Test Suite

Quality testing and visualization tools for the rrwm DCT watermarking system.

## Structure

```
test/
├── test_watermark.py   # Main test suite — runs insert/extract at multiple JPEG quality
│                       # levels, measures BER/PSNR/SSIM/MSE, generates graphs
├── output/
│   ├── results.json         # Machine-readable test results
│   ├── summary.md           # Markdown results table
│   ├── payloads/            # Generated test payloads
│   ├── watermarked_q*.jpeg  # Watermarked images at each quality
│   ├── extracted_q*.bin     # Extracted payload bytes
│   └── images/              # Generated visualization PNGs
└── README.md
```

## Running

```bash
cd /home/ark/Project/rrwm
python3.14 test/test_watermark.py
```

Requires: `numpy`, `Pillow`, `matplotlib`, `scipy`.

## What It Tests

| Quality | Embed | Self-Extract | Cross-Extract |
|:-------:|:-----:|:------------:|:-------------:|
| 75 | ✓ | ✓ | Q=80,90,95,100 |
| 85 | ✓ | ✓ | Q=70,90,95,100 |
| 90 | ✓ | ✓ | Q=70,80,95,100 |
| 95 | ✓ | ✓ | Q=70,80,90,100 |
| 100 | ✓ | ✓ | Q=70,80,90,95 |

## Metrics

- **BER**: Bit Error Rate between original and extracted payload
- **PSNR**: Peak Signal-to-Noise Ratio (full RGB image)
- **SSIM**: Structural Similarity (Y/luminance channel)
- **MSE**: Mean Squared Error (Y channel)
- **Pixel flip rate**: Fraction of pixels changed by watermark
- **File size**: Size impact of quality vs watermark

## Generated Visualizations

| File | Shows |
|------|-------|
| `01_quality_vs_ber.png` | BER bar chart across quality levels |
| `02_cross_quality_matrix.png` | Heatmap of embed×extract quality combinations |
| `03_image_quality_metrics.png` | PSNR + SSIM dual-axis chart |
| `04_before_after_comparison.png` | 512×512 crop comparison at Q=75/90/100 |
| `05_file_size_vs_quality.png` | File size across quality levels |
| `06_quality_degradation.png` | BER + PSNR overlay with threshold zones |
| `07_pixel_flip_rate.png` | Watermark-induced pixel changes |
| `08_lsb_embedding_detail.png` | Single block DCT walkthrough (embedding zone) |
| `09_embedding_zone_comparison.png` | Per-quality embedding zone coefficient values |
