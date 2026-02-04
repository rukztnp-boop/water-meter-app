#!/usr/bin/env python3
"""
🎯 Quick Demo - Test Single Image
สำหรับทดสอบภาพเดียวอย่างรวดเร็ว
"""

import sys
from pathlib import Path

def quick_test_image(image_path):
    """ทดสอบภาพเดียวแบบง่าย ๆ"""
    
    print("=" * 70)
    print(f"🧪 Quick Test: {Path(image_path).name}")
    print("=" * 70)
    
    # Import app functions
    try:
        from app import ocr_process, is_digital_meter
    except ImportError as e:
        print(f"❌ Error importing app.py: {e}")
        print("Make sure app.py is in the same directory")
        return
    
    # Read image
    try:
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        print(f"✅ อ่านภาพขนาด {len(image_bytes)} bytes")
    except Exception as e:
        print(f"❌ ไม่สามารถอ่านภาพ: {e}")
        return
    
    # Create configs for both types
    configs = {
        "VSD/Digital": {
            "point_id": "TEST_VSD",
            "type": "Electric",
            "name": "VSD Digital ACS580",
            "keyword": "Previous day",
            "decimals": 2,
            "expected_digits": 2,
            "allow_negative": "FALSE"
        },
        "Analog Water": {
            "point_id": "TEST_ANALOG",
            "type": "Water",
            "name": "Analog Water Meter",
            "keyword": "",
            "decimals": 0,
            "expected_digits": 5,
            "allow_negative": "FALSE"
        }
    }
    
    print("\n📋 Testing with different meter configurations...")
    print("-" * 70)
    
    results = []
    
    for meter_type, config in configs.items():
        print(f"\n🔍 Testing as {meter_type}:")
        try:
            value = ocr_process(
                image_bytes,
                config,
                debug=False,  # Set to True for detailed output
                return_candidates=False,
                use_roboflow=False
            )
            
            result = {
                "type": meter_type,
                "value": value,
                "status": "OK" if value > 0 else "WARNING",
                "config": config
            }
            
            print(f"  📊 Result: {value:.2f}")
            print(f"  Status: {'✅' if value > 0 else '⚠️ '} {result['status']}")
            
            results.append(result)
            
        except Exception as e:
            print(f"  ❌ Error: {str(e)[:100]}")
            results.append({
                "type": meter_type,
                "value": None,
                "status": "ERROR",
                "error": str(e)
            })
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 Summary:")
    print("=" * 70)
    
    for result in results:
        if result["value"] is not None:
            print(f"{result['type']:<20} → {result['value']:>10.2f}  [{result['status']}]")
        else:
            print(f"{result['type']:<20} → {'ERROR':>10}  [{result.get('error', 'Unknown error')[:30]}]")
    
    # Recommendation
    print("\n💡 Recommendation:")
    best = max([r for r in results if r["value"] is not None], 
               key=lambda x: x["value"] if x["value"] > 0 else 0,
               default=None)
    
    if best and best["value"] > 0:
        print(f"   ✅ Best result: {best['type']} = {best['value']:.2f}")
        print(f"   Use config: {best['config']['name']}")
    else:
        print("   ⚠️  No valid reading found")
        print("   💭 Try:")
        print("      1. Check if image is clear")
        print("      2. Run with debug=True to see details")
        print("      3. Adjust ROI if needed")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python quick_demo.py <image_path>")
        print("")
        print("Example:")
        print("  python quick_demo.py S__154140715_0.jpg")
        sys.exit(1)
    
    image_path = sys.argv[1]
    
    if not Path(image_path).exists():
        print(f"❌ Image not found: {image_path}")
        sys.exit(1)
    
    quick_test_image(image_path)
