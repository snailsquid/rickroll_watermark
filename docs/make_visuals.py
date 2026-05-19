#!/usr/bin/env python3
"""
Generates step-by-step visualization images for the rrwm JPEG DCT watermarking docs.
Outputs PNGs to docs/images/ and the final markdown to docs/watermarking.md
"""

import struct, math, os, io, json
import numpy as np
from PIL import Image as PILImage

OUTDIR = os.path.join(os.path.dirname(__file__), "images")
os.makedirs(OUTDIR, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
from matplotlib.colors import Normalize
import matplotlib.patches as mpatches

BLUE_RED = "RdBu_r"

# ── load the 50MP JPEG ──────────────────────────────────────────────

JPEG_PATH = os.path.join(os.path.dirname(__file__), "..", "input", "original.jpeg")
PILImage.MAX_IMAGE_PIXELS = None  # allow 50MP
orig = PILImage.open(JPEG_PATH)
w, h = orig.size
print(f"Input: {w}x{h} ({w*h/1e6:.1f}MP)")

# ── 1. JPEG decode → YCbCr ──────────────────────────────────────────

ycbr = orig.convert("YCbCr")
Y, Cb, Cr = ycbr.split()

fig, axes = plt.subplots(1, 3, figsize=(21, 7))
titles = ["Y (Luminance)", "Cb (Blue-difference Chroma)", "Cr (Red-difference Chroma)"]
for ax, ch, title in zip(axes, [Y, Cb, Cr], titles):
    ax.imshow(ch, cmap="gray", vmin=0, vmax=255)
    ax.set_title(title, fontsize=16)
    ax.axis("off")
fig.suptitle("Step 1: YCbCr Color Space Conversion", fontsize=20, y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "01_ycbcr_channels.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 01_ycbcr_channels.png")

# ── 2. Crop a small region to show detail ───────────────────────────
cx, cy = w // 2, h // 2
Y_np = np.array(Y, dtype=np.float64)
Cb_np = np.array(Cb, dtype=np.float64)
Cr_np = np.array(Cr, dtype=np.float64)

# ── 3. 8×8 Block Partitioning ──────────────────────────────────────

fig, ax = plt.subplots(1, 1, figsize=(8, 8))
ax.imshow(Y_np[cy-128:cy+128, cx-128:cx+128], cmap="gray", vmin=0, vmax=255)
for i in range(0, 257, 8):
    lw = 0.3 if i % 64 == 0 else 0.15
    c = "#00ff88" if i % 64 == 0 else "#88ffcc"
    ax.axhline(i, color=c, linewidth=lw, alpha=0.5)
    ax.axvline(i, color=c, linewidth=lw, alpha=0.5)
rect = Rectangle((64, 64), 8, 8, fill=False, edgecolor="red", linewidth=2.5)
ax.add_patch(rect)
ax.set_title("Step 2: 8×8 Block Partitioning\n(Red box = one block, thick lines = 64×64 superblock)", fontsize=14)
ax.axis("off")
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "02_block_partition.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 02_block_partition.png")

# ── 4. One block: pixel values → level shift → DCT ────────────────

block_r, block_c = 64, 64
y_block_orig = Y_np[cy-128+block_r:cy-128+block_r+8, cx-128+block_c:cx-128+block_c+8]
y_block_shifted = y_block_orig - 128

from scipy.fftpack import dct as scipy_dct, idct as scipy_idct
def dct2d(block):
    return scipy_dct(scipy_dct(block, axis=0, norm='ortho'), axis=1, norm='ortho')
def idct2d(block):
    return scipy_idct(scipy_idct(block, axis=0, norm='ortho'), axis=1, norm='ortho')

y_block_dct = dct2d(y_block_shifted)

fig, axes = plt.subplots(1, 3, figsize=(18, 6))
ax = axes[0]
im = ax.imshow(y_block_orig, cmap="gray", vmin=0, vmax=255)
for i in range(8):
    for j in range(8):
        ax.text(j, i, f"{int(y_block_orig[i,j])}", ha="center", va="center",
                fontsize=9, color="white" if y_block_orig[i,j] < 128 else "black")
ax.set_title("a) 8×8 Pixel Block\n(0–255 unsigned)", fontsize=14)
ax.axis("off")

