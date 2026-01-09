import streamlit as st
import io
import re
import gspread
import json
from google.oauth2 import service_account
from google.cloud import vision
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
import string

# --- PAGE CONFIG ---
st.set_page_config(page_title="Smart Meter System", page_icon="💧", layout="centered")

# --- CSS STYLING ---
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

# --- CONFIGURATION & SECRETS ---
# ⚠️ อ่านค่าจาก Streamlit Secrets
if 'gcp_service_account' in st.secrets:
    try:
        key_dict = json.loads(st.secrets['gcp_service_account'])
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
    st.error("❌ ไม่พบ Secrets 'gcp_service_account'. กรุณาตั้งค่าใน Streamlit Cloud")
    st.stop()

gc = gspread.authorize(creds)
DB_SHEET_NAME = 'WaterMeter_System_DB'     
REAL_REPORT_SHEET = 'TEST waterreport' 
IMAGE_FOLDER_NAME = 'WaterMeter_Images'

# --- GOOGLE DRIVE HELPER ---
def get_or_create_folder(drive_service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    else:
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        file = drive_service.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')

def upload_image_to_drive(image_bytes, file_name):
    try:
        drive_service = build('drive', 'v3', credentials=creds)
        folder_id = get_or_create_folder(drive_service, IMAGE_FOLDER_NAME)
        file_metadata = {'name': file_name, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg')
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        permission = {'type': 'anyone', 'role': 'reader'}
        drive_service.permissions().create(fileId=file.get('id'), body=permission).execute()
        return file.get('webViewLink')
    except Exception as e:
        return f"Error: {e}"

# --- SHEET HELPERS ---
def col_to_index(col_str):
    col_str = str(col_str).upper().strip()
    num = 0
    for c in col_str:
        if c in string.ascii_letters: num = num * 26 + (ord(c.upper()) - ord('A')) + 1
    return num

def get_thai_sheet_name(sh):
    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    now = datetime.now()
    m_idx = now.month - 1
    yy = str(now.year + 543)[-2:] 
    patterns = [f"{thai_months[m_idx]}{yy}", f"{thai_months[m_idx][:-1]}{yy}", f"{thai_months[m_idx]} {yy}", f"{thai_months[m_idx][:-1]} {yy}"]
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
    except: return None

def export_to_real_report(point_id, read_value, inspector, report_col):
    if not report_col: return False
    try:
        sh = gc.open(REAL_REPORT_SHEET)
        sheet_name = get_thai_sheet_name(sh)
        ws = sh.worksheet(sheet_name) if sheet_name else sh.get_worksheet(0)
        today_day = datetime.now().day
        try:
            cell = ws.find(str(today_day), in_column=1)
            target_row = cell.row
        except: target_row = 6 + today_day 
        target_col = col_to_index(report_col)
        if target_col == 0: return False
        ws.update_cell(target_row, target_col, read_value)
        return True
    except: return False

def save_to_db(point_id, inspector, meter_type, manual_val, ai_val, status, image_url="-"):
    try:
        sh = gc.open(DB_SHEET_NAME)
        ws = sh.worksheet("DailyReadings")
        row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), meter_type, point_id, inspector, manual_val, ai_val, status, image_url]
        ws.append_row(row)
        return True
    except: return False

