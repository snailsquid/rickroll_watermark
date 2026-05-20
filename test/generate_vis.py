#!/usr/bin/env python3
"""
Regenerate visualizations from existing results.json, with fixes:
- RGB-space comparison for PSNR/SSIM (avoids YCbCr matrix mismatch)
- Fixed subplot layout for embedding zone comparison
- Proper before/after images
"""

import json, math, os, sys
import numpy as np
from PIL import Image as PILImage
PILImage.MAX_IMAGE_PIXELS = None

OUTDIR = os.path.join(os.path.dirname(__file__), "output")
IMGDIR = os.path.join(OUTDIR, "images")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG_JPEG = os.path.join(ROOT, "input", "original.jpeg")
os.makedirs(IMGDIR, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import matplotlib.patches as mpatches
from scipy.fftpack import dct as scipy_dct

BLUE_RED = "RdBu_r"

# Load results
with open(os.path.join(OUTDIR, "results.json")) as f:
    results = json.load(f)

orig = PILImage.open(ORIG_JPEG)
w, h = orig.size
print(f"Source: {w}x{h} ({w*h/1e6:.1f} MP)")

# Fix results: recompute PSNR/MSE/SSIM in RGB space (both decoded by PIL, fair)
print("Recomputing metrics in RGB space...")
for r in results:
    q = r["quality"]
    wm_path = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
    if not os.path.exists(wm_path):
        continue
    wm = PILImage.open(wm_path)
    o_rgb = np.array(orig, dtype=np.float64)
    w_rgb = np.array(wm, dtype=np.float64)
    # compute per-channel MSE then average
    diff = (o_rgb - w_rgb) ** 2
    mse_rgb = diff.mean()  # mean over all pixels and all 3 channels
    r["mse_all"] = mse_rgb
    r["psnr"] = 100.0 if mse_rgb < 1e-10 else 20 * math.log10(255.0 / math.sqrt(mse_rgb))
    # SSIM on luminance (average of RGB for simplicity)
    o_lum = o_rgb.mean(axis=2)
    w_lum = w_rgb.mean(axis=2)
    C1, C2 = (0.01*255)**2, (0.03*255)**2
    m1, m2 = o_lum.mean(), w_lum.mean()
    s1, s2 = o_lum.var(), w_lum.var()
    s12 = ((o_lum-m1)*(w_lum-m2)).mean()
    r["ssim"] = float((2*m1*m2+C1)*(2*s12+C2) / ((m1**2+m2**2+C1)*(s1+s2+C2)))
    # flip rate in RGB
    r["flip_rate"] = float(np.mean(np.abs(o_rgb - w_rgb) > 0.5)) * 100
    # mse_y: just the green channel as luminance proxy
    r["mse_y"] = float(diff[:,:,1].mean())
    print(f"  Q={q}: PSNR={r['psnr']:.1f}dB  SSIM={r['ssim']:.6f}  MSE(RGB)={mse_rgb:.4f}  flips={r['flip_rate']:.2f}%")

with open(os.path.join(OUTDIR, "results_fixed.json"), "w") as f:
    json.dump(results, f, indent=2)

# ── Helpers ──────────────────────────────────────────────────────────

def zigzag_path():
    result, r, c, up = [], 0, 0, True
    for _ in range(64):
        result.append((r, c))
        if up:
            if c == 7: r += 1; up = False
            elif r == 0: c += 1; up = False
            else: r -= 1; c += 1
        else:
            if r == 7: c += 1; up = True
            elif c == 0: r += 1; up = True
            else: r += 1; c -= 1
    return result

zz = zigzag_path()
lum_q = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
         14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
         18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
         49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]

def scale_q(base, q):
    s = 5000/q if q < 50 else 200 - q*2
    return np.array([max(1, min(255, int((v*s+50)/100))) for v in base])

def dct2d(b):
    return scipy_dct(scipy_dct(b - 128, axis=0, norm='ortho'), axis=1, norm='ortho')

qs = [r["quality"] for r in results]
bers = [r["ber"] for r in results]
psnrs = [r["psnr"] for r in results]
ssims = [r["ssim"] for r in results]
mses = [r["mse_y"] for r in results]
sizes = [r["size"] / 1e6 for r in results]
flips = [r["flip_rate"] for r in results]

print("\nGenerating visualizations...")

