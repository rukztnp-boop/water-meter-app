#!/usr/bin/env python3
"""
🏭 SCADA UF System Auto Collector
============================================================
⚡ รันบนเครื่อง SCADA UF โดยตรง (ไม่ต้อง copy ไฟล์)

ดึงค่าจาก AF_Report_Gen อัตโนมัติ (หลังจาก user กดปุ่ม Report และ Save)
อ่านไฟล์จาก path จริงบนเครื่อง → ประมวลผล → บันทึก Google Sheets

สถานการณ์:
  - AF_Report_Gen.xlsx อยู่ที่ D:/report/
  - ไฟล์จะอัปเดตเมื่อ user กดปุ่ม Report และ Save
  - ค่าที่ต้องใช้: (เช่น วันก่อนหน้า เวลา 23:55 หรือ ตามที่กำหนด)

วิธีใช้:
  # รันครั้งเดียว (ค่าเริ่มต้น = วันนี้)
  python scada_uf_collector.py

  # ระบุวันที่รายงาน
  python scada_uf_collector.py --date 2026-02-09

  # Dry run (ทดสอบไม่บันทึกจริง)
  python scada_uf_collector.py --dry-run

  # แสดง config ปัจจุบัน
  python scada_uf_collector.py --show-config
"""

import os
import sys
import logging
import time
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# =====================================================================
# 📋 CONFIG — แก้ตรงนี้ให้ตรงกับเครื่องจริง
# =====================================================================
CONFIG = {
    # 📂 ที่อยู่ไฟล์บน SCADA Server UF System
    "UF_FILE": {
        "path": r"D:\\report",
        "filename": "AF_Report_Gen.xlsx",
        "required": True,
    },
    # 📂 Log folder (บนเครื่อง SCADA UF)
    "LOG_FOLDER": r"D:\\WaterMeter\\Logs",
    # ⏰ เวลาเป้าหมายที่ต้องการดึงค่า
    "TARGET_TIME": "23:55",
    # เวลาที่จะรัน scheduled mode (ค่าเริ่มต้น: 06:00 ตามที่ตกลง)
    "SCHEDULED_TIME": "06:00",
    # ถ้าต้องการให้สคริปต์รอ update ของไฟล์ก่อน (polling)
    "WAIT_FOR_UPDATE": False,
    "WAIT_TIMEOUT": 600,  # วินาที (default 10 นาที)
    # จำนวนแถวที่สแกนต่อไฟล์
    "MAX_SCAN_ROWS": 50000,
    # ไฟล์ mapping (ใช้ร่วมกับ WT ได้)
    "MAPPING_FILE": "DB_Water_Scada.xlsx",
    # 📝 Write Mode
    "WRITE_MODE": "overwrite",
}

# =====================================================================
# Setup Logging
# =====================================================================
def setup_logging():
    log_folder = Path(CONFIG["LOG_FOLDER"])
    log_folder.mkdir(parents=True, exist_ok=True)
    log_file = log_folder / f"uf_collector_{datetime.now().strftime('%Y%m')}.log"
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
# TODO: Import extraction and Google Sheets logic from app_standalone/app.py
# =====================================================================
# ... (to be implemented)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app_standalone import (
        load_scada_excel_mapping,
        extract_scada_values_from_exports,
        gc,
        DB_SHEET_NAME,
        REAL_REPORT_SHEET,
    )
    from app import (
        export_many_to_real_report_batch,
        append_rows_dailyreadings_batch,
        get_meter_config,
        infer_meter_type,
        get_thai_time,
    )
    IMPORTS_OK = True
except ImportError as e:
    logger.error(f"❌ Import error: {e}")
    logger.error("ตรวจสอบว่า app_standalone.py และ app.py อยู่ในโฟลเดอร์เดียวกัน และ dependencies ถูก mock/ติดตั้งแล้ว")
    IMPORTS_OK = False

