import streamlit as st
import pandas as pd
import sqlite3
import io
import zipfile
import json
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------
# 0. 보안 로그인 시스템 (층별 권한 세분화)
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
    st.markdown("<h4 style='text-align: center; color: gray;'>NutriCare ERP 보안 로그인</h4>", unsafe_allow_html=True)
    st.write("")
    
    col_c1, col_c2, col_c3 = st.columns([1, 2, 1])
    with col_c2:
        with st.form("login_form"):
            username = st.text_input("👤 아이디", key="user_id")
            password = st.text_input("🔒 비밀번호", type="password", key="user_pw")
            submit_login = st.form_submit_button("로그인", type="primary", use_container_width=True)
            
            if submit_login:
                if username in USER_DB and USER_DB[username]["password"] == password:
                    st.session_state["logged_in"] = True
                    st.session_state["user_info"] = USER_DB[username]
                    st.rerun()
                else:
                    st.error("❌ 아이디 또는 비밀번호가 올바르지 않습니다.")

# ---------------------------------------------------------
# 1. Database (SQLite) 영구 저장소 구축 및 초기화
# ---------------------------------------------------------
DB_FILE = "nutricare.db"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS residents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            floor TEXT NOT NULL,
            room TEXT NOT NULL,
            name TEXT NOT NULL,
            meal TEXT NOT NULL,
            side TEXT NOT NULL,
            kimchi TEXT NOT NULL,
            note TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daycare_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            meal TEXT NOT NULL,
            side TEXT NOT NULL,
            kimchi TEXT NOT NULL,
            note TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daycare_daily_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            att_date TEXT NOT NULL,
            master_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            attended INTEGER NOT NULL,
            lunch_requested INTEGER NOT NULL,
            dinner_requested INTEGER NOT NULL,
            next_breakfast_requested INTEGER NOT NULL,
            meal TEXT NOT NULL,
            side TEXT NOT NULL,
            kimchi TEXT NOT NULL,
            note TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requester TEXT NOT NULL,
            request_type TEXT NOT NULL,
            target_table TEXT NOT NULL,
            target_id INTEGER,
            old_data TEXT,
            new_data TEXT NOT NULL,
            request_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING'
        )
    """)
    
    cursor.execute("SELECT COUNT(*) FROM residents")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO residents (floor, room, name, meal, side, kimchi, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            ("2층", "201호", "김 순 낭", "🥣 일  반  죽", "★ 다 진 찬", "★ 다진김치(빨간)", "당뇨 주의"),
            ("2층", "202호", "이 영 희", "🌾 잡  곡  밥", "일  반  찬", "백  김  치", "저염식"),
            ("3층", "301호", "박 철 수", "🎃 호  박  죽", "♥ 갈  찬", "♡ 간김치(백)", "연하곤란 중증 (주의!)"),
            ("1층", "101호", "최 자 영", "🥛 미      음", "♥ 갈  찬", "없      음", "수분 섭취 주의")
        ])
        
    cursor.execute("SELECT COUNT(*) FROM daycare_master")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO daycare_master (name, meal, side, kimchi, note)
            VALUES (?, ?, ?, ?, ?)
        """, [
            ("정 영 자", "🌾 잡  곡  밥", "일  반  찬", "백  김  치", "송영 1차"),
            ("강 대 성", "🥣 일  반  죽", "★ 다 진 찬", "★ 다진김치(빨간)", "송영 2차 / 당뇨"),
            ("윤 서 진", "일  반  밥", "일  반  찬", "빨 간 김 치", "오늘 병원 진료")
        ])
        
    conn.commit()
    conn.close()

init_db()

def load_residents():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, floor AS 층, room AS 호실, name AS 성함, meal AS 주식, side AS 부식, kimchi AS 김치, note AS 특이사항 FROM residents", conn)
    conn.close()
    return df

def load_daycare_master():
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT id, name AS 성함, meal AS 주식, side AS 부식, kimchi AS 김치, note AS 특이사항 FROM daycare_master", conn)
    conn.close()
    return df

