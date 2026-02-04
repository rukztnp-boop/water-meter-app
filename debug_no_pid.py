#!/usr/bin/env python3
"""
🔍 Debug NO_PID cases - check why point_id not detected
"""
import os
import json
from google.cloud import vision
from google.oauth2 import service_account

# Load credentials
with open('service_account.json', 'r') as f:
    key_dict = json.load(f)

creds = service_account.Credentials.from_service_account_info(
    key_dict,
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
client = vision.ImageAnnotatorClient(credentials=creds)

def debug_point_id(image_path):
    """Debug point_id detection"""
    print(f"\n{'='*70}")
    print(f"Testing: {os.path.basename(image_path)}")
    print('='*70)
    
    with open(image_path, 'rb') as f:
        content = f.read()
    
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    
    if not response.text_annotations:
        print("❌ No text detected")
        return
    
    full_text = response.text_annotations[0].description
    
    print(f"\n📄 Full OCR Text:")
    print(full_text)
    print("\n" + "="*70)
    
    # Normalize text
    normalized = full_text.upper().replace('\n', ' ').replace('_', ' ')
    print(f"\n📝 Normalized: {normalized[:200]}")
    
    # Try to find point_id patterns
    import re
    
    patterns = [
        r'\b([A-Z]{1,4})[_\s]+([A-Z0-9_\s]{2,})\b',  # Current pattern
        r'\b([A-Z]{2,4})[_\s]([A-Z0-9]{2,})[_\s]([0-9]{1,3})\b',  # XX_YYY_123
        r'\b([A-Z]{2})[_\s]([A-Z0-9]+)[_\s]([0-9]+)\b',  # XX_ABC_123
    ]
    
    print(f"\n🔍 Testing patterns:")
    for i, pattern in enumerate(patterns, 1):
        matches = re.findall(pattern, normalized)
        print(f"   Pattern {i}: {pattern}")
        if matches:
            print(f"      Found: {matches[:5]}")
        else:
            print(f"      No match")
    
    # Check individual words
    words = [w.description for w in response.text_annotations[1:]]
    print(f"\n📝 Individual words ({len(words)} total):")
    for word in words[:30]:
        print(f"   - {word}")

def main():
    folder = "./รูป error หลังจากแก้ code วันนี้"
    
    no_pid_images = [
        "S__154140725_0.jpg",
        "S__154140677_0.jpg",
    ]
    
    for img_name in no_pid_images:
        path = os.path.join(folder, img_name)
        if os.path.exists(path):
            debug_point_id(path)
        else:
            print(f"❌ Not found: {img_name}")

if __name__ == "__main__":
    main()
