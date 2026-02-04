#!/usr/bin/env python3
"""
🔍 Extract text from screenshots using OCR
"""
import os
import sys

# Check if we can use Google Vision API
try:
    from google.cloud import vision
    from google.oauth2 import service_account
    import json
    
    # Load credentials
    if os.path.exists('service_account.json'):
        with open('service_account.json', 'r') as f:
            key_dict = json.load(f)
        
        creds = service_account.Credentials.from_service_account_info(
            key_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        client = vision.ImageAnnotatorClient(credentials=creds)
        has_vision = True
    else:
        has_vision = False
        print("⚠️ service_account.json not found, using basic analysis")
except ImportError:
    has_vision = False
    print("⚠️ Google Vision API not available")

def analyze_screenshot(filepath):
    """Analyze screenshot with Vision API"""
    if not has_vision:
        return None
    
    with open(filepath, 'rb') as f:
        content = f.read()
    
    image = vision.Image(content=content)
    response = client.text_detection(image=image)
    
    if response.text_annotations:
        full_text = response.text_annotations[0].description
        return full_text
    
    return None

def main():
    folder = "./error หลังอัพเดท 23.26"
    files = sorted([f for f in os.listdir(folder) if f.endswith('.png')])
    
    print("🔍 Analyzing screenshots with OCR...")
    print("="*70)
    
    for i, filename in enumerate(files, 1):
        filepath = os.path.join(folder, filename)
        print(f"\n{i}. {filename}")
        print("-"*70)
        
        text = analyze_screenshot(filepath)
        if text:
            # Print first 500 characters
            preview = text[:800] if len(text) > 800 else text
            print(preview)
            if len(text) > 800:
                print(f"\n... (total {len(text)} characters)")
        else:
            print("❌ Could not extract text")
        print()

if __name__ == "__main__":
    main()