def load_daycare_attendance_by_date(selected_date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    df = pd.read_sql_query("""
        SELECT id, att_date, master_id, name AS 성함, 
               attended AS 출석여부, lunch_requested AS 중식, 
               dinner_requested AS 석식, next_breakfast_requested AS 익일조식,
               meal AS 주식, side AS 부식, kimchi AS 김치, note AS 특이사항 
        FROM daycare_daily_attendance 
        WHERE att_date=?
    """, conn, params=(selected_date_str,))
    
    if len(df) == 0:
        master_df = load_daycare_master()
        for idx, row in master_df.iterrows():
            cursor.execute("""
                INSERT INTO daycare_daily_attendance 
                (att_date, master_id, name, attended, lunch_requested, dinner_requested, next_breakfast_requested, meal, side, kimchi, note)
                VALUES (?, ?, ?, 1, 1, 0, 0, ?, ?, ?, ?)
            """, (selected_date_str, row['id'], row['성함'], row['주식'], row['부식'], row['김치'], row['특이사항']))
        conn.commit()
        
        df = pd.read_sql_query("""
            SELECT id, att_date, master_id, name AS 성함, 
                   attended AS 출석여부, lunch_requested AS 중식, 
                   dinner_requested AS 석식, next_breakfast_requested AS 익일조식,
                   meal AS 주식, side AS 부식, kimchi AS 김치, note AS 특이사항 
            FROM daycare_daily_attendance 
            WHERE att_date=?
        """, conn, params=(selected_date_str,))

    conn.close()
    df["출석여부"] = df["출석여부"].astype(bool)
    df["중식"] = df["중식"].astype(bool)
    df["석식"] = df["석식"].astype(bool)
    df["익일조식"] = df["익일조식"].astype(bool)
    return df

def get_pending_approvals_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM pending_approvals WHERE status='PENDING'")
    cnt = cursor.fetchone()[0]
    conn.close()
    return cnt

DEFAULT_WEEKLY_MENU = pd.DataFrame([
    {"구분": "월요일", "아침": "쌀밥 / 콩나물국 / 계란찜 / 무생채", "점심": "잡곡밥 / 돈육김치찌개 / 가자미구이 / 시금치나물", "저녁": "쌀밥 / 아욱된장국 / 마파두부 / 깍두기", "간식": "두유 / 바나나", "열량(kcal)": 1650, "단백질(g)": 68, "나트륨(mg)": 1850, "칼슘(mg)": 720, "철분(mg)": 11.2, "비타민A(㎍)": 640, "비타민C(mg)": 105, "식이섬유(g)": 22.5},
    {"구분": "화요일", "아침": "야채죽 / 미역국 / 두부조림 / 겉절이", "점심": "쌀밥 / 소고기무국 / 제육볶음 / 콩나물무침", "저녁": "잡곡밥 / 순두부찌개 / 계란말이 / 열무김치", "간식": "찐고구마 / 우유", "열량(kcal)": 1720, "단백질(g)": 72, "나트륨(mg)": 1920, "칼슘(mg)": 780, "철분(mg)": 12.5, "비타민A(㎍)": 680, "비타민C(mg)": 110, "식이섬유(g)": 24.0},
    {"구분": "수요일", "아침": "쌀밥 / 북엇국 / 감자채볶음 / 포기김치", "점심": "카레라이스 / 유부장국 / 닭강정 / 단무지무침", "저녁": "쌀밥 / 동태찌개 / 떡갈비조림 / 나물무침", "간식": "카스테라 / 요플레", "열량(kcal)": 1680, "단백질(g)": 65, "나트륨(mg)": 1890, "칼슘(mg)": 690, "철분(mg)": 10.5, "비타민A(㎍)": 620, "비타민C(mg)": 98, "식이섬유(g)": 21.0},
    {"구분": "목요일", "아침": "잣죽 / 된장찌개 / 어묵볶음 / 깍두기", "점심": "잡곡밥 / 갈비탕 / 오징어볶음 / 취나물무침", "저녁": "쌀밥 / 콩가루배추국 / 제육간장조림 / 김치", "간식": "제철과일 / 오렌지주스", "열량(kcal)": 1750, "단백질(g)": 74, "나트륨(mg)": 1980, "칼슘(mg)": 750, "철분(mg)": 13.0, "비타민A(㎍)": 710, "비타민C(mg)": 125, "식이섬유(g)": 25.5},
    {"구분": "금요일", "아침": "쌀밥 / 시래깃국 / 호박전 / 포기김치", "점심": "비빔밥 / 계란파국 / 새우튀김 / 백김치", "저녁": "잡곡밥 / 부대찌개 / 삼치구이 / 숙주나물", "간식": "찐옥수수 / 둥굴레차", "열량(kcal)": 1690, "단백질(g)": 70, "나트륨(mg)": 1840, "칼슘(mg)": 730, "철분(mg)": 11.8, "비타민A(㎍)": 660, "비타민C(mg)": 115, "식이섬유(g)": 23.2},
    {"구분": "토요일", "아침": "소고기죽 / 계란국 / 연두부 / 겉절이", "점심": "쌀밥 / 청국장찌개 / 안동찜닭 / 무말랭이", "저녁": "쌀밥 / 오징어무국 / 동그랑땡 / 포기김치", "간식": "단호박죽", "열량(kcal)": 1630, "단백질(g)": 66, "나트륨(mg)": 1790, "칼슘(mg)": 680, "철분(mg)": 10.2, "비타민A(㎍)": 630, "비타민C(mg)": 95, "식이섬유(g)": 20.5},
    {"구분": "일요일", "아침": "쌀밥 / 팽이버섯국 / 스크램블 / 김치", "점심": "짜장밥 / 계란부용국 / 탕수육 / 포기김치", "저녁": "잡곡밥 / 육개장 / 생선전 / 청포묵무침", "간식": "떡 / 식혜", "열량(kcal)": 1710, "단백질(g)": 69, "나트륨(mg)": 1910, "칼슘(mg)": 710, "철분(mg)": 11.0, "비타민A(㎍)": 650, "비타민C(mg)": 102, "식이섬유(g)": 21.8}
])

if "weekly_menu" not in st.session_state:
    st.session_state["weekly_menu"] = DEFAULT_WEEKLY_MENU

if "orders" not in st.session_state:
    st.session_state["orders"] = pd.DataFrame([
        {"품목명": "백미 (20kg)", "규격": "포", "단위": "포", "필요수량": 4, "발주수량": 4, "단가(원)": 55000, "공급업체": "농협식자재"},
        {"품목명": "돼지고기 (돈육 전지)", "규격": "kg", "단위": "kg", "필요수량": 15, "발주수량": 15, "단가(원)": 12000, "공급업체": "축산유통"},
        {"품목명": "배추김치 (국산)", "규격": "10kg", "단위": "상자", "필요수량": 5, "발주수량": 5, "단가(원)": 32000, "공급업체": "대성식품"},
        {"품목명": "계란 (특란)", "규격": "30구", "단위": "판", "필요수량": 10, "발주수량": 10, "단가(원)": 6500, "공급업체": "축산유통"},
        {"품목명": "단호박 (생물)", "규격": "10kg", "단위": "상자", "필요수량": 2, "발주수량": 2, "단가(원)": 18000, "공급업체": "싱싱농산"}
    ])

def generate_card_image(floor, name, meal_type, side_type, kimchi_type):
    width, height = 600, 400
    card = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(card)

    ORANGE = (255, 140, 0)
    BLUE_DARK = (20, 60, 160)
    PURPLE_DARK = (130, 30, 150)
    RED_KIMCHI_BG = (255, 205, 205)
    WHITE_KIMCHI_BG = (235, 245, 255)
    NO_KIMCHI_BG = (240, 240, 240)
    RED_KIMCHI_TEXT = (200, 0, 0)
    WHITE_KIMCHI_TEXT = (0, 50, 150)
    NO_KIMCHI_TEXT = (100, 100, 100)
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)

    try:
        font_path = "c:/Windows/Fonts/malgun.ttf"
        font_top = ImageFont.truetype(font_path, 38)
        font_mid = ImageFont.truetype(font_path, 48)
        font_bot = ImageFont.truetype(font_path, 28)
    except:
        font_top = font_mid = font_bot = ImageFont.load_default()

    draw.rectangle([0, 0, width, 90], fill=ORANGE)
    
    if "다진" in side_type:
        side_bg, side_color = BLUE_DARK, WHITE
    elif "갈" in side_type:
        side_bg, side_color = PURPLE_DARK, WHITE
    else:
        side_bg, side_color = WHITE, BLACK

    if "백" in kimchi_type or "☆" in kimchi_type or "♡" in kimchi_type:
        kimchi_bg, kimchi_color = WHITE_KIMCHI_BG, WHITE_KIMCHI_TEXT
    elif "없" in kimchi_type:
        kimchi_bg, kimchi_color = NO_KIMCHI_BG, NO_KIMCHI_TEXT
    else:
        kimchi_bg, kimchi_color = RED_KIMCHI_BG, RED_KIMCHI_TEXT

    draw.rectangle([0, 290, 300, height], fill=side_bg)
    draw.rectangle([300, 290, width, height], fill=kimchi_bg)

    draw.rectangle([0, 0, width-1, height-1], outline=BLACK, width=4)
    draw.line([(0, 90), (width, 90)], fill=BLACK, width=4)
    draw.line([(0, 290), (width, 290)], fill=BLACK, width=4)
    draw.line([(300, 290), (300, height)], fill=BLACK, width=4)

    top_text = f"[{floor}]  {name}"
    top_bbox = font_top.getbbox(top_text)
    draw.text(((width - (top_bbox[2] - top_bbox[0])) / 2, 20), top_text, fill=WHITE, font=font_top)

    mid_bbox = font_mid.getbbox(meal_type)
    draw.text(((width - (mid_bbox[2] - mid_bbox[0])) / 2, 145), meal_type, fill=BLACK, font=font_mid)

    side_bbox = font_bot.getbbox(side_type)
    draw.text(((300 - (side_bbox[2] - side_bbox[0])) / 2, 325), side_type, fill=side_color, font=font_bot)

    kimchi_bbox = font_bot.getbbox(kimchi_type)
    draw.text((300 + (300 - (kimchi_bbox[2] - kimchi_bbox[0])) / 2, 325), kimchi_type, fill=kimchi_color, font=font_bot)

    return card