ax = axes[1]
ax.imshow(y_block_shifted, cmap=BLUE_RED, vmin=-128, vmax=127)
for i in range(8):
    for j in range(8):
        ax.text(j, i, f"{int(y_block_shifted[i,j])}", ha="center", va="center",
                fontsize=9, color="white" if abs(y_block_shifted[i,j]) > 60 else "black")
ax.set_title("b) Level Shift (subtract 128)\n-128..127 signed", fontsize=14)
ax.axis("off")

ax = axes[2]
dct_abs = np.abs(y_block_dct)
dct_log = np.log10(dct_abs + 1)
ax.imshow(dct_log, cmap="inferno")
for i in range(8):
    for j in range(8):
        v = y_block_dct[i,j]
        txt = f"{v:.0f}"
        ax.text(j, i, txt, ha="center", va="center",
                fontsize=8, color="white" if dct_log[i,j] < np.max(dct_log)*0.6 else "black",
                fontweight="bold")
ax.set_title("c) DCT Coefficients\n(DC + AC frequencies)", fontsize=14)
ax.axis("off")

fig.suptitle("Step 3: Per-Block DCT Transform", fontsize=18, y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "03_block_dct.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 03_block_dct.png")

# ── 5. DCT basis functions ─────────────────────────────────────────

fig, axes = plt.subplots(8, 8, figsize=(16, 16))
for u in range(8):
    for v in range(8):
        ax = axes[u, v]
        basis = np.zeros((8, 8))
        for i in range(8):
            for j in range(8):
                cu = 1.0/math.sqrt(2) if u == 0 else 1.0
                cv = 1.0/math.sqrt(2) if v == 0 else 1.0
                basis[i,j] = cu * cv * math.cos((2*i+1)*u*math.pi/16) * math.cos((2*j+1)*v*math.pi/16)
        ax.imshow(basis, cmap=BLUE_RED, vmin=-1, vmax=1)
        ax.set_title(f"({u},{v})", fontsize=8)
        ax.axis("off")
fig.suptitle("Step 3 (detail): 2D DCT Basis Functions (8×8)", fontsize=16, y=1.01)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "03b_dct_basis.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 03b_dct_basis.png")

# ── 6. Quantization tables ──────────────────────────────────────────

lum_q = [16, 11, 10, 16, 24, 40, 51, 61,
         12, 12, 14, 19, 26, 58, 60, 55,
         14, 13, 16, 24, 40, 57, 69, 56,
         14, 17, 22, 29, 51, 87, 80, 62,
         18, 22, 37, 56, 68, 109, 103, 77,
         24, 35, 55, 64, 81, 104, 113, 92,
         49, 64, 78, 87, 103, 121, 120, 101,
         72, 92, 95, 98, 112, 100, 103, 99]

chrom_q = [17, 18, 24, 47, 99, 99, 99, 99,
           18, 21, 26, 66, 99, 99, 99, 99,
           24, 26, 56, 99, 99, 99, 99, 99,
           47, 66, 99, 99, 99, 99, 99, 99,
           99, 99, 99, 99, 99, 99, 99, 99,
           99, 99, 99, 99, 99, 99, 99, 99,
           99, 99, 99, 99, 99, 99, 99, 99,
           99, 99, 99, 99, 99, 99, 99, 99]

def scale_q(base, quality):
    q = max(1, min(100, quality))
    if q < 50:
        scale = 5000 / q
    else:
        scale = 200 - q * 2
    out = []
    for v in base:
        s = int((v * scale + 50) / 100)
        out.append(max(1, min(255, s)))
    return out

lum_q90 = scale_q(lum_q, 90)
chrom_q90 = scale_q(chrom_q, 90)

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

for ax, tbl, label in [
    (axes[0], lum_q, "Luminance"),
    (axes[1], chrom_q, "Chrominance"),
]:
    tbl90 = scale_q(tbl, 90)
    mat = np.array(tbl90).reshape(8,8)
    ax.imshow(mat, cmap="Blues", vmin=1, vmax=255)
    for i in range(8):
        for j in range(8):
            ax.text(j, i, f"{mat[i,j]:d}", ha="center", va="center",
                    fontsize=10, color="white" if mat[i,j] > 100 else "black")
    ax.set_title(f"Step 4: {label} Q-Table (Q=90)", fontsize=14)
    ax.axis("off")
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "04_quant_tables.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 04_quant_tables.png")

