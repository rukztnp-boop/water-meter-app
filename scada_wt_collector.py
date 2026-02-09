#!/usr/bin/env python3
"""
🏭 SCADA WT System Auto Collector
============================================================
⚡ รันบนเครื่อง SCADA WT โดยตรง (ไม่ต้อง copy ไฟล์)

ดึงค่าจาก Daily_Report + SMMT_Daily_Report อัตโนมัติ
อ่านไฟล์จาก path จริงบนเครื่อง → ประมวลผล → บันทึก Google Sheets

สถานการณ์:
  - Daily_Report อยู่ที่ C:/Report/WT_Daily_Report/
  - SMMT_Daily_Report อยู่ที่ C:/Report/SMMT_Daily_Report/
  - ทั้ง 2 ไฟล์อัปเดตอัตโนมัติทุก 5 นาทีจาก SCADA
  - ค่าที่ต้องใช้: วันก่อนหน้า เวลา 23:55
  - เช่น รายงานวันที่ 9 ก.พ. → ใช้ข้อมูลวันที่ 8 ก.พ. เวลา 23:55

วิธีใช้:
  # รันครั้งเดียว (ค่าเริ่มต้น = วันนี้)
  python scada_wt_collector.py

  # ระบุวันที่รายงาน
  python scada_wt_collector.py --date 2026-02-09

  # รัน scheduled mode (รันทุกวันอัตโนมัติ)
  python scada_wt_collector.py --mode scheduled

  # Dry run (ทดสอบไม่บันทึกจริง)
  python scada_wt_collector.py --dry-run

  # แสดง config ปัจจุบัน
  python scada_wt_collector.py --show-config
"""

import os
import sys
import logging
import time
import json
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =====================================================================
# 📋 CONFIG — แก้ตรงนี้ให้ตรงกับเครื่องจริง
# =====================================================================
CONFIG = {
    # ──────────────────────────────────────────────────────────
    # 📂 ที่อยู่ไฟล์บน SCADA Server WT System
    # ──────────────────────────────────────────────────────────
    # ⚠️ แต่ละไฟล์อยู่คนละ folder:
    #   Daily_Report       → C:\Report\WT_Daily_Report\
    #   SMMT_Daily_Report  → C:\Report\SMMT_Daily_Report\
    #
    # ชื่อไฟล์: {YYYY}_{MM}_{D}_XXX.xlsx (วันที่ไม่มี leading zero)
    #   เช่น 2026_02_7_Daily_Report.xlsx
    #        2026_02_8_SMMT_Daily_Report.xlsx
    #
    # ⏰ ไฟล์อัปเดตอัตโนมัติทุก 5 นาที จาก SCADA
    # ──────────────────────────────────────────────────────────
    "WT_FILES": {
        "Daily_Report": {
            # Folder ที่ไฟล์อยู่
            "path": r"C:\Report\WT_Daily_Report",
            # Pattern ชื่อไฟล์ (เรียงจากเจาะจงไปกว้าง)
            "patterns": [
                "{YYYY}_{MM}_{D}_Daily_Report.xlsx",    # เช่น 2026_02_8_Daily_Report.xlsx ✅ ตรงกับจริง
                "{YYYY}_{MM}_{DD}_Daily_Report.xlsx",   # เช่น 2026_02_08_Daily_Report.xlsx (เผื่อ)
                "Daily_Report.xlsx",                     # fallback ชื่อคงที่
            ],
            "required": True,
        },
        "SMMT_Daily_Report": {
            # Folder ที่ไฟล์อยู่
            "path": r"C:\Report\SMMT_Daily_Report",
            # Pattern ชื่อไฟล์
            "patterns": [
                "{YYYY}_{MM}_{D}_SMMT_Daily_Report.xlsx",    # เช่น 2026_02_8_SMMT_Daily_Report.xlsx ✅ ตรงกับจริง
                "{YYYY}_{MM}_{DD}_SMMT_Daily_Report.xlsx",   # เผื่อ leading zero
                "SMMT_Daily_Report.xlsx",
            ],
            "required": True,
        },
    },

    # ──────────────────────────────────────────────────────────
    # 📂 Log folder (บนเครื่อง SCADA WT)
    # ──────────────────────────────────────────────────────────
    "LOG_FOLDER": r"C:\WaterMeter\Logs",

    # ──────────────────────────────────────────────────────────
    # ⏰ Scheduled Mode
    # ──────────────────────────────────────────────────────────
    # เวลาที่จะรันอัตโนมัติ (แนะนำ: 00:15 หลังเที่ยงคืน
    # เพราะข้อมูล 23:55 จะมีแน่แล้ว)
    "SCHEDULED_TIME": "00:15",

    # ──────────────────────────────────────────────────────────
    # 🔧 การประมวลผล
    # ──────────────────────────────────────────────────────────
    # เวลาเป้าหมายที่ต้องการดึงค่า
    "TARGET_TIME": "23:55",

    # จำนวนแถวที่สแกนต่อไฟล์
    "MAX_SCAN_ROWS": 50000,

    # ไฟล์ mapping
    "MAPPING_FILE": "DB_Water_Scada.xlsx",

    # ──────────────────────────────────────────────────────────
    # 📝 Write Mode
    # ──────────────────────────────────────────────────────────
    # "overwrite"   = เขียนทับทั้งหมด
    # "empty_only"  = เขียนเฉพาะช่องว่าง
    "WRITE_MODE": "overwrite",
}

