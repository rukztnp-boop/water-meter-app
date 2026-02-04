#!/usr/bin/env python3
"""
🧪 Batch test all images in error folder
"""
import os
import cv2
import numpy as np

def detect_red_digits(image_path):
    """ตรวจสอบว่ามีเลขแดงไหม"""
    img = cv2.imread(image_path)
    if img is None:
        return None, "Failed to load"
    
    H, W = img.shape[:2]
    
    # Convert to HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    
    # Red masks (less aggressive)
    lower_red1 = np.array([0, 70, 70])
    upper_red1 = np.array([15, 255, 255])
    lower_red2 = np.array([165, 70, 70])
    upper_red2 = np.array([180, 255, 255])
    
    mask_red = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    
    # Count red pixels in center region
    y_start = int(H * 0.3)
    y_end = int(H * 0.7)
    x_start = int(W * 0.4)
    
    roi_mask = mask_red[y_start:y_end, x_start:]
    red_pixels = np.sum(roi_mask > 0)
    total_pixels = roi_mask.shape[0] * roi_mask.shape[1]
    red_ratio = red_pixels / total_pixels if total_pixels > 0 else 0
    
    has_red = red_ratio > 0.005  # 0.5%
    
    return has_red, f"red_ratio={red_ratio*100:.2f}%"

def main():
    folder = "./รูป error หลังจากแก้ code วันนี้"
    images = sorted([f for f in os.listdir(folder) if f.endswith('.jpg')])
    
    print(f"🧪 Testing {len(images)} images from: {folder}")
    print("="*70)
    
    red_count = 0
    no_red_count = 0
    
    for img_name in images[:10]:  # Test first 10
        path = os.path.join(folder, img_name)
        has_red, info = detect_red_digits(path)
        
        if has_red:
            print(f"🔴 {img_name}: HAS RED ({info})")
            red_count += 1
        elif has_red is False:
            print(f"⚫ {img_name}: NO RED ({info})")
            no_red_count += 1
        else:
            print(f"❌ {img_name}: ERROR ({info})")
    
    print("="*70)
    print(f"📊 Summary: {red_count} with red, {no_red_count} without red")

if __name__ == "__main__":
    main()