# ── 1. BER vs Quality ────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 6))
clrs = ["#27ae60" if b == 0 else "#e74c3c" for b in bers]
bars = ax.bar([str(q) for q in qs], bers, color=clrs, edgecolor="#333", lw=1.2, width=0.6)
ax.set_yscale("log")
ax.set_xlabel("JPEG Quality", fontsize=14)
ax.set_ylabel("Bit Error Rate (BER)", fontsize=14)
ax.set_title("Extraction Fidelity vs JPEG Quality\n(Same-Quality Embed/Extract, 2 KB payload)", fontsize=15, fontweight="bold")
ax.grid(axis="y", alpha=0.3)
for b, v in zip(bars, bers):
    lbl = "0.0" if v == 0 else f"{v:.2e}"
    yoff = 0.0005 if v == 0 else v * 2
    ax.text(b.get_x() + b.get_width()/2, yoff, lbl, ha="center", va="bottom",
            fontsize=11, fontweight="bold", color="#27ae60" if v == 0 else "#e74c3c")
for i, r in enumerate(results):
    st = "✓ Perfect" if r["success"] else "✗ Lossy"
    c = "#27ae60" if r["success"] else "#e74c3c"
    yv = 0.0001 if bers[i] == 0 else bers[i] * 5
    ax.annotate(st, (i, bers[i]), xytext=(i, yv), ha="center", fontsize=9,
                fontstyle="italic", color=c)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "01_quality_vs_ber.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  01_quality_vs_ber.png")

# ── 2. Cross-quality heatmap ─────────────────────────────────────────
all_qs = sorted(set([str(r["quality"]) for r in results] +
                    [k for r in results for k in r["cross"].keys()]))
q_to_i = {q: i for i, q in enumerate(all_qs)}
n = len(all_qs)
cm = np.full((n, n), np.nan)
for r in results:
    sq = str(r["quality"])
    cm[q_to_i[sq], q_to_i[sq]] = r["ber"]
    for xq_str, xber in r["cross"].items():
        if xq_str in q_to_i:
            cm[q_to_i[sq], q_to_i[xq_str]] = xber

fig, ax = plt.subplots(figsize=(9, 7))
im = ax.imshow(cm, cmap="RdYlGn_r", vmin=0, vmax=0.5, aspect="auto")
ax.set_xticks(range(n)); ax.set_yticks(range(n))
ax.set_xticklabels([f"Q={q}" for q in all_qs])
ax.set_yticklabels([f"Q={q}" for q in all_qs])
ax.set_xlabel("Extraction Quality", fontsize=13)
ax.set_ylabel("Embedding Quality", fontsize=13)
ax.set_title("Cross-Quality BER Matrix", fontsize=14, fontweight="bold")
for i in range(n):
    for j in range(n):
        v = cm[i, j]
        if not np.isnan(v):
            c = "white" if v > 0.12 else "black"
            lbl = f"{v:.2e}" if v > 0 else "0"
            ax.text(j, i, lbl, ha="center", va="center", fontsize=8, color=c, fontweight="bold")
plt.colorbar(im, ax=ax, label="BER", shrink=0.8)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "02_cross_quality_matrix.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  02_cross_quality_matrix.png")

# ── 3. PSNR + SSIM ───────────────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(10, 6))
l1 = ax1.plot(qs, psnrs, "o-", color="#2980b9", lw=2.5, ms=8, label="PSNR")
ax1.set_xlabel("JPEG Quality", fontsize=14)
ax1.set_ylabel("PSNR (dB)", fontsize=14, color="#2980b9")
ax1.tick_params(axis="y", labelcolor="#2980b9")
for q, v in zip(qs, psnrs):
    ax1.annotate(f"{v:.1f}", (q, v), textcoords="offset points", xytext=(0, 12),
                 ha="center", fontsize=9, color="#2980b9", fontweight="bold")
ax2 = ax1.twinx()
l2 = ax2.plot(qs, ssims, "s--", color="#e67e22", lw=2.5, ms=8, label="SSIM")
ax2.set_ylabel("SSIM", fontsize=14, color="#e67e22")
ax2.tick_params(axis="y", labelcolor="#e67e22")
for q, v in zip(qs, ssims):
    ax2.annotate(f"{v:.4f}", (q, v), textcoords="offset points", xytext=(0, -14),
                 ha="center", fontsize=9, color="#e67e22", fontweight="bold")
ax1.legend(l1 + l2, [l.get_label() for l in l1 + l2], loc="lower right", fontsize=12)
ax1.set_title("Image Quality Metrics vs JPEG Quality\n(Higher is better — PSNR > 35 dB is imperceptible)", fontsize=14, fontweight="bold")
ax1.grid(alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "03_image_quality_metrics.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  03_image_quality_metrics.png")

