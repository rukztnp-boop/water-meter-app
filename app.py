import hashlib
import streamlit as st
import io
import os
import re
import gspread
import openpyxl
from openpyxl.utils.cell import column_index_from_string
import json
import cv2
import numpy as np
import pandas as pd
import math
from google.oauth2 import service_account
from google.cloud import vision
from google.cloud import storage
from datetime import datetime, timedelta, timezone, time # ✅ เพิ่ม time
import string

# =========================================================
# --- 📦 CONFIGURATION ---
# =========================================================
BUCKET_NAME = 'water-meter-images-watertreatmentplant'
FIXED_FOLDER_ID = '1XH4gKYb73titQLrgp4FYfLT2jzYRgUpO' 

# =========================================================
# --- 🕒 TIMEZONE HELPER ---
# =========================================================
def get_thai_time():
    """คืนค่าเวลาปัจจุบันในโซนไทย (UTC+7)"""
    tz = timezone(timedelta(hours=7))
    return datetime.now(tz)

# =========================================================
# --- PAGE CONFIG ---
# =========================================================
st.set_page_config(page_title="Smart Meter System", page_icon="💧", layout="centered")

st.markdown("""
    <style>
    .stButton>button { width: 100%; border-radius: 8px; font-weight: bold; }
    .status-box { padding: 15px; border-radius: 10px; margin-bottom: 15px; border: 1px solid #ddd; }
    .status-warning { background-color: #fff3cd; color: #856404; }
    .report-badge {
        background-color: #e3f2fd; color: #0d47a1;
        padding: 4px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# --- CONFIGURATION & SECRETS ---
# =========================================================
if 'gcp_service_account' in st.secrets:
    try:
        key_dict = json.loads(st.secrets['gcp_service_account'])
        if 'private_key' in key_dict:
            key_dict['private_key'] = key_dict['private_key'].replace('\\n', '\n')

        creds = service_account.Credentials.from_service_account_info(
            key_dict,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/cloud-platform"
            ]
        )
    except Exception as e:
        st.error(f"❌ Error loading secrets: {e}")
        st.stop()
else:
    st.error("❌ Secrets not found.")
    st.stop()

gc = gspread.authorize(creds)
DB_SHEET_NAME = 'WaterMeter_System_DB'
REAL_REPORT_SHEET = 'TEST waterreport'
VISION_CLIENT = vision.ImageAnnotatorClient(credentials=creds)
STORAGE_CLIENT = storage.Client(credentials=creds)

# =========================================================
# --- CLOUD STORAGE HELPERS ---
# =========================================================
def upload_image_to_storage(image_bytes, file_name):
    try:
        bucket = STORAGE_CLIENT.bucket(BUCKET_NAME)
        blob = bucket.blob(file_name)

        # ตั้งค่า Content-Type ให้ตรงกับนามสกุลไฟล์ (มือถือเปิดรูปได้ถูกต้อง)
        ext = str(file_name).lower().split(".")[-1] if "." in str(file_name) else "jpg"
        content_type = "image/png" if ext == "png" else "image/jpeg"

        blob.upload_from_string(image_bytes, content_type=content_type)
        return blob.public_url
    except Exception as e:
        return f"Error: {e}"


# =========================================================
# --- 🖼️ REFERENCE IMAGE (Auto Find) ---
# =========================================================
REF_IMAGE_FOLDER = "ref_images"

@st.cache_data(ttl=3600)
def load_ref_image_bytes_any(point_id: str):
    """
    หา reference รูปให้เอง:
    1) ref_images/POINT.(jpg/png)
    2) POINT.(jpg/png) ใน root
    3) ถ้าไม่เจอ → หาไฟล์ล่าสุดที่ขึ้นต้นด้วย POINT_ (เช่น POINT_2026...jpg)
    คืนค่า: (bytes, path) หรือ (None, None)
    """
    pid = str(point_id).strip().upper()
    bucket = STORAGE_CLIENT.bucket(BUCKET_NAME)

    # 1) ลองชื่อมาตรฐานก่อน
    candidates = []
    for ext in ["jpg", "jpeg", "png", "JPG", "JPEG", "PNG"]:
        candidates += [
            f"{REF_IMAGE_FOLDER}/{pid}.{ext}",
            f"{pid}.{ext}",
        ]

    # ลองดาวน์โหลดตรง ๆ (ไม่ต้องใช้ exists เพื่อกันเวอร์ชันไลบรารีต่างกัน)
    for path in candidates:
        try:
            blob = bucket.blob(path)
            data = blob.download_as_bytes()
            if data:
                return data, path
        except Exception:
            pass

    # 2) หาแบบ prefix เอาไฟล์ล่าสุด (POINT_....jpg/png)
    try:
        blobs = list(bucket.list_blobs(prefix=f"{pid}_"))
        blobs = [b for b in blobs if str(b.name).lower().endswith((".jpg", ".jpeg", ".png"))]
        if blobs:
            blobs.sort(key=lambda b: b.updated or datetime.min, reverse=True)
            b = blobs[0]
            data = b.download_as_bytes()
            return data, b.name
    except Exception:
        pass

    return None, None


# =========================================================
# --- SHEET HELPERS ---
# =========================================================
def col_to_index(col_str):
    col_str = str(col_str).upper().strip()
    num = 0
    for c in col_str:
        if c in string.ascii_letters:
            num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num

# ✅ แก้ไข: รับวันที่เข้ามาเพื่อหา Sheet เดือนที่ถูกต้อง (เผื่อลงย้อนหลังข้ามเดือน)
def get_thai_sheet_name(sh, target_date):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    
    # ใช้วันที่ที่เลือก (target_date) แทนเวลาปัจจุบัน
    m_idx = target_date.month - 1
    # ปีพุทธศักราช
    yy = str(target_date.year + 543)[-2:]
    
    patterns = [f"{thai_months[m_idx]}{yy}", f"{thai_months[m_idx][:-1]}{yy}", f"{thai_months[m_idx]} {yy}", f"{thai_months[m_idx][:-1]} {yy}"]
    all_sheets = [s.title for s in sh.worksheets()]
    for p in patterns:
        if p in all_sheets:
            return p
    return None

def find_day_row_exact(ws, day: int):
    col = ws.col_values(1)
    for i, v in enumerate(col, start=1):
        try:
            if int(str(v).strip()) == int(day):
                return i
        except:
            pass
    return None

@st.cache_data(ttl=300)
def load_points_master():
    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("PointsMaster")
    return ws.get_all_records()

def safe_int(x, default=0):
    try: return int(float(x)) if x and str(x).strip() else default
    except: return default

def safe_float(x, default=0.0):
    try: return float(x) if x and str(x).strip() else default
    except: return default

def parse_bool(v):
    if v is None: return False
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t", "on")

def get_meter_config(point_id):
    try:
        records = load_points_master()
        pid = str(point_id).strip().upper()
        for item in records:
            if str(item.get('point_id', '')).strip().upper() == pid:
                item['decimals'] = safe_int(item.get('decimals'), 0)
                item['keyword'] = str(item.get('keyword', '')).strip()
                exp = safe_int(item.get('expected_digits'), 0)
                if exp == 0: exp = safe_int(item.get('int_digits'), 0)
                item['expected_digits'] = exp
                item['report_col'] = str(item.get('report_col', '')).strip()
                item['ignore_red'] = parse_bool(item.get('ignore_red'))
                item['roi_x1'] = safe_float(item.get('roi_x1'), 0.0)
                item['roi_y1'] = safe_float(item.get('roi_y1'), 0.0)
                item['roi_x2'] = safe_float(item.get('roi_x2'), 0.0)
                item['roi_y2'] = safe_float(item.get('roi_y2'), 0.0)
                item['type'] = str(item.get('type', '')).strip()
                item['name'] = str(item.get('name', '')).strip()
                return item
        return None
    except: return None

# ✅ แก้ไข: รับ target_date เพื่อลงให้ถูกวัน
def export_to_real_report(point_id, read_value, inspector, report_col, target_date, debug=False):
    """ส่งค่าลง Google Sheet REAL_REPORT_SHEET
    - debug=False: คืน True/False เหมือนเดิม
    - debug=True : คืน (ok, message) เพื่อโชว์สาเหตุเวลาส่งไม่เข้า
    """

    def _ret(ok, msg=""):
        return (ok, msg) if debug else ok

    if not report_col:
        return _ret(False, "report_col ว่าง")
    report_col = str(report_col).strip()
    if report_col in ("-", "—", "–"):
        return _ret(False, "report_col เป็น '-' (ยังไม่ได้ตั้งค่าใน PointsMaster)")

    # เปิดชีท
    try:
        sh = gc.open(REAL_REPORT_SHEET)
    except Exception as e:
        return _ret(False, f"เปิดชีท '{REAL_REPORT_SHEET}' ไม่ได้: {e}")

    # หาแท็บเดือน
    sheet_name = None
    try:
        sheet_name = get_thai_sheet_name(sh, target_date)
    except Exception:
        sheet_name = None

    # ถ้าไม่เจอ → หาแบบฟัซซี่ (ตัดช่องว่าง/จุด)
    if not sheet_name:
        try:
            thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
            m_idx = target_date.month - 1
            yy2 = str(target_date.year + 543)[-2:]
            yy4 = str(target_date.year + 543)
            m_norm = thai_months[m_idx].replace(".", "").replace(" ", "")

            def norm(x):
                return str(x).replace(".", "").replace(" ", "").strip()

            for t in [s.title for s in sh.worksheets()]:
                tn = norm(t)
                if (m_norm in tn) and (yy2 in tn or yy4 in tn):
                    sheet_name = t
                    break
        except Exception:
            sheet_name = None

    # เปิด worksheet
    try:
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
    except Exception as e:
        return _ret(False, f"เปิดแท็บ '{sheet_name}' ไม่ได้: {e}")

    # หาแถวของวัน
    try:
        target_day = int(target_date.day)
        target_row = find_day_row_exact(ws, target_day) or (6 + target_day)
    except Exception as e:
        return _ret(False, f"หาแถวของวันไม่สำเร็จ: {e}")

    # หา col
    target_col = col_to_index(report_col)
    if target_col == 0:
        return _ret(False, f"report_col '{report_col}' แปลงเป็นคอลัมน์ไม่ได้")

    # เขียนค่า
    try:
        ws.update_cell(target_row, target_col, read_value)
        return _ret(True, f"OK → sheet='{ws.title}', row={target_row}, col={report_col}({target_col}), val={read_value}")
    except Exception as e:
        return _ret(False, f"เขียนค่าไม่สำเร็จ: {e}")



# ✅ แก้ไข: รับ target_date เพื่อลง Timestamp ให้ถูกวัน
def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, target_date, image_url="-"):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        
        # สร้าง Timestamp: วันที่เลือก + เวลาปัจจุบัน (เพื่อให้รู้ว่าคีย์ตอนกี่โมง แต่วันที่เป็นของวันที่เลือก)
        current_time = get_thai_time().time()
        record_timestamp = datetime.combine(target_date, current_time)
        
        row = [record_timestamp.strftime("%Y-%m-%d %H:%M:%S"), meter_type, point_id, inspector, manual_val, ai_val, status, image_url]
        ws.append_row(row)
        return True
    except: return False

# =========================================================
# --- 🧠 OCR ENGINE (Clean & Robust) ---
# =========================================================

# ------------------------ SCADA Excel Upload (Export) ------------------------
def _normalize_scada_time(token):
    """Normalize SCADA time tokens into 'HH:MM' string.

    Supports:
      - '23:55', '23.55', '23:55:00'
      - numbers like 23.55 (meaning 23:55) from DB mappings
      - Excel time fractions like 0.996527... (meaning 23:55)
      - datetime/time objects
    """
    if token is None:
        return None

    # datetime objects
    try:
        import datetime as _dt
        if isinstance(token, _dt.datetime):
            return f"{token.hour:02d}:{token.minute:02d}"
        if isinstance(token, _dt.time):
            return f"{token.hour:02d}:{token.minute:02d}"
    except Exception:
        pass

    # Numeric tokens
    if isinstance(token, (int, float)):
        x = float(token)

        # 1) HH.MM style (e.g., 23.55 -> 23:55, 0.10 -> 00:10)
        #    We detect it by "2-digit minutes" pattern: fractional part * 100 is close to an integer < 60.
        hh = int(x) if x >= 0 else None
        frac = x - (hh or 0)
        mm_candidate = int(round(frac * 100))

        # tolerance for binary float issues
        if hh is not None:
            approx = (hh + (mm_candidate / 100.0))
            if 0 <= hh <= 23 and 0 <= mm_candidate <= 59 and abs(x - approx) < 1e-6:
                return f"{hh:02d}:{mm_candidate:02d}"

        # 2) Excel fraction-of-day (0..1)
        if 0 <= x < 1:
            minutes = int(round(x * 24 * 60))
            hh2 = (minutes // 60) % 24
            mm2 = minutes % 60
            return f"{hh2:02d}:{mm2:02d}"

        return None

    # String tokens
    s = str(token).strip()
    if not s:
        return None

    # allow dot separator
    s = s.replace(".", ":")

    import re as _re
    m = _re.match(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"

    m = _re.match(r"^(\d{1,2})(\d{2})$", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"

    return None

def _strip_date_prefix(name: str) -> str:
    """
    เอาวันที่นำหน้าออก (เช่น 2026_01_12_Daily_Report -> Daily_Report)
    """
    base = os.path.splitext(os.path.basename(name))[0]
    base = re.sub(r"^\d{4}_\d{2}_\d{2}_", "", base)
    return base.strip().lower()


def load_scada_excel_mapping(local_path: str = "DB_Water_Scada.xlsx", uploaded_bytes=None):
    """
    อ่าน mapping จากไฟล์ DB_Water_Scada.xlsx
    ต้องมีหัวตาราง: PointID, File, Sheet, Time, Colume
    คืนค่าเป็น list ของ dict: {point_id, file_key, sheet, time, col}
    """
    if uploaded_bytes:
        wb = openpyxl.load_workbook(io.BytesIO(uploaded_bytes), data_only=True)
    else:
        if not os.path.exists(local_path):
            return []
        wb = openpyxl.load_workbook(local_path, data_only=True)

    ws = wb[wb.sheetnames[0]]

    # หาแถวหัวตาราง
    header_row = None
    header_map = {}
    for r in range(1, min(ws.max_row, 30) + 1):
        row_vals = [ws.cell(r, c).value for c in range(1, min(ws.max_column, 20) + 1)]
        row_str = [str(v).strip().lower() if v is not None else "" for v in row_vals]
        if "pointid" in row_str and "file" in row_str and "sheet" in row_str:
            header_row = r
            for idx, name in enumerate(row_str, start=1):
                if name in ["pointid", "file", "sheet", "time", "colume", "column"]:
                    header_map[name] = idx
            break

    if not header_row:
        return []

    # รองรับสะกด Colume/Column
    col_idx = header_map.get("colume") or header_map.get("column")
    out = []
    for r in range(header_row + 1, ws.max_row + 1):
        point_id = ws.cell(r, header_map["pointid"]).value
        if point_id is None or str(point_id).strip() == "":
            continue

        file_key = ws.cell(r, header_map["file"]).value
        sheet = ws.cell(r, header_map["sheet"]).value
        t = ws.cell(r, header_map.get("time", 0)).value if header_map.get("time") else None
        col = ws.cell(r, col_idx).value if col_idx else None

        out.append({
            "point_id": str(point_id).strip(),
            "file_key": str(file_key).strip() if file_key is not None else "",
            "sheet": str(sheet).strip() if sheet is not None else "Sheet1",
            "time": t,
            "col": str(col).strip() if col is not None else "",
        })
    return out


def _find_cell_exact(ws, target_text: str, max_rows=60, max_cols=40):
    target = target_text.strip().lower()
    for r in range(1, min(ws.max_row, max_rows) + 1):
        for c in range(1, min(ws.max_column, max_cols) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip().lower() == target:
                return r, c
    return None


def _extract_value_from_ws(ws, target_time_hhmm, value_col_letter: str, time_header="Time"):
    """
    หา row ของเวลาที่ต้องการ แล้วดึงค่าตามคอลัมน์ตัวอักษร (เช่น 'Y')
    ถ้าหาเวลาไม่เจอ จะ fallback ไป row สุดท้ายที่มีข้อมูล
    """
    hdr = _find_cell_exact(ws, time_header)
    if not hdr:
        return None, "NO_TIME_HEADER"

    hdr_row, time_col = hdr
    target_row = None

    if target_time_hhmm:
        for r in range(hdr_row + 1, ws.max_row + 1):
            v = ws.cell(r, time_col).value
            if _normalize_scada_time(v) == target_time_hhmm:
                target_row = r
                break

    if target_row is None:
        # หา row สุดท้ายที่ time ไม่ว่าง
        for r in range(ws.max_row, hdr_row, -1):
            v = ws.cell(r, time_col).value
            if _normalize_scada_time(v) is not None:
                target_row = r
                break

    if target_row is None:
        return None, "NO_DATA_ROW"

    try:
        col_idx = column_index_from_string(value_col_letter)
    except Exception:
        return None, "BAD_COLUMN"

    val = ws.cell(target_row, col_idx).value
    return val, "OK"


def extract_scada_values_from_exports(mapping_rows, uploaded_exports: dict):
    """
    mapping_rows: list[dict] จาก load_scada_excel_mapping
    uploaded_exports: dict filename->bytes ของไฟล์ Excel ที่อัปโหลด
    คืนค่า:
      - results: list[dict] สำหรับแสดงในตาราง
      - missing: list[dict] รายการที่ดึงไม่สำเร็จ
    """
    # โหลด workbook ทีละไฟล์ (cache ใน dict)
    wb_cache = {}
    for fname, b in uploaded_exports.items():
        try:
            wb_cache[fname] = openpyxl.load_workbook(io.BytesIO(b), data_only=True)
        except Exception:
            wb_cache[fname] = None

    # helper: หาไฟล์ที่ตรงกับ file_key
    def pick_file_for_key(file_key: str):
        if not uploaded_exports:
            return None
        key_norm = _strip_date_prefix(file_key)
        # exact by contains
        for fname in uploaded_exports.keys():
            if key_norm and key_norm in _strip_date_prefix(fname):
                return fname
        # fallback: ถ้ามีไฟล์เดียว ใช้อันนั้น
        if len(uploaded_exports) == 1:
            return list(uploaded_exports.keys())[0]
        return None

    results = []
    missing = []

    for row in mapping_rows:
        point_id = row["point_id"]
        file_key = row["file_key"]
        sheet = row.get("sheet") or "Sheet1"
        col = row.get("col") or ""
        t_hhmm = _normalize_scada_time(row.get("time"))

        fname = pick_file_for_key(file_key)
        if not fname or not wb_cache.get(fname):
            missing.append({**row, "reason": "NO_MATCH_FILE"})
            results.append({"point_id": point_id, "value": None, "file": file_key, "sheet": sheet, "time": t_hhmm, "col": col, "status": "NO_FILE"})
            continue

        wb = wb_cache[fname]
        if sheet not in wb.sheetnames:
            missing.append({**row, "reason": "NO_SHEET"})
            results.append({"point_id": point_id, "value": None, "file": file_key, "sheet": sheet, "time": t_hhmm, "col": col, "status": "NO_SHEET"})
            continue

        ws = wb[sheet]
        val, stt = _extract_value_from_ws(ws, t_hhmm, col)
        results.append({"point_id": point_id, "value": val, "file": file_key, "sheet": sheet, "time": t_hhmm, "col": col, "status": stt})

        if stt != "OK" or val is None:
            missing.append({**row, "reason": stt})

    return results, missing

def normalize_number_str(s: str, decimals: int = 0) -> str:
    if not s: return ""
    s = str(s).strip().replace(",", "").replace(" ", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\.{2,}", ".", s)
    if s.count(".") > 1:
        parts = [p for p in s.split(".") if p != ""]
        if len(parts) >= 2: s = parts[0] + "." + "".join(parts[1:])
        else: s = s.replace(".", "")
    if decimals == 0: s = s.replace(".", "")
    return s

def preprocess_text(text):
    patterns = [r'IP\s*51', r'50\s*Hz', r'Class\s*2', r'3x220/380\s*V', r'Type', r'Mitsubishi', r'Electric', r'Wire', r'kWh', r'MH\s*[-]?\s*96', r'30\s*\(100\)\s*A', r'\d+\s*rev/kWh', r'WATT-HOUR\s*METER', r'Indoor\s*Use', r'Made\s*in\s*Thailand']
    for p in patterns: text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b10,000\b', '', text)
    text = re.sub(r'\b1,000\b', '', text)
    text = re.sub(r'(?<=[\d\s])[\|Il!](?=[\d\s])', '1', text)
    text = re.sub(r'(?<=[\d\s])[Oo](?=[\d\s])', '0', text)
    return text

def is_digital_meter(config):
    blob = f"{config.get('type','')} {config.get('name','')} {config.get('keyword','')}".lower()
    return ("digital" in blob) or ("scada" in blob) or (int(config.get('decimals', 0) or 0) > 0)

def preprocess_image_cv(image_bytes, config, use_roi=True, variant="auto"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None: return image_bytes

    H, W = img.shape[:2]
    if W > 1280:
        scale = 1280 / W
        img = cv2.resize(img, (1280, int(H * scale)), interpolation=cv2.INTER_AREA)
        H, W = img.shape[:2]

    if use_roi:
        x1, y1, x2, y2 = config.get('roi_x1', 0), config.get('roi_y1', 0), config.get('roi_x2', 0), config.get('roi_y2', 0)
        if x2 and y2:
            if 0 < x2 <= 1 and 0 < y2 <= 1:
                x1, y1, x2, y2 = int(float(x1) * W), int(float(y1) * H), int(float(x2) * W), int(float(y2) * H)
            else:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            pad_x, pad_y = int(0.03 * W), int(0.03 * H)
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
            if x2 > x1 and y2 > y1:
                img = img[y1:y2, x1:x2]
                H, W = img.shape[:2]

    if config.get('ignore_red', False):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_red1 = np.array([0, 70, 50]);  upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 70, 50]); upper_red2 = np.array([180, 255, 255])
        mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
        img[mask > 0] = [255, 255, 255]

    if variant == "raw":
        ok, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes() if ok else image_bytes

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if variant == "invert": gray = 255 - gray

    use_digital_logic = (variant == "soft") or (variant == "auto" and is_digital_meter(config))

    if use_digital_logic:
        if min(H, W) < 300:
            gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        g = clahe.apply(gray)
        blur = cv2.GaussianBlur(g, (0, 0), 1.0)
        sharp = cv2.addWeighted(g, 1.6, blur, -0.6, 0)
        ok, encoded = cv2.imencode(".png", sharp)
        return encoded.tobytes() if ok else image_bytes
    else:
        gray2 = cv2.bilateralFilter(gray, 7, 50, 50)
        th = cv2.adaptiveThreshold(gray2, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
        ok, encoded = cv2.imencode(".png", th)
        return encoded.tobytes() if ok else image_bytes

def _vision_read_text(processed_bytes):
    try:
        image = vision.Image(content=processed_bytes)
        ctx = vision.ImageContext(language_hints=["en"])
        resp = VISION_CLIENT.text_detection(image=image, image_context=ctx)
        if getattr(resp, "error", None) and resp.error.message: return "", resp.error.message
        if resp.text_annotations: return (resp.text_annotations[0].description or ""), ""
        
        resp2 = VISION_CLIENT.document_text_detection(image=image, image_context=ctx)
        txt = ""
        if resp2.full_text_annotation and resp2.full_text_annotation.text: txt = resp2.full_text_annotation.text
        return (txt or ""), ""
    except Exception as e:
        return "", str(e)

def ocr_process(image_bytes, config, debug=False):
    decimal_places = int(config.get('decimals', 0) or 0)
    keyword = str(config.get('keyword', '') or '').strip()
    expected_digits = int(config.get('expected_digits', 0) or 0)
    
    attempts = [
        ("ROI_auto",  True,  "auto"),
        ("ROI_raw",   True,  "raw"),
        ("ROI_soft",  True,  "soft"),
        ("ROI_inv",   True,  "invert"),
        ("FULL_auto", False, "auto"),
        ("FULL_raw",  False, "raw"),
    ]

    raw_full_text = ""
    for tag, use_roi, variant in attempts:
        processed = preprocess_image_cv(image_bytes, config, use_roi=use_roi, variant=variant)
        txt, err = _vision_read_text(processed)
        if txt and txt.strip():
            if any(c.isdigit() for c in txt):
                raw_full_text = (txt or "").replace("\n", " ")
                raw_full_text = re.sub(r"\.{2,}", ".", raw_full_text)
                break
    
    if not raw_full_text: return 0.0

    full_text = preprocess_text(raw_full_text)
    full_text = re.sub(r"\.{2,}", ".", full_text)

    def check_digits(val: float) -> bool:
        if expected_digits <= 0: return True
        try:
            ln = len(str(int(abs(float(val)))))
            return 1 <= ln <= expected_digits + 1
        except: return False

    def looks_like_spec_context(text: str, start: int, end: int) -> bool:
        ctx = text[max(0, start - 10):min(len(text), end + 10)].lower()
        if "kwh" in ctx or "kw h" in ctx: return False
        bad = ["hz", "volt", " v", "v ", "amp", " a", "a ", "class", "ip", "rev", "rpm", "phase", "3x", "indoor"]
        return any(b in ctx for b in bad)

    common_noise = {10, 30, 50, 60, 100, 220, 230, 240, 380, 400, 415, 1000, 10000}
    candidates = []

    if keyword:
        kw = re.escape(keyword)
        patterns = [kw + r"[^\d]*((?:\d|O|o|l|I|\|)+[\.,]?\d*)", r"((?:\d|O|o|l|I|\|)+[\.,]?\d*)[^\d]*" + kw]
        for pat in patterns:
            match = re.search(pat, raw_full_text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("|", "1")
                val_str = normalize_number_str(val_str, decimal_places)
                try:
                    val = float(val_str)
                    if decimal_places > 0 and "." not in val_str: val = val / (10 ** decimal_places)
                    if check_digits(val): candidates.append({"val": float(val), "score": 600})
                except: pass

    clean_std = re.sub(r"\b202[0-9]\b|\b256[0-9]\b", "", full_text)
    clean_std = re.sub(r"\.{2,}", ".", clean_std)
    for m in re.finditer(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", clean_std):
        n_str = m.group(0)
        if looks_like_spec_context(raw_full_text, m.start(), m.end()): continue
        n_str2 = normalize_number_str(n_str, decimal_places)
        if not n_str2: continue
        try:
            val = float(n_str2) if "." in n_str2 else float(int(n_str2))
            if decimal_places > 0 and "." not in n_str2: val = val / (10 ** decimal_places)
            
            if int(abs(val)) in common_noise and not keyword: continue
            if not check_digits(val): continue

            score = 120
            int_part = str(int(abs(val)))
            score += min(len(int_part), 10) * 10
            if decimal_places > 0 and "." in n_str2: score += 25
            candidates.append({"val": float(val), "score": score})
        except: continue

    if candidates: return float(max(candidates, key=lambda x: x["score"])["val"])
    return 0.0

def calc_tolerance(decimals: int) -> float:
    if decimals <= 0: return 0.5
    return 0.5 * (10 ** (-decimals))
# =========================================================
# --- 🔳 QR + REF IMAGE HELPERS (Mobile) ---
# =========================================================
REF_IMAGE_FOLDER = "ref_images"  # โฟลเดอร์รูปตัวอย่างใน Bucket

def get_ref_image_url(point_id: str) -> str:
    pid = str(point_id).strip().upper()
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{REF_IMAGE_FOLDER}/{pid}.jpg"

def decode_qr(image_bytes: bytes):
    """คืนค่า point_id จาก QR (ถ้าอ่านไม่ได้จะคืน None)"""
    try:
        arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)
        data = (data or "").strip()
        return data.upper() if data else None
    except:
        return None

def infer_meter_type(config: dict) -> str:
    """เดา meter_type จาก config เพื่อกันกรอกผิด"""
    blob = f"{config.get('type','')} {config.get('name','')}".lower()
    if ("น้ำ" in blob) or ("water" in blob) or ("ประปา" in blob):
        return "Water"
    return "Electric"
# =========================================================
# --- UI LOGIC ---
# =========================================================
mode = st.sidebar.radio(
    "🔧 เลือกโหมดการทำงาน",
    ["📝 พนักงานจดมิเตอร์", "📥 อัปโหลด Excel (SCADA Export)", "👮‍♂️ Admin Approval"]
)


if mode == "📝 พนักงานจดมิเตอร์":
    st.title("Smart Meter System")
    st.markdown("### Water treatment Plant - Borthongindustrial")
    st.caption("Version 6.1 (QR-first for Mobile)")

    # --- session state ---
    if 'confirm_mode' not in st.session_state: st.session_state.confirm_mode = False
    if 'warning_msg' not in st.session_state: st.session_state.warning_msg = ""
    if 'last_manual_val' not in st.session_state: st.session_state.last_manual_val = 0.0

    if "emp_step" not in st.session_state: st.session_state.emp_step = "SCAN_QR"
    if "emp_point_id" not in st.session_state: st.session_state.emp_point_id = ""

    all_meters = load_points_master()
    if not all_meters:
        st.error("❌ โหลด PointsMaster ไม่ได้")
        st.stop()

    # --- ฟอร์มบนสุด (มือถือควรให้สั้น) ---
    c_insp, c_date = st.columns(2)
    with c_insp:
        inspector = st.text_input("ชื่อผู้ตรวจ", "Admin", key="emp_inspector")
    with c_date:
        selected_date = st.date_input(
            "📅 วันที่จดบันทึก (ลงย้อนหลังได้)",
            value=get_thai_time().date(),
            key="emp_date"
        )

    # ถ้าอยู่โหมด mismatch confirm ให้ล็อกอยู่จุดเดิม
    if st.session_state.get("confirm_mode", False):
        st.session_state.emp_point_id = st.session_state.get("last_point_id", st.session_state.emp_point_id)
        st.session_state.emp_step = "INPUT"

    # =========================================================
    # STEP 1: SCAN QR
    # =========================================================
    if st.session_state.emp_step == "SCAN_QR":
        st.subheader("ขั้นที่ 1: สแกน QR ที่มิเตอร์")
        st.write("📌 ถ่ายให้ใกล้ ๆ และชัด (ประมาณ 15–25 ซม.)")

        qr_pic = st.camera_input("ถ่าย QR ให้ชัด", key="emp_qr_cam")
        if qr_pic is not None:
            pid = decode_qr(qr_pic.getvalue())
            if pid:
                st.session_state.emp_point_id = pid
                st.session_state.emp_step = "CONFIRM_POINT"
                st.rerun()
            else:
                st.warning("ยังอ่าน QR ไม่ได้ ลองถ่ายใหม่ให้ชัดขึ้น/ใกล้ขึ้น")

        # --- ทางหนีฉุกเฉิน (ซ่อน) ---
        with st.expander("สแกนไม่ได้? พิมพ์รหัสเอง"):
            manual_pid = st.text_input("พิมพ์ point_id", key="emp_manual_pid")
            if st.button("ยืนยันรหัส", use_container_width=True, key="emp_manual_ok"):
                if manual_pid.strip():
                    st.session_state.emp_point_id = manual_pid.strip().upper()
                    st.session_state.emp_step = "CONFIRM_POINT"
                    st.rerun()
                else:
                    st.warning("กรุณาพิมพ์รหัสก่อน")

        st.stop()

    # =========================================================
    # STEP 2: CONFIRM POINT (show name + ref image)
    # =========================================================
    if st.session_state.emp_step == "CONFIRM_POINT":
        pid = st.session_state.emp_point_id
        config = get_meter_config(pid)
        if not config:
            st.error(f"❌ ไม่พบ point_id: {pid} ใน PointsMaster")
            if st.button("กลับไปสแกนใหม่", use_container_width=True):
                st.session_state.emp_step = "SCAN_QR"
                st.session_state.emp_point_id = ""
                st.rerun()
            st.stop()

        meter_type = infer_meter_type(config)

        st.subheader("ขั้นที่ 2: ยืนยันจุดตรวจ")
        st.write(f"**Point:** {pid}")
        if config.get("name"):
            st.write(f"**ชื่อจุด:** {config.get('name')}")
        st.write(f"**ประเภท:** {'💧 Water' if meter_type=='Water' else '⚡ Electric'}")
        # รูปตัวอย่าง (โหลดจาก GCS ด้วยสิทธิ์ service account ไม่ต้อง public)
        ref_bytes, ref_path = load_ref_image_bytes_any(pid)
        if ref_bytes:
            st.image(ref_bytes, caption=f"รูปตัวอย่าง (Reference): {ref_path}", use_container_width=True)
        else:
            st.warning("⚠️ ไม่พบรูปตัวอย่างใน bucket สำหรับจุดนี้")
            st.caption("แนะนำให้มีไฟล์ขึ้นต้นด้วย point_id เช่น CH_S11D_106_....jpg หรือทำไฟล์มาตรฐาน ref_images/CH_S11D_106.jpg")


        b1, b2 = st.columns(2)
        if b1.button("✅ ใช่จุดนี้", type="primary", use_container_width=True):
            st.session_state.emp_step = "INPUT"
            st.rerun()
        if b2.button("❌ ไม่ใช่ / สแกนใหม่", use_container_width=True):
            st.session_state.emp_step = "SCAN_QR"
            st.session_state.emp_point_id = ""
            st.rerun()

        st.stop()

    # =========================================================
    # STEP 3: INPUT + PHOTO + SAVE
    # =========================================================
    # มาถึงตรงนี้ = emp_step == "INPUT"
    point_id = st.session_state.emp_point_id
    config = get_meter_config(point_id)
    if not config:
        st.error("❌ ไม่พบ config ของจุดนี้")
        st.session_state.emp_step = "SCAN_QR"
        st.session_state.emp_point_id = ""
        st.stop()

    report_col = str(config.get('report_col', '-') or '-').strip()
    meter_type = infer_meter_type(config)

    st.write("---")
    c1, c2 = st.columns([2, 1])

    with c1:
        st.markdown(f"📍 จุดตรวจ: **{point_id}**")
        if config.get("name"):
            st.caption(config.get("name"))
        st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{report_col}</span>", unsafe_allow_html=True)
        if st.button("🔁 เปลี่ยนจุด (สแกนใหม่)", use_container_width=True, key="emp_change_point"):
            st.session_state.emp_step = "SCAN_QR"
            st.session_state.emp_point_id = ""
            st.session_state.confirm_mode = False
            st.rerun()

    with c2:
        decimals = int(config.get("decimals", 0) or 0)
        step = 1.0 if decimals == 0 else (0.1 if decimals == 1 else 0.01)
        fmt = "%.0f" if decimals == 0 else ("%.1f" if decimals == 1 else "%.2f")
        st.caption("ถ่ายรูปแล้ว AI จะเสนอค่าด้านล่าง")

    tab_cam, tab_up = st.tabs(["📷 ถ่ายรูป", "📂 อัปโหลด"])

    with tab_cam:
        img_cam = st.camera_input("ถ่ายภาพมิเตอร์", key="emp_meter_cam")

    with tab_up:
        img_up = st.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'], key="emp_meter_upload")
        if img_up is not None:
            st.image(img_up, caption=f"รูปที่เลือก: {getattr(img_up, 'name', 'upload')}", use_container_width=True)

    img_file = img_cam if img_cam is not None else img_up

    st.write("---")
    st.subheader("ขั้นที่ 3: AI เสนอค่า และบันทึก")

    # --- กัน OCR รันซ้ำเวลาหน้า rerun ---
    if "emp_ai_value" not in st.session_state:
        st.session_state.emp_ai_value = None
    if "emp_img_hash" not in st.session_state:
        st.session_state.emp_img_hash = ""

    if img_file is None:
        st.info("📷 ถ่ายรูป หรืออัปโหลดรูป แล้ว AI จะอ่านค่าให้เองอัตโนมัติ")
        st.stop()

    img_bytes = img_file.getvalue()
    img_hash = hashlib.md5(img_bytes).hexdigest()

    # ถ้ารูปเปลี่ยน → อ่านใหม่
    if img_hash != st.session_state.emp_img_hash:
        st.session_state.emp_img_hash = img_hash
        with st.spinner("🤖 AI กำลังอ่านค่า..."):
            st.session_state.emp_ai_value = float(ocr_process(img_bytes, config, debug=False))

    ai_val = float(st.session_state.emp_ai_value or 0.0)
    st.write(f"🤖 **AI เสนอค่า:** {fmt % ai_val}")

    choice = st.radio(
        "จะบันทึกค่าไหน?",
        ["✅ ใช้ค่า AI", "✍️ แก้เอง"],
        horizontal=True,
        key="emp_choice"
    )

    if choice == "✍️ แก้เอง":
        final_val = st.number_input(
            "พิมพ์ค่าที่ถูกต้อง",
            value=float(ai_val),
            min_value=0.0,
            step=step,
            format=fmt,
            key="emp_override_val"
        )
        status = "CONFIRMED_MANUAL"
    else:
        final_val = float(ai_val)
        status = "CONFIRMED_AI"

    st.info(f"ค่าที่จะบันทึก: {fmt % float(final_val)}")

    col_save, col_retry = st.columns(2)

    if col_save.button("💾 บันทึกค่า", type="primary", use_container_width=True):
        try:
            filename = f"{point_id}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
            image_url = upload_image_to_storage(img_bytes, filename)

            ok = save_to_db(point_id, inspector, meter_type, float(final_val), float(ai_val), status, selected_date, image_url)
            if ok:
                ok_r, msg_r = export_to_real_report(point_id, float(final_val), inspector, report_col, selected_date, debug=True)
                if not ok_r:
                    st.warning('⚠️ ส่งค่าไป TEST waterreport ไม่สำเร็จ: ' + msg_r)
                st.success("✅ บันทึกสำเร็จ")

                # ไปจุดถัดไป
                st.session_state.emp_ai_value = None
                st.session_state.emp_img_hash = ""
                st.session_state.emp_step = "SCAN_QR"
                st.session_state.emp_point_id = ""
                st.rerun()
            else:
                st.error("❌ Save Failed")
        except Exception as e:
            st.error(f"❌ บันทึกไม่สำเร็จ: {e}")

    if col_retry.button("🔁 ถ่าย/เลือกใหม่", use_container_width=True):
        st.session_state.emp_ai_value = None
        st.session_state.emp_img_hash = ""
        st.rerun()

elif mode == "👮‍♂️ Admin Approval":
    st.title("👮‍♂️ Admin Dashboard")
    st.caption("ระบบอนุมัติผลการอ่านค่ามิเตอร์น้ำ/ไฟ")
    if st.button("🔄 รีเฟรช"): st.rerun()

    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("DailyReadings")
    data = ws.get_all_records()
    pending = [d for d in data if str(d.get('Status', '')).strip().upper() == 'FLAGGED']

    if not pending: st.success("✅ All Clear")
    else:
        for i, item in enumerate(pending):
            with st.container():
                st.markdown("---")
                c_info, c_val, c_act = st.columns([1.5, 1.5, 1])
                with c_info:
                    st.subheader(f"🚩 {item.get('point_id')}")
                    st.caption(f"Inspector: {item.get('inspector')}")
                    img_url = item.get('image_url')
                    if img_url and img_url != '-' and str(img_url).startswith('http'):
                        st.image(img_url, width=220)
                    else:
                        st.warning("No Image")

                with c_val:
                    m_val = safe_float(item.get('Manual_Value'), 0.0)
                    a_val = safe_float(item.get('AI_Value'), 0.0)
                    options_map = {
                        f"👤 คนจด: {m_val}": m_val,
                        f"🤖 AI: {a_val}": a_val
                    }
                    selected_label = st.radio("เลือกค่าที่ถูกต้อง:", list(options_map.keys()), key=f"rad_{i}")
                    choice = options_map[selected_label]

                with c_act:
                    st.write("")
                    if st.button("✅ อนุมัติ", key=f"btn_{i}", type="primary"):
                        try:
                            timestamp = str(item.get('timestamp', '')).strip()
                            point_id = str(item.get('point_id', '')).strip()
                            cells = ws.findall(timestamp)
                            updated = False
                            for cell in cells:
                                if str(ws.cell(cell.row, 3).value).strip() == point_id:
                                    ws.update_cell(cell.row, 7, "APPROVED")
                                    ws.update_cell(cell.row, 5, choice)
                                    config = get_meter_config(point_id)
                                    report_col = (config.get('report_col', '') if config else '')
                                    
                                    # ✅ Parse timestamp กลับเป็นวันที่ เพื่อหา Sheet ให้เจอตอน Approve
                                    try:
                                        dt_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                        approve_date = dt_obj.date()
                                    except:
                                        approve_date = get_thai_time().date() # fallback
                                        
                                    ok_r, msg_r = export_to_real_report(point_id, choice, str(item.get('inspector', '')), report_col, approve_date, debug=True)
                                    if not ok_r:
                                        st.warning('⚠️ ส่งค่าไป TEST waterreport ไม่สำเร็จ: ' + msg_r)
                                    updated = True; break
                            if updated: st.success("Approved!"); st.rerun()
                            else: st.warning("หา row ไม่เจอ")
                        except Exception as e: st.error(f"Error approve: {e}")

elif mode == "📥 อัปโหลด Excel (SCADA Export)":
    st.title("📥 อัปโหลด Excel (SCADA Export)")
    st.caption("โหมดนี้ใช้แทนการถ่ายรูป SCADA: เอาไฟล์ Excel ที่ SCADA export มาอัปโหลด แล้วระบบจะดึงค่า + บันทึกลง WaterReport ให้อัตโนมัติ")

    st.info(
        "วิธีใช้ (แบบง่าย ป.6)\n"
        "1) กด 'Browse files' แล้วเลือกไฟล์ Excel ที่ลูกค้าส่งมา (เลือกได้หลายไฟล์)\n"
        "2) เลือก 'วันที่ของรายงาน' ให้ตรงกับวันที่ใน WaterReport\n"
        "3) กดปุ่ม 'ดึงค่าจาก Excel' เพื่อให้ระบบอ่านค่า\n"
        "4) ถ้ามีจุดที่ไม่มีใน Excel -> กรอกเองเฉพาะจุดนั้น\n"
        "5) กด 'บันทึกลง WaterReport' จบ ✅"
    )

    # เลือกวันที่รายงาน
    report_date = st.date_input("📅 วันที่ของรายงาน (ที่จะไปกรอกใน WaterReport)", value=get_thai_time().date())
    report_date_str = report_date.strftime("%Y/%m/%d")

    # โหลด mapping
    st.subheader("1) ไฟล์ Mapping (DB_Water_Scada.xlsx)")
    mapping_rows = []
    if os.path.exists("DB_Water_Scada.xlsx"):
        st.success("พบไฟล์ DB_Water_Scada.xlsx ในโปรเจกต์ ✅ (จะใช้ไฟล์นี้อัตโนมัติ)")
        mapping_rows = load_scada_excel_mapping(local_path="DB_Water_Scada.xlsx")
    else:
        st.warning("ไม่พบไฟล์ DB_Water_Scada.xlsx ในโปรเจกต์ — กรุณาอัปโหลดไฟล์นี้ก่อน (ไฟล์เล็ก ๆ)")
        uploaded_map = st.file_uploader("อัปโหลด DB_Water_Scada.xlsx", type=["xlsx"])
        if uploaded_map is not None:
            mapping_rows = load_scada_excel_mapping(uploaded_bytes=uploaded_map.getvalue())

    if not mapping_rows:
        st.stop()

    # อัปโหลด Excel export
    st.subheader("2) อัปโหลดไฟล์ Excel ที่ SCADA export")
    exports = st.file_uploader(
        "เลือกไฟล์ Excel (เลือกได้หลายไฟล์) เช่น ...Daily_Report.xlsx, ...UF_System.xlsx, ...SMMT_Daily_Report.xlsx",
        type=["xlsx"],
        accept_multiple_files=True,
    )

    if not exports:
        st.stop()

    uploaded_exports = {f.name: f.getvalue() for f in exports}

    # ปุ่มดึงค่า
    if st.button("🔎 ดึงค่าจาก Excel"):
        with st.spinner("กำลังอ่านค่าใน Excel..."):
            results, missing = extract_scada_values_from_exports(mapping_rows, uploaded_exports)

        # แสดงผล
        ok_count = sum(1 for r in results if r["status"] == "OK" and r["value"] is not None)
        st.success(f"อ่านได้แล้ว {ok_count}/{len(results)} จุด")

        df_show = pd.DataFrame(results)
        st.dataframe(df_show, use_container_width=True)

        # เก็บไว้ใน session
        st.session_state["excel_results"] = results
        st.session_state["excel_missing"] = missing

    # ถ้ามีผลแล้ว แสดงส่วนแก้/บันทึก
    if "excel_results" in st.session_state:
        results = st.session_state["excel_results"]
        missing = st.session_state.get("excel_missing", [])

        # เตือนจุดที่หาย
        missing_point_ids = [m["point_id"] for m in missing]
        if missing_point_ids:
            st.warning("มีจุดที่ดึงค่าไม่สำเร็จ/ไม่มีใน Excel: " + ", ".join(missing_point_ids))

        # ให้กรอกเองเฉพาะจุดที่หาย
        manual_inputs = {}
        with st.expander("✍️ กรอกเองเฉพาะจุดที่ไม่มีใน Excel (ถ้ามี)"):
            for pid in missing_point_ids:
                manual_inputs[pid] = st.text_input(f"{pid} (กรอกตัวเลข)", value="")

        # รวมค่า final
        final_values = {}
        for r in results:
            pid = r["point_id"]
            val = r["value"]
            if pid in manual_inputs and manual_inputs[pid].strip() != "":
                val = manual_inputs[pid].strip()
            final_values[pid] = val

        # ปุ่มบันทึกลง WaterReport
        st.subheader("3) บันทึกลง WaterReport")
        st.caption("จะบันทึกเฉพาะจุดที่มีค่า (ไม่ว่าง) ลง WaterReport ตาม report_col ใน PointsMaster")

        if st.button("✅ บันทึกลง WaterReport (อัตโนมัติ)"):
            saved_ok = 0
            saved_fail = 0
            fail_list = []

            with st.spinner("กำลังบันทึกลง WaterReport..."):
                for pid, val in final_values.items():
                    if val is None or str(val).strip() == "":
                        continue

                    cfg = get_meter_config(pid)
                    if not cfg:
                        saved_fail += 1
                        fail_list.append((pid, "NO_CONFIG"))
                        continue

                    # ส่งเข้ารายงาน
                    ok, msg = export_to_real_report(pid, val, report_date_str)
                    if ok:
                        saved_ok += 1
                        try:
                            # บันทึก log ลง DB
                            save_to_db(pid, cfg.get("name",""), cfg.get("group",""), report_date_str, "", str(val), "AUTO_EXCEL_SCADA", "Admin")
                        except Exception:
                            pass
                    else:
                        saved_fail += 1
                        fail_list.append((pid, msg))

            st.success(f"บันทึกสำเร็จ: {saved_ok} จุด")
            if saved_fail:
                st.error(f"บันทึกไม่สำเร็จ: {saved_fail} จุด")
                st.write(fail_list)

        st.divider()
        st.info("หมายเหตุ: ถ้าลูกค้าบอกว่า 'มีมิเตอร์ไฟ 1 จุดที่ไม่มี export มาใน Excel' -> ใช้ช่องกรอกเองด้านบนได้เลย (เหมือนมิเตอร์น้ำ)")
