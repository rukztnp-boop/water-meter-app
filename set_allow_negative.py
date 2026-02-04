#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def set_allow_negative():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1DI9C9nl0-Y6XkDLNQnabuaaZ_l3OA2C0R9NCFTnCELw/edit"
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = spreadsheet.worksheet('PointsMaster')
    
    headers = worksheet.row_values(1)
    
    # หา point_id (ตัวพิมพ์เล็ก)
    point_id_idx = headers.index('point_id')
    
    # หา/เพิ่ม allow_negative
    try:
        allow_neg_idx = headers.index('allow_negative')
        print(f"✅ พบคอลัมน์ allow_negative (col {allow_neg_idx + 1})")
    except ValueError:
        allow_neg_idx = len(headers)
        worksheet.update_cell(1, allow_neg_idx + 1, 'allow_negative')
        print(f"✅ เพิ่มคอลัมน์ allow_negative (col {allow_neg_idx + 1})")
    
    # อ่านข้อมูล
    all_data = worksheet.get_all_values()
    
    # หา H_M_H_FLOW_3
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) > point_id_idx:
            point_id = row[point_id_idx]
            if point_id == 'H_M_H_FLOW_3':
                worksheet.update_cell(i, allow_neg_idx + 1, 'TRUE')
                print(f"✅ {point_id}: allow_negative = TRUE (row {i})")

if __name__ == "__main__":
    set_allow_negative()
