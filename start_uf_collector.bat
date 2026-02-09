@echo off
REM ============================================================
REM  SCADA UF System Auto Collector
REM  รันบนเครื่อง SCADA UF Server โดยตรง
REM  อ่านไฟล์จาก D:\report\AF_Report_Gen.xlsx → ประมวลผล → บันทึก Google Sheets
REM ============================================================

REM *** แก้ path ตรงนี้ให้ตรงกับที่วาง project บนเครื่อง UF ***
cd /d "D:\WaterMeter\water-meter-project"

REM Activate virtual environment (ถ้ามี)
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM รันครั้งเดียว (สำหรับ Task Scheduler ให้ตั้งเวลาเป็น 06:00)
python scada_uf_collector.py --mode once

REM Log completion
echo [%date% %time%] UF Collector completed >> D:\WaterMeter\Logs\batch_log.txt

exit /b 0
