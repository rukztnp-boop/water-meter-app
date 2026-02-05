@echo off
REM Auto Processor - Scheduled Mode
REM รันทุกวันเวลา 08:00 และ 16:00

cd /d D:\WaterMeter
python auto_processor.py --mode scheduled
