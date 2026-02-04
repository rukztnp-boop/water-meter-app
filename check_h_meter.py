#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def check_meter():
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
    timestamp_idx = headers.index('timestamp')
    
    print("="*80)
    print("🔍 ข้อมูล H_M_H_FLOW_3")
    print("="*80)
    
    found = 0
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) <= max(point_id_idx, ai_value_idx, manual_idx):
            continue
        
        point_id = row[point_id_idx]
        
        if point_id == 'H_M_H_FLOW_3':
            ai_value = row[ai_value_idx].strip()
            manual = row[manual_idx].strip()
            timestamp = row[timestamp_idx]
            
            if manual:  # มี Manual Value
                found += 1
                if found <= 10:  # แสดง 10 รายการแรก
                    print(f"\n{timestamp[:19] if len(timestamp) >= 19 else timestamp}")
                    print(f"  AI:     '{ai_value}'")
                    print(f"  Manual: '{manual}'")
                    
                    try:
                        ai_float = float(ai_value) if ai_value else None
                        manual_float = float(manual)
                        
                        if ai_float is not None:
                            if ai_float < 0:
                                print(f"  ⚠️  AI ติดลบ!")
                            if manual_float < 0:
                                print(f"  ⚠️  Manual ก็ติดลบด้วย!")
                            
                            if abs(ai_float - manual_float) > 0.01:
                                print(f"  ❌ ต่างกัน {abs(ai_float - manual_float):.2f}")
                            else:
                                print(f"  ✅ ถูกต้อง")
                    except:
                        pass
    
    print(f"\n📊 พบทั้งหมด: {found} รายการ")

if __name__ == "__main__":
    check_meter()
