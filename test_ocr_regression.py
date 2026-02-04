#!/usr/bin/env python3
"""
🧪 OCR Regression Test Harness
ทดสอบการอ่านค่ามิเตอร์กับภาพทั้งหมดใน folder และสรุปผลเป็น CSV
"""

import os
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
import json

# Import functions from app.py
from app import (
    ocr_process, 
    is_digital_meter, 
    is_analog_meter,
    extract_point_id_from_image,
    preprocess_image_cv
)

def extract_meter_id_from_filename(filename):
    """
    ดึง meter_id จากชื่อไฟล์ (ถ้ามี)
    เช่น S11A_123.jpg → S11A_123
    """
    # Remove extension
    name = Path(filename).stem
    
    # Common patterns
    patterns = [
        r'([A-Z]\d+[A-Z]?[-_]\d+)',  # S11A-123, S11A_123
        r'([A-Z]{2,}_[A-Z0-9]+)',     # VSD_PUMP1
        r'(ACS\d+)',                   # ACS580
    ]
    
    for pat in patterns:
        match = re.search(pat, name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return name

def run_regression_test(image_folder, output_csv="ocr_regression_results.csv", debug=False):
    """
    วนอ่านทุกภาพใน folder และบันทึกผลลงใน CSV
    
    CSV columns: filename, meter_id, meter_type, predicted_value, status, notes
    """
    
    # Find all image files
    image_folder = Path(image_folder)
    if not image_folder.exists():
        print(f"❌ โฟลเดอร์ไม่พบ: {image_folder}")
        return
    
    image_files = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']:
        image_files.extend(image_folder.glob(ext))
    
    if not image_files:
        print(f"⚠️ ไม่พบไฟล์รูปภาพใน {image_folder}")
        return
    
    print(f"🧪 พบ {len(image_files)} ภาพสำหรับทดสอบ")
    print(f"📊 ผลลัพธ์จะบันทึกใน: {output_csv}")
    print("=" * 80)
    
    results = []
    
    for i, img_path in enumerate(sorted(image_files), 1):
        print(f"\n[{i}/{len(image_files)}] กำลังทดสอบ: {img_path.name}")
        
        result = {
            "filename": img_path.name,
            "meter_id": "",
            "meter_type": "",
            "predicted_value": "",
            "status": "PENDING",
            "notes": "",
            "debug_info": {}
        }
        
        try:
            # Read image
            with open(img_path, 'rb') as f:
                image_bytes = f.read()
            
            # Extract meter_id from filename
            result["meter_id"] = extract_meter_id_from_filename(img_path.name)
            
            # Detect meter type (we need config, so we'll use heuristics)
            # For testing, create a mock config based on filename
            config = create_test_config(img_path.name)
            
            result["meter_type"] = "Digital" if is_digital_meter(config) else "Analog"
            
            # Run OCR
            try:
                value = ocr_process(
                    image_bytes, 
                    config, 
                    debug=debug, 
                    return_candidates=False,
                    use_roboflow=False  # ไม่ใช้ Roboflow ใน test เพื่อความเร็ว
                )
                
                result["predicted_value"] = f"{value:.2f}"
                
                # Validate result
                if value == 0.0:
                    result["status"] = "WARNING"
                    result["notes"] = "ค่าเป็น 0.00 (อาจอ่านผิด)"
                elif value < 0:
                    result["status"] = "ERROR"
                    result["notes"] = "ค่าติดลบ"
                elif value > 1e6:
                    result["status"] = "WARNING"
                    result["notes"] = "ค่าสูงผิดปกติ"
                else:
                    result["status"] = "OK"
                    result["notes"] = "อ่านค่าสำเร็จ"
                
                # Store debug info
                if config.get('_auto_digit_bbox'):
                    result["debug_info"]["auto_digit_bbox"] = config['_auto_digit_bbox']
                
                print(f"  ✅ {result['meter_type']}: {result['predicted_value']} - {result['status']}")
                if result["notes"]:
                    print(f"     💬 {result['notes']}")
            
            except Exception as ocr_error:
                result["status"] = "ERROR"
                result["notes"] = f"OCR Error: {str(ocr_error)[:100]}"
                print(f"  ❌ {result['notes']}")
        
        except Exception as e:
            result["status"] = "ERROR"
            result["notes"] = f"File Error: {str(e)[:100]}"
            print(f"  ❌ {result['notes']}")
        
        results.append(result)
    
    # Write results to CSV
    print("\n" + "=" * 80)
    print(f"💾 บันทึกผลลัพธ์ลง {output_csv}...")
    
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'filename', 'meter_id', 'meter_type', 'predicted_value', 'status', 'notes'
        ])
        writer.writeheader()
        
        for result in results:
            # Remove debug_info before writing to CSV
            row = {k: v for k, v in result.items() if k != 'debug_info'}
            writer.writerow(row)
    
    # Summary statistics
    total = len(results)
    ok_count = sum(1 for r in results if r['status'] == 'OK')
    warning_count = sum(1 for r in results if r['status'] == 'WARNING')
    error_count = sum(1 for r in results if r['status'] == 'ERROR')
    zero_count = sum(1 for r in results if r.get('predicted_value') == '0.00')
    
    print("\n📊 สรุปผลการทดสอบ:")
    print(f"  ทั้งหมด:     {total} ภาพ")
    print(f"  ✅ OK:       {ok_count} ({ok_count/total*100:.1f}%)")
    print(f"  ⚠️  WARNING: {warning_count} ({warning_count/total*100:.1f}%)")
    print(f"  ❌ ERROR:    {error_count} ({error_count/total*100:.1f}%)")
    print(f"  🔴 0.00:     {zero_count} ({zero_count/total*100:.1f}%)")
    
    # Save summary
    summary_file = output_csv.replace('.csv', '_summary.json')
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "ok": ok_count,
        "warning": warning_count,
        "error": error_count,
        "zero_values": zero_count,
        "success_rate": f"{ok_count/total*100:.1f}%",
        "results": results
    }
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"\n📄 รายละเอียดเพิ่มเติมบันทึกใน: {summary_file}")
    print("=" * 80)

