# 🧪 OCR Testing & Debugging Guide

## การแก้ไขล่าสุด (Latest Fixes)

### 1. VSD/Digital (ACS580) Meter Reading Fix

**ปัญหา:** ระบบอ่านค่าเป็น 0.00 แทบทั้งหมด เพราะดึงตัวเลขตัวแรกที่เจอ (มักเป็น 0.00 หรือรหัสเมนู 01.53)

**การแก้ไข:**
- ✅ ใช้ **line-based OCR** ที่จัดกลุ่มคำตามตำแหน่ง y-coordinate
- ✅ **Fuzzy matching** หาบรรทัด "Previous day kWh" หรือ "01.53"
- ✅ ดึงเลขฝั่ง**ขวาสุด**ของบรรทัดนั้น (ไม่ใช่รหัสเมนู)
- ✅ กรองรหัสเมนู (01.XX, 02.XX) ออก

**ฟังก์ชันที่เพิ่ม:**
- `_vision_read_text_with_boxes()` - อ่าน OCR พร้อม bounding boxes
- `_group_words_into_lines()` - จัดกลุ่มคำเป็นบรรทัด
- `_extract_vsd_previous_day_kwh()` - ดึงค่า Previous day kWh แบบแม่นยำ
- `_fuzzy_match_text()` - เช็คความคล้ายของข้อความ

### 2. Analog Water Meter Auto-Detection

**ปัญหา:** มิเตอร์อนาล็อกที่ไม่มี ROI อ่านไม่ถูก เพราะมีสติ๊กเกอร์/ข้อความรบกวน

**การแก้ไข:**
- ✅ **Auto digit window detection** หาช่องเลขหลักอัตโนมัติ
- ✅ Crop เฉพาะ digit window เพื่อหลบสติ๊กเกอร์
- ✅ **Enhanced preprocessing** ทนต่อแสงแฟลช/การเอียง
- ✅ **CLAHE + Adaptive threshold** สำหรับแสงไม่สม่ำเสมอ

**ฟังก์ชันที่เพิ่ม:**
- `_detect_analog_digit_window()` - หา digit window ด้วย contour + aspect ratio
- `_has_red_digits()` - ตรวจสอบว่ามีเลขแดงหรือไม่
- ปรับ `preprocess_image_cv()` ให้รองรับ auto-detection

---

## 📋 การทดสอบ (Testing)

### 1. Regression Test ทั้งระบบ

```bash
# ทดสอบทุกภาพใน folder
python test_ocr_regression.py "path/to/error_images_folder"

# ระบุชื่อ output file
python test_ocr_regression.py "error_images/" -o results_20260204.csv

# เปิด debug mode
python test_ocr_regression.py "error_images/" -d
```

**ผลลัพธ์:**
- `ocr_regression_results.csv` - รายละเอียดแต่ละภาพ
- `ocr_regression_results_summary.json` - สรุปผลรวมและสถิติ

### 2. ทดสอบ VSD/Digital โดยเฉพาะ

```bash
# ทดสอบภาพเดียว
python test_vsd_meter.py "S__154140715_0.jpg" -e 38.87

# ทดสอบทุกภาพ VSD ใน folder
python test_vsd_meter.py "error_images/"
```

### 3. ทดสอบใน Python REPL

```python
from app import ocr_process, preprocess_image_cv

# Mock config
config = {
    "point_id": "TEST_VSD",
    "type": "Electric",
    "name": "VSD Digital ACS580",
    "keyword": "Previous day",
    "decimals": 2,
    "expected_digits": 2,
    "allow_negative": "FALSE"
}

# Read image
with open("S__154140715_0.jpg", 'rb') as f:
    image_bytes = f.read()

# Test
value, candidates = ocr_process(
    image_bytes, 
    config, 
    debug=True, 
    return_candidates=True,
    use_roboflow=False
)

print(f"Result: {value:.2f}")
for c in candidates[:5]:
    print(f"  {c['val']:.2f} - {c['score']:.0f} - {c.get('method', '')}")
```

---

## 🔍 Debug & Troubleshooting

### VSD/Digital ยังอ่านผิด