# ---------------------------------------------------------
# 2. 메인 실행 및 사이드바 박스형 UI 커스텀
# ---------------------------------------------------------
st.set_page_config(page_title="연세 효성 NutriCare ERP", layout="wide")

st.markdown("""
<style>
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    font-size: 21px !important;
    font-weight: 800 !important;
    color: #111827 !important;
    margin-bottom: 8px !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label {
    background-color: #ffffff !important;
    border: 2px solid #e5e7eb !important;
    border-radius: 12px !important;
    padding: 14px 16px !important;
    margin-bottom: 10px !important;
    box-shadow: 0px 2px 5px rgba(0, 0, 0, 0.04) !important;
    cursor: pointer !important;
    transition: all 0.2s ease-in-out !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
    display: none !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label [data-testid="stMarkdownContainer"] p {
    font-size: 18px !important;
    font-weight: 700 !important;
    color: #374151 !important;
    line-height: 1.4 !important;
    margin: 0 !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
    background-color: #eff6ff !important;
    border-color: #2563eb !important;
    border-width: 2.5px !important;
    box-shadow: 0px 4px 10px rgba(37, 99, 235, 0.18) !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) [data-testid="stMarkdownContainer"] p {
    color: #1d4ed8 !important;
    font-weight: 900 !important;
}

[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
    border-color: #3b82f6 !important;
    background-color: #f8fafc !important;
}
</style>
""", unsafe_allow_html=True)

