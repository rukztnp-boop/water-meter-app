import streamlit as st
import io
import re
import gspread
import json
import cv2
import numpy as np
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
        blob.upload_from_string(image_bytes, content_type='image/jpeg')
        return blob.public_url
    except Exception as e:
        return f"Error: {e}"

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
def export_to_real_report(point_id, read_value, inspector, report_col, target_date):
    if not report_col: return False
    try:
        sh = gc.open(REAL_REPORT_SHEET)
        # หา Sheet ตามเดือนของวันที่เลือก
        sheet_name = get_thai_sheet_name(sh, target_date)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
        
        # ใช้วันที่ที่เลือก (day) หาแถว
        target_day = target_date.day
        target_row = find_day_row_exact(ws, target_day) or (6 + target_day)
        
        target_col = col_to_index(report_col)
        if target_col == 0: return False
        
        ws.update_cell(target_row, target_col, read_value)
        return True
    except: return False

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
# --- UI LOGIC ---
# =========================================================
mode = st.sidebar.radio("🔧 เลือกโหมดการทำงาน", ["📝 พนักงานจดมิเตอร์", "👮‍♂️ Admin Approval"])

if mode == "📝 พนักงานจดมิเตอร์":
    st.title("Smart Meter System")
    st.markdown("### Water treatment Plant - Borthongindustrial")
    st.caption("Version 6.0 (Date Selection Supported)")

    if 'confirm_mode' not in st.session_state: st.session_state.confirm_mode = False
    if 'warning_msg' not in st.session_state: st.session_state.warning_msg = ""
    if 'last_manual_val' not in st.session_state: st.session_state.last_manual_val = 0.0

    all_meters = load_points_master()
    if not all_meters: st.stop()

    col_type, col_insp = st.columns(2)
    with col_type: cat_select = st.radio("ประเภทมิเตอร์", ["💧 ประปา (Water)", "⚡️ ไฟฟ้า (Electric)"], horizontal=True)
    with col_insp: inspector = st.text_input("ชื่อผู้ตรวจ", "Admin")

    # ✅ เพิ่ม Date Picker (ใช้ get_thai_time() เป็นค่า default)
    selected_date = st.date_input("📅 วันที่จดบันทึก (สำหรับลงย้อนหลัง)", value=get_thai_time())

    filtered_meters = []
    for m in all_meters:
        m_type = (str(m.get('type', '')).lower() + " " + str(m.get('name', '')).lower())
        if "ประปา" in cat_select:
            if any(x in m_type for x in ['น้ำ', 'water', 'ประปา']): filtered_meters.append(m)
        else:
            if any(x in m_type for x in ['ไฟ', 'electric', 'scada']): filtered_meters.append(m)

    option_map = {f"{m.get('point_id')} : {m.get('name')}": m for m in filtered_meters}
    
    st.write("---")
    c1, c2 = st.columns([2, 1])
    with c1:
        selected_label = st.selectbox("📍 เลือกจุดตรวจ", list(option_map.keys()))
        meter_data = option_map[selected_label]
        point_id = meter_data.get('point_id')
        report_col = str(meter_data.get('report_col', '-') or '-').strip()
        st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{report_col}</span>", unsafe_allow_html=True)
    with c2:
        manual_val = st.number_input("👁️ ค่าจริง", min_value=0.0, step=0.1, format="%.2f")

    tab_cam, tab_up = st.tabs(["📷 ถ่ายรูป", "📂 อัปโหลด"])

    # 📷 ถ่ายรูป (Streamlit มักมี preview ใน widget อยู่แล้วบนมือถือ)
    with tab_cam:
        img_cam = st.camera_input("ถ่ายภาพมิเตอร์")

    # 📂 อัปโหลด (แสดง preview ใต้ uploader ทันที)
    with tab_up:
        img_up = st.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'])
        if img_up is not None:
            st.image(img_up, caption=f"รูปที่เลือก: {getattr(img_up, 'name', 'upload')}", use_container_width=True)

    # เลือกใช้รูปจากกล้องก่อน ถ้าไม่มีค่อยใช้จากอัปโหลด
    img_file = img_cam if img_cam is not None else img_up

    st.write("---")

# ✅ เก็บค่า AI ใน session
if "ai_suggest" not in st.session_state:
    st.session_state.ai_suggest = None

# 1) ปุ่มให้ AI อ่านค่า
if st.button("🤖 ให้ AI อ่านค่า", type="primary", disabled=(img_file is None or not point_id)):
    try:
        img_bytes = img_file.getvalue()
        config = get_meter_config(point_id)
        if not config:
            st.error("❌ ไม่พบ config ของจุดนี้")
        else:
            ai_val = ocr_process(img_bytes, config, debug=False)
            st.session_state.ai_suggest = float(ai_val)
    except Exception as e:
        st.error(f"❌ อ่านค่าไม่สำเร็จ: {e}")

# 2) ถ้า AI อ่านค่าแล้ว → ให้ติ๊ก/แก้เอง
if st.session_state.ai_suggest is not None:
    config = get_meter_config(point_id)
    if not config:
        st.error("❌ ไม่พบ config ของจุดนี้")
        st.stop()

    decimals = int(config.get("decimals", 0) or 0)
    step = 1.0 if decimals == 0 else (0.1 if decimals == 1 else 0.01)
    fmt  = "%.0f" if decimals == 0 else ("%.1f" if decimals == 1 else "%.2f")

    ai_val = float(st.session_state.ai_suggest)

    st.subheader("ผลที่ AI อ่านได้")
    default_correct = False if ai_val == 0.0 else True
    is_correct = st.checkbox(f"✅ AI อ่านถูกต้อง ({ai_val:{fmt}})", value=default_correct)

    if is_correct:
        final_val = ai_val
        status = "CONFIRMED_AI"
    else:
        manual_val = st.number_input("✍️ กรอกค่าที่ถูกต้อง", min_value=0.0, step=step, format=fmt)
        final_val = float(manual_val)
        status = "CONFIRMED_MANUAL"

    st.info(f"ค่าที่จะบันทึก: {final_val:{fmt}}")

    c1, c2 = st.columns(2)

    # 3) ปุ่มบันทึกค่าเลย
    if c1.button("💾 บันทึกค่าเลย", type="primary"):
        try:
            img_bytes = img_file.getvalue()
            filename = f"{point_id}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
            image_url = upload_image_to_storage(img_bytes, filename)

            meter_type = "Water" if "ประปา" in cat_select else "Electric"

            ok = save_to_db(point_id, inspector, meter_type, final_val, ai_val, status, selected_date, image_url)
            if ok:
                export_to_real_report(point_id, final_val, inspector, report_col, selected_date)
                st.success("✅ บันทึกสำเร็จ!")
                st.session_state.ai_suggest = None
                st.rerun()
            else:
                st.error("❌ Save Failed")
        except Exception as e:
            st.error(f"❌ บันทึกไม่สำเร็จ: {e}")

    # 4) ปุ่มอ่านใหม่
    if c2.button("🔁 อ่านใหม่ / เปลี่ยนรูป"):
        st.session_state.ai_suggest = None
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
                                        
                                    export_to_real_report(point_id, choice, str(item.get('inspector', '')), report_col, approve_date)
                                    updated = True; break
                            if updated: st.success("Approved!"); st.rerun()
                            else: st.warning("หา row ไม่เจอ")
                        except Exception as e: st.error(f"Error approve: {e}")