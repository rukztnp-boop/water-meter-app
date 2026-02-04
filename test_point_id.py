#!/usr/bin/env python3
"""
🧪 Test Point ID Detection
ทดสอบการหา point_id จากภาพ
"""

import sys
from pathlib import Path

def test_point_id_detection(image_path):
    """ทดสอบการหา point_id จากภาพเดียว"""
    
    print("=" * 70)
    print(f"🧪 Testing Point ID Detection: {Path(image_path).name}")
    print("=" * 70)
    
    # Import functions
    try:
        from app import (
            extract_point_id_from_image,
            build_pid_norm_map,
            _vision_read_text,
            _crop_bottom_bytes,
            _norm_pid_key
        )
    except ImportError as e:
        print(f"❌ Error importing: {e}")
        return
    
    # Read image
    try:
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        print(f"✅ อ่านภาพขนาด {len(image_bytes):,} bytes\n")
    except Exception as e:
        print(f"❌ ไม่สามารถอ่านภาพ: {e}")
        return
    
    # Build norm_map
    print("🔍 Building point_id normalization map...")
    try:
        norm_map = build_pid_norm_map()
        print(f"✅ พบ {len(norm_map)} point_ids ใน PointsMaster")
        
        # Show sample
        sample = list(norm_map.items())[:10]
        print("\n📋 Sample point_ids (normalized → original):")
        for norm, orig in sample:
            print(f"  {norm} → {orig}")
        print()
    except Exception as e:
        print(f"❌ Error building norm_map: {e}")
        norm_map = {}
    
    # Test bottom crop OCR
    print("-" * 70)
    print("🔍 Pass 1: OCR ช่วงล่าง 40%")
    print("-" * 70)
    try:
        btm = _crop_bottom_bytes(image_bytes, frac=0.40)
        txt, err = _vision_read_text(btm)
        
        if err:
            print(f"⚠️ OCR Error: {err}")
        
        if txt:
            print(f"📄 OCR Text:\n{txt}\n")
            normalized = _norm_pid_key(txt)
            print(f"🔧 Normalized: {normalized}\n")
        else:
            print("⚠️ No text detected\n")
    except Exception as e:
        print(f"❌ Error in bottom OCR: {e}\n")
    
    # Test full image OCR
    print("-" * 70)
    print("🔍 Pass 2: OCR ทั้งภาพ")
    print("-" * 70)
    try:
        txt2, err2 = _vision_read_text(image_bytes)
        
        if err2:
            print(f"⚠️ OCR Error: {err2}")
        
        if txt2:
            print(f"📄 OCR Text:\n{txt2[:300]}\n")
            normalized2 = _norm_pid_key(txt2)
            print(f"🔧 Normalized: {normalized2[:300]}\n")
        else:
            print("⚠️ No text detected\n")
    except Exception as e:
        print(f"❌ Error in full OCR: {e}\n")
    
    # Test extraction
    print("=" * 70)
    print("🎯 Extracting Point ID...")
    print("=" * 70)
    try:
        point_id, ocr_text = extract_point_id_from_image(image_bytes, norm_map)
        
        if point_id:
            print(f"\n✅ Success!")
            print(f"   Point ID: {point_id}")
            print(f"   OCR Text used: {ocr_text[:100]}...")
        else:
            print(f"\n❌ Failed to detect point_id")
            print(f"   OCR Text: {ocr_text[:100]}...")
            
            # Suggest fixes
            print("\n💡 Troubleshooting:")
            print("   1. เช็คว่า point_id มีใน PointsMaster หรือไม่")
            print("   2. ดูว่า OCR อ่านได้ถูกต้องไหม (ด้านบน)")
            print("   3. ลอง normalize manually:")
            if ocr_text:
                manual_norm = _norm_pid_key(ocr_text)
                print(f"      Normalized: {manual_norm[:200]}")
                
                # Check if any pattern matches
                import re
                patterns = re.findall(r"[A-Z]{1,4}_[A-Z0-9_]{2,}", manual_norm)
                if patterns:
                    print(f"      Found patterns: {patterns[:5]}")
                    
                    # Try fuzzy match
                    from difflib import SequenceMatcher
                    print("\n      Fuzzy matching with norm_map:")
                    for pattern in patterns[:3]:
                        best_match = None
                        best_score = 0
                        for nkey, orig in norm_map.items():
                            score = SequenceMatcher(None, pattern, nkey).ratio()
                            if score > best_score:
                                best_score = score
                                best_match = (nkey, orig)
                        
                        if best_match:
                            print(f"        '{pattern}' → '{best_match[1]}' (score: {best_score:.2f})")
    
    except Exception as e:
        print(f"❌ Error during extraction: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_point_id.py <image_path>")
        print("")
        print("Example:")
        print("  python test_point_id.py S__154140725_0.jpg")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)
    
    test_point_id_detection(image_path)
