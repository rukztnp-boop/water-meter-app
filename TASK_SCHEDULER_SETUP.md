# วิธีตั้ง Task Scheduler ให้รัน Watch Mode อัตโนมัติ

## ขั้นตอน:

1. **เปิด Task Scheduler:**
   - กด `Win + R`
   - พิมพ์ `taskschd.msc`
   - กด Enter

2. **สร้าง Task ใหม่:**
   - คลิก "Create Task..." (ไม่ใช่ Basic Task)
   - Name: `Water Meter Auto Watch`
   - Description: `ตรวจจับไฟล์ Excel จาก SCADA และประมวลผลอัตโนมัติ`
   - ✅ เลือก "Run whether user is logged on or not"
   - ✅ เลือก "Run with highest privileges"

3. **Triggers Tab:**
   - คลิก "New..."
   - Begin the task: **At startup**
   - ✅ Enabled
   - คลิก OK

4. **Actions Tab:**
   - คลิก "New..."
   - Action: **Start a program**
   - Program/script: `D:\WaterMeter\start_watch_mode.bat`
   - Start in: `D:\WaterMeter`
   - คลิก OK

5. **Conditions Tab:**
   - ❌ ยกเลิก "Start the task only if the computer is on AC power"
   - ✅ เลือก "Wake the computer to run this task"

6. **Settings Tab:**
   - ✅ Allow task to be run on demand
   - ✅ If the task fails, restart every: **1 minute** (3 times)
   - ❌ ยกเลิก "Stop the task if it runs longer than"
   - ✅ If the running task does not end when requested, force it to stop

7. **คลิก OK**
   - ใส่รหัสผ่าน Windows (ถ้าถาม)

---

## ทดสอบ:

1. **ทดสอบรัน Task:**
   - คลิกขวาที่ Task ที่สร้าง
   - เลือก "Run"
   - ดู log ที่ `D:\WaterMeter\Logs\auto_processor_YYYYMM.log`

2. **Restart เครื่อง**
   - Task จะรันอัตโนมัติเมื่อเปิดเครื่อง

---

## การทำงาน:

```
เปิดเครื่อง
  ↓
Task Scheduler รัน start_watch_mode.bat
  ↓
Watch Mode เริ่มทำงาน (ตรวจสอบทุก 5 นาที)
  ↓
ช่างวางไฟล์ → ระบบตรวจจับ → ประมวลผล → บันทึก → ย้ายไฟล์
  ↓
เสร็จอัตโนมัติ! 🎉
```

---

## ตรวจสอบว่า Task ทำงานหรือไม่:

1. เปิด Task Manager (`Ctrl + Shift + Esc`)
2. มองหา `python.exe` ที่รัน `auto_processor.py`
3. ดู log file: `D:\WaterMeter\Logs\auto_processor_202602.log`

---

## หยุดการทำงาน:

1. เปิด Task Scheduler
2. คลิกขวาที่ `Water Meter Auto Watch`
3. เลือก "Disable" หรือ "Delete"
