#!/usr/bin/env python3
"""
🧪 Test final spatial cropping with actual images
"""
import cv2
import numpy as np
import os

def test_spatial_crop(image_path):
    """Test spatial cropping algorithm"""
    img = cv2.imread(image_path)
    if img is None:
        return False, "Failed to load"
    
    H, W = img.shape[:2]
    
    # Step 1: ROI (center 40%)
    y_start = int(H * 0.3)
    y_end = int(H * 0.7)
    roi_img = img[y_start:y_end, :].copy()
    
    # Step 2: HSV + Red detection
    hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    
    lower_red1 = np.array([0, 50, 50])
    upper_red1 = np.array([20, 255, 255])
    lower_red2 = np.array([160, 50, 50])
    upper_red2 = np.array([180, 255, 255])
    
    mask_red = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    contours, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Step 3: Find leftmost significant red region
    red_left_boundary = W
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 100:
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = h / w if w > 0 else 0
        
        if aspect < 0.3 or aspect > 8:
            continue
        
        if x < W * 0.35:
            continue
        
        if x < red_left_boundary:
            red_left_boundary = x
    
    # Step 4: Crop
    if red_left_boundary < W * 0.9:
        crop_right = red_left_boundary - 10
        
        if crop_right > W * 0.3:
            img_cropped = img[:, :crop_right].copy()
            removed_pct = (W - crop_right) / W * 100
            
            return True, f"Cropped at x={crop_right} (removed {removed_pct:.1f}%)"
    
    return False, "No red region detected"

def main():
    folder = "./รูป error หลังจากแก้ code วันนี้"
    images = sorted([f for f in os.listdir(folder) if f.endswith('.jpg')])[:10]
    
    print("🧪 Testing spatial cropping on 10 images")
    print("="*70)
    
    success_count = 0
    
    for img_name in images:
        path = os.path.join(folder, img_name)
        success, msg = test_spatial_crop(path)
        
        if success:
            print(f"✅ {img_name}: {msg}")
            success_count += 1
        else:
            print(f"❌ {img_name}: {msg}")
    
    print("="*70)
    print(f"📊 Success: {success_count}/{len(images)}")

if __name__ == "__main__":
    main()