# =====================================================================
# Setup
# =====================================================================

def get_thai_time():
    """คืนค่าเวลาปัจจุบันในโซนไทย (UTC+7)"""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz)


def setup_logging():
    """สร้างระบบ logging"""
    log_folder = Path(CONFIG["LOG_FOLDER"])
    log_folder.mkdir(parents=True, exist_ok=True)

    log_file = log_folder / f"wt_collector_{datetime.now().strftime('%Y%m')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


logger = setup_logging()


# =====================================================================
# Import จาก app.py (ผ่าน app_standalone wrapper)
# =====================================================================
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app_standalone import (
        load_scada_excel_mapping,
        extract_scada_values_from_exports,
        gc,
        DB_SHEET_NAME,
        REAL_REPORT_SHEET,
    )
    # Import เพิ่มเติมที่ต้องใช้
    # (ต้อง import หลังจาก mock streamlit แล้ว)
    from app import (
        export_many_to_real_report_batch,
        append_rows_dailyreadings_batch,
        get_meter_config,
        infer_meter_type,
    )
    IMPORTS_OK = True
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
    logger.error("ตรวจสอบว่า app_standalone.py, app.py อยู่ในโฟลเดอร์เดียวกัน")
    IMPORTS_OK = False


# =====================================================================
# 📂 File Discovery & Copy
# =====================================================================

def _expand_pattern(pattern: str, data_date) -> str:
    """
    แทนที่ placeholder ในชื่อไฟล์ด้วยวันที่จริง

    {YYYY} → 2026
    {MM}   → 02
    {DD}   → 08
    {D}    → 8
    {M}    → 2
    """
    return (
        pattern
        .replace("{YYYY}", f"{data_date.year:04d}")
        .replace("{MM}", f"{data_date.month:02d}")
        .replace("{DD}", f"{data_date.day:02d}")
        .replace("{D}", str(data_date.day))
        .replace("{M}", str(data_date.month))
    )


def find_wt_file(file_key: str, file_config: dict, data_date, search_folder: str) -> str | None:
    """
    หาไฟล์ใน search_folder ตาม patterns ที่กำหนด

    Returns:
        path ของไฟล์ที่เจอ (หรือ None)
    """
    search_path = Path(search_folder)

    if not search_path.exists():
        logger.warning(f"   ⚠️ Folder ไม่พบ: {search_folder}")
        return None

    for pattern in file_config["patterns"]:
        filename = _expand_pattern(pattern, data_date)
        filepath = search_path / filename

        if filepath.exists():
            logger.info(f"   ✅ พบไฟล์: {filepath.name}")
            return str(filepath)

    # Fallback: ค้นหาแบบ glob (กรณีชื่อไฟล์ไม่ตรง pattern แต่คล้าย)
    # เช่น "*Daily_Report*" แต่ต้องไม่ใช่ SMMT
    key_lower = file_key.lower()
    for f in search_path.glob("*.xlsx"):
        if f.name.startswith("~"):
            continue  # skip temp files
        fname_lower = f.name.lower()

        # ต้อง match key แต่ระวัง Daily_Report ชน SMMT_Daily_Report
        if key_lower in fname_lower:
            # ถ้า key ไม่ใช่ smmt แต่ไฟล์มี smmt → ข้าม
            if "smmt" not in key_lower and "smmt" in fname_lower:
                continue
            logger.info(f"   ✅ พบไฟล์ (glob): {f.name}")
            return str(f)

    return None


