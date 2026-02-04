#!/usr/bin/env python3
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'

def check_accuracy():
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
    meter_type_idx = headers.index('meter_type')
    
    total = 0
    correct = 0
    errors = []
    analog_correct = 0
    analog_total = 0
    
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) <= max(point_id_idx, ai_value_idx, manual_idx):
            continue
        
        point_id = row[point_id_idx]
        ai_value = row[ai_value_idx].strip()
        manual = row[manual_idx].strip()
        timestamp = row[timestamp_idx]
        meter_type = row[meter_type_idx].strip()
        
        if not manual:
            continue
        
        total += 1
        is_analog = 'analog' in meter_type.lower() or 'อนาล็อก' in meter_type
        
        if is_analog:
            analog_total += 1
        
        if ai_value == manual:
            correct += 1
            if is_analog:
                analog_correct += 1
        else:
            if len(errors) < 30:
                errors.append({
                    'row': i,
                    'timestamp': timestamp[:19] if len(timestamp) >= 19 else timestamp,
                    'point': point_id,
                    'type': meter_type,
                    'ai': ai_value,
                    'manual': manual
                })
    
    print("="*80)
    print("📊 ความแม่นยำ AI")
    print("="*80)
    print(f"ทั้งหมด: {total} รายการ")
    if total > 0:
        print(f"✅ ถูก: {correct} ({correct/total*100:.1f}%)")
        print(f"❌ ผิด: {total-correct} ({(total-correct)/total*100:.1f}%)")
    
    if analog_total > 0:
        print(f"\n🔴 Analog: {analog_correct}/{analog_total} ถูก ({analog_correct/analog_total*100:.1f}%)")
    
    if errors:
        print(f"\n⚠️  ความผิดพลาด ({len(errors)} รายการแรก):")
        print("-"*80)
        for e in errors:
            print(f"{e['row']} | {e['timestamp']} | {e['point']} [{e['type']}]")
            print(f"  AI: '{e['ai']}' | Manual: '{e['manual']}'")

if __name__ == "__main__":
    check_accuracy()
