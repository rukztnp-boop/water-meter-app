import os
import io
import re
import uvicorn
import gspread
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from pydantic import BaseModel
from google.oauth2 import service_account
from google.cloud import vision
from datetime import datetime
import string

# --- CONFIGURATION ---
KEY_FILE = 'service_account.json'
DB_SHEET_NAME = 'WaterMeter_System_DB'     
REAL_REPORT_SHEET = 'TEST waterreport' 

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = KEY_FILE

creds = service_account.Credentials.from_service_account_file(
    KEY_FILE, 
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/cloud-platform"
    ]
)
gc = gspread.authorize(creds)

# --- เพิ่ม Middleware รองรับ request body ขนาดใหญ่ (100MB) ---
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int):
        super().__init__(app)
        self.max_upload_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > self.max_upload_size:
            return Response(
                content=f"Request too large. Limit is {self.max_upload_size // (1024*1024)}MB.",
                status_code=413
            )
        return await call_next(request)

app = FastAPI()
app.add_middleware(LimitUploadSizeMiddleware, max_upload_size=100*1024*1024)  # 100MB

# --- Helper Functions (Sheet & Config) ---

def col_to_index(col_str):
    col_str = str(col_str).upper().strip()
    num = 0
    for c in col_str:
        if c in string.ascii_letters:
            num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num

def get_thai_sheet_name(sh):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    now = datetime.now()
    m_idx = now.month - 1
    yy = str(now.year + 543)[-2:] 
    
    patterns = [
        f"{thai_months[m_idx]}{yy}",       # ม.ค.69
        f"{thai_months[m_idx][:-1]}{yy}",  # ม.ค69
        f"{thai_months[m_idx]} {yy}",      # ม.ค. 69
        f"{thai_months[m_idx][:-1]} {yy}"  # ม.ค 69
    ]
    all_sheets = [s.title for s in sh.worksheets()]
    for p in patterns:
        if p in all_sheets: return p
    return None 

def get_meter_config(point_id):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("PointsMaster")
        records = ws.get_all_records()
        for item in records:
            if str(item.get('point_id', '')).strip().upper() == str(point_id).strip().upper():
                try: item['decimals'] = int(item.get('decimals') or 0)
                except: item['decimals'] = 0
                item['keyword'] = str(item.get('keyword', '')).strip()
                try: item['expected_digits'] = int(item.get('expected_digits') or 0)
                except: item['expected_digits'] = 0
                item['report_column'] = str(item.get('report_col', '')).strip() 
                return item
        return None
    except Exception as e:
        print(f"❌ DB Error: {e}")
        return None

def export_to_real_report(point_id, read_value, inspector, report_col, target_date=None):
    """
    เพิ่ม target_date (datetime.date) เพื่อรองรับบันทึกย้อนหลัง
    ถ้าไม่ระบุ target_date จะใช้วันที่ปัจจุบัน
    """
    if not report_col: return False
    try:
        sh = gc.open(REAL_REPORT_SHEET)
        sheet_name = get_thai_sheet_name(sh)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)

        day = target_date.day if target_date else datetime.now().day
        try:
            cell = ws.find(str(day), in_column=1)
            target_row = cell.row
        except:
            target_row = 6 + day # ✅ Offset 6

        target_col = col_to_index(report_col)
        if target_col == 0: return False

        ws.update_cell(target_row, target_col, read_value)
        print(f"✅ Exported to {ws.title} | R{target_row}, C{target_col} : {read_value} (day={day})")
        return True
    except Exception as e:
        print(f"❌ Export Error: {e}")
        return False

def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, image_url="-"):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), meter_type, point_id, inspector, manual_val, ai_val, status, image_url]
        ws.append_row(row)
        return True
    except: return False

# --- 🔥 BEST OCR LOGIC (รวมร่าง) ---