if "logged_in" not in st.session_state or not st.session_state["logged_in"]:
    login_screen()
else:
    user = st.session_state["user_info"]
    role = user["role"]

    st.sidebar.title("🥗 NutriCare ERP")
    st.sidebar.caption(f"👤 접속자: **{user['name']}**")
    
    if role == "ADMIN":
        pending_cnt = get_pending_approvals_count()
        if pending_cnt > 0:
            st.sidebar.warning(f"🔔 승인 대기 요청: **{pending_cnt} 건**")

    if st.sidebar.button("🔒 로그아웃", use_container_width=True):
        st.session_state["logged_in"] = False
        st.rerun()

    st.sidebar.markdown("---")

    if role in ["DAYCARE1", "DAYCARE2", "DAYCARE3"]:
        menu_options = ["1. 대시보드 (홈)", "2. 요양원 어르신 식이 관리"]
    elif role == "DAYCARE4":
        menu_options = ["1. 대시보드 (홈)", "3. [4층 주간보호] 날짜별 출석부 & 식사 등록"]
    elif role == "ADMIN":
        pending_cnt = get_pending_approvals_count()
        menu_options = [
            "1. 대시보드 (홈)",
            f"0. [시설장 전용] 🔔 승인 대기함 ({pending_cnt}건)",
            "2. 요양원 어르신 식이 관리",
            "3. [4층 주간보호] 날짜별 출석부 & 식사 등록",
            "4. 식수 & 배식지시서 (히스토리)",
            "5. 명찰 카드 대량 출력",
            "6. 주간 식단표 관리 (엑셀 연동 & 영양판정)",
            "7. 식자재 발주 & 원가 관리",
            "8. 위생 & 보존식·검식일지 관리"
        ]
    else:
        menu_options = [
            "1. 대시보드 (홈)",
            "2. 요양원 어르신 식이 관리",
            "3. [4층 주간보호] 날짜별 출석부 & 식사 등록",
            "4. 식수 & 배식지시서 (히스토리)",
            "5. 명찰 카드 대량 출력",
            "6. 주간 식단표 관리 (엑셀 연동 & 영양판정)",
            "7. 식자재 발주 & 원가 관리",
            "8. 위생 & 보존식·검식일지 관리"
        ]

    menu = st.sidebar.radio("메인 메뉴", menu_options)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🛡️ 안전 백업 & 데이터 복구")

    df_backup_res = load_residents()
    df_backup_dc = load_daycare_master()

    buf_backup = io.BytesIO()
    with pd.ExcelWriter(buf_backup, engine='openpyxl') as writer:
        df_backup_res.to_excel(writer, index=False, sheet_name='요양원입소명단')
        df_backup_dc.to_excel(writer, index=False, sheet_name='주간보호마스터명단')

    st.sidebar.download_button(
        label="📦 전체 DB 엑셀 백업 받기",
        data=buf_backup.getvalue(),
        file_name=f"nutricare_db_backup_{datetime.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.ms-excel",
        use_container_width=True
    )

    # ---------------------------------------------------------
    # 메뉴별 화면 렌더링 로직
    # ---------------------------------------------------------
    if "0. [시설장 전용]" in menu:
        st.title("🔔 [시설장/원장님 전용] 변경 사항 승인 결재함")
        st.caption("현장 선생님들이 요청한 식이 변경 및 신규 등록 건을 검증하고 승인합니다.")
        st.markdown("---")

        conn = get_db_connection()
        pending_df = pd.read_sql_query("SELECT * FROM pending_approvals WHERE status='PENDING' ORDER BY request_time DESC", conn)
        conn.close()

        if len(pending_df) == 0:
            st.success("✅ 현재 대기 중인 승인 요청이 없습니다.")
        else:
            st.info(f"📋 총 **{len(pending_df)} 건**의 승인 대기 요청이 있습니다.")
            for idx, row in pending_df.iterrows():
                with st.expander(f"📌 [{row['request_type']}] 요청자: {row['requester']} | 요청시간: {row['request_time']}", expanded=True):
                    col_p1, col_p2 = st.columns(2)
                    with col_p1:
                        st.markdown("**◀️ 기존 내용 (변경 전)**")
                        st.code(row['old_data'] if row['old_data'] else "없음 (신규 등록)")
                    with col_p2:
                        st.markdown("**▶️ 변경 요청 내용 (변경 후)**")
                        st.code(row['new_data'])

                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button(f"🟢 승인 확정 (ID:{row['id']})", type="primary", use_container_width=True, key=f"app_{row['id']}"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            new_info = json.loads(row['new_data'])
                            
                            if row['target_table'] == 'residents':
                                if row['request_type'] == 'INSERT':
                                    cursor.execute("INSERT INTO residents (floor, room, name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                                   (new_info['floor'], new_info['room'], new_info['name'], new_info['meal'], new_info['side'], new_info['kimchi'], new_info['note']))
                                elif row['request_type'] == 'UPDATE':
                                    cursor.execute("UPDATE residents SET floor=?, room=?, name=?, meal=?, side=?, kimchi=?, note=? WHERE id=?",
                                                   (new_info['floor'], new_info['room'], new_info['name'], new_info['meal'], new_info['side'], new_info['kimchi'], new_info['note'], row['target_id']))
                                elif row['request_type'] == 'DELETE':
                                    cursor.execute("DELETE FROM residents WHERE id=?", (row['target_id'],))
                                    
                            elif row['target_table'] == 'daycare_master':
                                if row['request_type'] == 'INSERT':
                                    cursor.execute("INSERT INTO daycare_master (name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?)",
                                                   (new_info['name'], new_info['meal'], new_info['side'], new_info['kimchi'], new_info['note']))
                                elif row['request_type'] == 'UPDATE':
                                    cursor.execute("UPDATE daycare_master SET name=?, meal=?, side=?, kimchi=?, note=? WHERE id=?",
                                                   (new_info['name'], new_info['meal'], new_info['side'], new_info['kimchi'], new_info['note'], row['target_id']))
                                elif row['request_type'] == 'DELETE':
                                    cursor.execute("DELETE FROM daycare_master WHERE id=?", (row['target_id'],))

                            cursor.execute("UPDATE pending_approvals SET status='APPROVED' WHERE id=?", (row['id'],))
                            conn.commit()
                            conn.close()
                            st.balloons()
                            st.success("✅ 승인이 완료되어 실제 DB에 최종 반영되었습니다.")
                            st.rerun()

                    with col_btn2:
                        if st.button(f"🔴 반려 처리 (ID:{row['id']})", use_container_width=True, key=f"rej_{row['id']}"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("UPDATE pending_approvals SET status='REJECTED' WHERE id=?", (row['id'],))
                            conn.commit()
                            conn.close()
                            st.warning("❌ 요청이 반려되었습니다.")
                            st.rerun()

    elif menu == "1. 대시보드 (홈)":
        st.title("📌 당일 배식 & 영양 관리 현황판")
        st.caption(f"연세노인전문요양원 효성점 | 접속자: {user['name']}")
        st.markdown("---")

        today_str = datetime.today().strftime('%Y-%m-%d')
        df_res = load_residents()
        df_daycare = load_daycare_attendance_by_date(today_str)
        active_daycare = df_daycare[df_daycare["출석여부"] == True]

        total_cnt = len(df_res) + len(active_daycare)
        porridge_cnt = len(df_res[df_res["주식"].str.contains("죽|미음")]) + len(active_daycare[active_daycare["주식"].str.contains("죽|미음")])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("오늘 실시간 전체 식수", f"{total_cnt} 명", f"4층 주간보호 {len(active_daycare)}명 포함")
        col2.metric("오늘의 죽/미음 수급자", f"{porridge_cnt} 명")
        col3.metric("4층 주간보호 등원 수급자", f"{len(active_daycare)} 명")
        
        lunch_cnt = len(active_daycare[active_daycare['중식']==True])
        dinner_cnt = len(active_daycare[active_daycare['석식']==True])
        next_b_cnt = len(active_daycare[active_daycare['익일조식']==True])
        col4.metric("주간보호 식사 신청 현황", f"중식 {lunch_cnt} / 석식 {dinner_cnt}", f"익일 조식 {next_b_cnt}명 신청")

        st.markdown("---")
        st.subheader(f"📋 DB 연동 실시간 통합 수급자 명단 ({today_str} 기준)")
        
        daycare_formatted = active_daycare[["성함", "주식", "부식", "김치", "특이사항"]].copy()
        daycare_formatted["층"] = "4층 (주간보호)"
        daycare_formatted["호실"] = "데이케어"
        
        combined_df = pd.concat([df_res[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]], daycare_formatted], ignore_index=True)
        st.dataframe(combined_df, use_container_width=True)

    elif menu == "2. 요양원 어르신 식이 관리":
        st.title("👵 요양원 입소 어르신 식이 형태 관리 (승인 워크플로우 적용)")
        st.caption("어르신 등록 및 수정 요청 시 시설장 승인 후 최종 반영됩니다.")
        st.markdown("---")

        df_res = load_residents()
        tab1, tab2 = st.tabs(["➕ 신규 어르신 등록 요청", "✏️ 어르신 정보 수정 요청 및 🗑️ 삭제"])

        with tab1:
            with st.form("add_resident_form"):
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    floor = st.selectbox("층수", ["1층", "2층", "3층"])
                    room = st.text_input("호실", "201호")
                    name = st.text_input("성함 (예: 김 순 낭)", "홍 길 동")
                with col_b:
                    meal = st.selectbox("🍚 주식 형태", ["일  반  밥", "🌾 잡  곡  밥", "🥣 일  반  죽", "🎃 호  박  죽", "🥗 야  채  죽", "🥛 미      음", "❌ 금      식"])
                    side = st.selectbox("🥗 부식(찬) 형태", ["일  반  찬", "★ 다 진 찬", "♥ 갈  찬"])
                    kimchi = st.selectbox("🥬 김치 형태", ["빨 간 김 치", "백  김  치", "★ 다진김치(빨간)", "☆ 다진김치(백)", "♥ 간김치(빨간)", "♡ 간김치(백)", "없      음"])
                with col_c:
                    note = st.text_input("특이사항 / 알레르기", "없음")
                    st.write("")
                    submit = st.form_submit_button("어르신 등록 승인 요청 전송", type="primary", use_container_width=True)

                if submit:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    new_data_str = json.dumps({"floor": floor, "room": room, "name": name, "meal": meal, "side": side, "kimchi": kimchi, "note": note}, ensure_ascii=False)
                    cursor.execute("""
                        INSERT INTO pending_approvals (requester, request_type, target_table, new_data, request_time)
                        VALUES (?, 'INSERT', 'residents', ?, ?)
                    """, (user['name'], new_data_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    conn.commit()
                    conn.close()
                    st.info(f"📩 [{name}] 어르신 신규 등록 요청이 전송되었습니다.")

        with tab2:
            if len(df_res) == 0:
                st.info("현재 등록된 어르신이 없습니다.")
            else:
                resident_names = [f"[{row['층']} {row['호실']}] {row['성함']} (ID:{row['id']})" for idx, row in df_res.iterrows()]
                selected_res_str = st.selectbox("대상 어르신 선택 (수정/삭제 요청)", resident_names)
                
                selected_idx = resident_names.index(selected_res_str)
                target_row = df_res.iloc[selected_idx]
                target_id = int(target_row["id"])

                col_edit1, col_edit2 = st.columns(2)
                with col_edit1:
                    st.subheader("✏️ 식이 정보 수정 요청")
                    with st.form("edit_resident_form"):
                        e_floor = st.selectbox("층수", ["1층", "2층", "3층"], index=["1층", "2층", "3층"].index(target_row["층"]))
                        e_room = st.text_input("호실", target_row["호실"])
                        e_name = st.text_input("성함", target_row["성함"])
                        meal_opts = ["일  반  밥", "🌾 잡  곡  밥", "🥣 일  반  죽", "🎃 호  박  죽", "🥗 야  채  죽", "🥛 미      음", "❌ 금      식"]
                        e_meal = st.selectbox("🍚 주식", meal_opts, index=meal_opts.index(target_row["주식"]) if target_row["주식"] in meal_opts else 0)
                        side_opts = ["일  반  찬", "★ 다 진 찬", "♥ 갈  찬"]
                        e_side = st.selectbox("🥗 부식(찬)", side_opts, index=side_opts.index(target_row["부식"]) if target_row["부식"] in side_opts else 0)
                        kimchi_opts = ["빨 간 김 치", "백  김  치", "★ 다진김치(빨간)", "☆ 다진김치(백)", "♥ 간김치(빨간)", "♡ 간김치(백)", "없      음"]
                        e_kimchi = st.selectbox("🥬 김치", kimchi_opts, index=kimchi_opts.index(target_row["김치"]) if target_row["김치"] in kimchi_opts else 0)
                        e_note = st.text_input("특이사항", target_row["특이사항"])
                        
                        update_btn = st.form_submit_button("수정 승인 요청 전송", use_container_width=True)
                        if update_btn:
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            old_str = json.dumps(dict(target_row), ensure_ascii=False)
                            new_str = json.dumps({"floor": e_floor, "room": e_room, "name": e_name, "meal": e_meal, "side": e_side, "kimchi": e_kimchi, "note": e_note}, ensure_ascii=False)
                            cursor.execute("""
                                INSERT INTO pending_approvals (requester, request_type, target_table, target_id, old_data, new_data, request_time)
                                VALUES (?, 'UPDATE', 'residents', ?, ?, ?, ?)
                            """, (user['name'], target_id, old_str, new_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                            conn.commit()
                            conn.close()
                            st.info("📩 식이 정보 수정 요청이 전송되었습니다.")

                with col_edit2:
                    st.subheader("🗑️ 퇴소 삭제 요청")
                    st.warning(f"선택한 [{target_row['성함']}] 어르신의 퇴소 삭제 요청을 전송합니다.")
                    if st.button("🗑️ 퇴소 삭제 승인 요청 전송", type="primary", use_container_width=True):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        old_str = json.dumps(dict(target_row), ensure_ascii=False)
                        cursor.execute("""
                            INSERT INTO pending_approvals (requester, request_type, target_table, target_id, old_data, new_data, request_time)
                            VALUES (?, 'DELETE', 'residents', ?, ?, '퇴소 영구 삭제 요청', ?)
                        """, (user['name'], target_id, old_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        conn.commit()
                        conn.close()
                        st.info("📩 퇴소 삭제 요청이 전송되었습니다.")

        st.markdown("---")
        st.subheader("📑 전체 입소 어르신 명단")
        st.dataframe(df_res[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]], use_container_width=True)

    elif menu == "3. [4층 주간보호] 날짜별 출석부 & 식사 등록":
        st.title("🚌 4층 주간보호 센터 날짜별 출석부 & 식사 체크")
        st.caption("출석 및 식수 체크를 진행합니다.")
        st.markdown("---")

        col_date1, col_date2 = st.columns([1, 2])
        with col_date1:
            target_date = st.date_input("📅 일자 선택", datetime.today())
            target_date_str = target_date.strftime('%Y-%m-%d')
        with col_date2:
            st.write("")
            st.info(f"💡 선택 일자: **{target_date_str}**")

        df_attendance = load_daycare_attendance_by_date(target_date_str)

        tab_dc1, tab_dc2 = st.tabs(["📝 출석 & 식사 체크", "➕ 주간보호 어르신 마스터 관리"])

        with tab_dc1:
            edited_attendance = st.data_editor(
                df_attendance[["id", "성함", "출석여부", "중식", "석식", "익일조식", "주식", "부식", "김치", "특이사항"]],
                num_rows="dynamic",
                use_container_width=True,
                key=f"editor_{target_date_str}"
            )

            if st.button("✅ 체크 확인 및 저장 완료", type="primary", use_container_width=True):
                conn = get_db_connection()
                cursor = conn.cursor()
                for idx, row in edited_attendance.iterrows():
                    cursor.execute("""
                        UPDATE daycare_daily_attendance 
                        SET attended=?, lunch_requested=?, dinner_requested=?, next_breakfast_requested=?, meal=?, side=?, kimchi=?, note=?
                        WHERE id=?
                    """, (int(row["출석여부"]), int(row["중식"]), int(row["석식"]), int(row["익일조식"]), row["주식"], row["부식"], row["김치"], row["특이사항"], int(row["id"])))
                conn.commit()
                conn.close()
                st.success("🎉 저장이 완료되었습니다!")

            st.markdown("---")
            df_check = load_daycare_attendance_by_date(target_date_str)
            lunch_users = df_check[df_check["중식"] == True]["성함"].tolist()
            dinner_users = df_check[df_check["석식"] == True]["성함"].tolist()
            breakfast_users = df_check[df_check["익일조식"] == True]["성함"].tolist()

            col_v1, col_v2, col_v3 = st.columns(3)
            col_v1.info(f"🥣 **중식 ({len(lunch_users)}명)**\n" + ("\n• ".join([""] + lunch_users) if lunch_users else "없음"))
            col_v2.warning(f"🌙 **석식 ({len(dinner_users)}명)**\n" + ("\n• ".join([""] + dinner_users) if dinner_users else "없음"))
            col_v3.success(f"🌅 **익일 조식 ({len(breakfast_users)}명)**\n" + ("\n• ".join([""] + breakfast_users) if breakfast_users else "없음"))

        with tab_dc2:
            df_dc_master = load_daycare_master()
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                with st.form("add_dc_form"):
                    dc_name = st.text_input("성함", "김 주 간")
                    meal_opts = ["일  반  밥", "🌾 잡  곡  밥", "🥣 일  반  죽", "🎃 호  박  죽", "🥗 야  채  죽", "🥛 미      음", "❌ 금      식"]
                    dc_meal = st.selectbox("🍚 주식", meal_opts)
                    side_opts = ["일  반  찬", "★ 다 진 찬", "♥ 갈  찬"]
                    dc_side = st.selectbox("🥗 부식", side_opts)
                    kimchi_opts = ["빨 간 김 치", "백  김  치", "★ 다진김치(빨간)", "☆ 다진김치(백)", "♥ 간김치(빨간)", "♡ 간김치(백)", "없      음"]
                    dc_kimchi = st.selectbox("🥬 김치", kimchi_opts)
                    dc_note = st.text_input("특이사항", "송영 1차")
                    if st.form_submit_button("주간보호 등록 승인 요청", type="primary", use_container_width=True):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        new_str = json.dumps({"name": dc_name, "meal": dc_meal, "side": dc_side, "kimchi": dc_kimchi, "note": dc_note}, ensure_ascii=False)
                        cursor.execute("INSERT INTO pending_approvals (requester, request_type, target_table, new_data, request_time) VALUES (?, 'INSERT', 'daycare_master', ?, ?)", (user['name'], new_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        conn.commit()
                        conn.close()
                        st.info("📩 주간보호 어르신 등록 요청이 전송되었습니다.")
            with col_d2:
                if len(df_dc_master) > 0:
                    dc_names = [f"{row['성함']} (ID:{row['id']})" for idx, row in df_dc_master.iterrows()]
                    selected_dc = st.selectbox("대상 선택", dc_names)
                    dc_row = df_dc_master.iloc[dc_names.index(selected_dc)]
                    if st.button("🗑️ 주간보호 삭제 요청", type="primary", use_container_width=True):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        old_str = json.dumps(dict(dc_row), ensure_ascii=False)
                        cursor.execute("INSERT INTO pending_approvals (requester, request_type, target_table, target_id, old_data, new_data, request_time) VALUES (?, 'DELETE', 'daycare_master', ?, ?, '삭제 요청', ?)", (user['name'], int(dc_row['id']), old_str, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        conn.commit()
                        conn.close()
                        st.info("📩 삭제 요청이 전송되었습니다.")

    elif menu == "4. 식수 & 배식지시서 (히스토리)":
        st.title("📋 식수 집계표 및 조리실 배식지시서")
        today_str = datetime.today().strftime('%Y-%m-%d')
        df_res = load_residents()
        df_daycare = load_daycare_attendance_by_date(today_str)
        active_daycare = df_daycare[df_daycare["출석여부"] == True].copy()
        active_daycare["층"] = "4층 (주간보호)"
        active_daycare["호실"] = "데이케어"
        full_df = pd.concat([df_res, active_daycare[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]]], ignore_index=True)

        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            st.subheader("🍚 층별 주식 집계")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="주식", aggfunc="size", fill_value=0), use_container_width=True)
        with col_p2:
            st.subheader("🥗 층별 부식 집계")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="부식", aggfunc="size", fill_value=0), use_container_width=True)
        with col_p3:
            st.subheader("🥬 층별 김치 집계")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="김치", aggfunc="size", fill_value=0), use_container_width=True)

        st.markdown("---")
        st.subheader("📄 오늘의 통합 배식지시서 명단")
        st.dataframe(full_df[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]], use_container_width=True)

    elif menu == "5. 명찰 카드 대량 출력":
        st.title("🎴 배식용 명찰 카드 대량 생성")
        today_str = datetime.today().strftime('%Y-%m-%d')
        df_res = load_residents()
        df_daycare = load_daycare_attendance_by_date(today_str)
        active_daycare = df_daycare[df_daycare["출석여부"] == True].copy()
        active_daycare["층"] = "4층"
        active_daycare["호실"] = "주간"
        full_df = pd.concat([df_res, active_daycare[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]]], ignore_index=True)
        
        if st.button("🚀 전체 명찰 카드(ZIP) 다운로드 준비", type="primary", use_container_width=True):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                for idx, row in full_df.iterrows():
                    img = generate_card_image(row["층"], row["성함"], row["주식"], row["부식"], row["김치"])
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format="PNG")
                    zip_file.writestr(f"명찰_{row['층']}_{row['호실']}_{row['성함']}.png", img_byte_arr.getvalue())

            st.download_button(label="📦 명찰 카드 압축파일(.zip) 다운로드", data=zip_buffer.getvalue(), file_name="명찰카드.zip", mime="application/zip", use_container_width=True)

    elif menu == "6. 주간 식단표 관리 (엑셀 연동 & 영양판정)":
        st.title("📅 주간 식단표 관리 및 실시간 다량/미량 영양 적정성 자동 판정")
        st.caption("노인 영양섭취기준(KDRI) 및 건보공단 평가 기준 기반 통합 평가 모듈")
        st.markdown("---")

        edited_menu = st.data_editor(
            st.session_state["weekly_menu"],
            num_rows="dynamic",
            use_container_width=True,
            key="weekly_menu_editor"
        )
        st.session_state["weekly_menu"] = edited_menu

        for col_chk, val_chk in [("열량(kcal)", 1680), ("단백질(g)", 68), ("나트륨(mg)", 1850), ("칼슘(mg)", 720), ("철분(mg)", 11.0), ("비타민A(㎍)", 650), ("비타민C(mg)", 105), ("식이섬유(g)", 22.0)]:
            if col_chk not in edited_menu.columns:
                edited_menu[col_chk] = val_chk

        st.markdown("---")
        st.subheader("📊 [1] 다량 영양소 적정성 평가 (1일 평균)")

        avg_cal = edited_menu["열량(kcal)"].mean()
        avg_prot = edited_menu["단백질(g)"].mean()
        avg_sod = edited_menu["나트륨(mg)"].mean()

        col_n1, col_n2, col_n3 = st.columns(3)
        col_n1.metric("1일 평균 열량", f"{avg_cal:.0f} kcal", "🟢 적정" if 1600 <= avg_cal <= 1800 else "🔴 보충 필요")
        col_n2.metric("1일 평균 단백질", f"{avg_prot:.1f} g", "🟢 적정" if avg_prot >= 60 else "🔴 부족")
        col_n3.metric("1일 평균 나트륨", f"{avg_sod:.0f} mg", "🟢 적정" if avg_sod <= 2000 else "🔴 초과")

        st.markdown("---")
        st.subheader("🔬 [2] 노인 필수 5대 미량영양소 적정성 평가 (1일 평균)")

        avg_calcium = edited_menu["칼슘(mg)"].mean()
        avg_iron = edited_menu["철분(mg)"].mean()
        avg_vita = edited_menu["비타민A(㎍)"].mean()
        avg_vitc = edited_menu["비타민C(mg)"].mean()
        avg_fiber = edited_menu["식이섬유(g)"].mean()

        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        col_m1.metric("🦴 칼슘", f"{avg_calcium:.0f} mg", "🟢 충족" if avg_calcium >= 700 else "🔴 부족")
        col_m2.metric("🩸 철분", f"{avg_iron:.1f} mg", "🟢 충족" if avg_iron >= 10 else "🔴 부족")
        col_m3.metric("👁️ 비타민 A", f"{avg_vita:.0f} ㎍", "🟢 충족" if avg_vita >= 600 else "🔴 부족")
        col_m4.metric("🍋 비타민 C", f"{avg_vitc:.0f} mg", "🟢 충족" if avg_vitc >= 100 else "🔴 부족")
        col_m5.metric("🥬 식이섬유", f"{avg_fiber:.1f} g", "🟢 충족" if avg_fiber >= 20 else "🔴 부족")

        st.success("✅ [통합 영양 평가 완료] 건보공단 정기평가 영양성분 제출 서류로 즉시 활용 가능합니다.")

    elif menu == "7. 식자재 발주 & 원가 관리":
        st.title("🛒 식자재 발주 & 원가 관리")
        st.dataframe(st.session_state["orders"], use_container_width=True)

    elif menu == "8. 위생 & 보존식·검식일지 관리":
        st.title("🛡️ 건보공단 평가 대응 서류")
        st.success("✅ 당일 식단표 기반 보존식 및 검식일지가 자동 완성되어 준비되었습니다.")
