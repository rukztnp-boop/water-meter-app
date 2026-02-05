@echo off
REM Auto Processor - Watch Mode
REM ตรวจจับไฟล์ใหม่และประมวลผลอัตโนมัติทุก 5 นาที

cd /d D:\WaterMeter
python auto_processor.py --mode watch

REM ถ้า script หยุดทำงาน รอ 10 วินาทีแล้วรันใหม่
timeout /t 10
goto :start