# ── 7. Quantization in action ──────────────────────────────────────

y_block_q = np.round(y_block_dct / np.array(lum_q90).reshape(8,8))

fig, axes = plt.subplots(1, 3, figsize=(18, 6))

ax = axes[0]
ax.imshow(np.abs(y_block_dct), cmap="inferno")
for i in range(8):
    for j in range(8):
        ax.text(j, i, f"{y_block_dct[i,j]:.0f}", ha="center", va="center",
                fontsize=8, color="white" if np.abs(y_block_dct[i,j]) < 50 else "black")
ax.set_title("a) DCT Coefficients (before)", fontsize=14)
ax.axis("off")

ax = axes[1]
mat_lum = np.array(lum_q90).reshape(8,8)
ax.imshow(mat_lum, cmap="Blues", vmin=1, vmax=255)
for i in range(8):
    for j in range(8):
        ax.text(j, i, f"{mat_lum[i,j]:d}", ha="center", va="center",
                fontsize=10, color="white" if mat_lum[i,j] > 100 else "black")
ax.set_title("b) Luminance Q-Table (Q=90)", fontsize=14)
ax.axis("off")

ax = axes[2]
ax.imshow(np.abs(y_block_q), cmap="inferno", vmin=0)
for i in range(8):
    for j in range(8):
        v = y_block_q[i,j]
        txt = f"{v:.0f}" if v != 0 else "0"
        ax.text(j, i, txt, ha="center", va="center",
                fontsize=9, color="white" if abs(v) > 5 else "gray",
                fontweight="bold" if v != 0 else "normal")
ax.set_title("c) Quantized DCT\n(round(DCT / Q-table))", fontsize=14)
ax.axis("off")

fig.suptitle("Step 4: Quantization — high-frequency coefficients become zero", fontsize=16, y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "05_quantization_action.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 05_quantization_action.png")

# ── 8. Zigzag ordering ─────────────────────────────────────────────

def zigzag_path():
    result = []
    r, c = 0, 0
    moving_up = True
    for _ in range(64):
        result.append((r, c))
        if moving_up:
            if c == 7:
                r += 1
                moving_up = False
            elif r == 0:
                c += 1
                moving_up = False
            else:
                r -= 1
                c += 1
        else:
            if r == 7:
                c += 1
                moving_up = True
            elif c == 0:
                r += 1
                moving_up = True
            else:
                r += 1
                c -= 1
    return result

zz = zigzag_path()

fig, ax = plt.subplots(1, 1, figsize=(8, 8))
for i in range(9):
    ax.axhline(i - 0.5, color="#ccc", linewidth=0.5)
    ax.axvline(i - 0.5, color="#ccc", linewidth=0.5)

for idx, (r, c) in enumerate(zz):
    if 10 <= idx <= 44:
        color = "red"
        marker = "s"
    elif idx == 0:
        color = "blue"
        marker = "o"
    else:
        color = "#888"
        marker = "o"
    ax.plot(c, r, marker, color=color, markersize=10)
    ax.text(c, r, str(idx), ha="center", va="center", fontsize=6,
            color="white" if 10 <= idx <= 44 else "black")

for i in range(len(zz) - 1):
    r1, c1 = zz[i]
    r2, c2 = zz[i+1]
    dx = c2 - c1
    dy = r2 - r1
    ax.arrow(c1, r1, dx*0.65, dy*0.65, head_width=0.15, head_length=0.15,
             fc="#888", ec="#888", alpha=0.4, length_includes_head=True)

ax.text(3, 0, "DC\n(idx 0)", ha="center", va="bottom", fontsize=9, fontweight="bold", color="blue")
ax.text(5, 7, "Mid-freq (idx 10–44)\nLSB embedding zone", ha="center", va="bottom",
        fontsize=9, color="red", fontweight="bold")
ax.text(6, 5.5, "High-freq (idx 45–63)", ha="center", va="center", fontsize=8, color="#888")

