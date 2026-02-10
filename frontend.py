import streamlit as st
import requests
from datetime import datetime

# --- CONFIGURATION ---
# ⚠️ ถ้าใช้คนละเครื่อง ต้องเปลี่ยน localhost เป็น IP เครื่อง Server (เช่น 192.168.1.116)
API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Smart Meter System", page_icon="💧", layout="centered")

# --- CSS ตกแต่ง ---
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

# --- SIDEBAR: เลือกโหมด ---
mode = st.sidebar.radio("🔧 เลือกโหมดการทำงาน", ["📝 พนักงานจดมิเตอร์", "👮‍♂️ Admin Approval"])

# ==========================================
# 📝 MODE 1: USER (จดมิเตอร์)
# ==========================================
if mode == "📝 พนักงานจดมิเตอร์":
    st.title("📝 ระบบจดมิเตอร์ (User)")
    
    # Initialize Session State
    if 'confirm_mode' not in st.session_state: st.session_state.confirm_mode = False
    if 'warning_msg' not in st.session_state: st.session_state.warning_msg = ""
    if 'last_manual_val' not in st.session_state: st.session_state.last_manual_val = 0.0

    # 1. ดึงข้อมูลรายชื่อมิเตอร์
    @st.cache_data(ttl=60)
    def fetch_meters():
        try:
            res = requests.get(f"{API_URL}/meters")
            if res.status_code == 200:
                return res.json().get("data", [])
        except Exception as e:
            st.error(f"❌ เชื่อมต่อ Server ไม่ได้: {e}")
        return []

    all_meters = fetch_meters()

    if not all_meters:
        st.warning("⚠️ ไม่พบข้อมูลมิเตอร์ (กรุณารัน main.py ก่อน)")
        st.stop()

    # 2. ตัวเลือกหมวดหมู่ (น้ำ/ไฟ)
    col_type, col_insp = st.columns(2)
    with col_type:
        cat_select = st.radio("ประเภทมิเตอร์", ["💧 ประปา (Water)", "⚡️ ไฟฟ้า (Electric)"], horizontal=True)
    with col_insp:
        inspector = st.text_input("ชื่อผู้ตรวจ", "Admin")

    # กรองรายการตามประเภท
    keyword = "น้ำ" if "ประปา" in cat_select else "ไฟ"
    filtered_meters = []
    
    for m in all_meters:
        # เช็คจาก type หรือ name หรือ category
        m_type = str(m.get('type', '')).lower() + str(m.get('name', '')).lower()
        
        if "ประปา" in cat_select:
            if any(x in m_type for x in ['น้ำ', 'water', 'ประปา']): 
                filtered_meters.append(m)
        else:
            if any(x in m_type for x in ['ไฟ', 'electric', 'scada']): 
                filtered_meters.append(m)

    if not filtered_meters:
        st.info(f"ไม่พบมิเตอร์ประเภท '{cat_select}'")
        st.stop()

    # สร้าง Dictionary สำหรับ Dropdown
    option_map = {}
    for m in filtered_meters:
        # แสดงชื่อ + รหัส + คอลัมน์รายงาน
        label = f"{m.get('point_id')} : {m.get('name')}"
        option_map[label] = m


    # 3. ฟอร์มกรอกข้อมูล
    st.write("---")
    c1, c2, c3 = st.columns([2, 1, 1])

    with c1:
        selected_label = st.selectbox("📍 เลือกจุดตรวจ", list(option_map.keys()))
        meter_data = option_map[selected_label]
        point_id = meter_data.get('point_id')
        report_col = meter_data.get('report_col', '-')
        # แสดงข้อมูล Report Column ให้ User เห็น
        st.markdown(f"💾 บันทึกลงคอลัมน์: <span class='report-badge'>{report_col}</span>", unsafe_allow_html=True)

    with c2:
        manual_val = st.number_input("👁️ ค่าจริง", min_value=0.0, step=0.1, format="%.2f")

    with c3:
        target_date = st.date_input("📅 วันที่บันทึก", value=datetime.today())

    # 4. รูปภาพ (ถ่าย/อัปโหลด)
    tab_cam, tab_up = st.tabs(["📷 ถ่ายรูป", "📂 อัปโหลด"])
    img_file = None
    
    with tab_cam:
        cam_pic = st.camera_input("ถ่ายภาพมิเตอร์")
        if cam_pic: img_file = cam_pic
        
    with tab_up:
        up_pic = st.file_uploader("เลือกรูปภาพ", type=['jpg', 'png', 'jpeg'])
        if up_pic: img_file = up_pic

    # 5. ปุ่มส่งข้อมูล
    st.write("---")

    # [Case A] โหมดปกติ (ส่งตรวจ)
    if not st.session_state.confirm_mode:
        if st.button("🚀 ตรวจสอบและบันทึก", type="primary"):
            if img_file and point_id:
                with st.spinner("🤖 AI กำลังประมวลผล..."):
                    try:
                        files = {"file": img_file.getvalue()}
                        data = {
                            "point_id": point_id,
                            "inspector": inspector,
                            "meter_type": "Water" if "ประปา" in cat_select else "Electric",
                            "manual_value": manual_val,
                            "confirm_mismatch": False,
                            "target_date": str(target_date) if target_date else ""
                        }
                        response = requests.post(f"{API_URL}/scan", data=data, files=files)
                        res = response.json()

                        if res['status'] == 'SUCCESS':
                            st.balloons()
                            st.success(f"✅ บันทึกสำเร็จ! (Status: {res['data']['status']})")
                            st.json(res['data'])
                        elif res['status'] == 'WARNING':
                            st.session_state.confirm_mode = True
                            st.session_state.warning_msg = res['message']
                            st.session_state.last_manual_val = manual_val
                            st.rerun()
                        else:
                            st.error(f"❌ Error: {res.get('message')}")
                    except Exception as e:
                        st.error(f"Connect Error: {e}")
            else:
                st.warning("⚠️ กรุณาถ่ายรูปและเลือกจุดตรวจ")

    # [Case B] โหมดเตือน (ค่าไม่ตรง)
    else:
        st.markdown(f"""
        <div class="status-box status-warning">
            <h4>⚠️ แจ้งเตือน: {st.session_state.warning_msg}</h4>
        </div>
        """, unsafe_allow_html=True)
        
        st.info(f"คุณยืนยันที่จะใช้ค่า **{st.session_state.last_manual_val}** หรือไม่?")
        
        col_conf1, col_conf2 = st.columns(2)
        
        if col_conf1.button("✅ ยืนยัน (ส่งให้ Admin)"):
            if img_file:
                with st.spinner("กำลังส่งข้อมูล..."):
                    try:
                        files = {"file": img_file.getvalue()}
                        data = {
                            "point_id": point_id,
                            "inspector": inspector,
                            "meter_type": "Water" if "ประปา" in cat_select else "Electric",
                            "manual_value": st.session_state.last_manual_val,
                            "confirm_mismatch": True,
                            "target_date": str(target_date) if target_date else ""
                        }
                        requests.post(f"{API_URL}/scan", data=data, files=files)
                        st.success("✅ ส่งเรื่องแล้ว (ข้อมูลถูก Flag รอตรวจสอบ)")
                        st.session_state.confirm_mode = False
                        st.rerun()
                    except:
                        st.error("Error sending confirmation.")
            else:
                st.error("⚠️ กรุณาถ่ายรูปใหม่เพื่อยืนยัน")

        if col_conf2.button("❌ ยกเลิก / แก้ไข"):
            st.session_state.confirm_mode = False
            st.rerun()


