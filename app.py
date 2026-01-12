import hashlib
import streamlit as st
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
DB_SHEET_NAME = 'WaterMeter_System_DB'
REAL_REPORT_SHEET = 'TEST waterreport'

# โฟลเดอร์รูปตัวอย่าง (Reference) ใน Bucket
REF_IMAGE_FOLDER = "ref_images"

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
    .stButton>button { width: 100%; border-radius: 10px; font-weight: 700; }
    .status-box { padding: 14px; border-radius: 10px; margin: 10px 0; border: 1px solid #ddd; }
    .status-warning { background-color: #fff3cd; color: #856404; }
    .status-good { background-color: #e8f5e9; color: #1b5e20; }
    .report-badge {
        background-color: #e3f2fd; color: #0d47a1;
        padding: 4px 8px; border-radius: 6px; font-size: 0.85em; font-weight: 700;
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
VISION_CLIENT = vision.ImageAnnotatorClient(credentials=creds)
STORAGE_CLIENT = storage.Client(credentials=creds)

# =========================================================
# --- CLOUD STORAGE HELPERS ---
# =========================================================
def upload_image_to_storage(image_bytes: bytes, file_name: str) -> str:
    """อัปโหลดรูปไป GCS แล้วคืน URL (แบบ public_url)"""
    try:
        bucket = STORAGE_CLIENT.bucket(BUCKET_NAME)
        blob = bucket.blob(file_name)

        ext = str(file_name).lower().split(".")[-1] if "." in str(file_name) else "jpg"
        content_type = "image/png" if ext == "png" else "image/jpeg"

        blob.upload_from_string(image_bytes, content_type=content_type)
        return blob.public_url
    except Exception as e:
        return f"Error: {e}"

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

    # 1) ลองชื่อมาตรฐาน
    candidates = []
    for ext in ["jpg", "jpeg", "png", "JPG", "JPEG", "PNG"]:
        candidates += [
            f"{REF_IMAGE_FOLDER}/{pid}.{ext}",
            f"{pid}.{ext}",
        ]

    for path in candidates:
        try:
            blob = bucket.blob(path)
            data = blob.download_as_bytes()
            if data:
                return data, path
        except Exception:
            pass

    # 2) หาไฟล์ล่าสุดแบบ prefix: POINT_*.jpg
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
def col_to_index(col_str: str) -> int:
    col_str = str(col_str).upper().strip()
    num = 0
    for c in col_str:
        if c in string.ascii_letters:
            num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num

def get_thai_sheet_name(sh, target_date):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    m_idx = target_date.month - 1
    yy = str(target_date.year + 543)[-2:]
    patterns = [
        f"{thai_months[m_idx]}{yy}",
        f"{thai_months[m_idx][:-1]}{yy}",
        f"{thai_months[m_idx]} {yy}",
        f"{thai_months[m_idx][:-1]} {yy}",
    ]
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
        except Exception:
            pass
    return None

@st.cache_data(ttl=300)
def load_points_master():
    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("PointsMaster")
    return ws.get_all_records()

def safe_int(x, default=0):
    try:
        return int(float(x)) if x and str(x).strip() else default
    except Exception:
        return default

def safe_float(x, default=0.0):
    try:
        return float(x) if x and str(x).strip() else default
    except Exception:
        return default

def parse_bool(v):
    if v is None:
        return False
    return str(v).strip().lower() in ("true", "1", "yes", "y", "t", "on")

def get_meter_config(point_id: str):
    try:
        records = load_points_master()
        pid = str(point_id).strip().upper()
        for item in records:
            if str(item.get('point_id', '')).strip().upper() == pid:
                item = dict(item)
                item['decimals'] = safe_int(item.get('decimals'), 0)
                item['keyword'] = str(item.get('keyword', '')).strip()
                exp = safe_int(item.get('expected_digits'), 0)
                if exp == 0:
                    exp = safe_int(item.get('int_digits'), 0)
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
    except Exception:
        return None

def export_to_real_report(point_id, read_value, inspector, report_col, target_date, return_info=False):
    """
    ส่งค่าไปลงชีท TEST waterreport
    - return_info=False : คืน True/False
    - return_info=True  : คืน (ok, msg, info_dict)
    """
    if not report_col or str(report_col).strip() in ("-", ""):
        if return_info:
            return False, "report_col ว่างหรือเป็น '-'", {}
        return False

    try:
        sh = gc.open(REAL_REPORT_SHEET)
        sheet_name = get_thai_sheet_name(sh, target_date)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)

        target_day = target_date.day
        target_row = find_day_row_exact(ws, target_day) or (6 + target_day)

        target_col = col_to_index(report_col)
        if target_col == 0:
            if return_info:
                return False, "แปลงคอลัมน์ไม่สำเร็จ", {}
            return False

        ws.update_cell(target_row, target_col, read_value)

        info = {
            "sheet": ws.title,
            "row": target_row,
            "col_letter": report_col,
            "col_index": target_col,
            "day": target_day
        }
        if return_info:
            return True, "OK", info
        return True

    except Exception as e:
        if return_info:
            return False, str(e), {}
        return False

def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, target_date, image_url="-"):
    """
    บันทึกลงชีท DB_SHEET_NAME -> DailyReadings
    """
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")

        current_time = get_thai_time().time()
        record_timestamp = datetime.combine(target_date, current_time)

        row = [
            record_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            meter_type,
            point_id,
            inspector,
            manual_val,
            ai_val,
            status,
            image_url
        ]
        ws.append_row(row)
        return True
    except Exception:
        return False

# =========================================================
# --- 🧠 OCR ENGINE ---
# =========================================================
def normalize_number_str(s: str, decimals: int = 0) -> str:
    if not s:
        return ""
    s = str(s).strip().replace(",", "").replace(" ", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"\.{2,}", ".", s)
    if s.count(".") > 1:
        parts = [p for p in s.split(".") if p != ""]
        if len(parts) >= 2:
            s = parts[0] + "." + "".join(parts[1:])
        else:
            s = s.replace(".", "")
    if decimals == 0:
        s = s.replace(".", "")
    return s

def preprocess_text(text: str) -> str:
    patterns = [
        r'IP\s*51', r'50\s*Hz', r'Class\s*2', r'3x220/380\s*V', r'Type',
        r'Mitsubishi', r'Electric', r'Wire', r'kWh', r'MH\s*[-]?\s*96',
        r'30\s*\(100\)\s*A', r'\d+\s*rev/kWh', r'WATT-HOUR\s*METER',
        r'Indoor\s*Use', r'Made\s*in\s*Thailand'
    ]
    for p in patterns:
        text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b10,000\b', '', text)
    text = re.sub(r'\b1,000\b', '', text)
    text = re.sub(r'(?<=[\d\s])[\|Il!](?=[\d\s])', '1', text)
    text = re.sub(r'(?<=[\d\s])[Oo](?=[\d\s])', '0', text)
    return text

def is_digital_meter(config: dict) -> bool:
    blob = f"{config.get('type','')} {config.get('name','')} {config.get('keyword','')}".lower()
    return ("digital" in blob) or ("scada" in blob) or (int(config.get('decimals', 0) or 0) > 0)

def preprocess_image_cv(image_bytes: bytes, config: dict, use_roi=True, variant="auto") -> bytes:
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

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
    if variant == "invert":
        gray = 255 - gray

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

def _vision_read_text(processed_bytes: bytes):
    try:
        image = vision.Image(content=processed_bytes)
        ctx = vision.ImageContext(language_hints=["en"])
        resp = VISION_CLIENT.text_detection(image=image, image_context=ctx)
        if getattr(resp, "error", None) and resp.error.message:
            return "", resp.error.message
        if resp.text_annotations:
            return (resp.text_annotations[0].description or ""), ""

        resp2 = VISION_CLIENT.document_text_detection(image=image, image_context=ctx)
        txt = ""
        if resp2.full_text_annotation and resp2.full_text_annotation.text:
            txt = resp2.full_text_annotation.text
        return (txt or ""), ""
    except Exception as e:
        return "", str(e)

def ocr_process(image_bytes: bytes, config: dict, debug=False) -> float:
    decimal_places = int(config.get('decimals', 0) or 0)
    keyword = str(config.get('keyword', '') or '').strip()
    # กัน keyword สั้นเกินไป (เช่น 'A', 'AL') ที่มักจับผิดง่าย
    if keyword and len(re.sub(r"[^A-Za-z0-9]+", "", keyword)) < 3:
        keyword = ""
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
    for _, use_roi, variant in attempts:
        processed = preprocess_image_cv(image_bytes, config, use_roi=use_roi, variant=variant)
        txt, _ = _vision_read_text(processed)
        if txt and txt.strip() and any(c.isdigit() for c in txt):
            raw_full_text = (txt or "").replace("\n", " ")
            raw_full_text = re.sub(r"\.{2,}", ".", raw_full_text)
            break

    if not raw_full_text:
        return 0.0

    full_text = preprocess_text(raw_full_text)
    full_text = re.sub(r"\.{2,}", ".", full_text)

    def check_digits(val: float) -> bool:
        if expected_digits <= 0:
            return True
        try:
            ln = len(str(int(abs(float(val)))))
            return 1 <= ln <= expected_digits + 1
        except Exception:
            return False

    def looks_like_spec_context(text: str, start: int, end: int) -> bool:
        ctx = text[max(0, start - 10):min(len(text), end + 10)].lower()
        if "kwh" in ctx or "kw h" in ctx:
            return False
        bad = ["hz", "volt", " v", "v ", "amp", " a", "a ", "class", "ip", "rev", "rpm", "phase", "3x", "indoor"]
        return any(b in ctx for b in bad)

    common_noise = {10, 30, 50, 60, 100, 220, 230, 240, 380, 400, 415, 1000, 10000}
    candidates = []

    # 1) มี keyword → ให้คะแนนสูง
    if keyword:
        kw = re.escape(keyword)
        patterns = [
            kw + r"[^\d]*((?:\d|O|o|l|I|\|)+[\.,]?\d*)",
            r"((?:\d|O|o|l|I|\|)+[\.,]?\d*)[^\d]*" + kw
        ]
        for pat in patterns:
            match = re.search(pat, raw_full_text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("|", "1")
                val_str = normalize_number_str(val_str, decimal_places)
                try:
                    val = float(val_str)
                    if decimal_places > 0 and "." not in val_str:
                        val = val / (10 ** decimal_places)
                    if check_digits(val):
                        candidates.append({"val": float(val), "score": 600})
                except Exception:
                    pass

    # 2) หาเลขทั้งหมด แล้วเลือกตัวที่คะแนนสูงสุด
    clean_std = re.sub(r"\b202[0-9]\b|\b256[0-9]\b", "", full_text)
    clean_std = re.sub(r"\.{2,}", ".", clean_std)

    for m in re.finditer(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", clean_std):
        n_str = m.group(0)
        if looks_like_spec_context(raw_full_text, m.start(), m.end()):
            continue

        n_str2 = normalize_number_str(n_str, decimal_places)
        if not n_str2:
            continue

        try:
            val = float(n_str2) if "." in n_str2 else float(int(n_str2))
            if decimal_places > 0 and "." not in n_str2:
                val = val / (10 ** decimal_places)

            if int(abs(val)) in common_noise and not keyword:
                continue
            if not check_digits(val):
                continue

            score = 120
            int_part = str(int(abs(val)))
            ln = len(int_part)
            # ถ้ามี expected_digits → ให้คะแนนตามความใกล้เคียง (ช่วยลดการหยิบเลขผิดจาก spec/เวลา)
            if expected_digits > 0:
                diff = abs(ln - expected_digits)
                score += max(0, 80 - diff * 40)
            score += min(ln, 10) * 10
            if decimal_places > 0 and "." in n_str2:
                score += 25

            candidates.append({"val": float(val), "score": score})
        except Exception:
            continue

    if candidates:
        return float(max(candidates, key=lambda x: x["score"])["val"])
    return 0.0

# =========================================================
# --- 🔳 QR + TYPE HELPERS ---
# =========================================================
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
    except Exception:
        return None

def infer_meter_type(config: dict) -> str:
    blob = f"{config.get('type','')} {config.get('name','')}".lower()
    if ("น้ำ" in blob) or ("water" in blob) or ("ประปา" in blob):
        return "Water"
    return "Electric"

def parse_image_pack(image_url: str) -> dict:
    """
    image_url ที่เป็น pack จะหน้าตาแบบ:
    'WT:https://... | UF:https://... | BST:https://...'
    """
    s = (image_url or "").strip()
    if not s or s == "-":
        return {}
    if " | " in s and ":" in s:
        out = {}
        parts = [p.strip() for p in s.split("|")]
        for p in parts:
            if ":" in p:
                k, v = p.split(":", 1)
                out[k.strip()] = v.strip()
        return out
    if s.startswith("http"):
        return {"IMG": s}
    return {}

def missing_required_photos(meter_type: str, image_url: str):
    pack = parse_image_pack(image_url)
    if meter_type == "SCADA":
        need = ["WT", "UF", "BST"]
    else:
        need = ["IMG"]
    missing = [k for k in need if k not in pack or not str(pack.get(k)).startswith("http")]
    return missing, pack

# =========================================================
# --- UI ---
# =========================================================
mode = st.sidebar.radio(
    "🔧 เลือกโหมดการทำงาน",
    ["📝 พนักงานจดมิเตอร์", "📟 SCADA (4 รูป)", "👮‍♂️ Admin Approval"]
)

# =========================================================
# MODE 1: พนักงานจดมิเตอร์ (QR → ยืนยัน → ถ่ายรูป → AI เสนอค่า → บันทึก)
# =========================================================
if mode == "📝 พนักงานจดมิเตอร์":
    st.title("Smart Meter System")
    st.markdown("### Water treatment Plant - Borthongindustrial")
    st.caption("Version 7.0 (Auto AI + Jump back to Scan)")

    # session
    if "emp_step" not in st.session_state:
        st.session_state.emp_step = "SCAN_QR"
    if "emp_point_id" not in st.session_state:
        st.session_state.emp_point_id = ""

    if "ai_suggest" not in st.session_state:
        st.session_state.ai_suggest = None
    if "last_img_hash" not in st.session_state:
        st.session_state.last_img_hash = ""
    if "last_upload_url" not in st.session_state:
        st.session_state.last_upload_url = ""
    if "last_report_info" not in st.session_state:
        st.session_state.last_report_info = None

    # top form
    c_insp, c_date = st.columns(2)
    with c_insp:
        inspector = st.text_input("ชื่อผู้ตรวจ", "Admin", key="emp_inspector")
    with c_date:
        selected_date = st.date_input("📅 วันที่ของข้อมูล", value=get_thai_time().date(), key="emp_date")

    # ---------------- STEP 1: SCAN QR ----------------
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

        with st.expander("สแกนไม่ได้? พิมพ์รหัสเอง"):
            manual_pid = st.text_input("พิมพ์ point_id", key="emp_manual_pid")
            if st.button("ยืนยันรหัส", use_container_width=True, key="emp_manual_ok"):
                if manual_pid.strip():
                    st.session_state.emp_point_id = manual_pid.strip().upper()
                    st.session_state.emp_step = "CONFIRM_POINT"
                    st.rerun()
                else:
                    st.warning("กรุณาพิมพ์รหัสก่อน")

        # โชว์รูป/ตำแหน่งล่าสุดที่เพิ่งบันทึก (ถ้ามี)
        if st.session_state.last_report_info:
            info = st.session_state.last_report_info
            st.markdown(
                f"<div class='status-box status-good'>✅ บันทึกล่าสุดลงรายงาน: <b>{info.get('sheet')}</b> | แถว <b>{info.get('row')}</b> | คอลัมน์ <b>{info.get('col_letter')}</b></div>",
                unsafe_allow_html=True
            )
        if st.session_state.last_upload_url and str(st.session_state.last_upload_url).startswith("http"):
            with st.expander("ดูรูปที่อัปโหลดล่าสุด"):
                st.image(st.session_state.last_upload_url, use_container_width=True)

        st.stop()

    # ---------------- STEP 2: CONFIRM POINT ----------------
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
        st.write(f"**ชื่อจุด:** {config.get('name','-')}")
        st.write(f"**ประเภท:** {'💧 Water' if meter_type=='Water' else '⚡ Electric'}")
        st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{config.get('report_col','-')}</span>", unsafe_allow_html=True)

        ref_bytes, ref_path = load_ref_image_bytes_any(pid)
        if ref_bytes:
            st.image(ref_bytes, caption=f"รูปตัวอย่าง (Reference): {ref_path}", use_container_width=True)
        else:
            st.warning("⚠️ ไม่พบรูปตัวอย่างใน bucket สำหรับจุดนี้")

        b1, b2 = st.columns(2)
        if b1.button("✅ ใช่จุดนี้", type="primary", use_container_width=True):
            st.session_state.emp_step = "INPUT"
            st.rerun()
        if b2.button("❌ ไม่ใช่ / สแกนใหม่", use_container_width=True):
            st.session_state.emp_step = "SCAN_QR"
            st.session_state.emp_point_id = ""
            st.rerun()

        st.stop()

    # ---------------- STEP 3: INPUT + PHOTO + AUTO AI + SAVE ----------------
    point_id = st.session_state.emp_point_id
    config = get_meter_config(point_id)
    if not config:
        st.error("❌ ไม่พบ config ของจุดนี้")
        st.session_state.emp_step = "SCAN_QR"
        st.session_state.emp_point_id = ""
        st.stop()

    report_col = str(config.get('report_col', '-') or '-').strip()
    meter_type = infer_meter_type(config)
    decimals = int(config.get("decimals", 0) or 0)
    step = 1.0 if decimals == 0 else (0.1 if decimals == 1 else 0.01)
    fmt  = "%.0f" if decimals == 0 else ("%.1f" if decimals == 1 else "%.2f")

    st.subheader("ขั้นที่ 3: ถ่ายรูป + AI เสนอค่า")
    st.write(f"📍 จุดตรวจ: **{point_id}**  |  {config.get('name','')}")
    st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{report_col}</span>", unsafe_allow_html=True)

    if st.button("🔁 เปลี่ยนจุด (สแกนใหม่)", use_container_width=True):
        st.session_state.emp_step = "SCAN_QR"
        st.session_state.emp_point_id = ""
        st.session_state.ai_suggest = None
        st.session_state.last_img_hash = ""
        st.rerun()

    tab_cam, tab_up = st.tabs(["📷 ถ่ายรูป", "📂 อัปโหลด"])
    with tab_cam:
        img_cam = st.camera_input("ถ่ายภาพมิเตอร์", key="emp_meter_cam")
    with tab_up:
        img_up = st.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'], key="emp_meter_upload")
        if img_up is not None:
            st.image(img_up, caption=f"รูปที่เลือก: {getattr(img_up, 'name', 'upload')}", use_container_width=True)

    img_file = img_cam if img_cam is not None else img_up

    if img_file is None:
        st.info("📷 ถ่ายรูปก่อน แล้วระบบจะให้ AI อ่านค่าให้เอง")
        st.stop()

    # อ่าน AI อัตโนมัติเมื่อรูปเปลี่ยน
    img_bytes = img_file.getvalue()
    img_hash = hashlib.md5(img_bytes).hexdigest()
    if img_hash != st.session_state.last_img_hash:
        st.session_state.last_img_hash = img_hash
        st.session_state.ai_suggest = None
        with st.spinner("🤖 AI กำลังอ่านค่า..."):
            st.session_state.ai_suggest = float(ocr_process(img_bytes, config, debug=False))

    ai_val = float(st.session_state.ai_suggest or 0.0)

    st.markdown("---")
    st.subheader("ผลที่ AI อ่านได้")
    st.metric("ค่า AI", fmt % ai_val)

    choice = st.radio("จะบันทึกค่าไหน?", ["✅ ใช้ค่า AI", "✍️ แก้เอง"], horizontal=True)
    if choice == "✍️ แก้เอง":
        final_val = st.number_input("ใส่ค่าที่ถูกต้อง", value=ai_val, min_value=0.0, step=step, format=fmt)
        status = "CONFIRMED_MANUAL"
    else:
        final_val = ai_val
        status = "CONFIRMED_AI"

    st.info(f"ค่าที่จะบันทึก: {fmt % float(final_val)}")

    colA, colB = st.columns(2)
    if colA.button("💾 บันทึกค่าเลย", type="primary", use_container_width=True):
        # 1) อัปโหลดรูป
        filename = f"{point_id}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
        image_url = upload_image_to_storage(img_bytes, filename)

        # 2) ลง DB
        ok_db = save_to_db(point_id, inspector, meter_type, float(final_val), float(ai_val), status, selected_date, image_url)

        # 3) ลง WaterReport + โชว์ตำแหน่ง
        ok_r, msg_r, info_r = export_to_real_report(point_id, float(final_val), inspector, report_col, selected_date, return_info=True)

        if ok_db:
            st.success("✅ บันทึกลงฐานข้อมูลสำเร็จ")
            st.session_state.last_upload_url = image_url if str(image_url).startswith("http") else ""
        else:
            st.error("❌ บันทึกลงฐานข้อมูลไม่สำเร็จ")

        if ok_r:
            st.session_state.last_report_info = info_r
            st.markdown(
                f"<div class='status-box status-good'>✅ ลงรายงานแล้ว: <b>{info_r.get('sheet')}</b> | แถว <b>{info_r.get('row')}</b> | คอลัมน์ <b>{info_r.get('col_letter')}</b></div>",
                unsafe_allow_html=True
            )
        else:
            st.warning(f"⚠️ ลงรายงานไม่สำเร็จ: {msg_r}")

        # 4) เคลียร์ + กลับไปสแกนจุดถัดไป
        st.session_state.ai_suggest = None
        st.session_state.last_img_hash = ""
        st.session_state.emp_step = "SCAN_QR"
        st.session_state.emp_point_id = ""
        st.balloons()
        st.rerun()

    if colB.button("🔁 ให้ AI อ่านใหม่", use_container_width=True):
        st.session_state.ai_suggest = None
        st.session_state.last_img_hash = ""
        st.rerun()

# =========================================================
# MODE 2: SCADA (4 รูป) → AI อ่านให้ → ใส่ค่าเลย (Auto) + แจ้งจุดที่อ่านไม่มั่นใจ
# =========================================================

elif mode == "📟 SCADA (4 รูป)":
    st.title("📟 SCADA (4 รูป)")
    st.caption("อัปโหลด 3–4 รูป (แนะนำให้ใช้ Screenshot ชัด ๆ) → AI อ่านค่า → ยืนยันทีละจุดแล้วลงรายงานทันที")

    # -----------------------------
    # Session state
    # -----------------------------
    if "scada_step" not in st.session_state: st.session_state.scada_step = "UPLOAD"  # UPLOAD / REVIEW
    if "scada_results" not in st.session_state: st.session_state.scada_results = {}  # point_id -> dict
    if "scada_order" not in st.session_state: st.session_state.scada_order = []
    if "scada_idx" not in st.session_state: st.session_state.scada_idx = 0
    if "scada_sig" not in st.session_state: st.session_state.scada_sig = ""
    if "scada_imgs" not in st.session_state: st.session_state.scada_imgs = {}        # group_key -> bytes
    if "scada_urls" not in st.session_state: st.session_state.scada_urls = {}        # group_key -> url

    # -----------------------------
    # Helpers (local)
    # -----------------------------
    def _scada_group(item: dict) -> str:
        """
        คืนค่า key ของกลุ่มรูปที่ควรใช้:
        - MON: Monitor View
        - WT_SYSTEM
        - UF_SYSTEM
        - BST: BoosterPumpCW
        """
        rc = str(item.get("report_col", "") or "").strip().upper()
        if rc.startswith("SCADA_MON") or rc.startswith("MON_") or "MONITOR" in rc:
            return "MON"
        if rc.startswith("SCADA_UF") or rc.startswith("UF_"):
            return "UF_SYSTEM"
        if rc.startswith("SCADA_BST") or rc.startswith("BST_") or "BOOST" in rc:
            return "BST"
        # default
        return "WT_SYSTEM"

    def _scada_excel_col(report_col: str) -> str:
        """
        รองรับ report_col แบบ:
        - "CH" (ปกติ)
        - "SCADA_WT_AL" -> "AL"
        - "UF_AX" -> "AX"
        ถ้าแยกไม่ได้ จะคืนค่าเดิม
        """
        rc = str(report_col or "").strip().upper()
        if "_" in rc:
            tail = rc.split("_")[-1].strip()
            if tail.isalpha() and 1 <= len(tail) <= 3:
                return tail
        if rc.isalpha() and 1 <= len(rc) <= 3:
            return rc
        return rc  # fallback

    def _md5(b: bytes) -> str:
        return hashlib.md5(b).hexdigest()

    def _calc_scada_signature(imgs: dict) -> str:
        # imgs: group_key -> bytes
        parts = []
        for k in sorted(imgs.keys()):
            parts.append(k + ":" + _md5(imgs[k]))
        return "|".join(parts)

    def _pick_image_bytes(group_key: str) -> bytes:
        # เลือกรูปตามกลุ่ม (ถ้าไม่มี ให้ fallback ไป WT)
        if group_key in st.session_state.scada_imgs:
            return st.session_state.scada_imgs[group_key]
        if "WT_SYSTEM" in st.session_state.scada_imgs:
            return st.session_state.scada_imgs["WT_SYSTEM"]
        # ลำดับ fallback
        for k in ["UF_SYSTEM", "BST", "MON"]:
            if k in st.session_state.scada_imgs:
                return st.session_state.scada_imgs[k]
        return b""

    def _run_scada_ocr(inspector: str, target_date):
        # โหลด SCADA points จาก PointsMaster
        all_points = load_points_master()
        scada_points = []
        for item in all_points:
            t = str(item.get("type", "") or "").strip().upper()
            name = str(item.get("name", "") or "").strip().upper()
            # SCADA เงื่อนไข: type หรือ name มีคำว่า SCADA
            if ("SCADA" in t) or ("SCADA" in name):
                scada_points.append(item)

        if not scada_points:
            st.error("❌ ไม่พบจุด SCADA ใน PointsMaster (เช็คคอลัมน์ type/name ว่ามีคำว่า SCADA)")
            return

        results = {}
        # จัด order: แยกตามกลุ่มก่อน แล้วตาม point_id
        scada_points_sorted = sorted(scada_points, key=lambda x: (_scada_group(x), str(x.get("point_id",""))))

        with st.spinner("🤖 AI กำลังอ่านค่า SCADA ..."):
            for item in scada_points_sorted:
                pid = str(item.get("point_id", "") or "").strip().upper()
                if not pid:
                    continue
                cfg = get_meter_config(pid)
                if not cfg:
                    continue

                # ตรวจ ROI เบื้องต้น (ถ้า ROI ผิดรูปแบบจะทำให้ AI อ่านมั่วมาก)
                try:
                    x1 = float(cfg.get('roi_x1', 0) or 0)
                    y1 = float(cfg.get('roi_y1', 0) or 0)
                    x2 = float(cfg.get('roi_x2', 0) or 0)
                    y2 = float(cfg.get('roi_y2', 0) or 0)
                    roi_bad = (x2 <= x1) or (y2 <= y1)
                except:
                    roi_bad = False

                grp = _scada_group(item)
                img_bytes = _pick_image_bytes(grp)
                if not img_bytes:
                    ai_val = 0.0
                else:
                    if roi_bad:
                        ai_val = 0.0
                    else:
                        try:
                            ai_val = float(ocr_process(img_bytes, cfg, debug=False) or 0.0)
                        except:
                            ai_val = 0.0

                report_col_raw = str(item.get("report_col", "") or "").strip()
                excel_col = _scada_excel_col(report_col_raw)
                decimals = int(cfg.get("decimals", 0) or 0)

                results[pid] = {
                    "group": grp,
                    "point_id": pid,
                    "name": str(cfg.get("name", "") or "").strip(),
                    "report_col_raw": report_col_raw,
                    "excel_col": excel_col,
                    "decimals": decimals,
                    "ai_value": float(ai_val),
                    "confirmed": False,
                    "final_value": None,
                    "status": "ROI_INVALID" if roi_bad else "AUTO_SCADA",
                }

        st.session_state.scada_results = results
        st.session_state.scada_order = list(results.keys())
        # เรียง order ให้เหมือนที่อ่าน
        st.session_state.scada_order = [str(item.get("point_id","")).strip().upper() for item in scada_points_sorted if str(item.get("point_id","")).strip().upper() in results]
        st.session_state.scada_idx = 0
        st.session_state.scada_step = "REVIEW"

    def _next_unconfirmed(start_idx: int = 0) -> int:
        order = st.session_state.scada_order
        res = st.session_state.scada_results
        for i in range(max(0, start_idx), len(order)):
            pid = order[i]
            if pid in res and not res[pid].get("confirmed", False):
                return i
        return min(start_idx, max(0, len(order) - 1))

    # -----------------------------
    # Input (inspector + date)
    # -----------------------------
    c_insp, c_date = st.columns(2)
    with c_insp:
        inspector = st.text_input("ชื่อผู้ตรวจ", "Admin", key="scada_inspector")
    with c_date:
        selected_date = st.date_input("📅 วันที่ของข้อมูล", value=get_thai_time().date(), key="scada_date")

    st.write("---")

    # -----------------------------
    # STEP: UPLOAD 4 IMAGES
    # -----------------------------
    if st.session_state.scada_step == "UPLOAD":
        st.subheader("อัปโหลดรูป SCADA (4 รูป)")

        st.caption("แนะนำ: ใช้ screenshot (คมชัดกว่า) • WT/UF/BST ควรครบ • MON เป็นทางเลือก (ถ้ามี)")

        col1, col2 = st.columns(2)
        with col1:
            f_mon = st.file_uploader("รูปที่ 1: Monitor View (ไม่บังคับ)", type=["jpg","jpeg","png"], key="scada_mon")
            f_wt  = st.file_uploader("รูปที่ 2: WT_SYSTEM (จำเป็น)", type=["jpg","jpeg","png"], key="scada_wt")
        with col2:
            f_uf  = st.file_uploader("รูปที่ 3: UF_SYSTEM (จำเป็น)", type=["jpg","jpeg","png"], key="scada_uf")
            f_bst = st.file_uploader("รูปที่ 4: BoosterPumpCW (จำเป็น)", type=["jpg","jpeg","png"], key="scada_bst")

        # เก็บ bytes ไว้ใน session (เพื่อใช้ตอน REVIEW)
        imgs = {}
        if f_mon is not None: imgs["MON"] = f_mon.getvalue()
        if f_wt  is not None: imgs["WT_SYSTEM"] = f_wt.getvalue()
        if f_uf  is not None: imgs["UF_SYSTEM"] = f_uf.getvalue()
        if f_bst is not None: imgs["BST"] = f_bst.getvalue()

        ready = ("WT_SYSTEM" in imgs) and ("UF_SYSTEM" in imgs) and ("BST" in imgs)

        if ready:
            sig = _calc_scada_signature(imgs)
            # ถ้าเปลี่ยนรูป → reset ผลเดิม แล้วอ่านใหม่
            if sig != st.session_state.scada_sig:
                st.session_state.scada_sig = sig
                st.session_state.scada_results = {}
                st.session_state.scada_order = []
                st.session_state.scada_idx = 0
                st.session_state.scada_imgs = imgs
                st.session_state.scada_urls = {}

            # เริ่มอ่านอัตโนมัติ "ทันที" หลังอัปโหลดครบ (ครั้งเดียวต่อ signature)
            if not st.session_state.scada_results:
                # อัปโหลดรูปไปที่ GCS ก่อน เพื่อเก็บหลักฐาน 4 รูป (ครั้งเดียว)
                urls = {}
                for k, b in imgs.items():
                    fname = f"SCADA_{k}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
                    urls[k] = upload_image_to_storage(b, fname)
                st.session_state.scada_urls = urls

                _run_scada_ocr(inspector, selected_date)
                st.rerun()

            st.success("✅ อัปโหลดครบแล้ว กำลังไปหน้า ‘ยืนยันทีละจุด’ ...")

        else:
            st.info("📌 อัปโหลดให้ครบอย่างน้อย WT / UF / BST แล้วระบบจะเริ่มอ่านค่าอัตโนมัติ")

        # ปุ่มรีเซ็ต
        if st.button("🧹 เริ่มใหม่ (ล้างผล/อัปโหลดใหม่)", use_container_width=True):
            st.session_state.scada_step = "UPLOAD"
            st.session_state.scada_results = {}
            st.session_state.scada_order = []
            st.session_state.scada_idx = 0
            st.session_state.scada_sig = ""
            st.session_state.scada_imgs = {}
            st.session_state.scada_urls = {}
            st.rerun()

        st.stop()

    # -----------------------------
    # STEP: REVIEW ทีละจุด (ไม่มีตารางกระพริบ)
    # -----------------------------
    st.subheader("ยืนยันค่า SCADA ทีละจุด (AI เสนอ → แก้ได้ → ยืนยันแล้วลงรายงานทันที)")

    res = st.session_state.scada_results
    order = st.session_state.scada_order

    if not res or not order:
        st.warning("ยังไม่มีผล AI — กลับไปอัปโหลดรูปใหม่")
        if st.button("⬅️ กลับไปหน้าอัปโหลด", use_container_width=True):
            st.session_state.scada_step = "UPLOAD"
            st.rerun()
        st.stop()

    confirmed_cnt = sum(1 for pid in order if res.get(pid, {}).get("confirmed", False))
    total_cnt = len(order)
    remain_cnt = total_cnt - confirmed_cnt
    zero_cnt = sum(1 for pid in order if float(res.get(pid, {}).get("ai_value", 0.0) or 0.0) == 0.0 and not res.get(pid, {}).get("confirmed", False))

    st.info(f"รวม {total_cnt} จุด | ยืนยันแล้ว {confirmed_cnt} | ค้าง {remain_cnt} | AI=0 (ยังไม่ยืนยัน) {zero_cnt}")

    # เลือก index ปัจจุบันให้ชี้ไปยังจุดที่ยังไม่ยืนยัน
    st.session_state.scada_idx = _next_unconfirmed(st.session_state.scada_idx)
    idx = st.session_state.scada_idx
    pid = order[idx]
    item = res[pid]

    # ปุ่มนำทาง
    nav1, nav2, nav3, nav4 = st.columns([1,1,1,1])
    if nav1.button("⬅️ ก่อนหน้า", use_container_width=True, disabled=(idx <= 0)):
        st.session_state.scada_idx = max(0, idx - 1)
        st.rerun()
    if nav2.button("➡️ ถัดไป", use_container_width=True, disabled=(idx >= total_cnt - 1)):
        st.session_state.scada_idx = min(total_cnt - 1, idx + 1)
        st.rerun()
    if nav3.button("⏭️ ไปจุดที่ยังไม่ยืนยัน", use_container_width=True, disabled=(remain_cnt == 0)):
        st.session_state.scada_idx = _next_unconfirmed(0)
        st.rerun()
    if nav4.button("⬅️ กลับไปอัปโหลด", use_container_width=True):
        st.session_state.scada_step = "UPLOAD"
        st.rerun()

    st.write("---")

    # แสดงข้อมูลจุด
    grp = item.get("group", "")
    name = item.get("name", "")
    decimals = int(item.get("decimals", 0) or 0)
    step = 1.0 if decimals == 0 else (0.1 if decimals == 1 else 0.01)
    fmt  = "%.0f" if decimals == 0 else ("%.1f" if decimals == 1 else "%.2f")
    ai_val = float(item.get("ai_value", 0.0) or 0.0)

    st.markdown(f"### 📍 {pid}")
    if name:
        st.caption(name)
    st.write(f"กลุ่มรูป: **{grp}** | คอลัมน์รายงาน: **{item.get('excel_col','')}**")

# เผื่อบางจุดอ่านผิดเพราะเลือกภาพผิด (WT/UF/BST) → ให้สลับรูปได้ต่อจุด
grp_opts = ["WT_SYSTEM", "UF_SYSTEM", "BST", "MON"]
try:
    default_i = grp_opts.index(grp) if grp in grp_opts else 0
except:
    default_i = 0
grp_pick = st.selectbox("🖼️ เลือกรูปที่ใช้สำหรับจุดนี้", grp_opts, index=default_i, key=f"grp_pick_{pid}")
if grp_pick != grp:
    st.session_state.scada_results[pid]["group"] = grp_pick
    grp = grp_pick


    # Preview ROI crop เพื่อช่วยคนเช็คเร็ว (ไม่ต้องดูรูปเต็ม)
    try:
        cfg = get_meter_config(pid)
        base_img = _pick_image_bytes(grp)
        if base_img and cfg:
            crop_bytes = preprocess_image_cv(base_img, cfg, use_roi=True, variant="raw")
            with st.expander("🖼️ ดูภาพเฉพาะส่วนตัวเลข (ROI Preview)"):
                st.image(crop_bytes, use_container_width=True)
    except:
        pass

    # ฟอร์มยืนยัน (กันกระพริบ)
    with st.form(key=f"scada_form_{pid}", clear_on_submit=False):
        st.write(f"🤖 AI เสนอค่า: **{fmt % ai_val}**")
        default_use_ai = False if ai_val == 0.0 else True
        use_ai = st.checkbox("✅ ใช้ค่า AI", value=default_use_ai, key=f"use_ai_{pid}")

        if use_ai:
            final_val = ai_val
            status = "CONFIRMED_SCADA_AI"
            st.success(f"ค่าที่จะบันทึก: {fmt % float(final_val)}")
        else:
            final_val = st.number_input("✍️ แก้ค่า (กรอกค่าที่ถูกต้อง)", value=float(ai_val), min_value=0.0, step=step, format=fmt, key=f"manual_{pid}")
            status = "CONFIRMED_SCADA_MANUAL"
            st.info(f"ค่าที่จะบันทึก: {fmt % float(final_val)}")

        colA, colB, colC = st.columns([1.2,1,1])
        submit = colA.form_submit_button("✅ ยืนยันจุดนี้ + ลงรายงาน", type="primary", use_container_width=True)
        reread = colB.form_submit_button("🔁 ให้ AI อ่านใหม่", use_container_width=True)
        skip   = colC.form_submit_button("➡️ ข้าม (ยังไม่ยืนยัน)", use_container_width=True)

    if reread:
        # อ่านใหม่เฉพาะจุดนี้
        try:
            cfg = get_meter_config(pid)
            base_img = _pick_image_bytes(grp)
            with st.spinner("🤖 อ่านใหม่..."):
                new_ai = float(ocr_process(base_img, cfg, debug=False) or 0.0) if (base_img and cfg) else 0.0
            st.session_state.scada_results[pid]["ai_value"] = new_ai
            # reset checkbox default ให้เหมาะ
            st.session_state[f"use_ai_{pid}"] = (new_ai != 0.0)
            st.rerun()
        except Exception as e:
            st.error(f"อ่านใหม่ไม่สำเร็จ: {e}")

    if skip:
        # ขยับไปตัวถัดไป
        st.session_state.scada_idx = min(total_cnt - 1, idx + 1)
        st.rerun()

    if submit:
        try:
            # ถ้า AI=0 แล้วติ๊กใช้ AI ให้บังคับแก้เอง
            if float(ai_val) == 0.0 and use_ai:
                st.warning("AI อ่านได้ 0.0 — แนะนำให้แก้เองก่อนยืนยัน")
                st.stop()

            report_col_for_write = item.get("excel_col", "")
            urls_pack = st.session_state.scada_urls or {}
            image_url = json.dumps(urls_pack, ensure_ascii=False)

            ok_db = save_to_db(pid, inspector, "SCADA", float(final_val), float(ai_val), status, selected_date, image_url)
            ok_rp = export_to_real_report(pid, float(final_val), inspector, report_col_for_write, selected_date)

            st.session_state.scada_results[pid]["confirmed"] = True
            st.session_state.scada_results[pid]["final_value"] = float(final_val)
            st.session_state.scada_results[pid]["status"] = status

            if ok_db and ok_rp:
                st.success("✅ ยืนยันแล้ว และลงรายงานเรียบร้อย")
            elif ok_db and not ok_rp:
                st.warning("บันทึก DB สำเร็จ แต่ลงรายงานไม่สำเร็จ (เช็ค report_col / sheet ชื่อเดือน)")
            else:
                st.error("บันทึกไม่สำเร็จ (เช็ค permission / sheet)")

            # ไปจุดถัดไปที่ยังไม่ยืนยัน
            st.session_state.scada_idx = _next_unconfirmed(idx + 1)
            st.rerun()
        except Exception as e:
            st.error(f"❌ ยืนยันไม่สำเร็จ: {e}")


elif mode == "👮‍♂️ Admin Approval":
    st.title("👮‍♂️ Admin Dashboard")
    st.caption("1) ตรวจงานที่ระบบ Flag  2) เช็คจุดที่ “ยังไม่มีรูป/ยังไม่มีข้อมูล”")

    col_r, col_date = st.columns([1, 1.2])
    with col_r:
        if st.button("🔄 รีเฟรช"):
            st.rerun()
    with col_date:
        admin_date = st.date_input("📅 วันที่ที่ต้องการตรวจ", value=get_thai_time().date(), key="admin_date")

    # โหลดข้อมูล
    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("DailyReadings")
    data = ws.get_all_records()
    points_master = load_points_master() or []
    all_point_ids = [str(p.get("point_id", "")).strip().upper() for p in points_master if str(p.get("point_id","")).strip()]

    tab1, tab2 = st.tabs(["🚩 งานที่ต้องตรวจ", "📌 จุดที่อาจลืมถ่ายรูป / ขาดข้อมูล"])

    # -------------------------
    # TAB 1: FLAGGED
    # -------------------------
    with tab1:
        pending = []
        for d in data:
            status = str(d.get('Status', d.get('status', ''))).strip().upper()
            if status.startswith("FLAGGED"):
                pending.append(d)

        if not pending:
            st.success("✅ ไม่มีรายการค้างตรวจ")
        else:
            for i, item in enumerate(pending):
                st.markdown("---")

                timestamp = str(item.get('timestamp', item.get('Timestamp', ''))).strip()
                point_id   = str(item.get('point_id', item.get('Point_ID', ''))).strip()
                meter_type = str(item.get('meter_type', item.get('Meter_Type', ''))).strip()
                inspector  = str(item.get('inspector', item.get('Inspector', ''))).strip()
                image_url  = str(item.get('image_url', item.get('Image_URL', ''))).strip()

                c_info, c_fix = st.columns([1.3, 1.7])

                with c_info:
                    st.subheader(f"🚩 {point_id}")
                    st.caption(f"เวลา: {timestamp}")
                    st.caption(f"ผู้บันทึก: {inspector} | ประเภท: {meter_type}")

                    # เตือนรูปไม่ครบ
                    missing, pack = missing_required_photos(meter_type, image_url)
                    if missing:
                        st.warning("⚠️ รูปไม่ครบ / ไม่มีรูป: " + ", ".join(missing))

                    # โชว์รูป (ถ้ามี)
                    if meter_type == "SCADA":
                        for k in ["MON", "WT", "UF", "BST"]:
                            if k in pack and str(pack[k]).startswith("http"):
                                st.caption(f"รูป {k}")
                                st.image(pack[k], use_container_width=True)
                    else:
                        if "IMG" in pack and str(pack["IMG"]).startswith("http"):
                            st.image(pack["IMG"], use_container_width=True)

                with c_fix:
                    cfg = get_meter_config(point_id) or {}
                    report_col = str(cfg.get("report_col", "")).strip()

                    m_val = safe_float(item.get('Manual_Value', item.get('manual_val', 0.0)), 0.0)
                    a_val = safe_float(item.get('AI_Value', item.get('ai_val', 0.0)), 0.0)

                    st.write("**เลือกค่าที่ถูกต้อง**")

                    if meter_type == "SCADA":
                        fixed_val = st.number_input(
                            "✍️ กรอกค่าที่ถูกต้อง",
                            value=float(m_val or a_val or 0.0),
                            min_value=0.0,
                            step=1.0,
                            format="%.2f",
                            key=f"fix_{i}"
                        )
                        choice_val = float(fixed_val)
                    else:
                        options_map = {
                            f"👤 คนจด: {m_val}": m_val,
                            f"🤖 AI: {a_val}": a_val
                        }
                        selected_label = st.radio("เลือกค่า:", list(options_map.keys()), key=f"rad_{i}")
                        choice_val = float(options_map[selected_label])

                    if st.button("✅ อนุมัติ + ลงรายงาน", key=f"btn_{i}", type="primary"):
                        try:
                            # หาแถวด้วย timestamp + point_id (เหมือนเดิม)
                            cells = ws.findall(timestamp)
                            updated = False
                            for cell in cells:
                                # col 3 = point_id (ตาม row ที่ append)
                                if str(ws.cell(cell.row, 3).value).strip() == point_id:
                                    ws.update_cell(cell.row, 7, "APPROVED")
                                    ws.update_cell(cell.row, 5, choice_val)

                                    # แปลง timestamp เป็นวันที่
                                    try:
                                        dt_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                        approve_date = dt_obj.date()
                                    except Exception:
                                        approve_date = get_thai_time().date()

                                    ok_r, msg_r, info_r = export_to_real_report(
                                        point_id, choice_val, inspector, report_col, approve_date, return_info=True
                                    )

                                    if ok_r:
                                        st.success(
                                            f"✅ Approved และลงรายงานแล้ว: {info_r.get('sheet')} | แถว {info_r.get('row')} | คอลัมน์ {info_r.get('col_letter')}"
                                        )
                                    else:
                                        st.warning(f"⚠️ Approved แล้ว แต่ลงรายงานไม่สำเร็จ: {msg_r}")

                                    updated = True
                                    break

                            if updated:
                                st.rerun()
                            else:
                                st.warning("หา row ไม่เจอ (timestamp/point_id อาจซ้ำหรือไม่ตรง)")
                        except Exception as e:
                            st.error(f"Error approve: {e}")

    # -------------------------
    # TAB 2: MISSING (ยังไม่มี record ของวันนั้น)
    # -------------------------
    with tab2:
        target_date_str = admin_date.strftime("%Y-%m-%d")

        submitted = set()
        for d in data:
            ts = str(d.get('timestamp', d.get('Timestamp', ''))).strip()
            pid = str(d.get('point_id', d.get('Point_ID', ''))).strip().upper()
            if ts[:10] == target_date_str and pid:
                submitted.add(pid)

        missing_points = [pid for pid in all_point_ids if pid and pid not in submitted]

        st.write(f"ทั้งหมด: **{len(all_point_ids)} จุด**  |  ส่งแล้ว: **{len(submitted)} จุด**  |  ขาด: **{len(missing_points)} จุด**")

        if not missing_points:
            st.success("✅ ครบทุกจุดแล้ว สำหรับวันที่เลือก")
        else:
            st.warning("⚠️ ยังมีจุดที่ไม่พบข้อมูล/ไม่พบรูป (อาจลืมถ่าย/ยังไม่ส่ง)")
            # โชว์เป็น 2 คอลัมน์ให้อ่านง่ายบนมือถือ
            cols = st.columns(2)
            half = (len(missing_points) + 1) // 2
            for idx, pid in enumerate(missing_points):
                with cols[0] if idx < half else cols[1]:
                    st.write("• " + pid)

