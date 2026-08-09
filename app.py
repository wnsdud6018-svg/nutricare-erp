import streamlit as st
import pandas as pd
import sqlite3
import io
import zipfile
import json
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------
# 0. 보안 로그인 시스템 (관리자/일반 계정 권한 분리)
# ---------------------------------------------------------
USER_DB = {
    "daycare1": {"name": "1층 담당 선생님", "password": "1003", "role": "DAYCARE1"},
    "daycare2": {"name": "2층 담당 선생님", "password": "1003", "role": "DAYCARE2"},
    "daycare3": {"name": "3층 담당 선생님", "password": "1003", "role": "DAYCARE3"},
    "daycare4": {"name": "4층 주간보호 센터", "password": "1003", "role": "DAYCARE4"},
    "nutrition": {"name": "통합 영양사님", "password": "7777", "role": "ADMIN"},
    "admin": {"name": "시설장 (원장님)", "password": "7777", "role": "ADMIN"}
}

def login_screen():
    st.markdown("<h2 style='text-align: center;'>🏥 연세노인전문요양원 효성점</h2>", unsafe_allow_html=True)
    with st.form("login_form"):
        username = st.text_input("아이디", key="user_id")
        password = st.text_input("비밀번호", type="password", key="user_pw")
        if st.form_submit_button("로그인"):
            if username in USER_DB and USER_DB[username]["password"] == password:
                st.session_state["logged_in"] = True
                st.session_state["user_info"] = USER_DB[username]
                st.rerun()
            else:
                st.error("❌ 아이디/비밀번호 불일치")

# ---------------------------------------------------------
# 1. Database 및 공통 함수
# ---------------------------------------------------------
DB_FILE = "nutricare.db"
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# 초기 데이터 로딩
if "weekly_menu" not in st.session_state:
    st.session_state["weekly_menu"] = pd.DataFrame([
        {"구분": "월요일", "열량(kcal)": 1650, "단백질(g)": 68, "나트륨(mg)": 1850, "칼슘(mg)": 720, "철분(mg)": 11.2, "비타민A(㎍)": 640, "비타민C(mg)": 105, "식이섬유(g)": 22.5}
    ])

# ---------------------------------------------------------
# 2. 메인 페이지 로직
# ---------------------------------------------------------
st.set_page_config(layout="wide")

if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
    login_screen()
else:
    user = st.session_state["user_info"]
    role = user["role"]
    
    st.sidebar.title("🥗 NutriCare ERP")
    st.sidebar.write(f"접속자: **{user['name']}**")
    
    # 메뉴 구성
    if role == "ADMIN":
        menu = st.sidebar.radio("메인 메뉴", [
            "1. 대시보드", "0. 🔔 승인 대기함", "2. 요양원 식이관리", 
            "3. [4층] 주간보호 출석부", "6. 식단표 & 영양판정"
        ])
    elif role == "DAYCARE4":
        menu = st.sidebar.radio("메인 메뉴", ["1. 대시보드", "3. [4층] 주간보호 출석부"])
    else:
        menu = st.sidebar.radio("메인 메뉴", ["1. 대시보드", "2. 요양원 식이관리"])

    # 화면 분기 처리
    if menu == "0. 🔔 승인 대기함":
        st.title("🔔 승인 결재함")
        conn = get_db_connection()
        pending = pd.read_sql_query("SELECT * FROM pending_approvals WHERE status='PENDING'", conn)
        conn.close()
        st.dataframe(pending)
        
    elif menu == "1. 대시보드":
        st.title("📌 대시보드")
        st.write("요양원 운영 현황입니다.")
        
    elif menu == "2. 요양원 식이관리":
        st.title("👵 어르신 식이 관리")
        st.write("입소 어르신 명단 및 식이 수정 페이지입니다.")
        # ... 여기에 어르신 등록/수정 코드 ...

    elif menu == "3. [4층] 주간보호 출석부":
        st.title("🚌 4층 주간보호 출석부")
        # ... 여기에 주간보호 로직 ...

    elif menu == "6. 식단표 & 영양판정":
        st.title("📅 식단 영양 판정")
        edited = st.data_editor(st.session_state["weekly_menu"])
        st.session_state["weekly_menu"] = edited
        st.success("영양소 자동 판정 완료")
        
    if st.sidebar.button("로그아웃"):
        st.session_state["logged_in"] = False
        st.rerun()