def find_wt_files_direct(data_date) -> dict:
    """
    หาไฟล์จาก path จริงบนเครื่อง SCADA WT โดยตรง (ไม่ต้อง copy)

    ⚡ รันบนเครื่อง SCADA WT:
      Daily_Report       → C:/Report/WT_Daily_Report/2026_02_8_Daily_Report.xlsx
      SMMT_Daily_Report  → C:/Report/SMMT_Daily_Report/2026_02_8_SMMT_Daily_Report.xlsx

    Args:
        data_date: วันที่ของข้อมูล (เช่น 8 ก.พ. สำหรับรายงาน 9 ก.พ.)

    Returns:
        dict: {filename: full_path} ของไฟล์ที่เจอ (อ่านจาก path จริง)
    """
    logger.info(f"📅 วันที่ข้อมูล: {data_date.strftime('%Y-%m-%d')}")

    found_files = {}
    missing_required = []

    for file_key, file_config in CONFIG["WT_FILES"].items():
        file_folder = file_config.get("path", "")
        logger.info(f"   🔍 หา: {file_key}")
        logger.info(f"      📂 {file_folder}")

        source_path = find_wt_file(file_key, file_config, data_date, file_folder)

        if source_path:
            file_size = os.path.getsize(source_path) / 1024 / 1024
            found_files[os.path.basename(source_path)] = source_path
            logger.info(f"      ✅ {os.path.basename(source_path)} ({file_size:.1f} MB)")
        else:
            logger.warning(f"      ❌ ไม่พบไฟล์ {file_key}")
            if file_config.get("required"):
                missing_required.append(file_key)

    if missing_required:
        logger.error(f"❌ ไฟล์จำเป็นที่หายไป: {', '.join(missing_required)}")

    return found_files


# =====================================================================
# 🔄 Processing
# =====================================================================

