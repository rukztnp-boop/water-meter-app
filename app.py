import streamlit as st
import io
import re
import gspread
import json
import cv2
import numpy as np
from google.oauth2 import service_account
from google.cloud import vision
from google.cloud import storage
from datetime import datetime, timedelta, timezone
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
        if c in string.ascii_letters: num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num

def get_thai_sheet_name(sh):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    now = get_thai_time()
    m_idx = now.month - 1
    yy = str(now.year + 543)[-2:] 
    patterns = [f"{thai_months[m_idx]}{yy}", f"{thai_months[m_idx][:-1]}{yy}", f"{thai_months[m_idx]} {yy}", f"{thai_months[m_idx][:-1]} {yy}"]
    all_sheets = [s.title for s in sh.worksheets()]
    for p in patterns:
        if p in all_sheets: return p
    return None 

def find_day_row_exact(ws, day: int):
    col = ws.col_values(1)
    for i, v in enumerate(col, start=1):
        try:
            if int(str(v).strip()) == int(day): return i
        except: pass
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
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t")

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
                # Ensure type/name exist for digital detection
                item['type'] = str(item.get('type', '')).strip()
                item['name'] = str(item.get('name', '')).strip()
                return item
        return None
    except: return None

def export_to_real_report(point_id, read_value, inspector, report_col):
    if not report_col: return False
    try:
        sh = gc.open(REAL_REPORT_SHEET)
        sheet_name = get_thai_sheet_name(sh)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
        today_day = get_thai_time().day
        target_row = find_day_row_exact(ws, today_day) or (6 + today_day) 
        target_col = col_to_index(report_col)
        if target_col == 0: return False
        ws.update_cell(target_row, target_col, read_value)
        return True
    except: return False

def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, image_url="-"):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        row = [get_thai_time().strftime("%Y-%m-%d %H:%M:%S"), meter_type, point_id, inspector, manual_val, ai_val, status, image_url]
        ws.append_row(row)
        return True
    except: return False

# =========================================================
# --- 🧠 OCR ENGINE (Smart 3-Pass Strategy + Unsharp Mask) ---
# =========================================================
def normalize_number_str(s: str, decimals: int = 0) -> str:
    if not s: return ""
    s = s.strip().replace(",", "").replace(" ", "")
    s = re.sub(r"\s+", "", s)
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
    blob = f"{config.get('type','')} {config.get('name','')}".lower()
    return ("digital" in blob) or ("scada" in blob) or ("electric" in blob)

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
                x1, y1, x2, y2 = int(x1 * W), int(y1 * H), int(x2 * W), int(y2 * H)
            else:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            pad_x, pad_y = int(0.03 * W), int(0.03 * H)
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
            if x2 > x1 and y2 > y1:
                img = img[y1:y2, x1:x2]

    if config.get('ignore_red', False):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower_red1 = np.array([0, 70, 50]); upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 70, 50]); upper_red2 = np.array([180, 255, 255])
        mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
        img[mask > 0] = [255, 255, 255]

    # Mode: Raw (for debugging or special cases)
    if variant == "raw":
        ok, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes() if ok else image_bytes

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Logic: Auto or Soft (for Digital/Difficult images)
    # ✅ ปรับปรุง: ใช้ Unsharp Mask เพื่อให้อ่านจอ LCD ได้ดีขึ้น
    if variant == "soft" or (variant == "auto" and is_digital_meter(config)):
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        g = clahe.apply(gray)
        blur = cv2.GaussianBlur(g, (0, 0), 1.0)
        # Unsharp Masking: เพิ่มความคมชัดขอบตัวเลข
        sharp = cv2.addWeighted(g, 1.7, blur, -0.7, 0)
        ok, encoded = cv2.imencode(".png", sharp)
    else:
        # Analog: Thresholding (ดีกับมิเตอร์หมุน)
        gray = cv2.bilateralFilter(gray, 7, 50, 50)
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7)
        ok, encoded = cv2.imencode(".png", th)
    
    return encoded.tobytes() if ok else image_bytes