if __name__ == "__main__":
    logger.info("[UF Collector] Script started. (ยังไม่สมบูรณ์ รอ implement logic)")
    # TODO: Implement extraction and upload logic
    # placeholder — real entry point is main()
    def read_uf_file_bytes() -> dict:
        """อ่านไฟล์ AF_Report_Gen.xlsx เป็น bytes และคืน dict ของ uploaded_exports"""
        p = Path(CONFIG["UF_FILE"]["path"]).expanduser()
        fn = CONFIG["UF_FILE"].get("filename")
        full = p / fn
        if not full.exists():
            logger.error(f"❌ ไม่พบไฟล์: {full}")
            return {}
        try:
            with open(full, 'rb') as f:
                b = f.read()
            return {fn: b}
        except Exception as e:
            logger.error(f"❌ อ่านไฟล์ล้มเหลว: {e}")
            return {}


    def show_config():
        print("=" * 60)
        print("📋 SCADA UF Collector - Configuration")
        print("=" * 60)
        for k, v in CONFIG.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for k2, v2 in v.items():
                    print(f"    {k2}: {v2}")
            else:
                print(f"  {k}: {v}")
        print("=" * 60)


    def run_once(report_date=None, dry_run=False):
        if not IMPORTS_OK:
            logger.error("❌ Imports not available. Aborting.")
            return {}

        if report_date is None:
            report_date = get_thai_time().date()

        data_date = report_date - timedelta(days=1)

        logger.info("=" * 60)
        logger.info("🏭 SCADA UF System Auto Collector")
        logger.info("=" * 60)
        logger.info(f"📅 วันที่รายงาน  : {report_date}")
        logger.info(f"📅 วันที่ข้อมูล  : {data_date} (23:55)")
        logger.info(f"🧪 Dry Run       : {'Yes' if dry_run else 'No'}")
        logger.info("=" * 60)

        # 1. อ่านไฟล์จาก path
        uploaded = read_uf_file_bytes()
        if not uploaded:
            logger.error("❌ ไม่มีไฟล์ AF_Report_Gen.xlsx ให้อ่าน")
            return {}

        # 2. โหลด mapping
        mapping_rows = load_scada_excel_mapping(local_path=CONFIG.get("MAPPING_FILE", "DB_Water_Scada.xlsx"))
        if not mapping_rows:
            logger.error("❌ โหลด mapping ล้มเหลวหรือไฟล์ DB_Water_Scada.xlsx ไม่มีข้อมูล")
            return {}

        # 3. ประมวลผลค่า
        try:
            results, missing = extract_scada_values_from_exports(
                mapping_rows,
                uploaded,
                target_date=data_date,
                allow_single_file_fallback=False,
            )
        except Exception as e:
            logger.error(f"❌ extract error: {e}")
            return {"error": str(e)}

        stats = {"total": len(results), "success": 0, "failed": 0, "skipped": 0}

        ok_results = [r for r in results if r.get("status") == "OK"]

        # 4. บันทึกลง DailyReadings
        if ok_results:
            logger.info("📝 กำลังบันทึกลง DailyReadings...")
            db_rows = []
            for r in ok_results:
                pid = str(r.get("point_id", "")).strip().upper()
                val = r.get("value")
                try:
                    cfg = get_meter_config(pid)
                    meter_type = infer_meter_type(cfg) if cfg else "Water"
                except Exception:
                    meter_type = "Water"

                try:
                    current_time = get_thai_time().time()
                    record_ts = datetime.combine(report_date, current_time).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    record_ts = get_thai_time().strftime("%Y-%m-%d %H:%M:%S")

                db_rows.append([
                    record_ts,
                    meter_type,
                    pid,
                    "UF_AUTO_COLLECTOR",
                    val,
                    val,
                    "AUTO_UF_SCADA",
                    "-",
                ])

            try:
                ok_db, db_msg = append_rows_dailyreadings_batch(db_rows)
                if ok_db:
                    logger.info(f"✅ DailyReadings: {db_msg}")
                else:
                    logger.warning(f"⚠️ DailyReadings ล้มเหลว: {db_msg}")
            except Exception as e:
                logger.error(f"❌ DailyReadings error: {e}")

        # 5. บันทึกลง WaterReport
        report_items = []
        for r in ok_results:
            pid = str(r.get("point_id", "")).strip().upper()
            val = r.get("value")
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

                write_val = val
                try:
                    write_val = float(str(val).replace(",", "").strip())
                except Exception:
                    write_val = str(val).strip()

                report_items.append({"point_id": pid, "value": write_val, "report_col": report_col})
            except Exception as e:
                logger.error(f"   ❌ {pid}: {e}")
                stats["failed"] += 1

        if report_items:
            try:
                ok_pids, fail_report = export_many_to_real_report_batch(
                    report_items,
                    report_date,
                    debug=True,
                    write_mode=CONFIG.get("WRITE_MODE", "overwrite"),
                )

                stats["success"] = len(ok_pids)
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
                stats["error"] = str(e)
        else:
            logger.warning("⚠️ ไม่มีข้อมูลให้บันทึกลง WaterReport")

        # Summary
        logger.info("=" * 60)
        logger.info(f"📊 สรุปผล: success={stats.get('success')} failed={stats.get('failed')} skipped={stats.get('skipped')} total={stats.get('total')}")
        logger.info("=" * 60)

        return stats


    def main():
        parser = argparse.ArgumentParser(description="🏭 SCADA UF System Auto Collector")
        parser.add_argument('--mode', choices=['once', 'scheduled'], default='once', help='โหมด: once หรือ scheduled')
        parser.add_argument('--date', type=str, default=None, help='วันที่รายงาน (YYYY-MM-DD)')
        parser.add_argument('--dry-run', action='store_true', help='ทดสอบโดยไม่บันทึกจริง')
        parser.add_argument('--show-config', action='store_true', help='แสดง config')
        args = parser.parse_args()

        if args.show_config:
            show_config()
            return

        report_date = None
        if args.date:
            try:
                report_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except Exception:
                logger.error("รูปแบบวันที่ไม่ถูกต้อง (ต้อง YYYY-MM-DD)")
                return

        if args.mode == 'once':
            run_once(report_date=report_date, dry_run=args.dry_run)
        else:
            def run_scheduled():
                target_time = CONFIG.get('SCHEDULED_TIME', '06:00')
                logger.info('=' * 60)
                logger.info('⏰ SCADA UF Collector - Scheduled Mode')
                logger.info(f'   เวลาที่ตั้งไว้: {target_time}')
                logger.info('   กด Ctrl+C เพื่อหยุด')
                logger.info('=' * 60)

                last_run_date = None
                try:
                    while True:
                        now = get_thai_time()
                        current_time = now.strftime('%H:%M')
                        current_date = now.date()
                        if current_time == target_time and current_date != last_run_date:
                            logger.info(f"🔔 ถึงเวลา {target_time} — เริ่มประมวลผล...")
                            run_once(report_date=current_date)
                            last_run_date = current_date
                        time.sleep(30)
                except KeyboardInterrupt:
                    logger.info('\n⚠️ หยุดโดยผู้ใช้')
                except Exception as e:
                    logger.error(f'❌ Error in scheduled loop: {e}')

            run_scheduled()


    main()