ax.set_xlim(-1, 8)
ax.set_ylim(8, -1)
ax.set_title("Step 5: Zigzag Ordering (DC → low → mid → high frequency)", fontsize=14)
ax.axis("off")
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "06_zigzag_path.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 06_zigzag_path.png")

# ── 9. LSB embedding ──────────────────────────────────────────────

y_block_q_flat = np.array([y_block_q[r,c] for r,c in zz])

fig, axes = plt.subplots(1, 2, figsize=(16, 7))

ax = axes[0]
# Plot stems manually to support per-marker coloring
for i in range(64):
    v = y_block_q_flat[i]
    color = "red" if 10 <= i <= 44 else ("blue" if i == 0 else "#888")
    size = 6 if (10 <= i <= 44 or i == 0) else 3
    ax.plot([i, i], [0, v], color=color, linewidth=0.5, alpha=0.4)
    if v != 0:
        ax.plot(i, v, "o", color=color, markersize=size)
    else:
        ax.plot(i, v, "o", color=color, markersize=2)
ax.axvspan(10, 44, alpha=0.1, color="red", label="Embedding zone (idx 10-44)")
ax.axhline(0, color="black", linewidth=0.5)
ax.set_xlabel("Zigzag Index", fontsize=12)
ax.set_ylabel("Quantized DCT Value", fontsize=12)
ax.set_title("a) One block's quantized DCT in zigzag order", fontsize=14)
ax.legend(fontsize=10)

ax = axes[1]
zone_vals = y_block_q_flat[10:45]
zone_bits = np.array([int(abs(v)) & 1 for v in zone_vals])
x = np.arange(len(zone_vals))
ax.bar(x, zone_vals, color=["#e74c3c" if b == 1 else "#3498db" for b in zone_bits],
       edgecolor="gray", linewidth=0.5)
ax.set_xlabel("Offset in Embedding Zone (idx 10→44)", fontsize=12)
ax.set_ylabel("Coefficient Value", fontsize=12)
ax.set_title("b) Mid-freq coefficients — LSB = embedded watermark bit\n(red=bit 1, blue=bit 0)", fontsize=14)
red_patch = mpatches.Patch(color="#e74c3c", label="LSB = 1")
blue_patch = mpatches.Patch(color="#3498db", label="LSB = 0")
ax.legend(handles=[red_patch, blue_patch], fontsize=10)

fig.suptitle("Step 6: LSB Embedding in Mid-Frequency AC Coefficients", fontsize=16, y=1.02)
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "07_lsb_embedding.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 07_lsb_embedding.png")

# ── 10. Pipeline overview diagram ──────────────────────────────────

fig, ax = plt.subplots(1, 1, figsize=(20, 12))
ax.set_xlim(0, 20)
ax.set_ylim(0, 12)
ax.axis("off")

def box(x, y, w, h, text, color="#e8f4f8", fontsize=11):
    rect = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15",
                          facecolor=color, edgecolor="#333", linewidth=1.5)
    ax.add_patch(rect)
    ax.text(x + w/2, y + h/2, text, ha="center", va="center",
            fontsize=fontsize, fontweight="bold")

def arrow_d(x1, y1, x2, y2, label=""):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="->", color="#555", lw=2))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my+0.2, label, ha="center", va="bottom", fontsize=9, color="#666",
                fontstyle="italic")

# ENCODE pipeline (top)
box(1, 9.5, 2.5, 1.2, "Input Video\n(.mp4)", color="#d5f5e3")
arrow_d(3.5, 10.1, 5, 10.1, "FFmpeg raw YUV420p")
box(5, 9.5, 2.5, 1.2, "YCbCr Bitstream\n6b/5b/5b", color="#d5f5e3")
arrow_d(7.5, 10.1, 9, 10.1)
box(9, 9.5, 2.5, 1.2, "optimized_video.bin\nY:6b Cb:5b Cr:5b", color="#d5f5e3")

