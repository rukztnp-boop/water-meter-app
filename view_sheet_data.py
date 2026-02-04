#!/usr/bin/env python3
"""ดูข้อมูลใน WaterMeter_System_DB"""

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def view_data():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1DI9C9nl0-Y6XkDLNQnabuaaZ_l3OA2C0R9NCFTnCELw/edit"
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    
    print("📋 รายชื่อ sheets ทั้งหมด:")
    print("="*70)
    for ws in spreadsheet.worksheets():
        print(f"  - {ws.title} ({ws.row_count} rows × {ws.col_count} cols)")
    
    print("\n🔍 ดูข้อมูลใน WaterMeter_System_DB...")
    print("="*70)
    
    worksheet = spreadsheet.worksheet('WaterMeter_System_DB')
    
    # อ่าน header
    headers = worksheet.row_values(1)
    print(f"\n📊 Headers ({len(headers)} คอลัมน์):")
    for i, h in enumerate(headers[:20], 1):
        print(f"  {i}. {h}")
    if len(headers) > 20:
        print(f"  ... และอีก {len(headers)-20} คอลัมน์")
    
    # อ่านข้อมูล 5 แถวแรก
    print(f"\n📝 ข้อมูล 5 แถวแรก:")
    print("-"*70)
    data = worksheet.get_all_values()[:6]  # header + 5 rows
    
    for row_idx, row in enumerate(data):
        if row_idx == 0:
            continue  # skip header
        print(f"\nRow {row_idx+1}:")
        for i, (header, value) in enumerate(zip(headers[:15], row[:15])):
            if value:
                print(f"  {header}: {value}")

if __name__ == "__main__":
    view_data()