# ==========================================
# 👮‍♂️ MODE 2: ADMIN (อนุมัติผล)
# ==========================================
elif mode == "👮‍♂️ Admin Approval":
    st.title("👮‍♂️ Admin Dashboard")
    st.caption("รายการที่ค่าไม่ตรงกัน (Flagged) รอการอนุมัติเพื่อลงไฟล์จริง")
    
    if st.button("🔄 รีเฟรชรายการ"):
        st.rerun()

    try:
        res = requests.get(f"{API_URL}/admin/pending")
        pending_data = res.json().get("data", [])
    except:
        st.error("❌ เชื่อมต่อ Server ไม่ได้")
        pending_data = []

    if not pending_data:
        st.success("✅ ไม่มียอดค้างตรวจสอบ (All Clear)")
    else:
        for i, item in enumerate(pending_data):
            with st.container():
                st.markdown("---")
                c_info, c_val, c_act = st.columns([1.5, 1.5, 1])
                
                with c_info:
                    st.subheader(f"🚩 {item.get('point_id')}")
                    st.write(f"👤 {item.get('inspector')}")
                    st.caption(f"🕒 {item.get('timestamp')}")
                
                with c_val:
                    st.write("**เลือกค่าที่ถูกต้อง:**")
                    # ดึงค่า Manual และ AI มาแสดงให้เลือก
                    m_val = float(item.get('Manual_Value') or 0)
                    a_val = float(item.get('AI_Value') or 0)
                    
                    choice = st.radio(
                        "Values:",
                        [m_val, a_val],
                        key=f"rad_{i}",
                        format_func=lambda x: f"{x} ({'คน' if x==m_val else 'AI'})"
                    )
                
                with c_act:
                    st.write("")
                    st.write("")
                    if st.button("✅ อนุมัติ", key=f"btn_{i}", type="primary"):
                        payload = {
                            "row_id": item['row_id'],
                            "point_id": str(item['point_id']),
                            "final_value": choice,
                            "inspector": str(item['inspector'])
                        }
                        # ส่งไป Approve
                        try:
                            res_app = requests.post(f"{API_URL}/admin/approve", json=payload).json()
                            if res_app['status'] == 'SUCCESS':
                                st.success("Approved & Exported!")
                                st.rerun()
                            else:
                                st.error(f"Failed: {res_app.get('message')}")
                        except Exception as e:
                            st.error(f"Error: {e}")