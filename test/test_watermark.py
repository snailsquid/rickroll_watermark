#!/usr/bin/env python3
"""
rrwm watermark quality test suite.

Tests watermark embedding at multiple JPEG quality levels, measures extraction
fidelity (BER), image distortion (MSE/PSNR/SSIM), and generates all
visualizations for the documentation.
"""

import struct, math, os, sys, json, io, subprocess
import numpy as np
from PIL import Image as PILImage

PILImage.MAX_IMAGE_PIXELS = None

OUTDIR = os.path.join(os.path.dirname(__file__), "output")
IMGDIR = os.path.join(OUTDIR, "images")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUTDIR, exist_ok=True)
os.makedirs(IMGDIR, exist_ok=True)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import matplotlib.patches as mpatches

BLUE_RED = "RdBu_r"
RWM_BIN = os.path.join(ROOT, "rrwm")
ORIG_JPEG = os.path.join(ROOT, "input", "original.jpeg")
PAYLOAD_DIR = os.path.join(OUTDIR, "payloads")
os.makedirs(PAYLOAD_DIR, exist_ok=True)


# ── Helpers ──────────────────────────────────────────────────────────

def run_rrwm(mode, *args, quality=90):
    cmd = f"{RWM_BIN} -quality {quality} {mode} " + " ".join(args)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
    return r.returncode == 0, r.stdout, r.stderr


def ber(orig, extracted):
    if len(orig) != len(extracted):
        return 1.0
    bo = np.unpackbits(np.frombuffer(orig, dtype=np.uint8))
    be = np.unpackbits(np.frombuffer(extracted, dtype=np.uint8))
    return float(np.sum(bo != be)) / len(bo)


def mse(a, b):
    return float(np.mean((a.astype(float) - b.astype(float)) ** 2))


def psnr(m):
    return 100.0 if m < 1e-10 else 20 * math.log10(255.0 / math.sqrt(m))


def ssim(img1, img2):
    C1, C2 = (0.01*255)**2, (0.03*255)**2
    m1, m2 = img1.mean(), img2.mean()
    s1, s2, s12 = img1.var(), img2.var(), ((img1-m1)*(img2-m2)).mean()
    return float((2*m1*m2+C1)*(2*s12+C2) / ((m1**2+m2**2+C1)*(s1+s2+C2)))


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


