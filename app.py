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
# ⚠️ อ่านค่าจาก Streamlit Secrets (จะตั้งค่าตอน Deploy)
if 'gcp_service_account' in st.secrets:
    key_dict = json.loads(st.secrets['gcp_service_account'])
    creds = service_account.Credentials.from_service_account_info(
        key_dict, 
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/cloud-platform"
        ]
    )
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
    client = vision.ImageAnnotatorClient(credentials=creds) # ✅ ใช้ Creds จาก Streamlit Secrets
    image = vision.Image(content=image_bytes)
    response = client.text_detection(image=image)
    texts = response.text_annotations
    if texts:
        raw_full_text = texts[0].description.replace('\n', ' ')
        full_text = preprocess_text(raw_full_text)
        
        if keyword:
            pattern = re.escape