#!/usr/bin/env python3
"""
🧪 Test VSD/Digital Meter OCR
ทดสอบเฉพาะ VSD/Digital (ACS580) meter reading
"""

import os
import sys
from pathlib import Path

# Import from app.py
from app import ocr_process, preprocess_image_cv

def test_vsd_image(image_path, expected_value=None):
    """
    ทดสอบภาพ VSD/Digital meter เดียว
    """
    print(f"🧪 ทดสอบ: {image_path}")
    print("=" * 60)
    
    # Mock config for VSD meter
    config = {
        "point_id": "TEST_VSD",
        "type": "Electric",
        "name": "VSD Digital ACS580",
        "keyword": "Previous day",
        "decimals": 2,
        "expected_digits": 2,
        "allow_negative": "FALSE"
    }
    
    # Read image
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    # Test with debug enabled
    print("\n🔍 กำลังอ่านค่า VSD meter...")
    try:
        value, candidates = ocr_process(
            image_bytes,
            config,
            debug=True,
            return_candidates=True,
            use_roboflow=False
        )
        
        print(f"\n{'='*60}")
        print(f"📊 ผลลัพธ์:")
        print(f"  ค่าที่อ่านได้: {value:.2f}")
        
        if expected_value is not None:
            diff = abs(value - expected_value)
            match = "✅" if diff < 0.1 else "❌"
            print(f"  ค่าที่คาดหวัง: {expected_value:.2f}")
            print(f"  {match} ผลการทดสอบ: {'PASS' if diff < 0.1 else 'FAIL'}")
        
        if candidates:
            print(f"\n🎯 Candidates (top 5):")
            for i, cand in enumerate(candidates[:5], 1):
                print(f"  {i}. {cand.get('val', 0):.2f} "
                      f"(score: {cand.get('score', 0):.0f}, "
                      f"method: {cand.get('method', 'unknown')})")
        
        return value
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_multiple_vsd_images(image_folder):
    """
    ทดสอบหลายภาพ VSD พร้อมกัน
    """
    image_folder = Path(image_folder)
    
    # Known test cases (ถ้ามี)
    test_cases = {
        "S__154140715_0.jpg": 38.87,  # ค่าที่ user บอกว่าต้องเป็น 38.87
    }
    
    # Find all VSD images
    vsd_patterns = ['*vsd*.jpg', '*acs*.jpg', '*abb*.jpg', '*VSD*.jpg', '*ACS*.jpg']
    image_files = []
    for pattern in vsd_patterns:
        image_files.extend(image_folder.glob(pattern))
    
    # Also check test_cases
    for filename in test_cases.keys():
        file_path = image_folder / filename
        if file_path.exists() and file_path not in image_files:
            image_files.append(file_path)
    
    if not image_files:
        print(f"⚠️ ไม่พบภาพ VSD ใน {image_folder}")
        return
    
    print(f"🧪 พบภาพ VSD ทั้งหมด {len(image_files)} ภาพ")
    print("=" * 60)
    
    results = []
    for img_path in sorted(image_files):
        expected = test_cases.get(img_path.name)
        value = test_vsd_image(img_path, expected)
        
        results.append({
            "filename": img_path.name,
            "predicted": value,
            "expected": expected,
            "status": "PASS" if (expected is None or (value and abs(value - expected) < 0.1)) else "FAIL"
        })
        
        print("\n" + "-" * 60 + "\n")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 สรุปผลการทดสอบ VSD:")
    print("=" * 60)
    
    for result in results:
        status_icon = "✅" if result["status"] == "PASS" else "❌"
        print(f"{status_icon} {result['filename']:<40} "
              f"Predicted: {result['predicted']:.2f if result['predicted'] else 'N/A':<8}  "
              f"{'Expected: ' + str(result['expected']) if result['expected'] else ''}")
    
    pass_count = sum(1 for r in results if r['status'] == 'PASS')
    print(f"\nPass rate: {pass_count}/{len(results)} ({pass_count/len(results)*100:.1f}%)")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Test VSD/Digital Meter OCR')
    parser.add_argument('image_path', help='ภาพ VSD หรือโฟลเดอร์ที่เก็บภาพ')
    parser.add_argument('-e', '--expected', type=float, help='ค่าที่คาดหวัง (สำหรับภาพเดียว)')
    
    args = parser.parse_args()
    
    path = Path(args.image_path)
    
    if path.is_file():
        # Test single image
        test_vsd_image(path, args.expected)
    elif path.is_dir():
        # Test multiple images
        test_multiple_vsd_images(path)
    else:
        print(f"❌ ไม่พบไฟล์หรือโฟลเดอร์: {path}")
