#!/usr/bin/env python3
"""
🧪 Test spatial cropping for analog meters (red digit removal)
ทดสอบว่า spatial analysis ตัดเลขแดงออกได้ถูกต้อง
"""
import sys
import os
import cv2
import numpy as np

# Import only image processing functions (not the full app)
def test_analog_spatial_crop():
    """
    ทดสอบด้วยรูปที่ user ส่งมา: meter แสดง 00091 (black) + 342 (red)
    คาดหวัง: spatial cropping ตัด red digits ออกได้
    """
    
    # Test with first image in error folder
    error_folder = "./รูป error หลังจากแก้ code วันนี้"
    
    if not os.path.exists(error_folder):
        print(f"❌ Folder not found: {error_folder}")
        return False
    
    # Get first jpg file
    images = [f for f in os.listdir(error_folder) if f.endswith('.jpg')]
    if not images:
        print(f"❌ No images found in {error_folder}")
        return False
    
    test_image = os.path.join(error_folder, images[0])
    print(f"📁 Using image: {images[0]}")
    
    print(f"🧪 Testing spatial crop with: {test_image}")
    print("="*60)
    
    # Read image
    img = cv2.imread(test_image)
    if img is None:
        print(f"❌ Failed to load image: {test_image}")
        return False
    
    H, W = img.shape[:2]
    print(f"📐 Original size: {W}x{H}")
    
    # 🔥 มองเฉพาะบริเวณกลาง (30-70% ความสูง) เพื่อหลีกเลี่ยง noise
    y_start = int(H * 0.3)
    y_end = int(H * 0.7)
    roi_img = img[y_start:y_end, :].copy()
    print(f"📍 ROI: y={y_start}-{y_end} (center {(y_end-y_start)/H*100:.0f}%)")
    
    # Convert to HSV and detect red regions
    hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    
    # Red color masks (aggressive)
    lower_red1 = np.array([0, 40, 40])
    upper_red1 = np.array([25, 255, 255])
    lower_red2 = np.array([155, 40, 40])
    upper_red2 = np.array([180, 255, 255])
    
    mask_red = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    
    # Find contours of red regions
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    contours, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Find rightmost significant red region (เลขแดงมักมี area ใหญ่กว่า noise)
    red_left_boundary = W  # เริ่มจากขวาสุด
    significant_red_regions = []
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 200:  # Skip small noise (เพิ่มจาก 50 → 200)
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        
        # 🔥 Filter: ต้องมี aspect ratio เหมือนตัวเลข (สูงกว่ากว้าง หรือเกือบจะสี่เหลี่ยม)
        aspect_ratio = h / w if w > 0 else 0
        if aspect_ratio < 0.5 or aspect_ratio > 5:  # Skip horizontal/vertical lines
            continue
        
        # 🔥 Filter: ต้องอยู่ด้านขวา (>40% ของความกว้าง)
        if x < W * 0.4:
            continue
        
        significant_red_regions.append((x, y, w, h, area))
        
        # เลขแดงมักอยู่ขวาสุด - เก็บตำแหน่งซ้ายสุดของ red region
        if x < red_left_boundary:
            red_left_boundary = x
    
    print(f"🔍 Significant red regions (after filtering): {len(significant_red_regions)}")
    for i, (x, y, w, h, area) in enumerate(significant_red_regions[:5]):
        print(f"   Region {i+1}: x={x}, y={y}, w={w}, h={h}, area={area:.0f}, aspect={h/w:.2f}")
    
    print(f"🔍 Red left boundary: x={red_left_boundary} (W={W}, {red_left_boundary/W*100:.1f}%)")
    
    # ถ้าเจอเลขแดง ให้ crop เฉพาะส่วนซ้าย (เลขดำ)
    if red_left_boundary < W * 0.9:  # มีเลขแดงจริง
        # Crop เฉพาะจนถึงก่อนเลขแดง (เผื่อ buffer 10px)
        crop_right = red_left_boundary - 10
        
        if crop_right > W * 0.3:  # ต้องมีพื้นที่เหลือพอ (>30%)
            img_cropped = img[:, :crop_right].copy()
            
            print(f"✂️ Cropped: 0:{crop_right} (removed {W-crop_right}px = {100*(W-crop_right)/W:.1f}%)")
            
            # Save results
            cv2.imwrite("debug_original.jpg", img)
            cv2.imwrite("debug_red_mask.jpg", mask_red)
            cv2.imwrite("debug_cropped.jpg", img_cropped)
            
            print("\n📊 RESULT:")
            print(f"   ✅ Original: {W}x{H} → Cropped: {img_cropped.shape[1]}x{img_cropped.shape[0]}")
            print(f"   ✅ Saved: debug_original.jpg, debug_red_mask.jpg, debug_cropped.jpg")
            
            return True
        else:
            print(f"❌ Crop region too small: {crop_right}px ({100*crop_right/W:.1f}%)")
            return False
    else:
        print(f"❌ No significant red regions detected")
        return False

if __name__ == "__main__":
    success = test_analog_spatial_crop()
    sys.exit(0 if success else 1)
