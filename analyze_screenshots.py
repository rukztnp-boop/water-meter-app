#!/usr/bin/env python3
"""
🔍 Analyze error screenshots to identify issues
"""
import os
import sys

def main():
    folder = "./error หลังอัพเดท 23.26"
    
    if not os.path.exists(folder):
        print(f"❌ Folder not found: {folder}")
        return
    
    files = sorted([f for f in os.listdir(folder) if f.endswith('.png')])
    
    print(f"📸 Found {len(files)} screenshots in: {folder}")
    print("="*70)
    
    for i, filename in enumerate(files, 1):
        filepath = os.path.join(folder, filename)
        size = os.path.getsize(filepath)
        
        print(f"{i}. {filename}")
        print(f"   Size: {size:,} bytes ({size/1024:.1f} KB)")
        print()
    
    print("="*70)
    print("\n💡 กรุณาอธิบายว่าแต่ละ screenshot แสดง error อะไร")
    print("   เช่น: meter ID ไหน, ค่าที่อ่านได้เท่าไร, ค่าที่ถูกต้องคือเท่าไร")
    print("\n   หรือ ถ้าเป็น screenshot ที่มี error message ให้บอกว่าเป็น error อะไร")

if __name__ == "__main__":
    main()
