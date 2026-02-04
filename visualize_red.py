#!/usr/bin/env python3
"""
🔍 Visualize red detection for debugging
"""
import cv2
import numpy as np
import sys

def visualize_red_detection(image_path):
    img = cv2.imread(image_path)
    if img is None:
        print(f"❌ Failed to load: {image_path}")
        return
    
    H, W = img.shape[:2]
    print(f"📐 Image: {W}x{H}")
    
    # ROI
    y_start = int(H * 0.3)
    y_end = int(H * 0.7)
    roi_img = img[y_start:y_end, :].copy()
    
    # HSV
    hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
    
    # Red masks (less aggressive)
    lower_red1 = np.array([0, 50, 50])
    upper_red1 = np.array([20, 255, 255])
    lower_red2 = np.array([160, 50, 50])
    upper_red2 = np.array([180, 255, 255])
    
    mask_red = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    
    # Morphology
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask_red = cv2.morphologyEx(mask_red, cv2.MORPH_CLOSE, kernel, iterations=2)
    
    contours, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    print(f"🔍 Total contours: {len(contours)}")
    
    # Draw all contours
    roi_with_boxes = roi_img.copy()
    significant = []
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 100:
            continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = h / w if w > 0 else 0
        
        # Less strict filtering
        if aspect < 0.3 or aspect > 8:
            continue
        
        if x < W * 0.35:  # More lenient (was 0.4)
            continue
        
        significant.append((x, y, w, h, area, aspect))
        cv2.rectangle(roi_with_boxes, (x, y), (x+w, y+h), (0, 255, 0), 2)
        cv2.putText(roi_with_boxes, f"{int(area)}", (x, y-5), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    
    print(f"🔍 Significant regions: {len(significant)}")
    for i, (x, y, w, h, area, aspect) in enumerate(significant[:10]):
        print(f"   {i+1}. x={x}, y={y}, w={w}, h={h}, area={int(area)}, aspect={aspect:.2f}")
    
    # Save visualization
    cv2.imwrite("debug_roi.jpg", roi_img)
    cv2.imwrite("debug_mask.jpg", mask_red)
    cv2.imwrite("debug_boxes.jpg", roi_with_boxes)
    
    print("\n✅ Saved: debug_roi.jpg, debug_mask.jpg, debug_boxes.jpg")
    
    if significant:
        leftmost = min(significant, key=lambda r: r[0])
        print(f"\n🎯 Leftmost red region: x={leftmost[0]} ({leftmost[0]/W*100:.1f}%)")

if __name__ == "__main__":
    image = "./รูป error หลังจากแก้ code วันนี้/S__154140675_0.jpg"
    visualize_red_detection(image)