def preprocess_text(text):
    # 1. De-Noiser (มาตรฐาน)
    patterns_to_remove = [
        r'IP\s*51', r'50\s*Hz', r'Class\s*2', r'3x220/380\s*V', 
        r'Type', r'Mitsubishi', r'Electric', r'Wire', r'kWh',
        r'MH\s*[-]?\s*96', r'30\s*\(100\)\s*A', r'\d+\s*rev/kWh',
        r'WATT-HOUR\s*METER', r'Indoor\s*Use', r'Made\s*in\s*Thailand'
    ]
    for p in patterns_to_remove:
        text = re.sub(p, '', text, flags=re.IGNORECASE)

    # 2. Scale Killer
    text = re.sub(r'\b10,000\b', '', text)
    text = re.sub(r'\b1,000\b', '', text)

    # 3. ✅ Symbol Fixer (จากโค้ดที่คุณชอบ: แปลง | เป็น 1)
    text = re.sub(r'(?<=[\d\s])[\|Il!](?=[\d\s])', '1', text)
    text = re.sub(r'(?<=[\d\s])[Oo](?=[\d\s])', '0', text)
    
    # 4. Garbage Collector (Force 8/7)
    text = re.sub(r'(?<=[\d\s]{4})(?<=\d)\s*[A-Za-z&%$#@!§\(\)\{\}\?\/](?=\s|$)', '8', text)
    text = re.sub(r'(?<=[\d])\s*[\/\?\)>\}\]TZ\-_](?=\s|$)', '7', text)
    
    return text

def ocr_process(image_bytes, decimal_places=0, keyword="", expected_digits=0):
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_bytes)
    response = client.text_detection(image=image)
    texts = response.text_annotations
    
    if texts:
        # เก็บข้อความดิบไว้หา Keyword (แก้เรื่อง Electric)
        raw_full_text = texts[0].description.replace('\n', ' ')
        # ล้างข้อความเพื่อหาเลข (แก้เรื่อง Analog)
        full_text = preprocess_text(raw_full_text)
        
        print(f"🔍 OCR Raw: {raw_full_text} | Clean: {full_text}")

        # --- 🎯 1. Keyword Hunter (หาจาก Raw Text) ---
        if keyword:
            pattern = re.escape(keyword) + r"[^\d]*((?:\d|O|o|l|I|\|)+[\.,]?\d*)"
            match = re.search(pattern, raw_full_text, re.IGNORECASE)
            if match:
                val_str = match.group(1)
                val_str = val_str.replace('O', '0').replace('o', '0')
                val_str = val_str.replace('l', '1').replace('I', '1').replace('|', '1')
                try: 
                    val = float(val_str.replace(',', ''))
                    if decimal_places > 0 and '.' not in str(val): val = val / (10**decimal_places)
                    print(f"🎯 Keyword found: {val}")
                    return val, full_text
                except: pass

        # --- 🚫 2. ID Killer ---
        blacklisted_values = []
        id_matches = re.finditer(r'(?i)(?:id|code|no\.?|serial|s\/n)[\D]{0,15}?(\d+(?:[\s-]+\d+)*)', full_text)
        for m in id_matches:
            for p in re.split(r'[\s-]+', m.group(1)):
                try: blacklisted_values.extend([float(p), float(int(p))])
                except: pass

        def check_digits(val):
            if expected_digits == 0: return True 
            try: return len(str(int(val))) in [expected_digits, expected_digits - 1]
            except: return False
        
        def is_binary_noise(val):
            s = str(int(val))
            return set(s).issubset({'0', '1'}) and len(s) > 1

        candidates = []

        # --- 🧵 3. Stitcher (รวมเลขห่างๆ) ---
        analog_labels = [r'10\D?000', r'1\D?000', r'100', r'10', r'1']
        stitched_digits = {}
        for idx, label in enumerate(analog_labels):
            match = re.search(label + r'[^\d]{0,30}\s+(\d)\b', raw_full_text)
            if match: stitched_digits[idx] = match.group(1)
        
        if len(stitched_digits) >= 2:
            sorted_keys = sorted(stitched_digits.keys())
            final_str = "".join([stitched_digits[k] for k in sorted_keys])
            try:
                val = float(final_str)
                if val not in blacklisted_values and check_digits(val):
                    score = len(stitched_digits) * 100 
                    if is_binary_noise(val): score -= 300 
                    candidates.append({'val': val, 'score': score})
            except: pass

        # --- 🛡️ 4. Loose Stitcher ---
        matches = re.finditer(r'\b\d(?:\D{0,10}\d){3,6}\b', full_text)
        for m in matches:
            clean = re.sub(r'\D', '', m.group(0))
            try:
                val = float(clean)
                if val not in blacklisted_values and val not in [10000, 1000, 100, 10, 1]:
                     if check_digits(val):
                         score = 100 + (len(clean) * 50)
                         candidates.append({'val': val, 'score': score})
            except: pass

        # --- 5. Standard Logic ---
        clean_std = re.sub(r'\b202[0-9]\b|\b256[0-9]\b', '', full_text)
        nums = re.findall(r'-?\d+\.\d+' if decimal_places > 0 else r'\d+', clean_std)
        for n_str in nums:
            try:
                val = float(n_str) if '.' in n_str else int(n_str)
                if decimal_places > 0 and '.' not in str(val): val = val / (10**decimal_places)
                if val in blacklisted_values: continue
                if not check_digits(val): continue
                score = 100
                if decimal_places > 0 and '.' in str(val): score += 50
                candidates.append({'val': float(val), 'score': score})
            except: continue

        if candidates:
            valid = [c for c in candidates if c['score'] > 0]
            if valid: return max(valid, key=lambda x: (x['score'], x['val']))['val'], full_text
            elif candidates: return max(candidates, key=lambda x: (x['score'], x['val']))['val'], full_text

    return 0, ""