# ── 4. Before/after visual comparison ────────────────────────────────
cy, cx = h // 2, w // 2
cr = 256
comp_qs = [75, 90, 100]
onp_rgb = np.array(orig)
oc = onp_rgb[cy-cr:cy+cr, cx-cr:cx+cr]

fig, axes = plt.subplots(2, 3, figsize=(18, 12))
for col, q in enumerate(comp_qs):
    wm_path = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
    if not os.path.exists(wm_path):
        axes[0, col].axis("off"); axes[1, col].axis("off"); continue
    wn = np.array(PILImage.open(wm_path))
    wc = wn[cy-cr:cy+cr, cx-cr:cx+cr]
    combined = np.hstack([oc, wc])
    axes[0, col].imshow(combined)
    axes[0, col].axvline(cr, color="white", lw=2, ls="--", alpha=0.7)
    axes[0, col].text(cr//2, 10, "Original", color="white", fontsize=12, fontweight="bold",
                      bbox=dict(facecolor="black", alpha=0.5, pad=2))
    axes[0, col].text(cr + cr//2, 10, f"Q={q}", color="white", fontsize=12, fontweight="bold",
                      bbox=dict(facecolor="black", alpha=0.5, pad=2))
    axes[0, col].set_title(f"Original vs Watermarked (Q={q})", fontsize=14, fontweight="bold")
    axes[0, col].axis("off")
    diff = np.abs(oc.astype(float) - wc.astype(float))
    diff_gray = np.mean(diff, axis=2)
    vmax = max(diff_gray.max() * 0.3, 1)
    axes[1, col].imshow(diff_gray, cmap="inferno", vmin=0, vmax=min(vmax, 30))
    axes[1, col].set_title(f"Difference Map\nMSE(RGB)={((oc.astype(float)-wc.astype(float))**2).mean():.2f}", fontsize=11)
    axes[1, col].axis("off")

fig.suptitle("Visual Comparison: Original vs Watermarked at Different JPEG Qualities",
             fontsize=16, fontweight="bold", y=1.01)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "04_before_after_comparison.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  04_before_after_comparison.png")

# ── 5. File size vs quality ──────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
bars = ax.bar([str(q) for q in qs], sizes, color="#8e44ad", edgecolor="#333", lw=1.2, width=0.6)
for b, v in zip(bars, sizes):
    ax.text(b.get_x() + b.get_width()/2, b.get_height() + 0.05,
            f"{v:.1f} MB", ha="center", fontsize=10, fontweight="bold")
ax.set_xlabel("JPEG Quality", fontsize=14)
ax.set_ylabel("File Size (MB)", fontsize=14)
ax.set_title("Watermarked JPEG File Size vs Quality", fontsize=14, fontweight="bold")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "05_file_size_vs_quality.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  05_file_size_vs_quality.png")

# ── 6. Quality degradation ───────────────────────────────────────────
fig, ax1 = plt.subplots(figsize=(10, 6))
l1 = ax1.plot(qs, bers, "o-", color="#e74c3c", lw=3, ms=8, label="BER")
ax1.set_xlabel("JPEG Quality", fontsize=14)
ax1.set_ylabel("Bit Error Rate", fontsize=14, color="#e74c3c")
ax1.tick_params(axis="y", labelcolor="#e74c3c")
ax1.axhspan(0, 1e-4, alpha=0.08, color="green", label="Perfect zone")
ax1.axhspan(1e-4, 1e-2, alpha=0.08, color="gold", label="Tolerable")
ax1.axhspan(1e-2, max([b for b in bers if b < 1] + [1e-2])*2, alpha=0.08, color="red", label="Lossy")
ax2 = ax1.twinx()
l2 = ax2.plot(qs, psnrs, "s--", color="#2980b9", lw=3, ms=8, label="PSNR (dB)")
ax2.set_ylabel("PSNR (dB)", fontsize=14, color="#2980b9")
ax2.tick_params(axis="y", labelcolor="#2980b9")
ax1.legend(l1 + l2, [l.get_label() for l in l1 + l2], loc="upper left", fontsize=12)
ax1.set_title("Watermark Degradation Across JPEG Quality", fontsize=14, fontweight="bold")
ax1.grid(alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "06_quality_degradation.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  06_quality_degradation.png")