**เช็คว่า:**
1. ชื่อ/type มี "vsd", "acs", หรือ "abb" หรือไม่?
2. ลองเปิด debug: `debug=True`
3. เช็ค log:
   - `🔥 ตรวจพบ VSD/Digital meter` ← ต้องมี
   - `📋 VSD OCR: พบ X บรรทัด` ← มีกี่บรรทัด
   - `🎯 VSD: เจอบรรทัดเป้าหมาย` ← หาบรรทัด Previous day เจอไหม

**การแก้:**
```python
# Force VSD mode
config["name"] = "VSD Digital ACS580"  # บังคับให้เป็น VSD
```

### Analog ยังอ่านไม่ถูก

**เช็คว่า:**
1. Auto digit window detection ทำงานไหม?
   - `config.get('_auto_digit_bbox')` มีค่าไหม
2. ภาพมีแสงแฟลชรบกวนหรือเอียงมากไหม?
3. ROI มีหรือไม่? ถ้ามีแล้วผิด → ลบ ROI ออก

**การแก้:**
```python
# ลบ ROI เพื่อให้ auto-detect
config['roi_x1'] = 0
config['roi_x2'] = 0
config['roi_y1'] = 0
config['roi_y2'] = 0

# หรือปิด ROI
value = ocr_process(image_bytes, config, use_roi=False)
```

### Save Debug Images

```python
import cv2
from app import preprocess_image_cv

# Test different preprocessing variants
for variant in ["auto", "soft", "raw", "invert"]:
    processed = preprocess_image_cv(image_bytes, config, use_roi=True, variant=variant)
    
    # Save
    with open(f"debug_{variant}.png", 'wb') as f:
        f.write(processed)
```

---

## 📊 Expected Test Results

### VSD/Digital (ACS580)
- ✅ S__154140715_0.jpg → **38.87** (ไม่ใช่ 0.00 หรือ 01.53)
- ✅ Previous day kWh = 0.00 → อ่านได้ 0.00 (ถูกต้อง)
- ✅ ไม่หยิบรหัสเมนู 01.53, 02.01, etc.

### Analog Water Meter
- ✅ ไม่มี ROI → auto-detect digit window
- ✅ มีเลขแดง → อ่านเฉพาะเลขดำ (integer)
- ✅ ไม่มีเลขแดง → อ่านเลขดำทั้งหมด
- ✅ ทนต่อแสงแฟลช/การเอียง

---

## 🚀 Production Deployment

หลังจากทดสอบผ่านแล้ว:

1. **Backup โค้ดเดิม:**
   ```bash
   cp app.py app.py.backup_$(date +%Y%m%d)
   ```

2. **Deploy โค้ดใหม่:**
   - Git commit + push
   - Restart Streamlit app

3. **Monitor ผลลัพธ์:**
   - เช็คค่า 0.00 ลดลงหรือไม่
   - เช็ค anomaly rate
   - เช็ค user feedback

4. **Rollback (ถ้าจำเป็น):**
   ```bash
   cp app.py.backup_YYYYMMDD app.py
   ```

---

## 📝 Test Checklist

- [ ] VSD/Digital: S__154140715_0.jpg = 38.87 ✅
- [ ] VSD/Digital: ไม่หยิบรหัสเมนู 01.53 ✅
- [ ] VSD/Digital: Previous day = 0.00 อ่านได้ถูกต้อง ✅
- [ ] Analog: Auto digit window detection ทำงาน ✅
- [ ] Analog: ไม่มี ROI อ่านค่าได้ ✅
- [ ] Analog: ทนต่อแสงแฟลช ✅
- [ ] Regression test pass > 80% ✅
- [ ] ค่า 0.00 ลดลง > 50% ✅

---

## 🐛 Known Issues & Limitations

1. **VSD line-based OCR:**
   - ต้อง Google Vision OCR (ใช้ credit)
   - บางภาพ OCR อาจไม่แม่นพอ → fallback to keyword-based

2. **Analog auto-detection:**
   - ไม่ทำงานกับมิเตอร์ที่ digit window ไม่เป็นรูปสี่เหลี่ยม
   - ต้อง contour ชัดพอ

3. **Performance:**
   - Line-based OCR ช้ากว่าเดิมเล็กน้อย (เพิ่ม ~0.5-1s)
   - แนะนำให้ใช้ Roboflow สำหรับ production (เร็วกว่า)

---

## 📞 Support

มีปัญหา? ติดต่อ:
1. ดู log ใน terminal
2. เปิด `debug=True` 
3. ส่งภาพที่อ่านผิด + log มาให้ดู
