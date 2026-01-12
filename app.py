
import hashlib
import streamlit as st
import re
import gspread
import json
import cv2
import numpy as np
import pandas as pd
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

# Reference images location in GCS (optional)
REF_IMAGE_FOLDER = "ref_images"  # e.g. ref_images/CH_S11D_106.jpg

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
.status-box { padding: 14px; border-radius: 12px; margin: 10px 0; border: 1px solid #ddd; }
.status-warning { background-color: #fff3cd; color: #856404; }
.status-danger { background-color: #f8d7da; color: #842029; }
.report-badge {
  background-color: #e3f2fd; color: #0d47a1;
  padding: 4px 10px; border-radius: 8px; font-size: 0.9em; font-weight: 700;
}
.small { font-size: 0.9em; opacity: 0.85; }
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
    """อัปโหลดรูปเข้า GCS และคืน public url"""
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
    except:
        return None

def export_to_real_report(point_id, read_value, inspector, report_col, target_date):
    if not report_col:
        return False
    try:
        sh = gc.open(REAL_REPORT_SHEET)
        sheet_name = get_thai_sheet_name(sh, target_date)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)

        target_day = target_date.day
        target_row = find_day_row_exact(ws, target_day) or (6 + target_day)

        target_col = col_to_index(report_col)
        if target_col == 0:
            return False

        ws.update_cell(target_row, target_col, read_value)
        return True
    except:
        return False

def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, target_date, image_url="-"):
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
    except:
        return False

# =========================================================
# --- 🔳 QR HELPERS ---
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
    except:
        return None

def infer_meter_type(config: dict) -> str:
    """เดา meter_type จาก config เพื่อกันกรอกผิด"""
    blob = f"{config.get('type','')} {config.get('name','')}".lower()
    if ("น้ำ" in blob) or ("water" in blob) or ("ประปา" in blob):
        return "Water"
    return "Electric"

# =========================================================
# --- 🧠 OCR ENGINE (เดิม) ---
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

def preprocess_text(text):
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

def is_digital_meter(config):
    blob = f"{config.get('type','')} {config.get('name','')} {config.get('keyword','')}".lower()
    return ("digital" in blob) or ("scada" in blob) or (int(config.get('decimals', 0) or 0) > 0)

def preprocess_image_cv(image_bytes, config, use_roi=True, variant="auto"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
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

def _vision_read_text(processed_bytes):
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
        except:
            return False

    def looks_like_spec_context(text: str, start: int, end: int) -> bool:
        ctx = text[max(0, start - 10):min(len(text), end + 10)].lower()
        if "kwh" in ctx or "kw h" in ctx:
            return False
        bad = ["hz", "volt", " v", "v ", "amp", " a", "a ", "class", "ip", "rev", "rpm", "phase", "3x", "indoor"]
        return any(b in ctx for b in bad)

    common_noise = {10, 30, 50, 60, 100, 220, 230, 240, 380, 400, 415, 1000, 10000}
    candidates = []

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
                except:
                    pass

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
            score += min(len(int_part), 10) * 10
            if decimal_places > 0 and "." in n_str2:
                score += 25
            candidates.append({"val": float(val), "score": score})
        except:
            continue

    if candidates:
        return float(max(candidates, key=lambda x: x["score"])["val"])
    return 0.0

# =========================================================
# --- SCADA HELPERS ---
# =========================================================
def build_config_map(all_points):
    m = {}
    for item in all_points:
        pid = str(item.get('point_id', '')).strip().upper()
        if not pid:
            continue
        cfg = dict(item)
        cfg['decimals'] = safe_int(cfg.get('decimals'), 0)
        cfg['keyword'] = str(cfg.get('keyword', '')).strip()
        exp = safe_int(cfg.get('expected_digits'), 0)
        if exp == 0:
            exp = safe_int(cfg.get('int_digits'), 0)
        cfg['expected_digits'] = exp
        cfg['report_col'] = str(cfg.get('report_col', '')).strip()
        cfg['ignore_red'] = parse_bool(cfg.get('ignore_red'))
        cfg['roi_x1'] = safe_float(cfg.get('roi_x1'), 0.0)
        cfg['roi_y1'] = safe_float(cfg.get('roi_y1'), 0.0)
        cfg['roi_x2'] = safe_float(cfg.get('roi_x2'), 0.0)
        cfg['roi_y2'] = safe_float(cfg.get('roi_y2'), 0.0)
        cfg['type'] = str(cfg.get('type', '')).strip()
        cfg['name'] = str(cfg.get('name', '')).strip()
        m[pid] = cfg
    return m

def uniq_point_ids(points):
    seen = set()
    out = []
    for p in points:
        pid = str(p.get("point_id", "")).strip().upper()
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out

def parse_image_pack(s: str) -> dict:
    d = {}
    if not s or "|" not in str(s):
        return d
    for part in str(s).split("|"):
        part = part.strip()
        if ":" in part:
            k, v = part.split(":", 1)
            d[k.strip().upper()] = v.strip()
    return d

# =========================================================
# --- UI ---
# =========================================================
mode = st.sidebar.radio("🔧 เลือกโหมดการทำงาน", ["📝 พนักงานจดมิเตอร์", "📟 SCADA (4 รูป)", "👮‍♂️ Admin Approval"])

# ---------------------------------------------------------
# 1) พนักงานจดมิเตอร์ (QR-first, AI auto-suggest)
# ---------------------------------------------------------
if mode == "📝 พนักงานจดมิเตอร์":
    st.title("Smart Meter System")
    st.caption("Version 8.0 (QR-first + AI เสนอค่าอัตโนมัติ)")

    # session state
    if "emp_step" not in st.session_state:
        st.session_state.emp_step = "SCAN_QR"
    if "emp_point_id" not in st.session_state:
        st.session_state.emp_point_id = ""
    if "ai_suggest" not in st.session_state:
        st.session_state.ai_suggest = None
    if "last_img_hash" not in st.session_state:
        st.session_state.last_img_hash = ""

    all_meters = load_points_master()
    if not all_meters:
        st.error("❌ โหลด PointsMaster ไม่ได้")
        st.stop()

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
        if config.get("name"):
            st.write(f"**ชื่อจุด:** {config.get('name')}")
        st.write(f"**ประเภท:** {'💧 Water' if meter_type=='Water' else '⚡ Electric'}")

        ref_bytes, ref_path = load_ref_image_bytes_any(pid)
        if ref_bytes:
            st.image(ref_bytes, caption=f"รูปตัวอย่าง (Reference): {ref_path}", use_container_width=True)
        else:
            st.warning("⚠️ ไม่พบรูปตัวอย่างของจุดนี้ใน bucket")
            st.caption("แนะนำชื่อไฟล์: ref_images/POINT.jpg หรือ POINT_....jpg")

        b1, b2 = st.columns(2)
        if b1.button("✅ ใช่จุดนี้", type="primary", use_container_width=True):
            st.session_state.emp_step = "INPUT"
            # reset AI cache
            st.session_state.ai_suggest = None
            st.session_state.last_img_hash = ""
            st.rerun()
        if b2.button("❌ ไม่ใช่ / สแกนใหม่", use_container_width=True):
            st.session_state.emp_step = "SCAN_QR"
            st.session_state.emp_point_id = ""
            st.rerun()
        st.stop()

    # ---------------- STEP 3: PHOTO -> AI -> SAVE ----------------
    point_id = st.session_state.emp_point_id
    config = get_meter_config(point_id)
    if not config:
        st.error("❌ ไม่พบ config ของจุดนี้")
        st.session_state.emp_step = "SCAN_QR"
        st.session_state.emp_point_id = ""
        st.stop()

    report_col = str(config.get("report_col", "-") or "-").strip()
    decimals = int(config.get("decimals", 0) or 0)
    step = 1.0 if decimals == 0 else (0.1 if decimals == 1 else 0.01)
    fmt  = "%.0f" if decimals == 0 else ("%.1f" if decimals == 1 else "%.2f")
    meter_type = infer_meter_type(config)

    st.subheader("ขั้นที่ 3: ถ่ายรูปให้ AI อ่านค่า")
    st.markdown(f"📍 จุดตรวจ: **{point_id}**")
    if config.get("name"):
        st.caption(config.get("name"))
    st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{report_col}</span>", unsafe_allow_html=True)

    if st.button("🔁 เปลี่ยนจุด (สแกนใหม่)", use_container_width=True, key="emp_change_point"):
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
        st.info("📷 ถ่ายรูป/อัปโหลดก่อน แล้ว AI จะอ่านค่าให้เอง")
        st.stop()

    # auto OCR by hash
    img_bytes = img_file.getvalue()
    img_hash = hashlib.md5(img_bytes).hexdigest()
    if img_hash != st.session_state.last_img_hash:
        st.session_state.last_img_hash = img_hash
        st.session_state.ai_suggest = None
        with st.spinner("🤖 AI กำลังอ่านค่า..."):
            st.session_state.ai_suggest = float(ocr_process(img_bytes, config, debug=False))

    ai_val = float(st.session_state.ai_suggest or 0.0)

    st.write("---")
    st.subheader("ผลที่ AI อ่านได้")
    st.metric("ค่า AI", fmt % ai_val)

    choice = st.radio("ต้องการบันทึกค่าไหน?", ["✅ ใช้ค่า AI", "✍️ แก้เอง"], horizontal=True, key="emp_choice")
    if choice == "✍️ แก้เอง":
        final_val = st.number_input("ใส่ค่าที่ถูกต้อง", value=float(ai_val), min_value=0.0, step=step, format=fmt, key="emp_override")
        status = "CONFIRMED_MANUAL"
    else:
        final_val = float(ai_val)
        status = "CONFIRMED_AI"

    st.info(f"ค่าที่จะบันทึก: {fmt % float(final_val)}")

    colA, colB = st.columns(2)
    if colA.button("💾 บันทึกค่าเลย", type="primary", use_container_width=True):
        filename = f"{point_id}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
        image_url = upload_image_to_storage(img_bytes, filename)

        ok = save_to_db(point_id, inspector, meter_type, float(final_val), float(ai_val), status, selected_date, image_url)
        if ok:
            export_to_real_report(point_id, float(final_val), inspector, report_col, selected_date)
            st.success("✅ บันทึกสำเร็จ")
            # ไปจุดถัดไป (ลดคลิก)
            st.session_state.emp_step = "SCAN_QR"
            st.session_state.emp_point_id = ""
            st.session_state.ai_suggest = None
            st.session_state.last_img_hash = ""
            st.rerun()
        else:
            st.error("❌ บันทึกไม่สำเร็จ (เช็คสิทธิ์ Sheet/ชื่อชีต)")

    if colB.button("🔁 อ่านใหม่", use_container_width=True):
        st.session_state.ai_suggest = None
        st.session_state.last_img_hash = ""
        st.rerun()

# ---------------------------------------------------------
# 2) SCADA (4 รูป)
# ---------------------------------------------------------
elif mode == "📟 SCADA (4 รูป)":
    st.title("📟 SCADA (4 รูป)")
    st.caption("อัปโหลด 3 รูปหลัก (WT/UF/Booster) + (Monitor optional) → AI อ่านค่า → บันทึกลงรายงาน")

    c1, c2 = st.columns(2)
    with c1:
        inspector = st.text_input("ชื่อผู้ตรวจ", "Admin", key="scada_inspector")
    with c2:
        selected_date = st.date_input("📅 วันที่ของข้อมูล", value=get_thai_time().date(), key="scada_date")

    with st.expander("✅ วิธีใช้ (ง่าย ๆ)", expanded=True):
        st.write("1) ถ้าเป็นรูปจากหน้าจอ SCADA แนะนำให้ใช้ “แคปหน้าจอ (screenshot)” จะอ่านติดกว่า")
        st.write("2) อัปโหลด 3 รูปหลักให้ครบ: WT / UF / Booster")
        st.write("3) กด “ให้ AI อ่านค่า” → (ถ้าจำเป็น) แก้ในตาราง → กด “บันทึกทั้งหมด”")

    img_mon = st.file_uploader("รูปที่ 1: Monitor View (Optional)", type=['jpg', 'png', 'jpeg'], key="scada_img_mon")
    img_wt  = st.file_uploader("รูปที่ 2: WT_SYSTEM (จำเป็น)", type=['jpg', 'png', 'jpeg'], key="scada_img_wt")
    img_uf  = st.file_uploader("รูปที่ 3: UF_SYSTEM (จำเป็น)", type=['jpg', 'png', 'jpeg'], key="scada_img_uf")
    img_bst = st.file_uploader("รูปที่ 4: BoosterPumpCW (จำเป็น)", type=['jpg', 'png', 'jpeg'], key="scada_img_bst")

    missing = []
    if img_wt is None:  missing.append("WT_SYSTEM")
    if img_uf is None:  missing.append("UF_SYSTEM")
    if img_bst is None: missing.append("BoosterPumpCW")

    if missing:
        st.markdown(f"<div class='status-box status-warning'><b>⚠️ ยังขาดรูป:</b> {', '.join(missing)}</div>", unsafe_allow_html=True)

    can_run = (img_wt is not None) and (img_uf is not None) and (img_bst is not None)

    # prepare session
    if "scada_df" not in st.session_state:
        st.session_state.scada_df = None
    if "scada_pack" not in st.session_state:
        st.session_state.scada_pack = None

    if st.button("🤖 ให้ AI อ่านค่า", type="primary", disabled=not can_run):
        all_points = load_points_master()
        if not all_points:
            st.error("❌ โหลด PointsMaster ไม่สำเร็จ")
            st.stop()

        config_map = build_config_map(all_points)

        wt_points = [p for p in all_points if "scada_wt" in str(p.get("type","")).lower()]
        uf_points = [p for p in all_points if "scada_uf" in str(p.get("type","")).lower()]
        bst_points = [p for p in all_points if ("scada_boosterpumpcw" in str(p.get("type","")).lower()) or ("cw1" in str(p.get("name","")).lower())]

        wt_ids = uniq_point_ids(wt_points)
        uf_ids = uniq_point_ids(uf_points)
        bst_ids = uniq_point_ids(bst_points)

        img_bytes_wt = img_wt.getvalue()
        img_bytes_uf = img_uf.getvalue()
        img_bytes_bst = img_bst.getvalue()

        # upload images (pack)
        tstamp = get_thai_time().strftime("%Y%m%d_%H%M%S")
        urls = {}
        urls["MON"] = upload_image_to_storage(img_mon.getvalue(), f"SCADA_MON_{selected_date.strftime('%Y%m%d')}_{tstamp}.png") if img_mon is not None else "-"
        urls["WT"]  = upload_image_to_storage(img_bytes_wt, f"SCADA_WT_{selected_date.strftime('%Y%m%d')}_{tstamp}.png")
        urls["UF"]  = upload_image_to_storage(img_bytes_uf, f"SCADA_UF_{selected_date.strftime('%Y%m%d')}_{tstamp}.png")
        urls["BST"] = upload_image_to_storage(img_bytes_bst, f"SCADA_BST_{selected_date.strftime('%Y%m%d')}_{tstamp}.png")
        image_url_pack = " | ".join([f"{k}:{v}" for k, v in urls.items()])
        st.session_state.scada_pack = image_url_pack

        rows = []

        def read_ids(group_name, ids, screen_bytes):
            for pid in ids:
                cfg = config_map.get(pid)
                if not cfg:
                    continue
                ai_val = ocr_process(screen_bytes, cfg, debug=False)
                rows.append({
                    "group": group_name,
                    "point_id": pid,
                    "name": str(cfg.get("name","")),
                    "ai_value": float(ai_val),
                    "final_value": float(ai_val),
                    "report_col": str(cfg.get("report_col","")).strip(),
                })

        with st.spinner("🤖 กำลังอ่านค่าจากรูป SCADA..."):
            read_ids("WT_SYSTEM", wt_ids, img_bytes_wt)
            read_ids("UF_SYSTEM", uf_ids, img_bytes_uf)
            read_ids("BOOSTER_CW_RO", bst_ids, img_bytes_bst)

        if not rows:
            st.error("❌ ไม่เจอรายการ SCADA ใน PointsMaster (เช็ค type ว่ามี SCADA_ ไหม)")
            st.stop()

        st.session_state.scada_df = pd.DataFrame(rows)
        st.success(f"อ่านค่าเสร็จ {len(rows)} จุด ✅")
        st.rerun()

    # show table if exists
    if st.session_state.scada_df is not None:
        df = st.session_state.scada_df.copy()

        st.write("---")
        st.subheader("ตารางผลลัพธ์ (แก้ได้)")
        edited = st.data_editor(
            df[["group","point_id","name","ai_value","final_value","report_col"]],
            use_container_width=True,
            num_rows="fixed"
        )

        colS1, colS2 = st.columns(2)
        if colS1.button("⚡ บันทึกทั้งหมด (ใช้ค่า AI)", type="primary", use_container_width=True):
            edited["final_value"] = edited["ai_value"]
            st.session_state.scada_df = edited
            st.success("ตั้งค่า final_value = ai_value เรียบร้อย ✅")
            st.rerun()

        if colS2.button("🧹 ล้างผลลัพธ์", use_container_width=True):
            st.session_state.scada_df = None
            st.session_state.scada_pack = None
            st.rerun()

        if st.button("💾 บันทึกทั้งหมดลงรายงาน", type="primary", use_container_width=True):
            ok_cnt, fail_cnt = 0, 0
            pack = st.session_state.scada_pack or "-"

            for _, r in edited.iterrows():
                pid = str(r.get("point_id","")).strip().upper()
                final_val = r.get("final_value", None)
                ai_val = r.get("ai_value", None)
                report_col = str(r.get("report_col","")).strip()

                if final_val is None or (isinstance(final_val, float) and np.isnan(final_val)):
                    fail_cnt += 1
                    continue

                status = "SCADA_AI" if float(final_val) == float(ai_val) else "SCADA_EDITED"
                try:
                    save_to_db(pid, inspector, "SCADA", float(final_val), float(ai_val) if ai_val is not None else "", status, selected_date, pack)
                    export_to_real_report(pid, float(final_val), inspector, report_col, selected_date)
                    ok_cnt += 1
                except:
                    fail_cnt += 1

            st.success(f"✅ บันทึกสำเร็จ {ok_cnt} รายการ | ❌ ไม่สำเร็จ {fail_cnt} รายการ")

# ---------------------------------------------------------
# 3) Admin
# ---------------------------------------------------------
else:
    st.title("👮‍♂️ Admin Dashboard")
    st.caption("อนุมัติ/ตรวจงาน + เตือนรูป SCADA ที่ขาด")

    if st.button("🔄 รีเฟรช", use_container_width=True):
        st.rerun()

    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("DailyReadings")
    data = ws.get_all_records()

    # ------------------ SCADA missing-photo warning ------------------
    st.write("---")
    st.subheader("🔔 เตือนรูป SCADA ที่ขาด")
    check_date = st.date_input("เลือกวันที่จะเช็ค", value=get_thai_time().date(), key="admin_check_date")

    scada_rows = []
    for d in data:
        ts = str(d.get("timestamp", d.get("Timestamp",""))).strip()
        mt = str(d.get("meter_type", d.get("Meter_Type",""))).strip().upper()
        img = str(d.get("image_url", d.get("Image_URL",""))).strip()
        if mt != "SCADA":
            continue
        try:
            dt_obj = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            if dt_obj.date() == check_date:
                scada_rows.append(img)
        except:
            continue

    if not scada_rows:
        st.info("ยังไม่พบการอัปโหลด SCADA ของวันนี้ใน DailyReadings")
    else:
        # เอา pack แรกที่เจอ (ปกติทุกแถวจะเหมือนกัน)
        pack = scada_rows[0]
        pack_map = parse_image_pack(pack)
        required = ["WT", "UF", "BST"]
        missing_keys = []
        for k in required:
            v = pack_map.get(k, "").strip()
            if (not v) or v == "-" or (not v.startswith("http")):
                missing_keys.append(k)

        if not missing_keys:
            st.success("✅ รูป SCADA หลักครบแล้ว (WT/UF/BST)")
        else:
            pretty = {"WT":"WT_SYSTEM", "UF":"UF_SYSTEM", "BST":"BoosterPumpCW"}
            st.markdown(f"<div class='status-box status-danger'><b>❌ ขาดรูป:</b> {', '.join(pretty.get(k,k) for k in missing_keys)}</div>", unsafe_allow_html=True)

        # แสดงลิงก์รูปที่มี
        if pack_map:
            st.write("รูปที่มีอยู่:")
            for k, v in pack_map.items():
                if v and v != "-" and v.startswith("http"):
                    st.markdown(f"- **{k}**: {v}")

    # ------------------ Pending approvals (FLAGGED) ------------------
    st.write("---")
    st.subheader("🚩 งานที่รออนุมัติ (FLAGGED)")
    pending = [d for d in data if str(d.get('Status', d.get('status', ''))).strip().upper() == 'FLAGGED']

    if not pending:
        st.success("✅ ไม่มีงานค้าง")
        st.stop()

    for i, item in enumerate(pending):
        with st.container():
            st.markdown("---")
            c_info, c_val, c_act = st.columns([1.5, 1.6, 1.0])

            # fields (robust)
            timestamp = str(item.get('timestamp', item.get('Timestamp',''))).strip()
            point_id = str(item.get('point_id', item.get('Point_ID',''))).strip()
            inspector = str(item.get('inspector', item.get('Inspector',''))).strip()
            img_url = str(item.get('image_url', item.get('Image_URL',''))).strip()

            with c_info:
                st.subheader(f"🚩 {point_id}")
                st.caption(f"Inspector: {inspector}")
                # รูป (รองรับทั้งแบบเดี่ยวและแบบ pack)
                if "|" in img_url:
                    pack_map = parse_image_pack(img_url)
                    if pack_map:
                        # โชว์ WT เป็นหลัก ถ้ามี
                        show_url = pack_map.get("WT", "") or next(iter(pack_map.values()), "")
                        if show_url and show_url != "-" and show_url.startswith("http"):
                            st.image(show_url, width=240)
                        # เตือนถ้าขาดรูปหลัก
                        required = ["WT","UF","BST"]
                        miss = []
                        for k in required:
                            v = pack_map.get(k, "").strip()
                            if (not v) or v == "-" or (not v.startswith("http")):
                                miss.append(k)
                        if miss:
                            st.markdown("<div class='small'>❌ รูป SCADA ขาด: " + ", ".join(miss) + "</div>", unsafe_allow_html=True)
                else:
                    if img_url and img_url != '-' and img_url.startswith('http'):
                        st.image(img_url, width=240)
                    else:
                        st.warning("No Image")

                st.caption(f"เวลา: {timestamp}")

            with c_val:
                m_val = safe_float(item.get('Manual_Value', item.get('manual_value', 0.0)), 0.0)
                a_val = safe_float(item.get('AI_Value', item.get('ai_value', 0.0)), 0.0)
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
                        # หาแถวด้วย timestamp แล้วเช็ค point_id ให้ตรง
                        cells = ws.findall(timestamp)
                        updated = False
                        for cell in cells:
                            if str(ws.cell(cell.row, 3).value).strip() == point_id:
                                ws.update_cell(cell.row, 7, "APPROVED")
                                ws.update_cell(cell.row, 5, choice)

                                cfg = get_meter_config(point_id)
                                report_col = (cfg.get('report_col', '') if cfg else '')

                                try:
                                    dt_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                    approve_date = dt_obj.date()
                                except:
                                    approve_date = get_thai_time().date()

                                export_to_real_report(point_id, choice, inspector, report_col, approve_date)
                                updated = True
                                break

                        if updated:
                            st.success("Approved!")
                            st.rerun()
                        else:
                            st.warning("หา row ไม่เจอ")
                    except Exception as e:
                        st.error(f"Error approve: {e}")