# ── 7. Pixel flip rate ───────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(qs, flips, "o-", color="#c0392b", lw=2.5, ms=8)
ax.fill_between(qs, flips, alpha=0.15, color="#c0392b")
for q, v in zip(qs, flips):
    ax.annotate(f"{v:.2f}%", (q, v), textcoords="offset points", xytext=(0, 10),
                ha="center", fontsize=10, fontweight="bold", color="#c0392b")
ax.set_xlabel("JPEG Quality", fontsize=14)
ax.set_ylabel("Pixel Difference Rate (%)", fontsize=14)
ax.set_title("Watermark-Induced Pixel Changes vs JPEG Quality\n(Measured in RGB, includes JPEG re-compression effects)", fontsize=14, fontweight="bold")
ax.grid(alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "07_pixel_flip_rate.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  07_pixel_flip_rate.png")

# ── 8. LSB embedding detail walkthrough ──────────────────────────────
onp_y = np.array(orig.convert("YCbCr"), dtype=np.float64)[:,:,0]
blk_orig = onp_y[cy-64:cy-56, cx-64:cx-56]
dct_orig = dct2d(blk_orig)

qv = 90
qt = scale_q(lum_q, qv).reshape(8, 8)
qdct = np.round(dct_orig / qt)

wm_path = os.path.join(OUTDIR, f"watermarked_q{qv}.jpeg")
wny = np.array(PILImage.open(wm_path).convert("YCbCr"), dtype=np.float64)[:,:,0]
blk_wm = wny[cy-64:cy-56, cx-64:cx-56]
dct_wm = dct2d(blk_wm)
qdct_wm = np.round(dct_wm / qt)

zz_orig = np.array([qdct[r,c] for r,c in zz])
zz_wm = np.array([qdct_wm[r,c] for r,c in zz])

fig, axes = plt.subplots(1, 3, figsize=(18, 6))
ax = axes[0]
zz_colors = []
for i in range(64):
    if 10 <= i <= 44: zz_colors.append("#e74c3c")
    elif i == 0: zz_colors.append("#3498db")
    else: zz_colors.append("#95a5a6")
ax.bar(range(64), np.abs(zz_orig), color=zz_colors, edgecolor="#333", lw=0.3)
ax.axvspan(9.5, 44.5, alpha=0.08, color="red", label="Embedding zone (idx 10-44)")
ax.set_yscale("symlog")
ax.set_xlabel("Zigzag Index", fontsize=12); ax.set_ylabel("|Quantized DCT Value|", fontsize=12)
ax.set_title("Quantized DCT in Zigzag Order (Original)", fontsize=13, fontweight="bold")
ax.legend(fontsize=10); ax.grid(axis="y", alpha=0.3)

ax = axes[1]
lsb_orig = np.array([int(abs(v)) & 1 for v in zz_orig[10:45]])
lsb_wm = np.array([int(abs(v)) & 1 for v in zz_wm[10:45]])
changed = lsb_orig != lsb_wm
bc = []
for i in range(35):
    if changed[i]: bc.append("#f39c12")
    elif lsb_wm[i] == 1: bc.append("#e74c3c")
    else: bc.append("#3498db")
ax.bar(range(35), zz_wm[10:45], color=bc, edgecolor="#333", lw=0.5)
ax.set_xlabel("Offset in Embedding Zone", fontsize=12)
ax.set_ylabel("Coefficient Value", fontsize=12)
ax.set_title("After Embedding (Q=90)\nRed=lsb1 Blue=lsb0 Gold=flipped", fontsize=13, fontweight="bold")
ax.grid(axis="y", alpha=0.3)
ax.legend(handles=[
    mpatches.Patch(color="#e74c3c", label="LSB=1"),
    mpatches.Patch(color="#3498db", label="LSB=0"),
    mpatches.Patch(color="#f39c12", label="Flipped"),
], fontsize=9)

ax = axes[2]
fc = int(np.sum(changed))
ax.text(0.5, 0.65, f"{fc}/35", ha="center", va="center", fontsize=36, fontweight="bold", color="#f39c12")
ax.text(0.5, 0.4, "bits flipped in\nembedding zone", ha="center", va="center", fontsize=14, color="#555")
ax.text(0.5, 0.2, f"{(1-fc/35)*100:.1f}% preserved", ha="center", va="center", fontsize=12, color="#27ae60")
ax.axis("off")

fig.suptitle("Detailed LSB Embedding: Single 8×8 Block Walkthrough (Q=90)",
             fontsize=15, fontweight="bold", y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "08_lsb_embedding_detail.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  08_lsb_embedding_detail.png")