def process_wt_files(found_files: dict, report_date, data_date, dry_run=False) -> dict:
    """
    ประมวลผลไฟล์ WT System

    Args:
        found_files: dict {filename: path} (path จริงบนเครื่อง — ไม่ต้อง copy)
        report_date: วันที่ของรายงาน (เช่น 9 ก.พ.)
        data_date: วันที่ของข้อมูล (เช่น 8 ก.พ.)
        dry_run: ถ้า True จะไม่บันทึกจริง

    Returns:
        dict: สถิติการประมวลผล
    """
    if not IMPORTS_OK:
        return {"error": "Import failed", "success": 0, "failed": 0}

    stats = {
        "success": 0,
        "failed": 0,
        "total": 0,
        "skipped": 0,
        "report_date": str(report_date),
        "data_date": str(data_date),
        "files_processed": len(found_files),
    }

    # 1. โหลด mapping
    mapping_file = Path(__file__).parent / CONFIG["MAPPING_FILE"]
    if not mapping_file.exists():
        logger.error(f"❌ ไม่พบไฟล์ mapping: {mapping_file}")
        stats["error"] = "Mapping file not found"
        return stats

    try:
        mapping_rows = load_scada_excel_mapping(str(mapping_file))
        logger.info(f"✅ โหลด mapping: {len(mapping_rows)} entries")
    except Exception as e:
        logger.error(f"❌ โหลด mapping ล้มเหลว: {e}")
        stats["error"] = str(e)
        return stats

    # 2. กรอง mapping เฉพาะ WT files (Daily_Report, SMMT_Daily_Report)
    #    (ไม่เอา UF_System / AF_Report_Gen)
    wt_file_keys = set()
    for key in CONFIG["WT_FILES"]:
        wt_file_keys.add(key.lower())
        # เพิ่ม variations
        wt_file_keys.add(key.lower().replace("_", ""))

    def is_wt_mapping(row):
        """เช็คว่า mapping row นี้เป็นของ WT file หรือไม่"""
        fk = str(row.get("file_key", "")).strip().lower()
        fk_norm = fk.replace(" ", "_")
        # ตัดวันที่นำหน้า
        import re
        fk_clean = re.sub(r"^\d{4}_\d{2}_\d{1,2}_", "", fk_norm)

        for wt_key in wt_file_keys:
            if wt_key in fk_clean or fk_clean in wt_key:
                return True
        # ด้วยความระวัง: daily_report ต้องไม่ match smmt
        if "daily_report" in fk_clean and "smmt" not in fk_clean:
            return True
        if "smmt" in fk_clean:
            return True
        return False

    wt_mapping = [r for r in mapping_rows if is_wt_mapping(r)]
    non_wt_mapping = [r for r in mapping_rows if not is_wt_mapping(r)]

    logger.info(f"📊 Mapping: {len(wt_mapping)} WT entries / {len(non_wt_mapping)} non-WT entries (ข้าม)")

    if not wt_mapping:
        logger.warning("⚠️ ไม่พบ mapping สำหรับ WT files — ลองใช้ mapping ทั้งหมด")
        wt_mapping = mapping_rows

    # 3. อ่านไฟล์เป็น bytes (อ่านจาก path จริงบนเครื่อง)
    uploaded_exports = {}
    for filename, filepath in found_files.items():
        try:
            with open(filepath, 'rb') as f:
                uploaded_exports[filename] = f.read()
            size_mb = os.path.getsize(filepath) / 1024 / 1024
            logger.info(f"   📖 อ่าน: {filename} ({size_mb:.1f} MB)")
        except Exception as e:
            logger.error(f"   ❌ อ่านไฟล์ล้มเหลว: {filename}: {e}")

    if not uploaded_exports:
        logger.error("❌ ไม่มีไฟล์ให้ประมวลผล")
        stats["error"] = "No files loaded"
        return stats

    # 4. Extract values (ใช้ data_date เพราะข้อมูลเป็นของวันก่อน)
    logger.info("🔄 กำลังดึงค่าจาก Excel...")
    logger.info(f"   📅 วันที่ข้อมูล (data_date): {data_date}")
    logger.info(f"   ⏰ เวลาเป้าหมาย: {CONFIG['TARGET_TIME']}")

    try:
        results, missing = extract_scada_values_from_exports(
            mapping_rows=wt_mapping,
            uploaded_exports=uploaded_exports,
            target_date=data_date,  # ← ใช้วันที่ข้อมูล ไม่ใช่วันที่รายงาน
            allow_single_file_fallback=True,
            custom_max_scan_rows=CONFIG["MAX_SCAN_ROWS"],
        )
    except Exception as e:
        logger.error(f"❌ Extract ล้มเหลว: {e}")
        import traceback
        traceback.print_exc()
        stats["error"] = str(e)
        return stats

    # 5. สรุปผล extract
    ok_results = [r for r in results if r.get("status") == "OK" and r.get("value") is not None]
    fail_results = [r for r in results if r.get("status") != "OK" or r.get("value") is None]

    stats["total"] = len(results)
    logger.info(f"✅ ดึงค่าได้: {len(ok_results)}/{len(results)} จุด")

    if fail_results:
        logger.warning(f"⚠️ ดึงค่าไม่ได้: {len(fail_results)} จุด")
        for r in fail_results[:10]:  # แสดงแค่ 10 จุดแรก
            logger.warning(f"   - {r.get('point_id')}: {r.get('status')} (file={r.get('matched_file', 'N/A')})")

    if not ok_results:
        logger.error("❌ ไม่มีข้อมูลที่ดึงสำเร็จ")
        stats["error"] = "No data extracted"
        return stats

    # ======= DRY RUN =======
    if dry_run:
        logger.info("=" * 50)
        logger.info("🧪 DRY RUN — ไม่บันทึกจริง")
        logger.info("=" * 50)
        for r in ok_results:
            logger.info(f"   {r['point_id']}: {r['value']} (time={r.get('time')}, file={r.get('matched_file')})")
        stats["success"] = len(ok_results)
        stats["mode"] = "dry_run"
        return stats

    # 6. บันทึกลง DailyReadings (log)
    logger.info("📝 กำลังบันทึกลง DailyReadings...")
    db_rows = []
    for r in ok_results:
        pid = str(r["point_id"]).strip().upper()
        val = r["value"]

        try:
            cfg = get_meter_config(pid)
            meter_type = infer_meter_type(cfg) if cfg else "Electric"
        except Exception:
            meter_type = "Electric"

        try:
            current_time = get_thai_time().time()
            record_ts = datetime.combine(report_date, current_time).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            record_ts = get_thai_time().strftime("%Y-%m-%d %H:%M:%S")

        db_rows.append([
            record_ts,
            meter_type,
            pid,
            "WT_AUTO_COLLECTOR",   # inspector
            val,                    # Manual_Value
            val,                    # AI_Value
            "AUTO_WT_SCADA",       # method
            "-"                     # image_url
        ])

    try:
        ok_db, db_msg = append_rows_dailyreadings_batch(db_rows)
        if ok_db:
            logger.info(f"✅ DailyReadings: {db_msg}")
        else:
            logger.warning(f"⚠️ DailyReadings ล้มเหลว: {db_msg}")
    except Exception as e:
        logger.error(f"❌ DailyReadings error: {e}")

    # 7. บันทึกลง WaterReport
    logger.info(f"📝 กำลังบันทึกลง WaterReport (วันที่: {report_date})...")

    report_items = []
    for r in ok_results:
        pid = str(r["point_id"]).strip().upper()
        val = r["value"]

        try:
            cfg = get_meter_config(pid)
            if not cfg:
                logger.warning(f"   ⚠️ {pid}: ไม่พบ config ใน PointsMaster")
                stats["failed"] += 1
                continue

            report_col = str(cfg.get("report_col", "") or "").strip()
            if not report_col or report_col in ("-", "—", "–"):
                logger.warning(f"   ⚠️ {pid}: report_col ว่าง/'-'")
                stats["failed"] += 1
                continue

            # แปลงค่าให้เป็นตัวเลข
            write_val = val
            try:
                write_val = float(str(val).replace(",", "").strip())
            except Exception:
                write_val = str(val).strip()

            report_items.append({
                "point_id": pid,
                "value": write_val,
                "report_col": report_col,
            })
        except Exception as e:
            logger.error(f"   ❌ {pid}: {e}")
            stats["failed"] += 1

    if report_items:
        try:
            ok_pids, fail_report = export_many_to_real_report_batch(
                report_items,
                report_date,   # ← วันที่รายงาน (9 ก.พ.)
                debug=True,
                write_mode=CONFIG["WRITE_MODE"],
            )

            stats["success"] = len(ok_pids)

            # แยก skip กับ error
            skipped = [(p, r) for p, r in fail_report if str(r) == "SKIP_NON_EMPTY"]
            real_fails = [(p, r) for p, r in fail_report if str(r) != "SKIP_NON_EMPTY"]
            stats["skipped"] = len(skipped)
            stats["failed"] += len(real_fails)

            logger.info(f"✅ WaterReport: บันทึกสำเร็จ {len(ok_pids)} จุด")
            if skipped:
                logger.info(f"⏭️ ข้าม {len(skipped)} จุด (ช่องมีข้อมูลแล้ว)")
            if real_fails:
                logger.error(f"❌ ล้มเหลว {len(real_fails)} จุด:")
                for pid, reason in real_fails:
                    logger.error(f"   - {pid}: {reason}")

        except Exception as e:
            logger.error(f"❌ WaterReport error: {e}")
            import traceback
            traceback.print_exc()
            stats["error"] = str(e)
    else:
        logger.warning("⚠️ ไม่มีข้อมูลให้บันทึกลง WaterReport")

    return stats


