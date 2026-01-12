# --- SCADA OCR Fix Snippets (drop into your Streamlit app) ---
# Key idea:
# 1) Crop ROI from the ORIGINAL image BEFORE any resizing (preserve digit detail)
# 2) Upscale the ROI a lot (SCADA digits are small)
# 3) Try multiple pre-processing variants (raw / sharpen / threshold / invert)
# 4) If Vision fails, SHOW the error instead of silently returning 0

import math
import numpy as np
import cv2

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def crop_roi_preserve_resolution(img_bgr, roi_x1, roi_y1, roi_x2, roi_y2, pad=0.02):
    """
    roi_* can be relative (0..1) OR pixel coordinates.
    Crops from the ORIGINAL image (no pre-resize), then returns the ROI image.
    """
    H, W = img_bgr.shape[:2]

    # relative ROI
    if 0 < roi_x2 <= 1 and 0 < roi_y2 <= 1:
        x1 = int(_clamp01(roi_x1) * W)
        y1 = int(_clamp01(roi_y1) * H)
        x2 = int(_clamp01(roi_x2) * W)
        y2 = int(_clamp01(roi_y2) * H)
    else:
        x1, y1, x2, y2 = int(roi_x1), int(roi_y1), int(roi_x2), int(roi_y2)

    # sanitize order
    if x2 < x1: x1, x2 = x2, x1
    if y2 < y1: y1, y2 = y2, y1

    # pad
    dx = int((x2 - x1) * pad)
    dy = int((y2 - y1) * pad)
    x1 = max(0, x1 - dx); y1 = max(0, y1 - dy)
    x2 = min(W, x2 + dx); y2 = min(H, y2 + dy)

    if x2 <= x1 or y2 <= y1:
        return None

    return img_bgr[y1:y2, x1:x2].copy()

def scada_vision_variants(img_bgr):
    """
    Returns list[(label, img_bgr_or_gray)] to try with Vision.
    """
    variants = []
    variants.append(("raw", img_bgr))

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # upscale strongly (SCADA digits are tiny)
    h, w = gray.shape[:2]
    target_min = 650  # increase if still failing
    scale = max(1.0, target_min / max(1, min(h, w)))
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # contrast
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray2 = clahe.apply(gray)

    # sharpen
    kernel = np.array([[0,-1,0],[-1,5,-1],[0,-1,0]], np.float32)
    sharp = cv2.filter2D(gray2, -1, kernel)

    # threshold (both normal + inverted)
    _, th = cv2.threshold(sharp, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    inv = 255 - th

    variants.extend([
        ("gray_sharp", sharp),
        ("th_otsu", th),
        ("inv_otsu", inv),
    ])
    return variants
