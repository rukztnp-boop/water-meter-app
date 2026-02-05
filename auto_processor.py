#!/usr/bin/env python3
"""
🤖 Auto Processor - ระบบประมวลผลไฟล์ Excel อัตโนมัติ
============================================================

สำหรับ: เครื่องพี่พจน์ (เครื่องหลักลงข้อมูล)

วิธีใช้งาน:
1. ช่างคัดลอกไฟล์ 3 ไฟล์จาก SCADA Server มาวางในโฟลเดอร์ WATCH_FOLDER
2. Script นี้จะตรวจจับและประมวลผลอัตโนมัติ
3. บันทึกผลลัพธ์ลง Google Sheets
4. ย้ายไฟล์ไปโฟลเดอร์ Processed พร้อม timestamp

รันแบบ Scheduled (แนะนำ):
  python auto_processor.py --mode scheduled

รันแบบ Watch Folder (real-time):
  python auto_processor.py --mode watch

รันแบบ Manual (ทันที):
  python auto_processor.py --mode manual
"""

import os
import sys
import glob
import shutil
import hashlib
import logging
import time
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

# ใช้ functions จาก app.py
sys.path.insert(0, os.path.dirname(__file__))

# Import from standalone wrapper instead of app.py directly
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app_standalone import (
        load_scada_excel_mapping,
        extract_scada_values_from_exports,
        gc,
        DB_SHEET_NAME,
        get_thai_time
    )
except ImportError as e:
    print(f"❌ Error importing from app_standalone.py: {e}")
    print("ตรวจสอบว่าไฟล์ app_standalone.py และ app.py อยู่ในโฟลเดอร์เดียวกัน")
    sys.exit(1)

# ==================== Configuration ====================

CONFIG = {
    # โฟลเดอร์ที่ช่างจะวางไฟล์
    # รองรับ 2 รูปแบบ:
    # 1. Folder เดียว: "D:\WaterMeter\Uploads"
    # 2. Folder แยกตามวัน: "D:\WaterMeter\Uploads\{date}" (แนะนำ)
    "WATCH_FOLDER": r"D:\WaterMeter\Uploads",
    
    # ใช้ folder แยกตามวันหรือไม่? (แนะนำให้เป็น True)
    "USE_DATE_FOLDERS": True,  # True = หา folder รูปแบบ "5_2_69", "6_2_69"
    
    # โฟลเดอร์เก็บไฟล์ที่ประมวลผลแล้ว
    "PROCESSED_FOLDER": r"D:\WaterMeter\Processed",
    
    # โฟลเดอร์เก็บ log
    "LOG_FOLDER": r"D:\WaterMeter\Logs",
    
    # Pattern ของไฟล์ที่ต้องการประมวลผล
    "FILE_PATTERNS": [
        "*Daily_Report*.xlsx",       # เช่น 2026_02_4_Daily_Report.xlsx
        "*UF_System*.xlsx",
        "*SMMT_Daily*.xlsx",         # เช่น 2026_02_4_SMMT_Daily_Report.xlsx
        "AF_Report_Gen.xlsx",        # ชื่อเดิมทุกวัน (ไม่มีวันที่)
        "*AF_Report*.xlsx"
    ],
    
    # ไฟล์ mapping (DB_Water_Scada.xlsx)
    "MAPPING_FILE": "DB_Water_Scada.xlsx",
    
    # จำนวนแถวที่สแกนต่อไฟล์ (50,000 = ปานกลาง)
    "MAX_SCAN_ROWS": 50000,
    
    # เวลาที่ต้องการประมวลผล (สำหรับ scheduled mode)
    "SCHEDULED_TIMES": ["08:00", "16:00"],  # 08:00 น. และ 16:00 น.
    
    # Check interval สำหรับ watch mode (วินาที)
    "WATCH_INTERVAL": 300,  # ตรวจสอบทุก 5 นาที
    
    # ส่ง notification หรือไม่
    "ENABLE_NOTIFICATION": False,
    
    # Email settings (ถ้าเปิด notification)
    "NOTIFICATION_EMAIL": "admin@example.com",
}

# ==================== Setup Logging ====================

def setup_logging():
    """สร้างระบบ logging"""
    log_folder = Path(CONFIG["LOG_FOLDER"])
    log_folder.mkdir(parents=True, exist_ok=True)
    
    log_file = log_folder / f"auto_processor_{datetime.now().strftime('%Y%m')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)

logger = setup_logging()

# ==================== Helper Functions ====================

