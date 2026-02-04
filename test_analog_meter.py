#!/usr/bin/env python3
"""
🧪 Test Analog Meter Reading
ทดสอบการอ่านค่ามิเตอร์อนาล็อก พร้อม debug รายละเอียด
"""

import sys
from pathlib import Path
import cv2
import numpy as np

def test_analog_meter(image_path, expected_value=None):
    """ทดสอบมิเตอร์อนาล็อกเดียว"""
    
    print("=" * 70)
    print(f"🧪 Testing Analog Meter: {Path(image_path).name}")
    print("=" * 70)
    
    # Import functions
    try:
        from app import (
            ocr_process,
            preprocess_image_cv,
            _detect_analog_digit_window,
            is_analog_meter
        )
    except ImportError as e:
        print(f"❌ Error importing: {e}")
        return
    
    # Read image
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    print(f"✅ อ่านภาพขนาด {len(image_bytes):,} bytes\n")
    
    # Mock config for analog water meter
    config = {
        "point_id": "TEST_ANALOG",
        "type": "Water",
        "name": "Analog Water Meter",
        "keyword": "",
        "decimals": 0,
        "expected_digits": 5,
        "allow_negative": "FALSE"
    }
    
    print(f"📋 Config: {config['name']}")
    print(f"   Expected digits: {config['expected_digits']}")
    print(f"   Decimals: {config['decimals']}\n")
    
    # Test digit window detection
    print("-" * 70)
    print("🔍 Step 1: Auto Digit Window Detection")
    print("-" * 70)
    
    # Decode image for digit window test
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is not None:
        digit_window, bbox = _detect_analog_digit_window(img, debug=True)
        
        if digit_window is not None and bbox:
            print(f"\n✅ Digit window detected: {bbox}")
            
            # Save digit window for inspection
            output_path = Path(image_path).stem + "_digit_window.jpg"
            cv2.imwrite(output_path, digit_window)
            print(f"💾 Saved digit window to: {output_path}")
        else:
            print("\n⚠️ Digit window not detected - will use full image")
    
    # Test preprocessing
    print("\n" + "-" * 70)
    print("🔍 Step 2: Preprocessing (Red Digit Removal)")
    print("-" * 70)
    
    for variant in ["raw", "auto"]:
        processed = preprocess_image_cv(image_bytes, config, use_roi=True, variant=variant)
        
        # Save preprocessed image
        output_path = Path(image_path).stem + f"_preprocessed_{variant}.png"
        with open(output_path, 'wb') as f:
            f.write(processed)
        
        print(f"💾 Saved {variant} preprocessing to: {output_path}")
    
    # Test OCR
    print("\n" + "-" * 70)
    print("🔍 Step 3: OCR Reading")
    print("-" * 70)
    
    try:
        value, candidates = ocr_process(
            image_bytes,
            config,
            debug=True,
            return_candidates=True,
            use_roboflow=False
        )
        
        print("\n" + "=" * 70)
        print("📊 Results:")
        print("=" * 70)
        print(f"  อ่านค่าได้: {value:.0f}")
        
        if expected_value is not None:
            diff = abs(value - expected_value)
            match = "✅" if diff < 1 else "❌"
            accuracy = (1 - diff/expected_value) * 100 if expected_value > 0 else 0
            
            print(f"  คาดหวัง:   {expected_value:.0f}")
            print(f"  ความแม่นยำ: {accuracy:.1f}%")
            print(f"  {match} ผลการทดสอบ: {'PASS' if diff < 1 else 'FAIL'}")
        
        if candidates:
            print(f"\n🎯 Top 5 Candidates:")
            for i, cand in enumerate(candidates[:5], 1):
                val = cand.get('val', 0)
                score = cand.get('score', 0)
                tag = cand.get('tag', 'unknown')
                print(f"  {i}. {val:.0f} (score: {score:.0f}, method: {tag})")
        
        # Check digit count
        digit_count = len(str(int(abs(value))))
        print(f"\n📏 Digit Analysis:")
        print(f"  จำนวนหลัก: {digit_count}")
        print(f"  Expected: {config['expected_digits']}")
        
        if digit_count != config['expected_digits']:
            if digit_count < config['expected_digits']:
                print(f"  ⚠️ ขาด {config['expected_digits'] - digit_count} หลัก (อาจต้องเติม 0 ข้างหน้า)")
            else:
                print(f"  ⚠️ เกิน {digit_count - config['expected_digits']} หลัก (อาจอ่านผิด)")
        else:
            print(f"  ✅ จำนวนหลักถูกต้อง")
        
        return value
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Analog Meter Reading')
    parser.add_argument('image_path', help='ภาพมิเตอร์อนาล็อก')
    parser.add_argument('-e', '--expected', type=float, help='ค่าที่คาดหวัง')
    
    args = parser.parse_args()
    
    if not Path(args.image_path).exists():
        print(f"❌ Image not found: {args.image_path}")
        sys.exit(1)
    
    test_analog_meter(args.image_path, args.expected)
