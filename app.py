import streamlit as st
import pandas as pd
import sqlite3
import io
import zipfile
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont

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
    
    # 1) 요양원 입소 어르신 테이블
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
    
    # 2) 4층 주간보호 어르신 마스터 테이블
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

    # 3) 4층 주간보호 날짜별 출석/식사(중식/석식/익일조식) 테이블
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
    
    # 4) 건보공단 대비 일자별 배식 히스토리 스냅샷 테이블
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_meal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            floor TEXT NOT NULL,
            room TEXT NOT NULL,
            name TEXT NOT NULL,
            meal TEXT NOT NULL,
            side TEXT NOT NULL,
            kimchi TEXT NOT NULL,
            note TEXT
        )
    """)
    
    # 샘플 데이터 초기 주입
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

# --- 기본 세션 데이터 (식단표 & 발주서) ---
if "weekly_menu" not in st.session_state:
    st.session_state["weekly_menu"] = pd.DataFrame([
        {"구분": "월요일", "아침": "쌀밥 / 콩나물국 / 계란찜 / 무생채", "점심": "잡곡밥 / 돈육김치찌개 / 가자미구이 / 시금치나물", "저녁": "쌀밥 / 아욱된장국 / 마파두부 / 깍두기", "간식": "두유 / 바나나"},
        {"구분": "화요일", "아침": "야채죽 / 미역국 / 두부조림 / 겉절이", "점심": "쌀밥 / 소고기무국 / 제육볶음 / 콩나물무침", "저녁": "잡곡밥 / 순두부찌개 / 계란말이 / 열무김치", "간식": "찐고구마 / 우유"},
        {"구분": "수요일", "아침": "쌀밥 / 북엇국 / 감자채볶음 / 포기김치", "점심": "카레라이스 / 유부장국 / 닭강정 / 단무지무침", "저녁": "쌀밥 / 동태찌개 / 떡갈비조림 / 나물무침", "간식": "카스테라 / 요플레"},
        {"구분": "목요일", "아침": "잣죽 / 된장찌개 / 어묵볶음 / 깍두기", "점심": "잡곡밥 / 갈비탕 / 오징어볶음 / 취나물무침", "저녁": "쌀밥 / 콩가루배추국 / 제육간장조림 / 김치", "간식": "제철과일 / 오렌지주스"},
        {"구분": "금요일", "아침": "쌀밥 / 시래깃국 / 호박전 / 포기김치", "점심": "비빔밥 / 계란파국 / 새우튀김 / 백김치", "저녁": "잡곡밥 / 부대찌개 / 삼치구이 / 숙주나물", "간식": "찐옥수수 / 둥굴레차"},
        {"구분": "토요일", "아침": "소고기죽 / 계란국 / 연두부 / 겉절이", "점심": "쌀밥 / 청국장찌개 / 안동찜닭 / 무말랭이", "저녁": "쌀밥 / 오징어무국 / 동그랑땡 / 포기김치", "간식": "단호박죽"},
        {"구분": "일요일", "아침": "쌀밥 / 팽이버섯국 / 스크램블 / 김치", "점심": "짜장밥 / 계란부용국 / 탕수육 / 포기김치", "저녁": "잡곡밥 / 육개장 / 생선전 / 청포묵무침", "간식": "떡 / 식혜"}
    ])

if "orders" not in st.session_state:
    st.session_state["orders"] = pd.DataFrame([
        {"품목명": "백미 (20kg)", "규격": "포", "단위": "포", "필요수량": 4, "발주수량": 4, "단가(원)": 55000, "공급업체": "농협식자재"},
        {"품목명": "돼지고기 (돈육 전지)", "규격": "kg", "단위": "kg", "필요수량": 15, "발주수량": 15, "단가(원)": 12000, "공급업체": "축산유통"},
        {"품목명": "배추김치 (국산)", "규격": "10kg", "단위": "상자", "필요수량": 5, "발주수량": 5, "단가(원)": 32000, "공급업체": "대성식품"},
        {"품목명": "계란 (특란)", "규격": "30구", "단위": "판", "필요수량": 10, "발주수량": 10, "단가(원)": 6500, "공급업체": "축산유통"},
        {"품목명": "단호박 (생물)", "규격": "10kg", "단위": "상자", "필요수량": 2, "발주수량": 2, "단가(원)": 18000, "공급업체": "싱싱농산"}
    ])

def auto_recalculate_ingredients_and_cost():
    df_res = load_residents()
    today_str = datetime.today().strftime('%Y-%m-%d')
    df_daycare = load_daycare_attendance_by_date(today_str)
    active_dc = df_daycare[df_daycare["출석여부"] == True]
    total_residents = len(df_res) + len(active_dc)
    
    if total_residents == 0:
        total_residents = 1
        
    menu_df = st.session_state["weekly_menu"]
    all_menu_text = " ".join(menu_df["아침"].fillna('') + " " + menu_df["점심"].fillna('') + " " + menu_df["저녁"].fillna(''))
    
    rice_bags = max(2, int(total_residents * 0.08))
    pork_kg = max(5, int(total_residents * 0.3)) if "돼지" in all_menu_text or "제육" in all_menu_text or "돈육" in all_menu_text else 8
    kimchi_box = max(2, int(total_residents * 0.1))
    egg_box = max(4, int(total_residents * 0.2)) if "계란" in all_menu_text or "스크램블" in all_menu_text else 3
    pumpkin_box = max(1, int(total_residents * 0.05)) if "호박" in all_menu_text else 1

    st.session_state["orders"] = pd.DataFrame([
        {"품목명": "백미 (20kg)", "규격": "포", "단위": "포", "필요수량": rice_bags, "발주수량": rice_bags, "단가(원)": 55000, "공급업체": "농협식자재"},
        {"품목명": "돼지고기 (돈육 전지)", "규격": "kg", "단위": "kg", "필요수량": pork_kg, "발주수량": pork_kg, "단가(원)": 12000, "공급업체": "축산유통"},
        {"품목명": "배추김치 (국산)", "규격": "10kg", "단위": "상자", "필요수량": kimchi_box, "발주수량": kimchi_box, "단가(원)": 32000, "공급업체": "대성식품"},
        {"품목명": "계란 (특란)", "규격": "30구", "단위": "판", "필요수량": egg_box, "발주수량": egg_box, "단가(원)": 6500, "공급업체": "축산유통"},
        {"품목명": "단호박 (생물)", "규격": "10kg", "단위": "상자", "필요수량": pumpkin_box, "발주수량": pumpkin_box, "단가(원)": 18000, "공급업체": "싱싱농산"}
    ])

# ---------------------------------------------------------
# 2. 명찰 카드 이미지 생성 엔진
# ---------------------------------------------------------
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
        side_bg = BLUE_DARK
        side_color = WHITE
    elif "갈" in side_type:
        side_bg = PURPLE_DARK
        side_color = WHITE
    else:
        side_bg = WHITE
        side_color = BLACK

    if "백" in kimchi_type or "☆" in kimchi_type or "♡" in kimchi_type:
        kimchi_bg = WHITE_KIMCHI_BG
        kimchi_color = WHITE_KIMCHI_TEXT
    elif "없" in kimchi_type:
        kimchi_bg = NO_KIMCHI_BG
        kimchi_color = NO_KIMCHI_TEXT
    else:
        kimchi_bg = RED_KIMCHI_BG
        kimchi_color = RED_KIMCHI_TEXT

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
# 3. 레이아웃 & 사이드바
# ---------------------------------------------------------
st.set_page_config(page_title="요양원 영양사 통합 ERP", layout="wide")

st.sidebar.title("🥗 NutriCare ERP")
st.sidebar.caption("💾 SQLite DB 영구 보존 엔진 가동 중")
st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "메인 메뉴",
    [
        "1. 대시보드 (홈)",
        "2. 요양원 어르신 식이 관리",
        "3. [4층 주간보호] 날짜별 출석부 & 식사 등록",
        "4. 식수 & 배식지시서 (히스토리)",
        "5. 명찰 카드 대량 출력",
        "6. 주간 식단표 관리 (엑셀 연동)",
        "7. 식자재 발주 & 원가 관리",
        "8. 위생 & 보존식·검식일지 관리"
    ]
)

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

uploaded_file = st.sidebar.file_uploader("📂 백업 엑셀로 DB 복원하기", type=["xlsx"])
if uploaded_file is not None:
    if st.sidebar.button("🔄 이 엑셀 파일로 DB 덮어쓰기 복원", type="primary", use_container_width=True):
        try:
            excel_res = pd.read_excel(uploaded_file, sheet_name='요양원입소명단')
            excel_dc = pd.read_excel(uploaded_file, sheet_name='주간보호마스터명단')
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM residents")
            cursor.execute("DELETE FROM daycare_master")
            
            for idx, row in excel_res.iterrows():
                cursor.execute("INSERT INTO residents (floor, room, name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (row['층'], row['호실'], row['성함'], row['주식'], row['부식'], row['김치'], row['특이사항']))
            
            for idx, row in excel_dc.iterrows():
                cursor.execute("INSERT INTO daycare_master (name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?)",
                               (row['성함'], row['주식'], row['부식'], row['김치'], row['특이사항']))
            
            conn.commit()
            conn.close()
            st.sidebar.success("🎉 DB가 백업 엑셀 내용으로 완벽 복원되었습니다!")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"복원 실패: {e}")

# ---------------------------------------------------------
# [메뉴 1] 대시보드
# ---------------------------------------------------------
if menu == "1. 대시보드 (홈)":
    st.title("📌 당일 배식 & 영양 관리 현황판")
    st.caption("오늘의 식수 현황과 핵심 업무를 한눈에 확인합니다.")
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

# ---------------------------------------------------------
# [메뉴 2] 요양원 어르신 식이 관리
# ---------------------------------------------------------
elif menu == "2. 요양원 어르신 식이 관리":
    st.title("👵 요양원 입소 어르신 식이 형태 관리 (DB 저장)")
    st.caption("어르신 신규 등록, 식이 정보 수정, 퇴소 어르신 영구 삭제를 진행합니다.")
    st.markdown("---")

    df_res = load_residents()
    tab1, tab2 = st.tabs(["➕ 신규 어르신 등록", "✏️ 어르신 정보 수정 및 🗑️ 삭제"])

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
                st.write("")
                submit = st.form_submit_button("어르신 등록하기 (DB 저장)", type="primary", use_container_width=True)

            if submit:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("INSERT INTO residents (floor, room, name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                               (floor, room, name, meal, side, kimchi, note))
                conn.commit()
                conn.close()
                st.success(f"✅ {name} 어르신이 DB에 영구 등록되었습니다!")
                st.rerun()

    with tab2:
        if len(df_res) == 0:
            st.info("현재 등록된 어르신이 없습니다.")
        else:
            resident_names = [f"[{row['층']} {row['호실']}] {row['성함']} (ID:{row['id']})" for idx, row in df_res.iterrows()]
            selected_res_str = st.selectbox("대상 어르신 선택 (수정 또는 삭제)", resident_names)
            
            selected_idx = resident_names.index(selected_res_str)
            target_row = df_res.iloc[selected_idx]
            target_id = int(target_row["id"])

            col_edit1, col_edit2 = st.columns(2)
            with col_edit1:
                st.subheader("✏️ 식이 정보 수정")
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
                    
                    update_btn = st.form_submit_button("수정사항 DB 저장하기", use_container_width=True)
                    if update_btn:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("UPDATE residents SET floor=?, room=?, name=?, meal=?, side=?, kimchi=?, note=? WHERE id=?", 
                                       (e_floor, e_room, e_name, e_meal, e_side, e_kimchi, e_note, target_id))
                        conn.commit()
                        conn.close()
                        st.success("✅ DB 정보가 성공적으로 수정되었습니다.")
                        st.rerun()

            with col_edit2:
                st.subheader("🗑️ 어르신 삭제 (퇴소 처리)")
                st.warning(f"선택한 [{target_row['성함']}] 어르신의 정보를 DB에서 영구 삭제합니다.")
                if st.button("🗑️ 선택한 어르신 DB 삭제하기", type="primary", use_container_width=True):
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM residents WHERE id=?", (target_id,))
                    conn.commit()
                    conn.close()
                    st.success(f"[{target_row['성함']}] 어르신 데이터가 DB에서 삭제되었습니다.")
                    st.rerun()

    st.markdown("---")
    st.subheader("📑 전체 입소 어르신 명단 (DB 가동 중)")
    st.dataframe(df_res[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]], use_container_width=True)

# ---------------------------------------------------------
# [메뉴 3] 4층 주간보호 출석부 (확인 및 저장 완료 완편)
# ---------------------------------------------------------
elif menu == "3. [4층 주간보호] 날짜별 출석부 & 식사 등록":
    st.title("🚌 4층 주간보호 센터 날짜별 출석부 & 식사 체크 (오전 10시 입력)")
    st.caption("달력으로 일자를 지정하여 [출석], [중식], [석식], [익일 조식] 식수를 체크하고 확정합니다.")
    st.markdown("---")

    col_date1, col_date2 = st.columns([1, 2])
    with col_date1:
        target_date = st.date_input("📅 출석 및 식사 작성 일자 선택", datetime.today())
        target_date_str = target_date.strftime('%Y-%m-%d')
    with col_date2:
        st.write("")
        st.info(f"💡 선택 작성 일자: **{target_date_str}** | 사회복지사 선생님 입력 화면")

    df_attendance = load_daycare_attendance_by_date(target_date_str)

    # 현시간 식수 카운터 요약 카드
    c_att = len(df_attendance[df_attendance["출석여부"] == True])
    c_lunch = len(df_attendance[df_attendance["중식"] == True])
    c_dinner = len(df_attendance[df_attendance["석식"] == True])
    c_next_b = len(df_attendance[df_attendance["익일조식"] == True])

    col_c1, col_c2, col_c3, col_c4 = st.columns(4)
    col_c1.metric("오늘 등원 인원", f"{c_att} 명")
    col_c2.metric("중식 신청 인원", f"{c_lunch} 명")
    col_c3.metric("석식 신청 인원", f"{c_dinner} 명")
    col_c4.metric("익일 조식 신청 인원", f"{c_next_b} 명")

    st.markdown("---")

    tab_dc1, tab_dc2 = st.tabs(["📝 날짜별 출석 & 식사(중식/석식/익일조식) 체크", "➕ 주간보호 어르신 마스터 등록/수정/삭제"])

    with tab_dc1:
        st.subheader(f"📝 [{target_date_str}] 주간보호 출석 및 식사 체크")
        
        # [상단 저장 버튼]
        if st.button("✅ 체크 확인 및 저장 완료 (상단 1클릭 저장)", type="primary", use_container_width=True, key="save_top"):
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
            st.balloons()
            st.success(f"🎉 저장이 완료되었습니다! ({target_date_str} 출석 및 식사 식수가 DB에 완벽하게 저장 연동되었습니다.)")

        st.write("")
        edited_attendance = st.data_editor(
            df_attendance[["id", "성함", "출석여부", "중식", "석식", "익일조식", "주식", "부식", "김치", "특이사항"]],
            num_rows="dynamic",
            use_container_width=True,
            key=f"editor_{target_date_str}"
        )
        
        st.write("")
        # [하단 저장 버튼]
        if st.button("✅ 체크 확인 및 저장 완료 (하단 저장 확정)", type="primary", use_container_width=True, key="save_bottom"):
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
            st.balloons()
            st.success(f"🎉 저장이 완료되었습니다! ({target_date_str} 출석 및 식사 식수가 DB에 완벽하게 저장 연동되었습니다.)")

    with tab_dc2:
        df_dc_master = load_daycare_master()
        col_d1, col_d2 = st.columns(2)

        with col_d1:
            st.subheader("➕ 신규 주간보호 어르신 마스터 등록")
            with st.form("add_daycare_master_form"):
                dc_name = st.text_input("성함", "김 주 간")
                meal_opts = ["일  반  밥", "🌾 잡  곡  밥", "🥣 일  반  죽", "🎃 호  박  죽", "🥗 야  채  죽", "🥛 미      음", "❌ 금      식"]
                dc_meal = st.selectbox("🍚 주식", meal_opts)
                side_opts = ["일  반  찬", "★ 다 진 찬", "♥ 갈  찬"]
                dc_side = st.selectbox("🥗 부식(찬)", side_opts)
                kimchi_opts = ["빨 간 김 치", "백  김  치", "★ 다진김치(빨간)", "☆ 다진김치(백)", "♥ 간김치(빨간)", "♡ 간김치(백)", "없      음"]
                dc_kimchi = st.selectbox("🥬 김치", kimchi_opts)
                dc_note = st.text_input("특이사항 (송영 차수 등)", "송영 1차")

                submit_dc = st.form_submit_button("주간보호 마스터 명단 DB 등록", type="primary", use_container_width=True)
                if submit_dc:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO daycare_master (name, meal, side, kimchi, note) VALUES (?, ?, ?, ?, ?)",
                                   (dc_name, dc_meal, dc_side, dc_kimchi, dc_note))
                    conn.commit()
                    conn.close()
                    st.success(f"✅ 주간보호 어르신 [{dc_name}] 님이 마스터 DB에 등록되었습니다.")
                    st.rerun()

        with col_d2:
            st.subheader("✏️ 마스터 정보 수정 및 🗑️ 삭제")
            if len(df_dc_master) == 0:
                st.info("등록된 주간보호 어르신이 없습니다.")
            else:
                dc_names = [f"{row['성함']} (ID:{row['id']})" for idx, row in df_dc_master.iterrows()]
                selected_dc_str = st.selectbox("대상 주간보호 어르신 선택", dc_names)
                dc_idx = dc_names.index(selected_dc_str)
                dc_row = df_dc_master.iloc[dc_idx]
                dc_id = int(dc_row["id"])

                with st.form("edit_daycare_master_form"):
                    edc_name = st.text_input("성함", dc_row["성함"])
                    edc_meal = st.selectbox("🍚 주식", meal_opts, index=meal_opts.index(dc_row["주식"]) if dc_row["주식"] in meal_opts else 0)
                    edc_side = st.selectbox("🥗 부식", side_opts, index=side_opts.index(dc_row["부식"]) if dc_row["부식"] in side_opts else 0)
                    edc_kimchi = st.selectbox("🥬 김치", kimchi_opts, index=kimchi_opts.index(dc_row["김치"]) if dc_row["김치"] in kimchi_opts else 0)
                    edc_note = st.text_input("특이사항", dc_row["특이사항"])

                    update_dc_btn = st.form_submit_button("수정 DB 저장하기", use_container_width=True)
                    if update_dc_btn:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("UPDATE daycare_master SET name=?, meal=?, side=?, kimchi=?, note=? WHERE id=?",
                                       (edc_name, edc_meal, edc_side, edc_kimchi, edc_note, dc_id))
                        conn.commit()
                        conn.close()
                        st.success("✅ DB 주간보호 마스터 정보가 수정되었습니다.")
                        st.rerun()

                st.markdown("---")
                if st.button(f"🗑️ [{dc_row['성함']}] 주간보호 어르신 DB 삭제", type="primary", use_container_width=True):
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM daycare_master WHERE id=?", (dc_id,))
                    conn.commit()
                    conn.close()
                    st.success(f"[{dc_row['성함']}] 어르신이 마스터 DB에서 삭제되었습니다.")
                    st.rerun()

# ---------------------------------------------------------
# [메뉴 4] 식수 & 배식지시서
# ---------------------------------------------------------
elif menu == "4. 식수 & 배식지시서 (히스토리)":
    st.title("📋 식수 집계표 및 조리실 배식지시서 (건보공단 이력 대응)")
    st.caption("오늘의 실시간 식수 집계 및 과거 일자별 배식지시서 이력 조회가 가능합니다.")
    st.markdown("---")

    tab_m1, tab_m2 = st.tabs(["⚡ 오늘 실시간 배식지시서", "📅 과거 일자별 배식 히스토리 조회"])

    with tab_m1:
        today_str = datetime.today().strftime('%Y-%m-%d')
        df_res = load_residents()
        df_daycare = load_daycare_attendance_by_date(today_str)

        active_daycare = df_daycare[df_daycare["출석여부"] == True].copy()
        active_daycare["층"] = "4층 (주간보호)"
        active_daycare["호실"] = "데이케어"
        
        full_df = pd.concat([df_res, active_daycare[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]]], ignore_index=True)

        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            st.subheader("🍚 층별 주식 집계 현황")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="주식", aggfunc="size", fill_value=0), use_container_width=True)
        with col_p2:
            st.subheader("🥗 층별 부식(찬) 집계 현황")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="부식", aggfunc="size", fill_value=0), use_container_width=True)
        with col_p3:
            st.subheader("🥬 층별 김치 집계 현황")
            st.dataframe(pd.pivot_table(full_df, index="층", columns="김치", aggfunc="size", fill_value=0), use_container_width=True)

        st.markdown("---")
        st.subheader("📄 오늘의 통합 배식지시서 명단")
        st.dataframe(full_df[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]], use_container_width=True)

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            buffer_sheet = io.BytesIO()
            with pd.ExcelWriter(buffer_sheet, engine='openpyxl') as writer:
                full_df[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]].to_excel(writer, index=False, sheet_name='오늘배식지시서')
            
            st.download_button(
                label="🖨️ 오늘 배식지시서 A4 엑셀 다운로드",
                data=buffer_sheet.getvalue(),
                file_name=f"통합배식지시서_{datetime.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )
        
        with col_btn2:
            if st.button("📸 오늘 배식 내역 히스토리 스냅샷 DB 저장", type="primary", use_container_width=True):
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute("DELETE FROM daily_meal_snapshots WHERE snapshot_date=?", (today_str,))
                for idx, row in full_df.iterrows():
                    cursor.execute("""
                        INSERT INTO daily_meal_snapshots (snapshot_date, floor, room, name, meal, side, kimchi, note)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (today_str, row['층'], row['호실'], row['성함'], row['주식'], row['부식'], row['김치'], row['특이사항']))
                
                conn.commit()
                conn.close()
                st.success(f"🎉 [{today_str}] 배식지시서 스냅샷이 DB에 이력으로 저장되었습니다!")

    with tab_m2:
        st.subheader("🔍 과거 날짜별 배식지시서 복원 및 조회")
        conn = get_db_connection()
        dates_df = pd.read_sql_query("SELECT DISTINCT snapshot_date FROM daily_meal_snapshots ORDER BY snapshot_date DESC", conn)
        conn.close()

        if len(dates_df) == 0:
            st.info("아직 저장된 과거 배식 히스토리 스냅샷이 없습니다. [오늘 실시간 배식지시서] 탭에서 스냅샷을 저장해 주세요.")
        else:
            selected_date = st.selectbox("조회할 과거 일자 선택", dates_df["snapshot_date"])
            
            conn = get_db_connection()
            hist_df = pd.read_sql_query("SELECT floor AS 층, room AS 호실, name AS 성함, meal AS 주식, side AS 부식, kimchi AS 김치, note AS 특이사항 FROM daily_meal_snapshots WHERE snapshot_date=?", conn, params=(selected_date,))
            conn.close()

            st.write(f"📅 **[{selected_date}] 배식 내역 복원 결과 (총 {len(hist_df)}명)**")
            st.dataframe(hist_df, use_container_width=True)

            buffer_hist = io.BytesIO()
            with pd.ExcelWriter(buffer_hist, engine='openpyxl') as writer:
                hist_df.to_excel(writer, index=False, sheet_name=f'{selected_date}_배식지시서')
            
            st.download_button(
                label=f"📄 [{selected_date}] 과거 배식지시서 엑셀 다운로드",
                data=buffer_hist.getvalue(),
                file_name=f"과거배식지시서_{selected_date}.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )

# ---------------------------------------------------------
# [메뉴 5] 명찰 카드 대량 출력
# ---------------------------------------------------------
elif menu == "5. 명찰 카드 대량 출력":
    st.title("🎴 배식용 명찰 카드 1클릭 대량 생성")
    st.caption("본원 + 4층 주간보호 등원 어르신 명찰을 동시에 압축파일로 출력합니다.")
    st.markdown("---")

    today_str = datetime.today().strftime('%Y-%m-%d')
    df_res = load_residents()
    df_daycare = load_daycare_attendance_by_date(today_str)

    active_daycare = df_daycare[df_daycare["출석여부"] == True].copy()
    active_daycare["층"] = "4층"
    active_daycare["호실"] = "주간"
    
    full_df = pd.concat([df_res, active_daycare[["층", "호실", "성함", "주식", "부식", "김치", "특이사항"]]], ignore_index=True)
    st.write(f"현재 본원 + 4층 등원 어르신 총 **{len(full_df)}명**의 명찰 카드가 출력 대상입니다.")

    if st.button("🚀 전체 명찰 카드(ZIP) 생성 및 다운로드 준비", type="primary", use_container_width=True):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            for idx, row in full_df.iterrows():
                img = generate_card_image(row["층"], row["성함"], row["주식"], row["부식"], row["김치"])
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format="PNG")
                file_name = f"명찰_{row['층']}_{row['호실']}_{row['성함']}.png"
                zip_file.writestr(file_name, img_byte_arr.getvalue())

        st.success("✅ 모든 어르신(주간보호 포함)의 명찰 카드 작성이 완료되었습니다!")
        st.download_button(
            label="📦 통합 명찰 카드 압축파일(.zip) 다운로드",
            data=zip_buffer.getvalue(),
            file_name="배식_명찰카드_통합전체.zip",
            mime="application/zip",
            use_container_width=True
        )

