@echo off
REM ============================================================
REM  SCADA WT System Auto Collector
REM  รันบนเครื่อง SCADA WT Server โดยตรง
REM  อ่านไฟล์จาก path จริง -> ประมวลผล -> บันทึก Google Sheets
REM ============================================================
REM
REM  ไฟล์ที่อ่าน:
REM    C:\Report\WT_Daily_Report\2026_02_8_Daily_Report.xlsx
REM    C:\Report\SMMT_Daily_Report\2026_02_8_SMMT_Daily_Report.xlsx
REM
REM  วิธีตั้ง Task Scheduler:
REM  1. เปิด Task Scheduler (taskschd.msc)
REM  2. Create Task (ไม่ใช่ Basic Task)
REM  3. General:
REM     - Name: SCADA WT Auto Collector
REM     - Run whether user is logged on or not
REM     - Run with highest privileges
REM  4. Triggers:
REM     - Daily, Start at: 00:15
REM  5. Actions:
REM     - Start a program: C:\WaterMeter\water-meter-project\start_wt_collector.bat
REM  6. Settings:
REM     - If task fails, restart every: 5 minutes, up to 3 times
REM ============================================================

REM *** แก้ path ตรงนี้ให้ตรงกับที่วาง project ***
cd /d "C:\WaterMeter\water-meter-project"

REM Activate virtual environment (ถ้ามี)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM รันครั้งเดียว (วันนี้)
python scada_wt_collector.py --mode once

REM Log completion
echo [%date% %time%] WT Collector completed >> C:\WaterMeter\Logs\batch_log.txt

pause
