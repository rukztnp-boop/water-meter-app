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

def ensure_dailyreadings_columns(ws):
    """Ensure extra columns exist on DailyReadings for PointID confidence tracking."""
    try:
        header = ws.row_values(1)
        if not header:
            header = ["timestamp","Type","point_id","inspector","Manual_Value","AI_Value","Status","Image_URL"]
            ws.update("A1", [header])
        needed = ["AI_PointID", "PointID_Confidence"]
        missing = [c for c in needed if c not in header]
        if missing:
            new_header = header + missing
            ws.update("A1", [new_header])
            return new_header
        return header
    except Exception:
        return None

# ✅ แก้ไข: รับ target_date เพื่อลง Timestamp ให้ถูกวัน + เก็บ AI_PointID/Confidence ถ้ามีคอลัมน์
def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, target_date, image_url="-", ai_point_id=None, pid_confidence=None):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")

        header = ensure_dailyreadings_columns(ws) or ws.row_values(1)
        # สร้าง Timestamp: วันที่เลือก + เวลาปัจจุบัน (เพื่อให้รู้ว่าคีย์ตอนกี่โมง แต่วันที่เป็นของวันที่เลือก)
        current_time = get_thai_time().time()
        record_timestamp = datetime.combine(target_date, current_time)

        # map col name -> index
        col_map = {str(h).strip(): i for i, h in enumerate(header, start=1)}

        def _set(row, col_name, value):
            if col_name in col_map:
                row[col_map[col_name]-1] = value

        row = [""] * len(header)
        _set(row, "timestamp", record_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        _set(row, "Timestamp", record_timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        _set(row, "Type", meter_type)
        _set(row, "point_id", point_id)
        _set(row, "PointID", point_id)
        _set(row, "inspector", inspector)
        _set(row, "Inspector", inspector)
        _set(row, "Manual_Value", manual_val)
        _set(row, "manual_val", manual_val)
        _set(row, "AI_Value", ai_val)
        _set(row, "ai_val", ai_val)
        _set(row, "Status", status)
        _set(row, "Image_URL", image_url)
        _set(row, "image_url", image_url)

        if ai_point_id is not None:
            _set(row, "AI_PointID", ai_point_id)
        if pid_confidence is not None:
            _set(row, "PointID_Confidence", pid_confidence)

        ws.append_row(row)
        return True
    except Exception:
        return False

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



# =========================================================
# --- 🔎 POINT-ID DETECTION (Auto) ---
# =========================================================
def _build_anchor_maps(meters: list[dict]):
    """
    Build helper maps from PointsMaster 'name' field.
    We use anchors like 'S11A-105', 'S11D-107', 'C07' etc to map -> point_id.
    """
    code_to_pid = {}
    cxx_to_pids = {}
    for m in meters:
        pid = str(m.get("point_id", "")).strip()
        name = str(m.get("name", "")).upper()

        # Anchor: S11A-105 / S11D-107 etc.
        for code in re.findall(r"S11[A-Z]-\d{2,3}", name):
            code_to_pid.setdefault(code, []).append(pid)

        # Anchor: C07 / C12 etc (customer code)
        for cxx in re.findall(r"\bC\d{2}\b", name):
            cxx_to_pids.setdefault(cxx, []).append(pid)

    return code_to_pid, cxx_to_pids

@st.cache_data(ttl=3600)
def _cached_anchor_maps():
    meters = load_points_master()
    return _build_anchor_maps(meters)

def detect_point_candidates_from_text(raw_text: str, meters: list[dict], max_k: int = 5):
    """
    Return list of candidates: [{"point_id":..., "score":..., "reason":...}, ...]
    score in [0,1] heuristic confidence.
    """
    if not raw_text:
        return []

    text_u = preprocess_text(raw_text).upper()

    # 0) direct exact point_id present
    all_pids = [str(m.get("point_id","")).strip().upper() for m in meters if m.get("active", True)]
    direct_hits = [pid for pid in all_pids if pid and pid in text_u]
    if len(direct_hits) == 1:
        return [{"point_id": direct_hits[0], "score": 0.98, "reason": "พบ PointID ในรูปโดยตรง"}]
    elif len(direct_hits) > 1:
        # multiple direct hits -> ambiguous
        return [{"point_id": pid, "score": 0.70, "reason": "พบ PointID หลายตัวในรูป (กำกวม)"} for pid in direct_hits[:max_k]]

    code_to_pid, cxx_to_pids = _cached_anchor_maps()

    # 1) match S11?-NNN anchors
    codes = list(dict.fromkeys(re.findall(r"S11[A-Z]-\d{2,3}", text_u)))
    candidates = []
    for code in codes:
        pids = code_to_pid.get(code, [])
        if len(pids) == 1:
            candidates.append({"point_id": pids[0], "score": 0.92, "reason": f"พบโค้ด {code} ในรูป"})
        elif len(pids) > 1:
            # ambiguous: same anchor maps to multiple points (rare)
            for pid in pids[:max_k]:
                candidates.append({"point_id": pid, "score": 0.65, "reason": f"พบโค้ด {code} แต่หลายจุดใช้ร่วมกัน"})

    # 2) match Cxx anchors as fallback
    cxxs = list(dict.fromkeys(re.findall(r"\bC\d{2}\b", text_u)))
    for cxx in cxxs:
        pids = cxx_to_pids.get(cxx, [])
        if len(pids) == 1:
            candidates.append({"point_id": pids[0], "score": 0.80, "reason": f"พบรหัสลูกค้า {cxx} ในรูป"})
        elif len(pids) > 1:
            for pid in pids[:max_k]:
                candidates.append({"point_id": pid, "score": 0.55, "reason": f"พบ {cxx} แต่ยังไม่ชัว (หลายจุด)"})

    # de-dup keep best score per pid
    best = {}
    for c in candidates:
        pid = c["point_id"]
        if pid not in best or c["score"] > best[pid]["score"]:
            best[pid] = c

    ranked = sorted(best.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:max_k]

def detect_point_id_from_image(image_bytes: bytes, meters: list[dict]):
    """
    Return (best_point_id, confidence, candidates, ocr_text)
    """
    try:
        raw_text = _vision_read_text(image_bytes) or ""
    except Exception:
        raw_text = ""

    candidates = detect_point_candidates_from_text(raw_text, meters, max_k=5)
    if not candidates:
        return None, 0.0, [], raw_text

    best = candidates[0]
    return best["point_id"], float(best["score"]), candidates, raw_text


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
    for m in re.finditer(r"-?\d+(?:\.\d+)?", clean_std):
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
mode = st.sidebar.radio("🔧 เลือกโหมดการทำงาน", ["📷 โหมดถ่ายภาพ (Auto PointID)", "📝 พนักงานจดมิเตอร์", "👮‍♂️ Admin Approval"])


if mode == "📷 โหมดถ่ายภาพ (Auto PointID)":
    st.title("📷 โหมดถ่ายภาพ (Auto PointID)")
    st.caption("ช่างถ่ายรูป + กรอกค่าที่อ่านได้ | ระบบพยายามหา PointID ให้เอง และตรวจเทียบกับ AI")

    inspector = st.text_input("ชื่อผู้ตรวจ", "User")
    selected_date = st.date_input("📅 วันที่จดบันทึก (สำหรับลงย้อนหลัง)", value=get_thai_time())

    all_meters = load_points_master()
    if not all_meters:
        st.error("❌ ไม่พบ PointsMaster"); st.stop()

    uploaded = st.file_uploader("📸 อัปโหลดรูปมิเตอร์ (JPG/PNG)", type=["jpg","jpeg","png"])
    if uploaded is None:
        st.info("กรุณาอัปโหลดรูปเพื่อเริ่ม"); st.stop()

    image_bytes = uploaded.getvalue()

    # 🔒 Rule: ถ้ารูปตะแคง/แนวนอน ให้ถ่ายใหม่ (ตาม requirement ลูกค้า)
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(image_bytes))
        w, h = im.size
        if w > h:
            st.error("⚠️ รูปนี้เป็นแนวนอน/ตะแคง กรุณาถ่ายใหม่ให้ตั้งตรง (Portrait)")
            st.image(im, use_container_width=True)
            st.stop()
        st.image(im, caption="รูปที่อัปโหลด", use_container_width=True)
    except Exception:
        pass

    with st.spinner("🔎 กำลังหา PointID จากรูป..."):
        pid, pid_conf, pid_candidates, _raw = detect_point_id_from_image(image_bytes, all_meters)

    if pid is None:
        st.error("❌ AI ยังหา PointID ไม่เจอ (รูปอาจเอียง/ไม่ชัด/ไม่ใช่จุดที่ถูกต้อง) กรุณาถ่ายใหม่")
        st.stop()

    st.markdown(f"### 🎯 PointID ที่ AI คิดว่าใช่: **{pid}**  (ความมั่นใจ {pid_conf:.2f})")

    # show top candidates (ช่วย admin/ช่าง)
    with st.expander("ดู Top candidates"):
        for c in pid_candidates:
            st.write(f"- {c['point_id']} | conf={c['score']:.2f} | {c['reason']}")

    # show reference image if available (optional column ref_image_url in PointsMaster)
    ref_url = None
    try:
        for m in all_meters:
            if str(m.get("point_id","")).strip() == pid:
                ref_url = m.get("ref_image_url") or m.get("Ref_Image_URL") or m.get("reference_image") or None
                break
    except Exception:
        ref_url = None

    st.markdown("### 🖼️ ภาพตัวอย่างที่ถูกต้อง (Reference)")
    if ref_url:
        st.image(ref_url, use_container_width=True)
    else:
        st.info("ยังไม่มีรูปตัวอย่างสำหรับจุดนี้ (สามารถเพิ่มได้ในหน้า Admin)")

    # manual input
    config = get_meter_config(pid) or {}
    decimals = safe_int(config.get("decimals", 0), 0)
    step = 1.0 if decimals <= 0 else float(10 ** (-decimals))
    fmt = "%.0f" if decimals <= 0 else f"%.{decimals}f"
    manual_val = st.number_input("👁️ ค่าที่ช่างอ่านได้", min_value=0.0, step=step, format=fmt)

    if st.button("🚀 ตรวจสอบและบันทึก", type="primary"):
        with st.spinner("🤖 AI กำลังอ่านค่าจากรูป..."):
            ai_val = ocr_process(image_bytes, config)

        st.info(f"AI อ่านได้: {ai_val} | คนกรอก: {manual_val}")

        tol = calc_tolerance(decimals)
        is_match = abs(float(manual_val) - float(ai_val)) <= tol
        is_pid_confident = pid_conf >= 0.85

        status = "VERIFIED" if (is_match and is_pid_confident) else "FLAGGED"

        # upload image
        filename = f"{pid}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
        try:
            image_url = upload_image_to_storage(image_bytes, filename)
        except Exception:
            image_url = "-"

        meter_type = "Water"
        if save_to_db(pid, inspector, meter_type, manual_val, ai_val, status, selected_date, image_url, ai_point_id=pid, pid_confidence=pid_conf):
            if status == "VERIFIED":
                report_col = config.get("report_col", "")
                export_to_real_report(pid, manual_val, inspector, report_col, selected_date)
                st.success("✅ VERIFIED และกรอกลงรายงานทันทีแล้ว")
            else:
                st.warning("⚠️ FLAGGED (คนกับ AI ไม่ตรง หรือ AI ไม่มั่นใจ PointID) ส่งให้ Admin ตรวจสอบ")
            st.balloons()
        else:
            st.error("❌ Save Failed")


elif mode == "📝 พนักงานจดมิเตอร์":
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
    img_file = tab_cam.camera_input("ถ่ายภาพมิเตอร์")
    if not img_file: img_file = tab_up.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'])

    st.write("---")

    if not st.session_state.confirm_mode:
        if st.button("🚀 ตรวจสอบและบันทึก", type="primary"):
            if img_file and point_id:
                with st.spinner(f"🤖 กำลังบันทึกข้อมูลของวันที่ {selected_date}..."):
                    try:
                        img_bytes = img_file.getvalue()
                        config = get_meter_config(point_id)
                        if not config: st.error("❌ ไม่พบ config"); st.stop()

                        # Hardcode Debug=False for production
                        ai_val = ocr_process(img_bytes, config, debug=False)
                        
                        filename = f"{point_id}_{selected_date.strftime('%Y%m%d')}_{get_thai_time().strftime('%H%M%S')}.jpg"
                        image_url = upload_image_to_storage(img_bytes, filename)

                        tol = calc_tolerance(config.get('decimals', 0))
                        if abs(manual_val - ai_val) <= tol:
                            meter_type = "Water" if "ประปา" in cat_select else "Electric"
                            # ✅ ส่ง selected_date เข้าไปบันทึก
                            if save_to_db(point_id, inspector, meter_type, manual_val, ai_val, "VERIFIED", selected_date, image_url):
                                export_to_real_report(point_id, manual_val, inspector, report_col, selected_date)
                                st.balloons()
                                st.success(f"✅ บันทึกสำเร็จ! (วันที่: {selected_date})")
                                st.info(f"AI: {ai_val} | Manual: {manual_val}")
                            else: st.error("Save Failed")
                        else:
                            st.session_state.confirm_mode = True
                            st.session_state.warning_msg = f"ไม่ตรงกัน! กรอก {manual_val} / AI {ai_val}"
                            st.session_state.last_manual_val = manual_val
                            st.session_state.last_ai_val = ai_val
                            st.session_state.last_img_url = image_url
                            st.session_state.last_selected_date = selected_date # เก็บวันที่ไว้ใช้ตอน Confirm
                            st.rerun()
                    except Exception as e: st.error(f"Error: {e}")
            else: st.warning("⚠️ กรุณาถ่ายรูปและเลือกจุดตรวจ")
    else:
        st.markdown(f"""<div class="status-box status-warning"><h4>⚠️ {st.session_state.warning_msg}</h4></div>""", unsafe_allow_html=True)
        col_conf1, col_conf2 = st.columns(2)
        if col_conf1.button("✅ ยืนยัน (ส่งให้ Admin)"):
            # ✅ ใช้วันที่ที่เก็บไว้ใน session_state
            target_date = st.session_state.get('last_selected_date', get_thai_time().date())
            save_to_db(point_id, inspector, "Water", st.session_state.last_manual_val, st.session_state.last_ai_val, "FLAGGED", target_date, st.session_state.last_img_url)
            st.success("✅ ส่งเรื่องแล้ว"); st.session_state.confirm_mode = False; st.rerun()
        if col_conf2.button("❌ แก้ไข"):
            st.session_state.confirm_mode = False; st.rerun()


elif mode == "👮‍♂️ Admin Approval":
    st.title("👮‍♂️ Admin Approval")
    st.caption("อนุมัติรายการ FLAGGED (คนกับ AI ไม่ตรง หรือ AI ไม่มั่นใจ PointID) ก่อนเขียนลง Test WaterReport")

    if st.button("🔄 รีเฟรช"): st.rerun()

    # load points master for dropdown
    all_meters = load_points_master()
    all_pids = [str(m.get("point_id","")).strip() for m in all_meters if str(m.get("point_id","")).strip()]
    all_pids = sorted(list(dict.fromkeys(all_pids)))

    def update_points_master_field(point_id: str, field_name: str, value):
        """Update a field in PointsMaster by header name."""
        try:
            sh = gc.open(DB_SHEET_NAME)
            ws_pm = sh.worksheet("PointsMaster")
            header = ws_pm.row_values(1)
            if field_name not in header:
                # append new column
                header2 = header + [field_name]
                ws_pm.update("A1", [header2])
                header = header2
            col = header.index(field_name) + 1

            # find row by point_id in column 1 (assume point_id col exists)
            cells = ws_pm.findall(point_id)
            for c in cells:
                if str(ws_pm.cell(c.row, 1).value).strip() == point_id:
                    ws_pm.update_cell(c.row, col, value)
                    return True
            return False
        except Exception:
            return False

    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("DailyReadings")
    header = ws.row_values(1)
    data = ws.get_all_records()
    pending = [d for d in data if str(d.get("Status", "")).strip().upper() == "FLAGGED"]

    if not pending:
        st.success("✅ ไม่มีรายการค้าง (All Clear)")
        st.stop()

    for i, item in enumerate(pending):
        st.markdown("---")
        timestamp = str(item.get("timestamp", item.get("Timestamp", ""))).strip()
        point_id_now = str(item.get("point_id", item.get("PointID", ""))).strip()
        ai_pid = str(item.get("AI_PointID", point_id_now)).strip()
        pid_conf = safe_float(item.get("PointID_Confidence", 0.0), 0.0)

        c1, c2 = st.columns([1.2, 1.8])

        with c1:
            st.write(f"🕒 **{timestamp}**")
            st.write(f"🤖 AI PointID: **{ai_pid}**  (conf {pid_conf:.2f})")
            st.write(f"📌 PointID ในรายการ: **{point_id_now}**")

            # Image
            img_url = item.get("Image_URL", item.get("image_url", "-"))
            if img_url and img_url != "-":
                st.image(img_url, use_container_width=True)

        with c2:
            # ให้ admin เลือก/แก้ PointID (โดยเฉพาะกรณี AI ไม่มั่นใจ)
            default_pid = point_id_now if point_id_now in all_pids else (ai_pid if ai_pid in all_pids else (all_pids[0] if all_pids else point_id_now))
            selected_point_id = st.selectbox("เลือก PointID ที่ถูกต้อง", all_pids, index=(all_pids.index(default_pid) if default_pid in all_pids else 0), key=f"pid_{i}")

            m_val = safe_float(item.get("Manual_Value", item.get("manual_val", 0.0)), 0.0)
            a_val = safe_float(item.get("AI_Value", item.get("ai_val", 0.0)), 0.0)

            options_map = {
                f"👤 คนจด: {m_val}": m_val,
                f"🤖 AI: {a_val}": a_val,
            }
            selected_label = st.radio("เลือกค่าที่ถูกต้อง:", list(options_map.keys()), key=f"rad_{i}")
            choice = options_map[selected_label]

            # เผื่อ admin อยากแก้เอง
            if st.checkbox("แก้ค่าเอง", key=f"edit_{i}"):
                cfg = get_meter_config(selected_point_id) or {}
                decimals = safe_int(cfg.get("decimals", 0), 0)
                step = 1.0 if decimals <= 0 else float(10 ** (-decimals))
                fmt = "%.0f" if decimals <= 0 else f"%.{decimals}f"
                choice = st.number_input("ใส่ค่าที่ถูกต้อง", value=float(choice), step=step, format=fmt, key=f"num_{i}")

            if st.button("✅ Approve & เขียนลงรายงาน", key=f"btn_{i}", type="primary"):
                try:
                    # หา row ด้วย timestamp
                    cells = ws.findall(timestamp)
                    updated = False
                    for cell in cells:
                        row = cell.row
                        # ตรวจว่าเป็นแถว FLAGGED จริง และ point_id ตรงกับรายการเดิม
                        pid_cell = str(ws.cell(row, 3).value).strip()
                        status_cell = str(ws.cell(row, 7).value).strip().upper()
                        if status_cell == "FLAGGED" and pid_cell == point_id_now:
                            # update point_id ถ้าแก้
                            if selected_point_id and selected_point_id != pid_cell:
                                ws.update_cell(row, 3, selected_point_id)

                            # update manual value + status
                            ws.update_cell(row, 5, choice)
                            ws.update_cell(row, 7, "APPROVED")

                            # export to report
                            config = get_meter_config(selected_point_id) or {}
                            report_col = config.get("report_col", "")

                            try:
                                dt_obj = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                                approve_date = dt_obj.date()
                            except Exception:
                                approve_date = get_thai_time().date()

                            export_to_real_report(selected_point_id, choice, str(item.get("inspector", "")), report_col, approve_date)
                            updated = True
                            break

                    if updated:
                        st.success("✅ Approved!")
                        st.rerun()
                    else:
                        st.error("ไม่พบแถวที่จะอัปเดต (อาจถูก Approve ไปแล้ว)")

                except Exception as e:
                    st.error(f"Approve error: {e}")

            # --- Reference image management ---
            with st.expander("🖼️ ตั้งค่า Reference Image ของจุดนี้ (เพื่อให้ช่างถ่ายตาม)"):
                st.caption("อัปโหลดรูปตัวอย่าง 1 รูป แล้วระบบจะเก็บ URL ไว้ใน PointsMaster (คอลัมน์ ref_image_url)")
                ref_file = st.file_uploader("อัปโหลดรูปตัวอย่าง", type=["jpg","jpeg","png"], key=f"refup_{i}")
                if ref_file is not None:
                    b = ref_file.getvalue()
                    fn = f"REF_{selected_point_id}.jpg"
                    try:
                        ref_url = upload_image_to_storage(b, fn)
                        ok = update_points_master_field(selected_point_id, "ref_image_url", ref_url)
                        if ok:
                            st.success("บันทึก Reference Image แล้ว ✅")
                        else:
                            st.warning("อัปโหลดได้ แต่ยังบันทึกลง PointsMaster ไม่สำเร็จ")
                        st.image(ref_url, use_container_width=True)
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