# ── Main test runner ─────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("rrwm Watermark Quality Test Suite")
    print("=" * 60)

    orig = PILImage.open(ORIG_JPEG)
    w, h = orig.size
    print(f"Source: {w}x{h} ({w*h/1e6:.1f} MP)")

    # Create a smaller test crop for speed (4MP center crop)
    CROP_JPEG = os.path.join(OUTDIR, "test_crop.jpeg")
    crop_size = 2048
    cx, cy = w // 2, h // 2
    crop = orig.crop((cx - crop_size//2, cy - crop_size//2,
                      cx + crop_size//2, cy + crop_size//2))
    crop.save(CROP_JPEG, "JPEG", quality=95)
    print(f"Test crop: {crop_size}x{crop_size} ({crop_size*crop_size/1e6:.1f} MP)")

    # Generate 2 KB test payload
    rng = np.random.RandomState(42)
    payload = rng.bytes(2048)
    payload_path = os.path.join(PAYLOAD_DIR, "test_2048b.bin")
    with open(payload_path, "wb") as f:
        f.write(payload)
    print(f"Payload: {len(payload)} bytes")

    # Test qualities
    qualities = [75, 85, 90, 95, 100]
    results = []

    for q in qualities:
        print(f"\n--- Q={q} ---")
        wm_path = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
        base_path = os.path.join(OUTDIR, f"baseline_q{q}.jpeg")

        ok, out, err = run_rrwm("insert", CROP_JPEG, wm_path, payload_path, quality=q)
        if not ok:
            print(f"  INSERT FAILED: {err}")
            continue

        # Create baseline re-encode (same DCT pipeline, no watermark)
        ok, _, _ = run_rrwm("reencode", CROP_JPEG, base_path, quality=q)
        if not ok:
            print(f"  REENCODE FAILED — falling back to original comparison")
            base_path = ORIG_JPEG

        # Image metrics: compare watermarked vs baseline (isolates watermark-only distortion)
        wm_img = PILImage.open(wm_path)
        base_img = PILImage.open(base_path)
        onp = np.array(base_img.convert("YCbCr"), dtype=np.float64)
        wnp = np.array(wm_img.convert("YCbCr"), dtype=np.float64)
        mse_y = mse(onp[:,:,0], wnp[:,:,0])
        mse_all = mse(onp, wnp)
        psnr_val = psnr(mse_all)
        ssim_val = ssim(onp[:,:,0], wnp[:,:,0])
        flip_rate = float(np.mean(np.abs(onp - wnp) > 0.5)) * 100
        fmtsize = os.path.getsize(wm_path)

        print(f"  MSE(Y)={mse_y:.4f}  PSNR={psnr_val:.1f}dB  SSIM={ssim_val:.6f}  flips={flip_rate:.3f}%  size={fmtsize/1e6:.2f}MB")

        # Extract at same quality
        ext_path = os.path.join(OUTDIR, f"extracted_q{q}.bin")
        ok, _, _ = run_rrwm("extract", wm_path, ext_path, quality=q)
        if ok and os.path.exists(ext_path):
            with open(ext_path, "rb") as f:
                ext_data = f.read()
            ber_val = ber(payload, ext_data)
        else:
            ext_data = None
            ber_val = 1.0
        print(f"  BER={ber_val:.2e}  {'✓ Perfect' if ber_val == 0 else '✗ LOSSY'}")

        # Cross-quality extractions — limit to 2 for speed
        cross = {}
        for xq in [80, 95]:
            if xq == q:
                continue
            xp = os.path.join(OUTDIR, f"extracted_q{q}_at{xq}.bin")
            ok, _, _ = run_rrwm("extract", wm_path, xp, quality=xq)
            if ok and os.path.exists(xp):
                with open(xp, "rb") as f:
                    xd = f.read()
                cross[str(xq)] = ber(payload, xd)
            else:
                cross[str(xq)] = 1.0

        results.append({
            "quality": q, "mse_y": mse_y, "mse_all": mse_all,
            "psnr": psnr_val, "ssim": ssim_val, "ber": ber_val,
            "success": ber_val == 0, "size": fmtsize, "flip_rate": flip_rate,
            "cross": cross,
        })

    with open(os.path.join(OUTDIR, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    return results, orig, CROP_JPEG


# ── Visualization generation ─────────────────────────────────────────

def generate_vis(results, orig, crop_path):
    print("\n" + "=" * 60)
    print("Generating visualizations...")
    print("=" * 60)

    qs = [r["quality"] for r in results]
    bers = [r["ber"] for r in results]
    psnrs = [r["psnr"] for r in results]
    ssims = [r["ssim"] for r in results]
    mses = [r["mse_y"] for r in results]
    sizes = [r["size"] / 1e6 for r in results]
    flips = [r["flip_rate"] for r in results]

    # ── 1. BER vs quality ──────────────────────────────────────────
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
        # Place label above the bar; use fixed offset for zero bars
        yoff = max(1e-6, v * 1.5) if v > 0 else 1e-5
        ax.text(b.get_x() + b.get_width()/2, yoff, lbl, ha="center", va="bottom",
                fontsize=11, fontweight="bold", color="#27ae60" if v == 0 else "#e74c3c")
    plt.tight_layout()
    fig.savefig(os.path.join(IMGDIR, "01_quality_vs_ber.png"), dpi=150, bbox_inches="tight"); plt.close()
    print("  01_quality_vs_ber.png")

    # ── 2. Cross-quality heatmap ───────────────────────────────────
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

    # ── 3. PSNR + SSIM dual-axis ───────────────────────────────────
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
    ax1.set_title("Image Quality Metrics vs JPEG Quality", fontsize=14, fontweight="bold")
    ax1.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(os.path.join(IMGDIR, "03_image_quality_metrics.png"), dpi=150, bbox_inches="tight"); plt.close()
    print("  03_image_quality_metrics.png")

    # ── 4. Before/after visual comparison (baseline vs watermarked) ──
    crop_img = PILImage.open(crop_path)
    cy, cx = crop_img.size[1] // 2, crop_img.size[0] // 2
    cr = 256  # crop radius
    comp_qs = [75, 90, 100]

    fig, axes = plt.subplots(2, 3, figsize=(18, 12))

    for col, q in enumerate(comp_qs):
        wm_path = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
        base_path = os.path.join(OUTDIR, f"baseline_q{q}.jpeg")
        if not os.path.exists(wm_path) or not os.path.exists(base_path):
            axes[0, col].axis("off"); axes[1, col].axis("off"); continue
        
        bc = np.array(PILImage.open(base_path))
        wc = np.array(PILImage.open(wm_path))
        bc = bc[cy-cr:cy+cr, cx-cr:cx+cr]
        wc = wc[cy-cr:cy+cr, cx-cr:cx+cr]

        combined = np.hstack([bc, wc])
        axes[0, col].imshow(combined)
        axes[0, col].axvline(cr, color="white", lw=2, ls="--", alpha=0.7)
        axes[0, col].text(cr//2, 10, f"Re-encode Q={q}", color="white", fontsize=12, fontweight="bold",
                          bbox=dict(facecolor="black", alpha=0.5, pad=2))
        axes[0, col].text(cr + cr//2, 10, "Watermarked", color="white", fontsize=12, fontweight="bold",
                          bbox=dict(facecolor="black", alpha=0.5, pad=2))
        axes[0, col].set_title(f"Baseline vs Watermarked (Q={q})", fontsize=14, fontweight="bold")
        axes[0, col].axis("off")

        diff = np.abs(bc.astype(float) - wc.astype(float))
        diff_gray = np.mean(diff, axis=2)
        vmax = max(diff_gray.max(), 1)
        axes[1, col].imshow(diff_gray, cmap="inferno", vmin=0, vmax=min(vmax, 10))
        axes[1, col].set_title(f"Watermark-only Difference\nMSE={mse(bc, wc):.4f}", fontsize=11)
        axes[1, col].axis("off")

    fig.suptitle("Visual Comparison: Baseline Re-encode vs Watermarked at Different JPEG Qualities",
                 fontsize=16, fontweight="bold", y=1.01)
    plt.tight_layout()
    fig.savefig(os.path.join(IMGDIR, "04_before_after_comparison.png"), dpi=150, bbox_inches="tight"); plt.close()
    print("  04_before_after_comparison.png")

    # ── 5. File size vs quality ────────────────────────────────────
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

    # ── 6. Degradation overlay ─────────────────────────────────────
    fig, ax1 = plt.subplots(figsize=(10, 6))
    l1 = ax1.plot(qs, bers, "o-", color="#e74c3c", lw=3, ms=8, label="BER")
    ax1.set_xlabel("JPEG Quality", fontsize=14)
    ax1.set_ylabel("Bit Error Rate", fontsize=14, color="#e74c3c")
    ax1.tick_params(axis="y", labelcolor="#e74c3c")
    ax1.axhspan(0, 1e-4, alpha=0.08, color="green", label="Perfect zone")
    ax1.axhspan(1e-4, 1e-2, alpha=0.08, color="gold", label="Tolerable")
    ax1.axhspan(1e-2, max(bers)*1.1, alpha=0.08, color="red", label="Lossy")
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

    # ── 7. Pixel flip rate ─────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(qs, flips, "o-", color="#c0392b", lw=2.5, ms=8)
    ax.fill_between(qs, flips, alpha=0.15, color="#c0392b")
    for q, v in zip(qs, flips):
        ax.annotate(f"{v:.3f}%", (q, v), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=10, fontweight="bold", color="#c0392b")
    ax.set_xlabel("JPEG Quality", fontsize=14)
    ax.set_ylabel("Pixel Difference Rate (%)", fontsize=14)
    ax.set_title("Watermark-Induced Pixel Changes vs JPEG Quality", fontsize=14, fontweight="bold")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(os.path.join(IMGDIR, "07_pixel_flip_rate.png"), dpi=150, bbox_inches="tight"); plt.close()
    print("  07_pixel_flip_rate.png")

    # ── 8. LSB embedding detail walkthrough ────────────────────────
    from scipy.fftpack import dct as scipy_dct

    def dct2d(b):
        return scipy_dct(scipy_dct(b - 128, axis=0, norm='ortho'), axis=1, norm='ortho')

    lum_q = [16, 11, 10, 16, 24, 40, 51, 61,
             12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
             14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77,
             24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103, 121, 120, 101,
             72, 92, 95, 98, 112, 100, 103, 99]

    def scale_q(base, q):
        s = 5000/q if q < 50 else 200 - q*2
        return np.array([max(1, min(255, int((v*s+50)/100))) for v in base])

    zz = zigzag_path()

    # Single block at Q=90
    qv = 90
    base_path = os.path.join(OUTDIR, f"baseline_q{qv}.jpeg")
    wm_path = os.path.join(OUTDIR, f"watermarked_q{qv}.jpeg")

    # Load baseline (re-encode at same quality, no watermark)
    bny = np.array(PILImage.open(base_path).convert("YCbCr"), dtype=np.float64)[:,:,0]
    blk_base = bny[cy-64:cy-56, cx-64:cx-56]
    dct_base = dct2d(blk_base)
    qt = scale_q(lum_q, qv).reshape(8, 8)
    qdct_base = np.round(dct_base / qt)

    # Load watermarked
    wny = np.array(PILImage.open(wm_path).convert("YCbCr"), dtype=np.float64)[:,:,0]
    blk_wm = wny[cy-64:cy-56, cx-64:cx-56]
    dct_wm = dct2d(blk_wm)
    qdct_wm = np.round(dct_wm / qt)

    zz_base = np.array([qdct_base[r,c] for r,c in zz])
    zz_wm = np.array([qdct_wm[r,c] for r,c in zz])

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    ax = axes[0]
    zz_colors = []
    for i in range(64):
        if 10 <= i <= 44: zz_colors.append("#e74c3c")
        elif i == 0: zz_colors.append("#3498db")
        else: zz_colors.append("#95a5a6")
    ax.bar(range(64), np.abs(zz_base), color=zz_colors, edgecolor="#333", lw=0.3)
    ax.axvspan(9.5, 44.5, alpha=0.08, color="red", label="Embedding zone (idx 10-44)")
    ax.set_yscale("symlog")
    ax.set_xlabel("Zigzag Index", fontsize=12)
    ax.set_ylabel("|Quantized DCT Value|", fontsize=12)
    ax.set_title("Quantized DCT in Zigzag Order (Baseline Re-encode)", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10); ax.grid(axis="y", alpha=0.3)

    ax = axes[1]
    lsb_orig = np.array([int(abs(v)) & 1 for v in zz_base[10:45]])
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
    ax.set_title(f"After Embedding (Q={qv})\nRed=lsb1 Blue=lsb0 Gold=flipped", fontsize=13, fontweight="bold")
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

    # ── 9. Embedding zone per-quality comparison ────────────────────
    embed_qs = [75, 85, 90, 95, 100]
    fig, axes = plt.subplots(2, len(embed_qs), figsize=(25, 10))
    
    for idx, q in enumerate(embed_qs):
        wmp = os.path.join(OUTDIR, f"watermarked_q{q}.jpeg")
        bp = os.path.join(OUTDIR, f"baseline_q{q}.jpeg")
        if not os.path.exists(wmp) or not os.path.exists(bp): continue
        
        wny2 = np.array(PILImage.open(wmp).convert("YCbCr"), dtype=np.float64)[:,:,0]
        bny = np.array(PILImage.open(bp).convert("YCbCr"), dtype=np.float64)[:,:,0]
        bw = bny[cy-64:cy-56, cx-64:cx-56]
        ww = wny2[cy-64:cy-56, cx-64:cx-56]
        dw_b = dct2d(bw)
        dw_w = dct2d(ww)
        qtw = scale_q(lum_q, q).reshape(8, 8)
        qdw_b = np.round(dw_b / qtw)
        qdw_w = np.round(dw_w / qtw)
        zzw_b = np.array([qdw_b[r,c] for r,c in zz])
        zzw_w = np.array([qdw_w[r,c] for r,c in zz])
        
        ax = axes[0, idx]
        lsb_w = np.array([int(abs(v)) & 1 for v in zzw_w[10:45]])
        bc2 = ["#e74c3c" if b == 1 else "#3498db" for b in lsb_w]
        ax.bar(range(35), zzw_w[10:45], color=bc2, edgecolor="#333", lw=0.3)
        ax.set_title(f"Q={q} Watermarked Zone", fontsize=12)
        ax.set_xlabel("Coeff offset"); ax.set_ylabel("Value")
        ax.grid(axis="y", alpha=0.3)
        
        ax = axes[1, idx]
        diff_from_base = zzw_w[10:45] - zzw_b[10:45]
        dcolors = ["#27ae60" if d == 0 else "#e74c3c" for d in diff_from_base]
        ax.bar(range(35), diff_from_base, color=dcolors, edgecolor="#333", lw=0.3)
        ax.set_title(f"Δ from Baseline (Q={q})", fontsize=12)
        ax.set_xlabel("Coeff offset"); ax.set_ylabel("Δ Value")
        ax.grid(axis="y", alpha=0.3)
    
    fig.suptitle("Embedding Zone Comparison Across Quality Levels", fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    fig.savefig(os.path.join(IMGDIR, "09_embedding_zone_comparison.png"), dpi=150, bbox_inches="tight"); plt.close()
    print("  09_embedding_zone_comparison.png")

    # ── Print summary table ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    hdr = f"{'Q':>4} | {'BER':>12} | {'PSNR':>8} | {'SSIM':>8} | {'MSE(Y)':>10} | {'Size':>10} | {'Flips':>8} | Status"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        st = "✓" if r["success"] else "✗"
        print(f"{r['quality']:>4d} | {r['ber']:>12.2e} | {r['psnr']:>7.1f} | {r['ssim']:>8.6f} | {r['mse_y']:>10.4f} | {r['size']/1e6:>8.2f}MB | {r['flip_rate']:>7.3f}% | {st}")

    # Save summary markdown
    md = ["## Test Results Summary\n",
          "| Quality | BER | PSNR (dB) | SSIM | MSE (Y) | File Size | Pixel Flips | Extraction |",
          "|---------|-----|-----------|------|---------|-----------|-------------|------------|"]
    for r in results:
        st = "Perfect" if r["success"] else "Failed"
        md.append(f"| {r['quality']} | {r['ber']:.2e} | {r['psnr']:.1f} | {r['ssim']:.6f} | {r['mse_y']:.4f} | {r['size']/1e6:.2f} MB | {r['flip_rate']:.3f}% | {st} |")
    with open(os.path.join(OUTDIR, "summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")

    print(f"\nDone. Summary → {os.path.join(OUTDIR, 'summary.md')}")
    return results


if __name__ == "__main__":
    r, o, c = run_all()
    generate_vis(r, o, c)
