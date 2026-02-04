#!/usr/bin/env python3
"""
🧪 Debug VSD meter OCR failures
"""
import os
import sys
import cv2
import numpy as np
from google.cloud import vision
from google.oauth2 import service_account
import json

# Load credentials
with open('service_account.json', 'r') as f:
    key_dict = json.load(f)

creds = service_account.Credentials.from_service_account_info(
    key_dict,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
client = vision.ImageAnnotatorClient(credentials=creds)

def vision_ocr_with_boxes(image_path):
    """Run Vision OCR and return text with bounding boxes"""
    with open(image_path, 'rb') as f:
        content = f.read()
    
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    
    if not response.text_annotations:
        return [], ""
    
    # Full text
    full_text = response.text_annotations[0].description
    
    # Individual words with boxes
    words = []
    for annotation in response.text_annotations[1:]:
        vertices = annotation.bounding_poly.vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        
        x = min(x_coords)
        y = min(y_coords)
        w = max(x_coords) - x
        h = max(y_coords) - y
        
        words.append({
            'text': annotation.description,
            'bbox': (x, y, w, h)
        })
    
    return words, full_text

def group_words_into_lines(words, tolerance=10):
    """Group words into lines by Y coordinate"""
    if not words:
        return []
    
    # Sort by Y coordinate
    sorted_words = sorted(words, key=lambda w: w['bbox'][1])
    
    lines = []
    current_line = [sorted_words[0]]
    current_y = sorted_words[0]['bbox'][1]
    
    for word in sorted_words[1:]:
        y = word['bbox'][1]
        
        if abs(y - current_y) <= tolerance:
            current_line.append(word)
        else:
            lines.append(current_line)
            current_line = [word]
            current_y = y
    
    if current_line:
        lines.append(current_line)
    
    return lines

def fuzzy_match(s1, s2):
    """Simple fuzzy matching"""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

def extract_previous_day_kwh(words):
    """Extract 'Previous day kWh' value"""
    lines = group_words_into_lines(words, tolerance=15)
    
    print(f"📝 Found {len(lines)} lines:")
    for i, line in enumerate(lines):
        line_text = ' '.join([w['text'] for w in line])
        print(f"   Line {i+1}: {line_text}")
    
    # Find line with "Previous day kWh" (NOT "Previous hour kWh")
    target_line = None
    target_score = 0
    target_idx = -1
    
    for i, line in enumerate(lines):
        line_text = ' '.join([w['text'] for w in line]).lower()
        score = 0
        
        # 🔥 Must have "previous" + "day" but NOT "hour"
        has_previous = any(kw in line_text for kw in ["previous", "previos", "previ0us", "previou"])
        has_day = "day" in line_text
        has_hour = "hour" in line_text
        
        if has_previous and has_day and not has_hour:
            # Perfect match: "previous" + "day" without "hour"
            score = 100
        elif has_previous and not has_hour:
            # Has "previous" but no "hour" (may or may not have day)
            score = 80
        elif has_previous and has_hour:
            # Has "previous" + "hour" → skip this line
            continue
        
        # Pattern 2: "01.53"
        import re
        if re.search(r"01\s*[.\s]\s*53", line_text):
            score = max(score, 90)
        
        # Pattern 3: "kwh"
        if "kwh" in line_text or "kw h" in line_text:
            score += 30
        
        if score > target_score:
            target_score = score
            target_line = line
            target_idx = i
    
    if not target_line or target_score < 50:
        print("\n❌ Could not find 'Previous day kWh' line")
        return None
    
    line_text = ' '.join([w['text'] for w in target_line]).lower()
    print(f"\n✅ Found target line {target_idx+1} (score={target_score}): {line_text}")
    
    # Extract rightmost number (skip menu codes like 01.53)
    numbers = []
    import re
    for word in target_line:
        text = word['text'].replace(',', '').replace(' ', '')
        
        # Skip menu codes (01.XX, 02.XX)
        if re.match(r'^0[0-9]\.[0-9]{2}$', text):
            continue
        
        try:
            num = float(text)
            x = word['bbox'][0]
            numbers.append((num, x, text))
        except:
            continue
    
    if numbers:
        numbers.sort(key=lambda n: n[1], reverse=True)  # Sort by X (rightmost first)
        value = numbers[0][0]
        print(f"   → Extracted value: {value}")
        return value
    
    print("\n❌ No valid number found in target line")
    return None

def test_vsd_meter(image_path):
    """Test VSD meter OCR"""
    print(f"\n{'='*70}")
    print(f"Testing: {os.path.basename(image_path)}")
    print('='*70)
    
    # Load image
    img = cv2.imread(image_path)
    if img is None:
        print("❌ Failed to load image")
        return
    
    H, W = img.shape[:2]
    print(f"📐 Image size: {W}x{H}")
    
    # Run OCR
    words, full_text = vision_ocr_with_boxes(image_path)
    print(f"📝 OCR found {len(words)} words")
    
    # Try to extract value
    value = extract_previous_day_kwh(words)
    
    if value is not None:
        print(f"\n✅ SUCCESS: {value}")
    else:
        print(f"\n❌ FAILED to extract value")
        print(f"\n📄 Full OCR text preview:")
        print(full_text[:500])

def main():
    folder = "./รูป error หลังจากแก้ code วันนี้"
    
    vsd_images = [
        "S__154140713_0.jpg",  # GI_VSD NO_2
        "S__154140714_0.jpg",  # GH_VSD NO_1
        "S__154140715_0.jpg",  # GJ_VSD NO_3
        "S__154140716_0.jpg",  # GK_VSD NO_4
    ]
    
    for img_name in vsd_images:
        path = os.path.join(folder, img_name)
        if os.path.exists(path):
            test_vsd_meter(path)
        else:
            print(f"❌ Not found: {img_name}")

if __name__ == "__main__":
    main()