def parse_date_from_folder_name(folder_name):
    """
    แปลงชื่อ folder เป็นวันที่
    
    รองรับรูปแบบ:
    - 5_2_69 → 2026-02-05
    - 15_2_69 → 2026-02-15
    - 05_02_69 → 2026-02-05
    - 5_2_2569 → 2026-02-05
    
    Returns:
        datetime.date or None
    """
    import re
    
    # Pattern: d_m_yy or dd_mm_yy or d_m_yyyy
    patterns = [
        r'^(\d{1,2})_(\d{1,2})_(\d{2})$',      # 5_2_69
        r'^(\d{1,2})_(\d{1,2})_(\d{4})$',      # 5_2_2569
    ]
    
    for pattern in patterns:
        match = re.match(pattern, folder_name)
        if match:
            day, month, year = match.groups()
            day = int(day)
            month = int(month)
            year = int(year)
            
            # แปลง year แบบ Buddhist Era (2569) → Christian Era (2026)
            if year > 2500:
                year = year - 543
            # แปลง short year (69) → full year (2026)
            elif year < 100:
                year = 2000 + year
            
            try:
                return datetime(year, month, day).date()
            except ValueError:
                logger.warning(f"Invalid date from folder: {folder_name}")
                return None
    
    return None

def create_folders():
    """สร้างโฟลเดอร์ที่จำเป็น"""
    folders = [
        CONFIG["WATCH_FOLDER"],
        CONFIG["PROCESSED_FOLDER"],
        CONFIG["LOG_FOLDER"]
    ]
    
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)
        logger.info(f"✅ Folder ready: {folder}")

def get_file_hash(filepath):
    """คำนวณ hash ของไฟล์ (เพื่อเช็คไฟล์ซ้ำ)"""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()

def find_new_files():
    """หาไฟล์ Excel ใหม่ในโฟลเดอร์ watch"""
    watch_folder = Path(CONFIG["WATCH_FOLDER"])
    found_files = []
    
    if CONFIG["USE_DATE_FOLDERS"]:
        # โหมด: หา folder ตามวัน (เช่น 5_2_69, 6_2_69)
        # รองรับรูปแบบ: d_m_yy, dd_m_yy, d_mm_yy, dd_mm_yy
        date_folders = []
        
        for item in watch_folder.iterdir():
            if item.is_dir():
                # เช็คว่าชื่อ folder เป็นรูปแบบวันที่หรือไม่
                # เช่น 5_2_69, 05_02_69, 5_2_2569
                if '_' in item.name and item.name.replace('_', '').isdigit():
                    date_folders.append(item)
        
        if date_folders:
            # เรียงตาม modified time (ล่าสุดก่อน)
            date_folders.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            logger.info(f"📁 Found {len(date_folders)} date folder(s)")
            
            # ประมวลผล folder ล่าสุด (หรือทั้งหมดถ้าต้องการ)
            for folder in date_folders[:3]:  # เอา 3 folder ล่าสุด
                logger.info(f"   Scanning: {folder.name}")
                for pattern in CONFIG["FILE_PATTERNS"]:
                    files = list(folder.glob(pattern))
                    found_files.extend(files)
        else:
            logger.warning("⚠️ No date folders found! Looking in main folder...")
            # Fallback: หาในโฟลเดอร์หลัก
            for pattern in CONFIG["FILE_PATTERNS"]:
                files = list(watch_folder.glob(pattern))
                found_files.extend(files)
    else:
        # โหมด: หาในโฟลเดอร์เดียว
        for pattern in CONFIG["FILE_PATTERNS"]:
            files = list(watch_folder.glob(pattern))
            found_files.extend(files)
    
    # เอาแค่ไฟล์ที่ไม่ได้ซ่อน (ไม่ขึ้นต้นด้วย ~)
    found_files = [f for f in found_files if not f.name.startswith('~')]
    
    logger.info(f"🔍 Found {len(found_files)} file(s) total")
    return found_files