# --- API Endpoints ---

@app.get("/meters")
async def get_all_meters_list():
    try:
        sh = gc.open(DB_SHEET_NAME)
        data = sh.worksheet("PointsMaster").get_all_records()
        sorted_data = sorted(data, key=lambda x: x.get('point_id', ''))
        return {"status": "SUCCESS", "data": sorted_data}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

@app.post("/scan")
async def scan_meter(
    point_id: str = Form(...), 
    inspector: str = Form(...), 
    meter_type: str = Form(...), 
    manual_value: float = Form(...), 
    confirm_mismatch: bool = Form(False),
    file: UploadFile = File(...)
):
    config = get_meter_config(point_id)
    if not config: return {"status": "ERROR", "message": "Point ID not found"}
    
    image_bytes = await file.read()
    # เรียกใช้ OCR ตัวเทพ
    ai_value, _ = ocr_process(image_bytes, config['decimals'], config['keyword'], config['expected_digits'])
    
    is_match = abs(manual_value - ai_value) <= 1.0 
    report_col = config.get('report_col', '')

    if is_match:
        if save_to_db(point_id, inspector, meter_type, manual_value, ai_value, "VERIFIED"):
            export_to_real_report(point_id, manual_value, inspector, report_col)
            return {"status": "SUCCESS", "message": "Matched", "data": {"manual": manual_value, "ai": ai_value, "status": "VERIFIED"}}
        return {"status": "ERROR", "message": "Save failed"}
    else:
        if confirm_mismatch:
            if save_to_db(point_id, inspector, meter_type, manual_value, ai_value, "FLAGGED"):
                return {"status": "SUCCESS", "message": "Flagged", "data": {"manual": manual_value, "ai": ai_value, "status": "FLAGGED"}}
            return {"status": "ERROR", "message": "Save failed"}
        else:
            return {"status": "WARNING", "message": f"ไม่ตรงกัน! กรอก {manual_value} / AI {ai_value}", "data": {"manual": manual_value, "ai": ai_value}}

@app.get("/admin/pending")
async def get_pending_approvals():
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        data = ws.get_all_records()
        pending_list = []
        for i, row in enumerate(data):
            if row.get('Status') == 'FLAGGED':
                row['row_id'] = i + 2 
                pending_list.append(row)
        return {"status": "SUCCESS", "data": pending_list}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

class ApproveRequest(BaseModel):
    row_id: int
    point_id: str
    final_value: float
    inspector: str

@app.post("/admin/approve")
async def approve_reading(req: ApproveRequest):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        ws.update_cell(req.row_id, 7, "APPROVED") 
        ws.update_cell(req.row_id, 5, req.final_value)

        config = get_meter_config(req.point_id)
        report_col = config.get('report_col', '') if config else ''

        if export_to_real_report(req.point_id, req.final_value, req.inspector, report_col):
             return {"status": "SUCCESS", "message": "Approved & Exported"}
        else:
             return {"status": "WARNING", "message": "Approved but Export failed"}
             
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)