# --- OCR LOGIC (THE BEST VERSION) ---
def preprocess_text(text):
    patterns = [r'IP\s*51', r'50\s*Hz', r'Class\s*2', r'3x220/380\s*V', r'Type', r'Mitsubishi', r'Electric', r'Wire', r'kWh', r'MH\s*[-]?\s*96', r'30\s*\(100\)\s*A', r'\d+\s*rev/kWh', r'WATT-HOUR\s*METER', r'Indoor\s*Use', r'Made\s*in\s*Thailand']
    for p in patterns: text = re.sub(p, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b10,000\b', '', text)
    text = re.sub(r'\b1,000\b', '', text)
    text = re.sub(r'(?<=[\d\s])[\|Il!](?=[\d\s])', '1', text)
    text = re.sub(r'(?<=[\d\s])[Oo](?=[\d\s])', '0', text)
    text = re.sub(r'(?<=[\d\s]{4})(?<=\d)\s*[A-Za-z&%$#@!§\(\)\{\}\?\/](?=\s|$)', '8', text)
    text = re.sub(r'(?<=[\d])\s*[\/\?\)>\}\]TZ\-_](?=\s|$)', '7', text)
    return text

def ocr_process(image_bytes, decimal_places=0, keyword="", expected_digits=0):
    client = vision.ImageAnnotatorClient(credentials=creds) 
    image = vision.Image(content=image_bytes)
    response = client.text_detection(image=image)
    texts = response.text_annotations
    if texts:
        raw_full_text = texts[0].description.replace('\n', ' ')
        full_text = preprocess_text(raw_full_text)
        
        # 1. Keyword Hunter (Raw Text)
        if keyword:
            pattern = re.escape(keyword) + r"[^\d]*((?:\d|O|o|l|I|\|)+[\.,]?\d*)"
            match = re.search(pattern, raw_full_text, re.IGNORECASE)
            if match:
                val_str = match.group(1).replace('O','0').replace('o','0').replace('l','1').replace('I','1').replace('|','1')
                try: 
                    val = float(val_str.replace(',', ''))
                    if decimal_places > 0 and '.' not in str(val): val = val / (10**decimal_places)
                    return val
                except: pass

        blacklisted = []
        id_matches = re.finditer(r'(?i)(?:id|code|no\.?|serial|s\/n)[\D]{0,15}?(\d+(?:[\s-]+\d+)*)', full_text)
        for m in id_matches:
            for p in re.split(r'[\s-]+', m.group(1)):
                try: blacklisted.extend([float(p), float(int(p))])
                except: pass

        def check_digits(val):
            if expected_digits == 0: return True 
            try: return len(str(int(val))) in [expected_digits, expected_digits - 1]
            except: return False
        
        def is_binary_noise(val):
            s = str(int(val))
            return set(s).issubset({'0', '1'}) and len(s) > 1

        candidates = []
        # Stitcher
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
                if val not in blacklisted and check_digits(val):
                    score = len(stitched_digits) * 100 
                    if is_binary_noise(val): score -= 300 
                    candidates.append({'val': val, 'score': score})
            except: pass

        # Loose Stitcher
        matches = re.finditer(r'\b\d(?:\D{0,10}\d){3,6}\b', full_text)
        for m in matches:
            clean = re.sub(r'\D', '', m.group(0))
            try:
                val = float(clean)
                if val not in blacklisted and val not in [10000, 1000, 100, 10, 1]:
                     if check_digits(val):
                         score = 100 + (len(clean) * 50)
                         candidates.append({'val': val, 'score': score})
            except: pass

        # Standard
        clean_std = re.sub(r'\b202[0-9]\b|\b256[0-9]\b', '', full_text)
        nums = re.findall(r'-?\d+\.\d+' if decimal_places > 0 else r'\d+', clean_std)
        for n_str in nums:
            try:
                val = float(n_str) if '.' in n_str else int(n_str)
                if decimal_places > 0 and '.' not in str(val): val = val / (10**decimal_places)
                if val in blacklisted: continue
                if not check_digits(val): continue
                score = 100
                if decimal_places > 0 and '.' in str(val): score += 50
                candidates.append({'val': float(val), 'score': score})
            except: continue

        if candidates: return max(candidates, key=lambda x: (x['score'], x['val']))['val']
    return 0

# ==========================================
# 🖥️ UI LOGIC
# ==========================================
mode = st.sidebar.radio("🔧 เลือกโหมดการทำงาน", ["📝 พนักงานจดมิเตอร์", "👮‍♂️ Admin Approval"])

if mode == "📝 พนักงานจดมิเตอร์":
    # 1. หัวข้อหลัก
    st.title("Smart Meter System")
    # 2. ชื่อโรงงาน
    st.markdown("### Water treatment Plant - Borthongindustrial")
   
    if 'confirm_mode' not in st.session_state: st.session_state.confirm_mode = False
    if 'warning_msg' not in st.session_state: st.session_state.warning_msg = ""
    if 'last_manual_val' not in st.session_state: st.session_state.last_manual_val = 0.0

    sh = gc.open(DB_SHEET_NAME)
    all_meters = sh.worksheet("PointsMaster").get_all_records()
    if not all_meters: st.stop()

    col_type, col_insp = st.columns(2)
    with col_type: cat_select = st.radio("ประเภทมิเตอร์", ["💧 ประปา (Water)", "⚡️ ไฟฟ้า (Electric)"], horizontal=True)
    with col_insp: inspector = st.text_input("ชื่อผู้ตรวจ", "Admin")

    filtered_meters = []
    for m in all_meters:
        m_type = str(m.get('type', '')).lower() + str(m.get('name', '')).lower()
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
        report_col = meter_data.get('report_col', '-')
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
                with st.spinner("🤖 AI กำลังประมวลผล + อัปโหลดรูป..."):
                    try:
                        img_bytes = img_file.getvalue()
                        config = get_meter_config(point_id)
                        ai_val = ocr_process(img_bytes, config['decimals'], config['keyword'], config['expected_digits'])
                        
                        filename = f"{point_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        image_url = upload_image_to_drive(img_bytes, filename)

                        if abs(manual_val - ai_val) <= 1.0:
                            if save_to_db(point_id, inspector, "Water" if "ประปา" in cat_select else "Electric", manual_val, ai_val, "VERIFIED", image_url):
                                export_to_real_report(point_id, manual_val, inspector, report_col)
                                st.balloons()
                                st.success("✅ บันทึกสำเร็จ!")
                                st.info(f"AI: {ai_val} | Manual: {manual_val}")
                            else: st.error("Save Failed")
                        else:
                            st.session_state.confirm_mode = True
                            st.session_state.warning_msg = f"ไม่ตรงกัน! กรอก {manual_val} / AI {ai_val}"
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
            st.success("✅ ส่งเรื่องแล้ว")
            st.session_state.confirm_mode = False
            st.rerun()
        if col_conf2.button("❌ แก้ไข"):
            st.session_state.confirm_mode = False
            st.rerun()

elif mode == "👮‍♂️ Admin Approval":
    st.title("👮‍♂️ Admin Dashboard")
    st.caption("ระบบอนุมัติผลการอ่านค่ามิเตอร์น้ำ/ไฟ")
    if st.button("🔄 รีเฟรช"): st.rerun()
    sh = gc.open(DB_SHEET_NAME)
    ws = sh.worksheet("DailyReadings")
    data = ws.get_all_records()
    pending = [d for d in data if d.get('Status') == 'FLAGGED']

    if not pending: st.success("✅ All Clear")
    else:
        for i, item in enumerate(pending):
            with st.container():
                st.markdown("---")
                c_info, c_val, c_act = st.columns([1.5, 1.5, 1])
                with c_info:
                    st.subheader(f"🚩 {item.get('point_id')}")
                    st.caption(f"Inspector: {item.get('inspector')}")
                    if item.get('image_url') and item.get('image_url') != '-':
                        st.image(item.get('image_url'), width=200)
                with c_val:
                    m_val = float(item.get('Manual_Value') or 0)
                    a_val = float(item.get('AI_Value') or 0)
                    choice = st.radio("เลือกค่า:", [m_val, a_val], key=f"rad_{i}")
                with c_act:
                    st.write("")
                    if st.button("✅ อนุมัติ", key=f"btn_{i}", type="primary"):
                        # หา Row ID (ต้องระวังเรื่อง index)
                        # เพื่อความง่าย ให้อนุมัติแล้วแก้ status เป็น APPROVED
                        row_idx = i + 2 
                        # หา Row จริงจากการวนลูปใน Sheet จะชัวร์กว่า
                        cells = ws.findall(item.get('timestamp'))
                        for cell in cells:
                            if ws.cell(cell.row, 3).value == item.get('point_id'): 
                                ws.update_cell(cell.row, 7, "APPROVED")
                                ws.update_cell(cell.row, 5, choice)
                                # Export
                                config = get_meter_config(str(item['point_id']))
                                export_to_real_report(str(item['point_id']), choice, str(item['inspector']), config.get('report_col', ''))
                                st.success("Approved!")
                                st.rerun()