def load_processed_history():
    """โหลดประวัติไฟล์ที่ประมวลผลไปแล้ว"""
    history_file = Path(CONFIG["LOG_FOLDER"]) / "processed_history.json"
    
    if history_file.exists():
        with open(history_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_processed_history(history):
    """บันทึกประวัติไฟล์ที่ประมวลผล"""
    history_file = Path(CONFIG["LOG_FOLDER"]) / "processed_history.json"
    
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def is_file_processed(filepath, history):
    """เช็คว่าไฟล์นี้ประมวลผลไปแล้วหรือยัง"""
    file_hash = get_file_hash(filepath)
    filename = os.path.basename(filepath)
    
    return history.get(filename, {}).get('hash') == file_hash

# ==================== Core Processing ====================

def process_files_batch(files, target_date=None):
    """
    ประมวลผลไฟล์ทั้งหมดและบันทึกลง Google Sheets
    
    Returns:
        dict: สถิติการประมวลผล
    """
    if not files:
        logger.warning("⚠️ No files to process")
        return {"success": 0, "failed": 0, "total": 0}
    
    if target_date is None:
        target_date = get_thai_time().date()
    
    logger.info(f"📅 Target date: {target_date}")
    logger.info(f"📂 Processing {len(files)} file(s)...")
    
    # 1. โหลด mapping
    try:
        mapping_file = Path(__file__).parent / CONFIG["MAPPING_FILE"]
        if not mapping_file.exists():
            logger.error(f"❌ Mapping file not found: {mapping_file}")
            return {"success": 0, "failed": 0, "total": 0, "error": "Mapping file not found"}
        
        mapping = load_scada_excel_mapping(str(mapping_file))
        logger.info(f"✅ Loaded {len(mapping)} mapping entries")
    except Exception as e:
        logger.error(f"❌ Error loading mapping: {e}")
        return {"success": 0, "failed": 0, "total": 0, "error": str(e)}
    
    # 2. อ่านไฟล์ Excel
    uploaded_exports = {}
    for file_path in files:
        try:
            filename = os.path.basename(file_path)
            with open(file_path, 'rb') as f:
                uploaded_exports[filename] = f.read()
            logger.info(f"✅ Loaded: {filename} ({os.path.getsize(file_path) / 1024 / 1024:.1f} MB)")
        except Exception as e:
            logger.error(f"❌ Error reading {file_path}: {e}")
    
    if not uploaded_exports:
        logger.error("❌ No files could be loaded")
        return {"success": 0, "failed": 0, "total": 0, "error": "No files loaded"}
    
    # 3. Extract values
    try:
        logger.info("🔄 Extracting values from Excel files...")
        results, missing = extract_scada_values_from_exports(
            uploaded_exports=uploaded_exports,
            mapping_rows=mapping,
            target_date=target_date,
            custom_max_scan_rows=CONFIG["MAX_SCAN_ROWS"]
        )
        logger.info(f"✅ Extracted {len(results)} point values")
    except Exception as e:
        logger.error(f"❌ Error extracting values: {e}")
        return {"success": 0, "failed": 0, "total": 0, "error": str(e)}
    
    # 4. บันทึกลง Google Sheets
    success_count = 0
    failed_count = 0
    
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        
        current_time = get_thai_time()
        timestamp_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
        
        # results is a list of dicts, not a dict itself
        for result in results:
            point_id = result.get("point_id")
            val = result.get("value")
            status = result.get("status")
            
            if val is not None and status == "OK":
                try:
                    row = [
                        timestamp_str,
                        "SCADA",
                        point_id,
                        "AUTO_SYSTEM",
                        val,
                        "-",
                        "AUTO",
                        "-"
                    ]
                    ws.append_row(row)
                    success_count += 1
                    logger.debug(f"  ✓ {point_id}: {val}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"  ✗ {point_id}: {e}")
            else:
                failed_count += 1
                logger.warning(f"  ⚠ {point_id}: {status or 'No value'}")
        
        logger.info(f"✅ Saved {success_count}/{len(results)} records to Google Sheets")
        
    except Exception as e:
        logger.error(f"❌ Error saving to Google Sheets: {e}")
        return {
            "success": success_count,
            "failed": len(results) - success_count,
            "total": len(results),
            "error": str(e)
        }
    
    return {
        "success": success_count,
        "failed": failed_count,
        "total": len(results),
        "missing": len(missing),
        "files_processed": len(files)
    }

def move_to_processed(files):
    """ย้ายไฟล์ที่ประมวลผลแล้วไปโฟลเดอร์ Processed"""
    processed_folder = Path(CONFIG["PROCESSED_FOLDER"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # ลบ duplicates ออก (ใช้ set แล้วแปลงกลับเป็น list)
    unique_files = list(set([str(f) for f in files]))
    
    for file_path in unique_files:
        try:
            # เช็คว่าไฟล์ยังอยู่หรือไม่ (อาจถูกย้ายไปแล้ว)
            if not os.path.exists(file_path):
                logger.debug(f"⏭ Skipped (already moved): {os.path.basename(file_path)}")
                continue
                
            filename = os.path.basename(file_path)
            dest = processed_folder / f"{timestamp}_{filename}"
            shutil.move(str(file_path), str(dest))
            logger.info(f"📦 Moved: {filename} → {dest.name}")
        except Exception as e:
            logger.error(f"❌ Error moving {file_path}: {e}")

# ==================== Processing Modes ====================

def process_manual():
    """โหมด Manual: ประมวลผลทันที"""
    logger.info("=" * 60)
    logger.info("🚀 Manual Processing Mode")
    logger.info("=" * 60)
    
    create_folders()
    files = find_new_files()
    
    if not files:
        logger.info("ℹ️ No files to process. Exiting.")
        return
    
    stats = process_files_batch([str(f) for f in files])
    
    if stats.get("success", 0) > 0:
        # อัพเดท history ก่อนย้ายไฟล์ (เพื่อเก็บ hash)
        history = load_processed_history()
        unique_files = list(set([str(f) for f in files]))
        
        for file_path in unique_files:
            if os.path.exists(file_path):  # เช็คว่าไฟล์ยังอยู่
                filename = os.path.basename(file_path)
                history[filename] = {
                    "hash": get_file_hash(str(file_path)),
                    "processed_at": datetime.now().isoformat(),
                    "records": stats.get("success", 0)
                }
        save_processed_history(history)
        
        # ย้ายไฟล์หลังจาก save history แล้ว
        move_to_processed([str(f) for f in files])
    
    logger.info("=" * 60)
    logger.info(f"✅ Processing complete!")
    logger.info(f"   Success: {stats.get('success', 0)}")
    logger.info(f"   Failed:  {stats.get('failed', 0)}")
    logger.info(f"   Total:   {stats.get('total', 0)}")
    logger.info("=" * 60)

def process_scheduled():
    """โหมด Scheduled: รันตามเวลาที่กำหนด"""
    logger.info("=" * 60)
    logger.info("⏰ Scheduled Processing Mode")
    logger.info(f"   Scheduled times: {CONFIG['SCHEDULED_TIMES']}")
    logger.info("=" * 60)
    
    create_folders()
    
    while True:
        current_time = datetime.now().strftime("%H:%M")
        
        if current_time in CONFIG["SCHEDULED_TIMES"]:
            logger.info(f"🔔 Scheduled time reached: {current_time}")
            process_manual()
            
            # รอ 1 นาทีเพื่อไม่ให้ประมวลผลซ้ำ
            time.sleep(60)
        
        time.sleep(30)  # เช็คทุก 30 วินาที

def process_watch():
    """โหมด Watch: ตรวจจับไฟล์ใหม่แบบ real-time"""
    logger.info("=" * 60)
    logger.info("👀 Watch Folder Mode")
    logger.info(f"   Watch folder: {CONFIG['WATCH_FOLDER']}")
    logger.info(f"   Check interval: {CONFIG['WATCH_INTERVAL']} seconds")
    logger.info("=" * 60)
    
    create_folders()
    history = load_processed_history()
    
    while True:
        try:
            files = find_new_files()
            new_files = [f for f in files if not is_file_processed(str(f), history)]
            
            if new_files:
                logger.info(f"🆕 Found {len(new_files)} new file(s)")
                stats = process_files_batch([str(f) for f in new_files])
                
                if stats.get("success", 0) > 0:
                    move_to_processed([str(f) for f in new_files])
                    
                    # อัพเดท history
                    for file_path in new_files:
                        filename = os.path.basename(file_path)
                        history[filename] = {
                            "hash": get_file_hash(str(file_path)),
                            "processed_at": datetime.now().isoformat(),
                            "records": stats.get("success", 0)
                        }
                    save_processed_history(history)
            
            time.sleep(CONFIG["WATCH_INTERVAL"])
            
        except KeyboardInterrupt:
            logger.info("\n⚠️ Watch mode stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Error in watch loop: {e}")
            time.sleep(60)

# ==================== Main ====================

def main():
    parser = argparse.ArgumentParser(description="🤖 Auto Processor - ระบบประมวลผลอัตโนมัติ")
    parser.add_argument(
        '--mode',
        choices=['manual', 'scheduled', 'watch'],
        default='manual',
        help='โหมดการทำงาน: manual (ทันที), scheduled (ตามเวลา), watch (ตรวจจับอัตโนมัติ)'
    )
    
    args = parser.parse_args()
    
    try:
        if args.mode == 'manual':
            process_manual()
        elif args.mode == 'scheduled':
            process_scheduled()
        elif args.mode == 'watch':
            process_watch()
    except KeyboardInterrupt:
        logger.info("\n⚠️ Process interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