def _vision_read_text(processed_bytes):
    try:
        image = vision.Image(content=processed_bytes)
        response = VISION_CLIENT.text_detection(image=image)
        if not response.text_annotations: return ""
        return response.text_annotations[0].description or ""
    except: return ""

def ocr_process(image_bytes, config):
    decimal_places = int(config.get('decimals', 0) or 0)
    keyword = str(config.get('keyword', '') or '').strip()
    expected_digits = int(config.get('expected_digits', 0) or 0)

    # ✅ Pass 1: Standard (ROI + Auto)
    processed_bytes = preprocess_image_cv(image_bytes, config, use_roi=True, variant="auto")
    raw_full_text = _vision_read_text(processed_bytes)

    # ✅ Pass 2: Soft Mode (ROI + Sharpness) - ไม้ตายสำหรับจอ LCD จางๆ
    if not raw_full_text:
        processed_bytes = preprocess_image_cv(image_bytes, config, use_roi=True, variant="soft")
        raw_full_text = _vision_read_text(processed_bytes)

    # ✅ Pass 3: Full Image (No ROI + Soft) - กันเหนียวถ้า ROI ผิด
    has_roi = bool(config.get('roi_x2', 0)) and bool(config.get('roi_y2', 0))
    if not raw_full_text and has_roi:
        processed_bytes = preprocess_image_cv(image_bytes, config, use_roi=False, variant="soft")
        raw_full_text = _vision_read_text(processed_bytes)

    if not raw_full_text: return 0.0

    raw_full_text = raw_full_text.replace("\n", " ")
    full_text = preprocess_text(raw_full_text)

    # Keyword Hunter
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
                    return float(val)
                except: pass

    # Blacklist
    blacklisted = set()
    id_matches = re.finditer(r"(?i)(?:id|code|no\.?|serial|s\/n)[\D]{0,15}?(\d+(?:[\s-]+\d+)*)", full_text)
    for m in id_matches:
        for p in re.split(r"[\s-]+", m.group(1)):
            try: blacklisted.add(float(p))
            except: pass

    def check_digits(val):
        if expected_digits == 0: return True
        try: return len(str(int(float(val)))) in (expected_digits, expected_digits - 1)
        except: return False

    candidates = []
    # Stitcher
    analog_labels = [r"10\D?000", r"1\D?000", r"100", r"10", r"1"]
    stitched_digits = {}
    for idx, label in enumerate(analog_labels):
        m = re.search(label + r"[^\d]{0,30}\s+(\d)\b", raw_full_text)
        if m: stitched_digits[idx] = m.group(1)
    if len(stitched_digits) >= 2:
        sorted_keys = sorted(stitched_digits.keys())
        final_str = "".join([stitched_digits[k] for k in sorted_keys])
        try:
            val = float(final_str)
            if val not in blacklisted and check_digits(val):
                candidates.append({"val": float(val), "score": 300 + len(final_str) * 10})
        except: pass

    # Standard
    clean_std = re.sub(r"\b202[0-9]\b|\b256[0-9]\b", "", full_text)
    nums = re.findall(r"-?\d+\.\d+|\d+", clean_std)
    for n_str in nums:
        n_str2 = normalize_number_str(n_str, decimal_places)
        if not n_str2: continue
        try:
            val = float(n_str2) if "." in n_str2 else float(int(n_str2))
            if decimal_places > 0 and "." not in n_str2: val = val / (10 ** decimal_places)
            if val in blacklisted: continue
            if not check_digits(val): continue
            score = 100
            if decimal_places > 0 and "." in n_str2: score += 30
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

    if 'confirm_mode' not in st.session_state: st.session_state.confirm_mode = False
    if 'warning_msg' not in st.session_state: st.session_state.warning_msg = ""
    if 'last_manual_val' not in st.session_state: st.session_state.last_manual_val = 0.0

    all_meters = load_points_master()
    if not all_meters: st.stop()

    col_type, col_insp = st.columns(2)
    with col_type: cat_select = st.radio("ประเภทมิเตอร์", ["💧 ประปา (Water)", "⚡️ ไฟฟ้า (Electric)"], horizontal=True)
    with col_insp: inspector = st.text_input("ชื่อผู้ตรวจ", "Admin")

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
    img_file = tab_cam.camera_input("ถ่ายภาพมิเตอร์")
    if not img_file: img_file = tab_up.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'])

    st.write("---")

    if not st.session_state.confirm_mode:
        if st.button("🚀 ตรวจสอบและบันทึก", type="primary"):
            if img_file and point_id:
                with st.spinner("🤖 AI กำลังประมวลผล (3-Pass Strategy)..."):
                    try:
                        img_bytes = img_file.getvalue()
                        config = get_meter_config(point_id)
                        if not config: st.error("❌ ไม่พบ config"); st.stop()

                        # อ่านค่า (3 รอบ)
                        ai_val = ocr_process(img_bytes, config)
                        
                        # อัปโหลดรูปขึ้น Cloud Storage
                        filename = f"{point_id}_{get_thai_time().strftime('%Y%m%d_%H%M%S')}.jpg"
                        image_url = upload_image_to_storage(img_bytes, filename)

                        tol = calc_tolerance(config.get('decimals', 0))
                        if abs(manual_val - ai_val) <= tol:
                            meter_type = "Water" if "ประปา" in cat_select else "Electric"
                            if save_to_db(point_id, inspector, meter_type, manual_val, ai_val, "VERIFIED", image_url):
                                export_to_real_report(point_id, manual_val, inspector, report_col)
                                st.balloons()
                                st.success("✅ บันทึกสำเร็จ!")
                                st.info(f"AI: {ai_val} | Manual: {manual_val}")
                            else: st.error("Save Failed")
                        else:
                            st.session_state.confirm_mode = True
                            st.session_state.warning_msg = f"ไม่ตรงกัน! กรอก {manual_val} / AI {ai_val} (tol {tol})"
                            st.session_state.last_manual_val = manual_val
                            st.session_state.last_ai_val = ai_val
                            st.session_state.last_img_url = image_url
                            st.rerun()
                    except Exception as e: st.error(f"Error: {e}")
            else: st.warning("⚠️ กรุณาถ่ายรูปและเลือกจุดตรวจ")
    else:
        st.markdown(f"""<div class="status-box status-warning"><h4>⚠️ {st.session_state.warning_msg}</h4></div>""", unsafe_allow_html=True)
        col_conf1, col_conf2 = st.columns(2)
        if col_conf1.button("✅ ยืนยัน (ส่งให้ Admin)"):
            save_to_db(point_id, inspector, "Water", st.session_state.last_manual_val, st.session_state.last_ai_val, "FLAGGED", st.session_state.last_img_url)
            st.success("✅ ส่งเรื่องแล้ว"); st.session_state.confirm_mode = False; st.rerun()
        if col_conf2.button("❌ แก้ไข"):
            st.session_state.confirm_mode = False; st.rerun()

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
                    if img_url and img_url != '-' and img_url.startswith('http'):
                        st.image(img_url, width=220)
                    else:
                        st.warning("No Image")

                with c_val:
                    m_val = safe_float(item.get('Manual_Value'), 0.0)
                    a_val = safe_float(item.get('AI_Value'), 0.0)
                    
                    # ✅ ส่วนที่ผมแก้ไขให้: ใส่ Mapping ให้ Admin ดูง่าย
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
                                    export_to_real_report(point_id, choice, str(item.get('inspector', '')), report_col)
                                    updated = True; break
                            if updated: st.success("Approved!"); st.rerun()
                            else: st.warning("หา row ไม่เจอ")
                        except Exception as e: st.error(f"Error approve: {e}")