# EMBED pipeline (bottom)
box(1, 4, 2.5, 1.2, "Source JPEG\n(50MP)", color="#fdebd0")
arrow_d(3.5, 4.6, 5, 4.6)
box(5, 4, 2.5, 1.2, "Decode to\nYCbCr", color="#fdebd0")
arrow_d(7.5, 4.6, 9, 4.6)
box(9, 4, 2.5, 1.2, "Split into\n8x8 Blocks", color="#fdebd0")
arrow_d(11.5, 4.6, 13, 4.6)
box(13, 4, 2.5, 1.2, "Level Shift\n(-128)", color="#fdebd0")
arrow_d(15.5, 4.6, 17, 4.6)
box(17, 4, 2.5, 1.2, "2D DCT\n(per block)", color="#fdebd0")

arrow_d(17, 3.4, 17, 2.4, "")
arrow_d(17, 2.4, 14.5, 2.4, "")
box(12, 1.8, 2.5, 1.2, "Zigzag\nReorder", color="#d4e6f1")
arrow_d(12, 1.8, 9.5, 1.8, "")
box(7, 1.8, 2.5, 1.2, "LSB Embed\n(mid-freq AC\nidx 10-44)", color="#f5b7b1")
arrow_d(7, 1.8, 4.5, 1.8, "")
box(2, 1.8, 2.5, 1.2, "3x Redundancy\nMajority Voting", color="#f5b7b1")

arrow_d(4.5, 2.4, 7, 2.4, "")
arrow_d(9.5, 2.4, 12, 2.4, "Inv Zigzag")
arrow_d(14, 4.0, 14, 4.6, "")

box(14, 5.3, 2.5, 1.2, "Inverse DCT\n-> Pixel Blocks", color="#fdebd0")
arrow_d(14, 6.6, 14, 7.3, "")
box(14, 7.3, 2.5, 1.2, "Reconstruct\nYCbCr Image", color="#fdebd0")
arrow_d(14, 8.6, 14, 9.3, "")
box(14, 9.3, 2.5, 1.2, "JPEG Encode\n-> modified.jpeg", color="#fdebd0")
arrow_d(12, 10.1, 9, 10.1, "combine")

arrow_d(11.5, 10.1, 9.5, 3.3, "watermark payload")

# dequantize box
bx = FancyBboxPatch((14, 2.9), 2.5, 1.0, boxstyle="round,pad=0.15",
                     facecolor="#d4e6f1", edgecolor="#333", linewidth=1.5)
ax.add_patch(bx)
ax.text(14 + 1.25, 2.9 + 0.5, "Dequantize", ha="center", va="center", fontweight="bold", fontsize=11)

ax.set_title("rrwm Watermarking Pipeline Overview", fontsize=18, fontweight="bold")
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "00_pipeline_overview.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 00_pipeline_overview.png")

# ── 11. Before/after comparison ────────────────────────────────────

