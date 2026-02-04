#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def analyze():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1DI9C9nl0-Y6XkDLNQnabuaaZ_l3OA2C0R9NCFTnCELw/edit"
    spreadsheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = spreadsheet.worksheet('DailyReadings')
    
    headers = worksheet.row_values(1)
    all_data = worksheet.get_all_values()
    
    point_id_idx = headers.index('point_id')
    ai_value_idx = headers.index('AI_Value')
    manual_idx = headers.index('Manual_Value')
    
    errors_by_type = {
        'negative': 0,
        'too_short': 0,
        'too_long': 0,
        'completely_wrong': 0
    }
    
    total = 0
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) <= max(point_id_idx, ai_value_idx, manual_idx):
            continue
        
        ai_value = row[ai_value_idx].strip()
        manual = row[manual_idx].strip()
        
        if not manual:
            continue
        
        total += 1
        
        try:
            ai_float = float(ai_value)
            manual_float = float(manual)
            
            if ai_value != manual:
                # วิเคราะห์ประเภทข้อผิดพลาด
                ai_digits = len(str(int(abs(ai_float))))
                manual_digits = len(str(int(abs(manual_float))))
                
                if ai_float < 0 and manual_float >= 0:
                    errors_by_type['negative'] += 1
                elif ai_digits < manual_digits - 1:
                    errors_by_type['too_short'] += 1
                elif ai_digits > manual_digits + 1:
                    errors_by_type['too_long'] += 1
                else:
                    errors_by_type['completely_wrong'] += 1
        except:
            pass
    
    print("="*60)
    print("📊 วิเคราะห์ประเภทข้อผิดพลาด")
    print("="*60)
    total_errors = sum(errors_by_type.values())
    for error_type, count in errors_by_type.items():
        pct = (count/total_errors*100) if total_errors > 0 else 0
        print(f"  {error_type}: {count} ({pct:.1f}%)")
    print(f"\nรวม: {total_errors} ข้อผิดพลาดจาก {total} รายการ")

if __name__ == "__main__":
    analyze()