# ---------------------------------------------------------
# [메뉴 6] 주간 식단표 관리
# ---------------------------------------------------------
elif menu == "6. 주간 식단표 관리 (엑셀 연동)":
    st.title("📅 주간 식단표 엑셀 업로드 & 필요 식자재 자동 연동")
    st.caption("작성하신 식단표 엑셀(.xlsx)을 업로드하면 식단표 게시, 필요 식자재 산출, 원가가 자동 연동됩니다.")
    st.markdown("---")

    col_menu_a, col_menu_b = st.columns([1, 1])

    with col_menu_a:
        st.subheader("📤 작성된 식단표 엑셀 파일 업로드")
        menu_excel_file = st.file_uploader("주간 식단표 엑셀(.xlsx) 파일 선택", type=["xlsx"], key="menu_uploader")
        
        if menu_excel_file is not None:
            if st.button("🚀 엑셀 식단표 데이터 반영 및 식자재·원가 자동 계산 실행", type="primary", use_container_width=True):
                try:
                    uploaded_menu_df = pd.read_excel(menu_excel_file)
                    st.session_state["weekly_menu"] = uploaded_menu_df
                    auto_recalculate_ingredients_and_cost()
                    st.success("🎉 식단표가 완벽하게 연동되었습니다! 식자재 발주량과 원가가 실시간 재산출되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"식단표 파일 읽기 오류: {e}")

    with col_menu_b:
        st.subheader("📄 표준 식단표 엑셀 양식 다운로드")
        sample_menu_buf = io.BytesIO()
        with pd.ExcelWriter(sample_menu_buf, engine='openpyxl') as writer:
            st.session_state["weekly_menu"].to_excel(writer, index=False, sheet_name='주간식단표')
        
        st.download_button(
            label="📄 표준 주간 식단표 엑셀 양식(.xlsx) 다운로드",
            data=sample_menu_buf.getvalue(),
            file_name="표준_주간식단표_양식.xlsx",
            mime="application/vnd.ms-excel",
            use_container_width=True
        )

    st.markdown("---")
    st.subheader("📝 현재 적용된 주간 표준 식단표")
    edited_menu = st.data_editor(
        st.session_state["weekly_menu"], 
        num_rows="fixed", 
        use_container_width=True
    )
    if not edited_menu.equals(st.session_state["weekly_menu"]):
        st.session_state["weekly_menu"] = edited_menu
        auto_recalculate_ingredients_and_cost()

# ---------------------------------------------------------
# [메뉴 7] 식자재 발주 & 원가 관리
# ---------------------------------------------------------
elif menu == "7. 식자재 발주 & 원가 관리":
    st.title("🛒 식자재 발주 및 식재료비 원가 관리 (식단표 연동)")
    st.caption("업로드된 식단표 및 실시간 수급자 식수 인원에 기반하여 산출된 발주 및 원가 현황입니다.")
    st.markdown("---")

    today_str = datetime.today().strftime('%Y-%m-%d')
    df_res = load_residents()
    df_daycare = load_daycare_attendance_by_date(today_str)
    active_dc = df_daycare[df_daycare["출석여부"] == True]
    total_residents = len(df_res) + len(active_dc)

    df_order = st.session_state["orders"].copy()
    df_order["총 금액(원)"] = df_order["발주수량"] * df_order["단가(원)"]

    total_order_cost = df_order["총 금액(원)"].sum()
    daily_cost_per_person = int(total_order_cost / (total_residents * 7)) if total_residents > 0 else 0

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("이번 주 총 식자재 발주 추정액", f"{total_order_cost:,} 원")
    col_m2.metric("실시간 전체 식수 인원", f"{total_residents} 명", f"본원 {len(df_res)}명 + 4층 {len(active_dc)}명")
    col_m3.metric("어르신 1인 1일 추정 식재료비", f"{daily_cost_per_person:,} 원", "건보공단 수가 기준 반영")

    st.markdown("---")
    st.subheader("📦 식단표 기반 자동 산출 발주서")
    edited_order = st.data_editor(
        df_order,
        num_rows="dynamic",
        use_container_width=True
    )
    st.session_state["orders"] = edited_order[["품목명", "규격", "단위", "필요수량", "발주수량", "단가(원)", "공급업체"]]

    st.markdown("---")
    buf_order_export = io.BytesIO()
    with pd.ExcelWriter(buf_order_export, engine='openpyxl') as writer:
        df_order.to_excel(writer, index=False, sheet_name='식자재발주서')
    
    st.download_button(
        label="🚀 거래처 제출용 식자재 발주서 엑셀(.xlsx) 다운로드",
        data=buf_order_export.getvalue(),
        file_name=f"식자재발주서_{datetime.today().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.ms-excel",
        type="primary",
        use_container_width=True
    )

# ---------------------------------------------------------
# [메뉴 8] 위생 & 보존식·검식일지 관리
# ---------------------------------------------------------
elif menu == "8. 위생 & 보존식·검식일지 관리":
    st.title("🛡️ 건보공단 평가 대응 보존식 & 검식일지 자동화")
    st.caption("주간 식단표의 당일 메뉴를 자동 연동하여 보존식 채취 기록지 및 검식일지를 1초 만에 완성합니다.")
    st.markdown("---")

    today_str = datetime.today().strftime('%Y-%m-%d')
    weekdays_kor = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    today_weekday_str = weekdays_kor[datetime.today().weekday()]

    st.info(f"📅 **오늘 작성 기준일:** {today_str} ({today_weekday_str}) — 주간 식단표에서 [{today_weekday_str}] 메뉴를 자동으로 추출하여 매핑합니다.")

    menu_df = st.session_state["weekly_menu"]
    match_menu = menu_df[menu_df["구분"].str.contains(today_weekday_str[:2])]
    
    if len(match_menu) > 0:
        b_menu = str(match_menu.iloc[0]["아침"])
        l_menu = str(match_menu.iloc[0]["점심"])
        d_menu = str(match_menu.iloc[0]["저녁"])
        snack_menu = str(match_menu.iloc[0]["간식"])
    else:
        b_menu = "쌀밥 / 콩나물국 / 계란찜 / 무생채"
        l_menu = "잡곡밥 / 돈육김치찌개 / 가자미구이"
        d_menu = "쌀밥 / 아욱된장국 / 마파두부"
        snack_menu = "두유 / 바나나"

    tab_eval1, tab_eval2, tab_eval3 = st.tabs(["🧪 보존식 채취 기록지", "🔍 영양사/원장 검식 일지", "🧹 조리실 위생점검표"])

    with tab_eval1:
        st.subheader(f"🧪 보존식 채취 기록지 ({today_str})")
        st.caption("건보공단 규정: 매끼(조/중/석/간식) 100g 이상, -18℃ 이하 보존식 전용 냉동고 144시간(6일) 보관")
        
        df_sample = pd.DataFrame([
            {"구분": "조식", "채취시간": "07:30", "채취메뉴": b_menu, "채취량": "100g 이상", "보관온도": "-18℃ 이하", "채취자": "영양사 (인)"},
            {"구분": "중식", "채취시간": "11:30", "채취메뉴": l_menu, "채취량": "100g 이상", "보관온도": "-18℃ 이하", "채취자": "영양사 (인)"},
            {"구분": "석식", "채취시간": "16:30", "채취메뉴": d_menu, "채취량": "100g 이상", "보관온도": "-18℃ 이하", "채취자": "영양사 (인)"},
            {"구분": "간식", "채취시간": "14:00", "채취메뉴": snack_menu, "채취량": "100g 이상", "보관온도": "-18℃ 이하", "채취자": "영양사 (인)"}
        ])
        st.dataframe(df_sample, use_container_width=True)

    with tab_eval2:
        st.subheader(f"🔍 당일 식사 검식 일지 ({today_str})")
        st.caption("배식 30분 전 실시: 성상, 간, 온도, 이물질 여부 점검 후 결재")
        
        df_inspection = pd.DataFrame([
            {"식사구분": "조식 (07:30)", "검식메뉴": b_menu, "외관/성상": "양호", "맛/간": "적정 (저염)", "배식온도": "보온(65℃이상)", "판정": "합격", "검식자": "영양사"},
            {"식사구분": "중식 (11:30)", "검식메뉴": l_menu, "외관/성상": "양호", "맛/간": "적정", "배식온도": "보온(65℃이상)", "판정": "합격", "검식자": "영양사"},
            {"식사구분": "석식 (16:30)", "검식메뉴": d_menu, "외관/성상": "양호", "맛/간": "적정", "배식온도": "보온(65℃이상)", "판정": "합격", "검식자": "시설장"}
        ])
        st.dataframe(df_inspection, use_container_width=True)

    with tab_eval3:
        st.subheader(f"🧹 조리실 일일 위생점검표 ({today_str})")
        df_hygiene = pd.DataFrame([
            {"점검항목": "1. 조리원 건강상태 및 위생복/위생모 착용", "점검결과": "양호"},
            {"점검항목": "2. 식재료 보관온도 (냉장 5℃ 이하, 냉동 -18℃ 이하)", "점검결과": "양호"},
            {"점검항목": "3. 칼, 도마, 행주 용도별 구분 사용 및 소독", "점검결과": "양호"},
            {"점검항목": "4. 식기세척기 헹굼수 온도 (80℃ 이상 유지)", "점검결과": "양호"},
            {"점검항목": "5. 잔반 처리 및 쓰레기통 덮개 관리", "점검결과": "양호"}
        ])
        st.dataframe(df_hygiene, use_container_width=True)

    st.markdown("---")
    buf_eval = io.BytesIO()
    with pd.ExcelWriter(buf_eval, engine='openpyxl') as writer:
        df_sample.to_excel(writer, index=False, sheet_name='보존식기록지')
        df_inspection.to_excel(writer, index=False, sheet_name='검식일지')
        df_hygiene.to_excel(writer, index=False, sheet_name='위생점검표')

    st.download_button(
        label="📄 건보공단 제출용 [보존식 + 검식일지 + 위생일지] 통합 엑셀 다운로드",
        data=buf_eval.getvalue(),
        file_name=f"건보공단_보존식_검식일지_{today_str}.xlsx",
        mime="application/vnd.ms-excel",
        type="primary",
        use_container_width=True
    )