MOD_PATH = os.path.join(os.path.dirname(__file__), "..", "output", "modified.jpeg")
if os.path.exists(MOD_PATH):
    mod = PILImage.open(MOD_PATH)
    mod_ycbr = mod.convert("YCbCr")
    MY_np = np.array(mod_ycbr.split()[0], dtype=np.float64)
    MCb_np = np.array(mod_ycbr.split()[1], dtype=np.float64)
    MCr_np = np.array(mod_ycbr.split()[2], dtype=np.float64)

    channels_before = [Y_np, Cb_np, Cr_np]
    channels_after = [MY_np, MCb_np, MCr_np]
    ch_names = ["Y (Luminance)", "Cb (Chroma Blue)", "Cr (Chroma Red)"]

    fig, axes = plt.subplots(2, 3, figsize=(21, 14))
    for col, (ch_b, ch_a, name) in enumerate(zip(channels_before, channels_after, ch_names)):
        r0, r1 = cy-256, cy+256
        c0, c1 = cx-256, cx+256
        ax = axes[0, col]
        ax.imshow(ch_b[r0:r1,c0:c1], cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"Original - {name}", fontsize=13)
        ax.axis("off")

        ax = axes[1, col]
        ax.imshow(ch_a[r0:r1,c0:c1], cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"Watermarked - {name}", fontsize=13)
        ax.axis("off")

    fig.suptitle("Step 7: Original vs Watermarked (512x512 crop)", fontsize=18, y=1.01)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTDIR, "08_before_after.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("  saved 08_before_after.png")

    # Difference map
    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    for col, (ch_b, ch_a, name) in enumerate(zip(channels_before, channels_after, ch_names)):
        r0, r1 = cy-256, cy+256
        c0, c1 = cx-256, cx+256
        diff = ch_a[r0:r1,c0:c1].astype(float) - ch_b[r0:r1,c0:c1].astype(float)
        vmax = max(abs(diff.min()), abs(diff.max()), 1)
        ax = axes[col]
        ax.imshow(diff, cmap=BLUE_RED, vmin=-vmax, vmax=vmax)
        ax.set_title(f"{name} - Difference", fontsize=14)
        ax.axis("off")
    fig.suptitle("Step 7 (detail): Pixel-Level Difference", fontsize=18, y=1.02)
    plt.tight_layout()
    fig.savefig(os.path.join(OUTDIR, "09_difference_map.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("  saved 09_difference_map.png")

    # Extraction pipeline
    fig, ax = plt.subplots(1, 1, figsize=(18, 3.5))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 3.5)
    ax.axis("off")

    steps = [
        (0.5, "Watermarked\nJPEG"),
        (3, "Decode\nYCbCr"),
        (5.5, "8x8\nBlocks"),
        (8, "DCT +\nQuantize"),
        (10.5, "Zigzag\nOrder"),
        (13, "Read LSB\n(idx 10-44)"),
        (15.5, "Majority Vote\n(3x red.)"),
    ]
    colors = ["#fdebd0","#fdebd0","#fdebd0","#d4e6f1","#d4e6f1","#f5b7b1","#f5b7b1"]
    for (x, label), c in zip(steps, colors):
        bx = FancyBboxPatch((x, 0.8), 2.2, 1.8, boxstyle="round,pad=0.1",
                            facecolor=c, edgecolor="#333", linewidth=1.5)
        ax.add_patch(bx)
        ax.text(x+1.1, 1.7, label, ha="center", va="center", fontsize=10, fontweight="bold")
    for i in range(len(steps)-1):
        x1 = steps[i][0] + 2.2
        x2 = steps[i+1][0]
        ax.annotate("", xy=(x2, 1.7), xytext=(x1, 1.7),
                    arrowprops=dict(arrowstyle="->", color="#555", lw=2))

    ax.set_title("Extraction Pipeline (Reverse of Embedding)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(os.path.join(OUTDIR, "10_extract_pipeline.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print("  saved 10_extract_pipeline.png")

# ── 12. Capacity calculation ────────────────────────────────────────

y_blocks_total = (w // 8) * (h // 8)
cbw = (w + 1) // 2
cbh = (h + 1) // 2
cb_blocks_total = (cbw // 8) * (cbh // 8)
cr_blocks_total = cb_blocks_total
total_blocks = y_blocks_total + cb_blocks_total + cr_blocks_total
bits_per_block = 35  # idx 10-44 inclusive
total_bits = total_blocks * bits_per_block
total_bytes = total_bits // 8
usable_bits = (total_bits - 32) // 3  # 32-bit header, then /3 for redundancy
usable_bytes = usable_bits // 8

fig, ax = plt.subplots(1, 1, figsize=(12, 5))
ax.axis("off")
info = [
    f"Image: {w}x{h} ({w*h/1e6:.1f} MP)",
    f"8x8 blocks - Y: {y_blocks_total:,} | Cb: {cb_blocks_total:,} | Cr: {cr_blocks_total:,}",
    f"Total blocks: {total_blocks:,}",
    f"Coefficients per block (embedding zone 10-44): 35",
    f"Total raw bits: {total_bits:,} ({total_bytes/1e6:.1f} MB)",
    f"After 4-byte header + 3x redundancy: ~{usable_bytes/1e6:.1f} MB payload",
]
text = "\n".join(info)
ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=14,
        fontfamily="monospace", transform=ax.transAxes,
        bbox=dict(boxstyle="round", facecolor="#f0f0f0", edgecolor="#ccc", pad=1.0))
ax.set_title("Capacity Breakdown", fontsize=16, fontweight="bold")
plt.tight_layout()
fig.savefig(os.path.join(OUTDIR, "11_capacity.png"), dpi=150, bbox_inches="tight", pad_inches=0.15)
plt.close(fig)
print("  saved 11_capacity.png")

print("\nAll visuals generated successfully!")