def log_processed_files(found_files: dict, report_date, stats: dict):
    """
    บันทึกว่าประมวลผลไฟล์ไหนไปแล้ว (ไม่ย้าย/ไม่ลบ เพราะ SCADA ยังใช้อยู่)
    """
    try:
        log_folder = Path(CONFIG["LOG_FOLDER"])
        log_folder.mkdir(parents=True, exist_ok=True)

        history_file = log_folder / "wt_processed_history.json"

        history = []
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []

        entry = {
            "report_date": str(report_date),
            "processed_at": get_thai_time().strftime("%Y-%m-%d %H:%M:%S"),
            "files": {name: path for name, path in found_files.items()},
            "success": stats.get("success", 0),
            "total": stats.get("total", 0),
        }
        history.append(entry)

        # เก็บแค่ 60 entries ล่าสุด
        history = history[-60:]

        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False, default=str)

        logger.info(f"📝 บันทึก history: {report_date} ({len(found_files)} ไฟล์)")
    except Exception as e:
        logger.error(f"❌ บันทึก history ล้มเหลว: {e}")


# =====================================================================
# 🚀 Main Entry Points
# =====================================================================

def run_once(report_date=None, dry_run=False):
    """
    รันครั้งเดียว

    Args:
        report_date: วันที่รายงาน (default = วันนี้)
        dry_run: ถ้า True จะไม่บันทึกจริง
    """
    if report_date is None:
        report_date = get_thai_time().date()

    # ข้อมูลที่ต้องใช้ = วันก่อนหน้า เวลา 23:55
    data_date = report_date - timedelta(days=1)

    logger.info("=" * 60)
    logger.info("🏭 SCADA WT System Auto Collector")
    logger.info("=" * 60)
    logger.info(f"📅 วันที่รายงาน  : {report_date}")
    logger.info(f"📅 วันที่ข้อมูล  : {data_date} (23:55)")
    for fk, fc in CONFIG['WT_FILES'].items():
        logger.info(f"📂 {fk}: {fc.get('path', 'N/A')}")
    logger.info(f"🧪 Dry Run       : {'Yes' if dry_run else 'No'}")
    logger.info("=" * 60)

    # 1. หาไฟล์จาก path จริงบนเครื่อง (ไม่ต้อง copy)
    found_files = find_wt_files_direct(data_date)

    if not found_files:
        logger.error("❌ ไม่พบไฟล์ Excel")
        logger.info("💡 ลองตรวจสอบ:")
        for fk, fc in CONFIG['WT_FILES'].items():
            logger.info(f"   📂 {fk}: {fc.get('path', 'N/A')}")
        logger.info(f"   - ไฟล์วันที่ {data_date} มีอยู่ใน folder หรือยัง")
        return

    # 2. ประมวลผล
    stats = process_wt_files(found_files, report_date, data_date, dry_run=dry_run)

    # 3. บันทึก history (ไม่ย้าย/ไม่ลบไฟล์ เพราะ SCADA ยังใช้อยู่)
    if not dry_run and stats.get("success", 0) > 0:
        log_processed_files(found_files, report_date, stats)

    # 4. สรุป
    logger.info("=" * 60)
    logger.info("📊 สรุปผล:")
    logger.info(f"   ✅ สำเร็จ  : {stats.get('success', 0)} จุด")
    logger.info(f"   ❌ ล้มเหลว : {stats.get('failed', 0)} จุด")
    logger.info(f"   ⏭️ ข้าม   : {stats.get('skipped', 0)} จุด")
    logger.info(f"   📄 ทั้งหมด : {stats.get('total', 0)} จุด")
    if stats.get("error"):
        logger.info(f"   ⚠️ Error  : {stats['error']}")
    logger.info("=" * 60)

    # 5. บันทึก stats ลง JSON (สำหรับตรวจสอบทีหลัง)
    save_run_stats(stats)

    return stats


