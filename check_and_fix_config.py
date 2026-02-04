"""
🔧 ตรวจสอบและแก้ไข Config ใน PointsMaster
- ตรวจสอบ decimals, expected_digits, ignore_red
- แก้ไขมิเตอร์อนาล็อกให้ถูกต้อง (decimals=0, ignore_red=TRUE)
"""

import gspread
from google.oauth2 import service_account
import json

# เชื่อมต่อ Google Sheets
with open('service_account.json', 'r') as f:
    key_dict = json.load(f)

creds = service_account.Credentials.from_service_account_info(
    key_dict,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
)

gc = gspread.authorize(creds)

# เปิด sheet
SHEET_URL = "https://docs.google.com/spreadsheets/d/1DI9C9nl0-Y6XkDLNQnabuaaZ_l3OA2C0R9NCFTnCELw/edit"
sh = gc.open_by_url(SHEET_URL)
ws = sh.worksheet("PointsMaster")

print("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
print(f"📊 Sheet: {sh.title}")
print("-" * 60)

# อ่านข้อมูล
records = ws.get_all_records()
print(f"📋 พบ {len(records)} จุดทั้งหมด\n")

# ตรวจสอบและแนะนำการแก้ไข
issues = []
fixes = []

for idx, rec in enumerate(records, start=2):  # start=2 เพราะแถว 1 เป็น header
    point_id = str(rec.get('point_id', '')).strip()
    if not point_id:
        continue
    
    meter_type = str(rec.get('type', '')).strip().lower()
    name = str(rec.get('name', '')).strip().lower()
    keyword = str(rec.get('keyword', '')).strip().lower()
    decimals = rec.get('decimals', '')
    expected_digits = rec.get('expected_digits', '')
    ignore_red = rec.get('ignore_red', '')
    
    # ตรวจสอบว่าเป็นมิเตอร์อนาล็อกหรือไม่
    is_digital = 'digital' in meter_type or 'scada' in meter_type or 'digital' in name or 'scada' in keyword
    is_analog = not is_digital
    
    # ตรวจสอบปัญหา
    has_issue = False
    fix_data = {'row': idx, 'point_id': point_id}
    
    # 1. มิเตอร์อนาล็อก ต้อง decimals = 0
    if is_analog and decimals != 0:
        issues.append(f"⚠️ {point_id}: มิเตอร์อนาล็อกแต่ decimals = {decimals} (ควรเป็น 0)")
        fix_data['decimals'] = 0
        has_issue = True
    
    # 2. มิเตอร์อนาล็อก ควร ignore_red = TRUE
    if is_analog and str(ignore_red).strip().upper() not in ['TRUE', '1', 'YES', 'Y']:
        issues.append(f"⚠️ {point_id}: มิเตอร์อนาล็อกแต่ ignore_red = {ignore_red} (ควรเป็น TRUE)")
        fix_data['ignore_red'] = 'TRUE'
        has_issue = True
    
    # 3. expected_digits ควรมีค่า (แนะนำ 5-7)
    if not expected_digits or expected_digits == '' or expected_digits == '-':
        issues.append(f"ℹ️ {point_id}: ไม่มี expected_digits (แนะนำตั้งค่า 5-7)")
        # ไม่แก้ไขอัตโนมัติ - ให้ user ตั้งเอง
    
    if has_issue:
        fixes.append(fix_data)

# แสดงผลการตรวจสอบ
print("=" * 60)
print("📊 สรุปผลการตรวจสอบ")
print("=" * 60)

if not issues:
    print("✅ ไม่พบปัญหา - Config ทั้งหมดถูกต้อง!")
else:
    print(f"❌ พบปัญหา {len(issues)} รายการ:\n")
    for issue in issues:
        print(f"  {issue}")
    
    print("\n" + "=" * 60)
    print("🔧 ต้องการแก้ไขอัตโนมัติหรือไม่?")
    print("=" * 60)
    print(f"จะแก้ไข {len(fixes)} จุด:")
    for fix in fixes:
        changes = []
        if 'decimals' in fix:
            changes.append(f"decimals → 0")
        if 'ignore_red' in fix:
            changes.append(f"ignore_red → TRUE")
        print(f"  • {fix['point_id']}: {', '.join(changes)}")
    
    response = input("\nพิมพ์ 'yes' เพื่อแก้ไข หรือ Enter เพื่อข้าม: ").strip().lower()
    
    if response == 'yes':
        print("\n🔄 กำลังแก้ไข...")
        
        # หา column index
        header = ws.row_values(1)
        col_decimals = header.index('decimals') + 1 if 'decimals' in header else None
        col_ignore_red = header.index('ignore_red') + 1 if 'ignore_red' in header else None
        
        for fix in fixes:
            row = fix['row']
            if 'decimals' in fix and col_decimals:
                ws.update_cell(row, col_decimals, 0)
                print(f"  ✅ {fix['point_id']}: decimals → 0")
            
            if 'ignore_red' in fix and col_ignore_red:
                ws.update_cell(row, col_ignore_red, 'TRUE')
                print(f"  ✅ {fix['point_id']}: ignore_red → TRUE")
        
        print("\n✅ แก้ไขเสร็จสิ้น!")
    else:
        print("\n⏭️ ข้ามการแก้ไข - กรุณาแก้ไขใน Sheet เอง")

print("\n" + "=" * 60)
print("📝 คำแนะนำเพิ่มเติม:")
print("=" * 60)
print("1. ตรวจสอบ expected_digits ของแต่ละจุด (แนะนำ 5-7)")
print("2. มิเตอร์อนาล็อก: ตั้งค่า decimals=0, ignore_red=TRUE")
print("3. มิเตอร์ดิจิทัล: ตั้งค่า decimals ตามจำนวนทศนิยมจริง (0-3)")
print("=" * 60)