def create_test_config(filename):
    """
    สร้าง mock config สำหรับ testing โดยดูจากชื่อไฟล์
    """
    filename_lower = filename.lower()
    
    config = {
        "point_id": extract_meter_id_from_filename(filename),
        "decimals": 0,
        "expected_digits": 5,
        "keyword": "",
        "type": "Water",
        "name": "",
        "allow_negative": "FALSE"
    }
    
    # Detect VSD/Digital
    if any(kw in filename_lower for kw in ['vsd', 'acs', 'abb', 'digital', 'scada']):
        config["type"] = "Electric"
        config["name"] = "VSD Digital"
        config["decimals"] = 2
        config["expected_digits"] = 2
        config["keyword"] = "Previous day"
    
    # Detect analog water meter
    elif any(kw in filename_lower for kw in ['s11', 's12', 'water', 'meter']):
        config["type"] = "Water"
        config["name"] = "Analog Water Meter"
        config["decimals"] = 0
        config["expected_digits"] = 5
    
    return config

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='OCR Regression Test Harness')
    parser.add_argument('image_folder', help='โฟลเดอร์ที่เก็บภาพทดสอบ')
    parser.add_argument('-o', '--output', default='ocr_regression_results.csv', 
                       help='ชื่อไฟล์ CSV สำหรับบันทึกผลลัพธ์')
    parser.add_argument('-d', '--debug', action='store_true', 
                       help='เปิด debug mode (แสดงรายละเอียดเพิ่มเติม)')
    
    args = parser.parse_args()
    
    run_regression_test(args.image_folder, args.output, args.debug)