def run_scheduled():
    """
    รัน scheduled mode — เช็คทุก 30 วินาที ถ้าถึงเวลาที่กำหนดจะรันอัตโนมัติ
    """
    target_time = CONFIG["SCHEDULED_TIME"]

    logger.info("=" * 60)
    logger.info("⏰ SCADA WT Collector - Scheduled Mode")
    logger.info(f"   เวลาที่ตั้งไว้: {target_time}")
    for fk, fc in CONFIG['WT_FILES'].items():
        logger.info(f"   📂 {fk}: {fc.get('path', 'N/A')}")
    logger.info("   กด Ctrl+C เพื่อหยุด")
    logger.info("=" * 60)

    last_run_date = None

    while True:
        try:
            now = get_thai_time()
            current_time = now.strftime("%H:%M")
            current_date = now.date()

            # รันแค่วันละครั้ง ถ้าถึงเวลาที่ตั้งไว้
            if current_time == target_time and current_date != last_run_date:
                logger.info(f"🔔 ถึงเวลา {target_time} — เริ่มประมวลผล...")
                run_once(report_date=current_date)
                last_run_date = current_date

            time.sleep(30)

        except KeyboardInterrupt:
            logger.info("\n⚠️ หยุดโดยผู้ใช้")
            break
        except Exception as e:
            logger.error(f"❌ Error in scheduled loop: {e}")
            time.sleep(60)