# ── 9. Embedding zone per-quality ────────────────────────────────────
# Use 2 rows, 3 cols layout — show Q=75,85,90 in row 0, Q=95,100 in row 1
embed_qs = [75, 85, 90, 95, 100]
fig, axes = plt.subplots(2, 3, figsize=(18, 10))

for idx, q in enumerate(embed_qs):
    row = idx // 3
    col = idx % 3
    wmp = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
    if not os.path.exists(wmp):
        axes[row, col].axis("off"); continue
    
    wny2 = np.array(PILImage.open(wmp).convert("YCbCr"), dtype=np.float64)[:,:,0]
    bw = wny2[cy-64:cy-56, cx-64:cx-56]
    dw = dct2d(bw)
    qtw = scale_q(lum_q, q).reshape(8, 8)
    qdw = np.round(dw / qtw)
    zzw = np.array([qdw[r,c] for r,c in zz])
    
    ax = axes[row, col]
    lsb_w = np.array([int(abs(v)) & 1 for v in zzw[10:45]])
    bc2 = ["#e74c3c" if b == 1 else "#3498db" for b in lsb_w]
    ax.bar(range(35), zzw[10:45], color=bc2, edgecolor="#333", lw=0.3)
    ax.set_title(f"Q={q} Embedding Zone", fontsize=12)
    ax.set_xlabel("Coeff offset"); ax.set_ylabel("Value")
    ax.grid(axis="y", alpha=0.3)

# Hide the unused last subplot (row 1, col 2)
axes[1, 2].axis("off")

fig.suptitle("Embedding Zone Comparison Across Quality Levels", fontsize=15, fontweight="bold", y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(IMGDIR, "09_embedding_zone_comparison.png"), dpi=150, bbox_inches="tight"); plt.close()
print("  09_embedding_zone_comparison.png")

# ── Print summary table ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("RESULTS SUMMARY (RGB-space metrics)")
print("=" * 70)
hdr = f"{'Q':>4} | {'BER':>12} | {'PSNR':>8} | {'SSIM':>8} | {'MSE(G)':>10} | {'Size':>10} | {'Flips':>8} | Status"
print(hdr)
print("-" * len(hdr))
for r in results:
    st = "✓" if r["success"] else "✗"
    print(f"{r['quality']:>4d} | {r['ber']:>12.2e} | {r['psnr']:>7.1f} | {r['ssim']:>8.6f} | {r['mse_y']:>10.4f} | {r['size']/1e6:>8.2f}MB | {r['flip_rate']:>7.2f}% | {st}")

# Cross-quality summary
print("\nCross-Quality BER (embed row, extract col):")
label = "Embed\\Extract"
print(f"{label:>16}", end="")
xq_list = sorted(set([k for r in results for k in r["cross"].keys()]))
for xq in xq_list:
    print(f"{xq:>10}", end="")
print()
for r in results:
    print(f"Q={r['quality']:>3d}            ", end="")
    for xq in xq_list:
        v = r["cross"].get(xq, 1.0)
        lbl = f"{v:.2e}" if v < 0.01 else ("1.0" if v >= 0.999 else f"{v:.3f}")
        print(f"{lbl:>10}", end="")
    print()

# Save summary markdown
md = ["## Test Results Summary\n",
      "| Quality | BER | PSNR (dB) | SSIM | MSE (G) | File Size | Pixel Flips | Extraction |",
      "|---------|-----|-----------|------|---------|-----------|-------------|------------|"]
for r in results:
    st = "Perfect" if r["success"] else "Failed"
    md.append(f"| {r['quality']} | {r['ber']:.2e} | {r['psnr']:.1f} | {r['ssim']:.6f} | {r['mse_y']:.4f} | {r['size']/1e6:.2f} MB | {r['flip_rate']:.2f}% | {st} |")
md.append("\n### Cross-Quality BER Matrix\n")
md.append("| Embed \\ Ext | " + " | ".join(xq_list) + " |")
md.append("|" + "---|" * (len(xq_list) + 1))
for r in results:
    row = f"| Q={r['quality']} "
    for xq in xq_list:
        v = r["cross"].get(xq, 1.0)
        lbl = f"{v:.2e}" if v < 0.01 else ("1.0" if v >= 0.999 else f"{v:.3f}")
        row += f"| {lbl} "
    row += "|"
    md.append(row)

with open(os.path.join(OUTDIR, "summary.md"), "w") as f:
    f.write("\n".join(md) + "\n")

print(f"\nSummary → {os.path.join(OUTDIR, 'summary.md')}")
print("All visualizations complete!")
