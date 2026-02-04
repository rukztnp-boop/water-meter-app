# 💧 Water Meter Monitoring System

AI-powered water and electric meter reading system with automated OCR and data logging to Google Sheets.

## ✨ Recent Updates (Feb 4, 2026)

### 🔥 Major OCR Bug Fixes

**Fixed Issues:**
1. **VSD/Digital (ACS580) Meters** - ระบบอ่านค่าผิดเป็น 0.00 เกือบทั้งหมด
2. **Analog Water Meters** - มิเตอร์ที่ไม่มี ROI อ่านไม่ถูก

**New Features:**
- ✅ **Line-based OCR** สำหรับ VSD/Digital meters (หาบรรทัด "Previous day kWh" อัตโนมัติ)
- ✅ **Auto digit window detection** สำหรับมิเตอร์อนาล็อก
- ✅ **Enhanced preprocessing** ทนต่อแสงแฟลช/การเอียง
- ✅ **Regression test suite** สำหรับ quality assurance

📖 **Documentation:**
- [OCR Fix Summary](OCR_FIX_SUMMARY.md) - รายละเอียดการแก้ไข
- [Testing Guide](OCR_TESTING_GUIDE.md) - วิธีทดสอบและ troubleshooting

---

## 🚀 Quick Start

### Installation

```bash
# Clone repository
git clone <repo-url>
cd water-meter-project

# Install dependencies
pip install -r requirements.txt
```

### Quick Test

```bash
# Test single image
python quick_demo.py your_meter_image.jpg

# Test VSD/Digital meter
python test_vsd_meter.py S__154140715_0.jpg -e 38.87

# Run full regression test
python test_ocr_regression.py test_images/

# Quick test script (includes zip extraction)
./quick_test.sh "รูป error หลังจากแก้ code วันนี้.zip"
```

---

## 📋 Features

### Core Functions
- 🤖 **AI-powered OCR** - Google Vision API + Roboflow object detection
- 📊 **Multiple meter types** - Analog water, Digital electric, VSD/ACS580
- 🎯 **Smart reading** - Auto ROI detection, red digit filtering, anomaly detection
- 📝 **Google Sheets integration** - Auto-logging to DailyReadings
- 📱 **Mobile-friendly** - Streamlit web interface
- 🔍 **QR code support** - Auto meter identification

### Meter Types Supported

#### 1. VSD/Digital (ABB ACS580)
- Line-based OCR with fuzzy matching
- Extracts "Previous day kWh (01.53)" correctly
- Filters out menu codes (01.XX, 02.XX)
- Confidence scoring

#### 2. Analog Water Meter
- Auto digit window detection
- Red digit filtering (for decimal places)
- Adaptive preprocessing for flash/tilt
- Morphological noise reduction

#### 3. SCADA/Digital Display
- Direct Excel export reading
- Time-based value extraction
- Multi-point support

---

## 🧪 Testing

### Test Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `quick_demo.py` | Test single image quickly | `python quick_demo.py image.jpg` |
| `test_vsd_meter.py` | Test VSD/Digital meters | `python test_vsd_meter.py folder/ -e 38.87` |
| `test_ocr_regression.py` | Full regression test | `python test_ocr_regression.py folder/ -o results.csv` |
| `quick_test.sh` | Automated test suite | `./quick_test.sh image_folder/` |

### Expected Test Results

**VSD/Digital:**
```
S__154140715_0.jpg → 38.87 ✅ (not 0.00 or 01.53)
Success rate: > 90%
```

**Analog:**
```
Auto-detect digit window ✅
Handle no ROI ✅
Flash/tilt resistant ✅
Success rate: > 80%
```

---

## 📁 Project Structure

```
water-meter-project/
├── app.py                      # Main application
├── frontend.py                 # Streamlit UI
├── daily_report_logger.py      # Daily reporting
├── test_ocr_regression.py      # Regression test harness
├── test_vsd_meter.py          # VSD meter testing
├── quick_demo.py              # Quick demo script
├── quick_test.sh              # Automated test script
├── OCR_FIX_SUMMARY.md         # Detailed fix documentation
├── OCR_TESTING_GUIDE.md       # Testing & troubleshooting
├── requirements.txt           # Python dependencies
└── service_account.json       # Google Cloud credentials
```

---

## 🔧 Configuration

### Google Cloud Setup
1. Create Google Cloud project
2. Enable Vision API
3. Enable Sheets API  
4. Download service account JSON
5. Place as `service_account.json`

### Streamlit Secrets
Create `.streamlit/secrets.toml`:
```toml
roboflow_api_key = "your_key_here"
db_sheet_name = "YourSheetName"
```

### Meter Configuration (Google Sheets)

**PointsMaster sheet columns:**
- `point_id` - Unique identifier
- `type` - Water/Electric
- `name` - Meter name (include "VSD", "ACS", "Digital")
- `keyword` - OCR keyword (e.g., "Previous day")
- `decimals` - Decimal places
- `expected_digits` - Expected digit count
- `roi_x1, roi_y1, roi_x2, roi_y2` - Region of interest

---

## 🐛 Troubleshooting

### VSD/Digital reads 0.00

```python
# Enable debug mode
value = ocr_process(image_bytes, config, debug=True)

# Check logs for:
# - "🔥 ตรวจพบ VSD/Digital meter" (detection)
# - "📋 VSD OCR: พบ X บรรทัด" (line count)
# - "🎯 VSD: เจอบรรทัดเป้าหมาย" (target line found)
```

### Analog reads wrong

```python
# Check auto digit window
config_copy = config.copy()
value = ocr_process(image_bytes, config_copy)
bbox = config_copy.get('_auto_digit_bbox')
print(f"Auto-detected bbox: {bbox}")

# Try without ROI
config['roi_x1'] = 0
config['roi_x2'] = 0
```

### Save debug images

```python
from app import preprocess_image_cv
import cv2

for variant in ["auto", "soft", "raw"]:
    processed = preprocess_image_cv(image_bytes, config, variant=variant)
    with open(f"debug_{variant}.png", 'wb') as f:
        f.write(processed)
```

---

## 📊 Performance

| Operation | Time | Notes |
|-----------|------|-------|
| VSD line-based OCR | +0.5-1s | Uses Google Vision |
| Analog auto-detect | +0.2-0.5s | OpenCV contours |
| Roboflow detection | 1-2s | Fastest, most accurate |
| Standard OCR | 1-3s | Fallback method |

**Recommendations:**
- Use Roboflow for production (fastest + most accurate)
- Enable caching for repeated images
- Batch process multiple images

---

## 🔜 Roadmap

- [ ] Support more VSD brands (Schneider, Siemens)
- [ ] Perspective correction for tilted meters
- [ ] Custom model training for Thai meter brands
- [ ] Real-time video stream processing
- [ ] Mobile app (iOS/Android)
- [ ] Anomaly detection ML model
- [ ] Multi-language support

---

## 📝 License

[Your License Here]

## 📞 Contact

[Your Contact Info]

---

## 🙏 Credits

- Google Cloud Vision API
- Roboflow Object Detection
- OpenCV
- Streamlit
- gspread

**Last Updated:** February 4, 2026