def save_run_stats(stats: dict):
    """บันทึกสถิติการรันลง JSON"""
    try:
        log_folder = Path(CONFIG["LOG_FOLDER"])
        log_folder.mkdir(parents=True, exist_ok=True)

        stats_file = log_folder / "wt_collector_stats.json"

        # อ่าน history
        history = []
        if stats_file.exists():
            try:
                with open(stats_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []

        # เพิ่ม entry ใหม่
        stats["timestamp"] = get_thai_time().strftime("%Y-%m-%d %H:%M:%S")
        history.append(stats)

        # เก็บแค่ 30 entries ล่าสุด
        history = history[-30:]

        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error(f"❌ บันทึก stats ล้มเหลว: {e}")


def show_config():
    """แสดง config ปัจจุบัน"""
    print("=" * 60)
    print("📋 SCADA WT Collector - Configuration")
    print("=" * 60)
    for key, value in CONFIG.items():
        if isinstance(value, dict):
            print(f"\n  {key}:")
            for k2, v2 in value.items():
                if isinstance(v2, dict):
                    print(f"    {k2}:")
                    for k3, v3 in v2.items():
                        print(f"      {k3}: {v3}")
                else:
                    print(f"    {k2}: {v2}")
        else:
            print(f"  {key}: {value}")
    print("=" * 60)


# =====================================================================
# CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🏭 SCADA WT System Auto Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่างการใช้งาน:
  python scada_wt_collector.py                         # รันครั้งเดียว (วันนี้)
  python scada_wt_collector.py --date 2026-02-09       # ระบุวันที่รายงาน
  python scada_wt_collector.py --dry-run               # ทดสอบไม่บันทึก
  python scada_wt_collector.py --mode scheduled         # รันทุกวัน
  python scada_wt_collector.py --show-config            # ดู config

วิธีตั้ง Task Scheduler:
  ใช้ start_wt_collector.bat (จะสร้างให้อัตโนมัติ)
        """
    )

    parser.add_argument(
        '--mode',
        choices=['once', 'scheduled'],
        default='once',
        help='โหมด: once (รันครั้งเดียว), scheduled (รันทุกวัน)'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=None,
        help='วันที่รายงาน (YYYY-MM-DD) เช่น 2026-02-09'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='ทดสอบโดยไม่บันทึกจริง'
    )
    parser.add_argument(
        '--show-config',
        action='store_true',
        help='แสดง config ปัจจุบัน'
    )
    args = parser.parse_args()

    # Show config
    if args.show_config:
        show_config()
        return

    # Parse date
    report_date = None
    if args.date:
        try:
            report_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"❌ รูปแบบวันที่ไม่ถูกต้อง: {args.date} (ต้องเป็น YYYY-MM-DD)")
            sys.exit(1)

    # Run
    if args.mode == 'once':
        run_once(report_date=report_date, dry_run=args.dry_run)
    elif args.mode == 'scheduled':
        run_scheduled()


if __name__ == "__main__":
    main()
