import streamlit as st
import traceback
import requests
import json
import time
import urllib.request
import urllib.parse
import bcrypt
import base64
import uuid
from supabase import create_client, Client
from openai import OpenAI

# ---------------------------------------------------------
# [0] 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="스마트스토어 상세페이지 자동화",
    page_icon="🛍️",
    layout="wide",
)

# ---------------------------------------------------------
# [1] Supabase 초기화 및 세션 (Mock 지원)
# ---------------------------------------------------------
class MockSupabase:
    def __init__(self):
        self.auth = MockAuth()
        
    def table(self, *args, **kwargs):
        return MockTable()

class MockAuth:
    def sign_in_with_password(self, *args, **kwargs):
        class MockUserRes:
            user = lambda: None
            user.id = "mock-user-123"
        return MockUserRes()
    def sign_up(self, *args, **kwargs):
        class MockUserRes:
            user = lambda: None
            user.id = "mock-user-123"
        return MockUserRes()
    def sign_out(self):
        pass

class MockTable:
    def select(self, *args, **kwargs): return self
    def eq(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    def insert(self, *args, **kwargs): return self
    def update(self, *args, **kwargs): return self
    def execute(self):
        class MockData:
            data = [{"email": "test@test.com", "name": "테스트 계정(임시)", "role": "admin", "api_key": "mock-api"}]
        return MockData()

def _is_mock_mode():
    """secrets.toml이 없거나 플레이스홀더 값이 들어있으면 Mock 모드"""
    try:
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_ANON_KEY", "")
        if not url or not key:
            return True
        if "your-project" in url or url == "https://your-project.supabase.co":
            return True
        return False
    except Exception:
        return True

@st.cache_resource
def init_supabase():
    if _is_mock_mode():
        return MockSupabase()
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_ANON_KEY"]
        return create_client(url, key)
    except Exception:
        return MockSupabase()

supabase = init_supabase()

if isinstance(supabase, MockSupabase) and "_mock_warned" not in st.session_state:
    st.session_state["_mock_warned"] = True

def init_session_state():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "profile" not in st.session_state:
        st.session_state.profile = None

init_session_state()

# ---------------------------------------------------------
# [2] 인증 화면 로직 (로그인 / 회원가입)
# ---------------------------------------------------------
def render_auth_page():
    st.title("🛍️ 스마트스토어 상세페이지 자동화 시스템")
    st.write("2인(사장/직원)을 위한 전용 자동화 솔루션입니다.")

    tab1, tab2 = st.tabs(["로그인", "회원가입"])

    with tab1:
        st.subheader("로그인")
        login_email = st.text_input("이메일", key="login_email")
        login_password = st.text_input("비밀번호", type="password", key="login_pass")
        if st.button("로그인", type="primary", use_container_width=True):
            if login_email and login_password:
                try:
                    res = supabase.auth.sign_in_with_password({
                        "email": login_email,
                        "password": login_password
                    })
                    st.session_state.user = res.user
                    # 프로필 정보 가져오기
                    profile_res = supabase.table("user_profiles").select("*").eq("id", res.user.id).execute()
                    if profile_res.data:
                        st.session_state.profile = profile_res.data[0]
                    st.success("로그인 성공!")
                    st.rerun()
                except Exception as e:
                    st.error(f"로그인 실패: {e}")
            else:
                st.warning("이메일과 비밀번호를 모두 입력해주세요.")

    with tab2:
        st.subheader("초대코드로 회원가입")
        signup_email = st.text_input("가입할 이메일", key="signup_email")
        signup_name = st.text_input("사용자 이름", key="signup_name")
        signup_password = st.text_input("새로운 비밀번호", type="password", key="signup_pass")
        invite_code = st.text_input("초대 코드", key="signup_code")
        
        if st.button("가입하기", use_container_width=True):
            if not (signup_email and signup_name and signup_password and invite_code):
                st.warning("모든 필드를 입력해주세요.")
                return

            # 1. 초대 코드 체킹
            code_res = supabase.table("invite_codes").select("*").eq("code", invite_code).eq("is_active", True).execute()
            if not code_res.data:
                st.error("유효하지 않거나 만료된 초대 코드입니다.")
                return
            
            # 2. Supabase Auth 회원가입
            try:
                auth_res = supabase.auth.sign_up({
                    "email": signup_email,
                    "password": signup_password
                })
                new_user_id = auth_res.user.id

                # 3. user_profiles 테이블에 삽입
                profile_data = {
                    "id": new_user_id,
                    "email": signup_email,
                    "name": signup_name,
                    "role": "user" # 기본 권한
                }
                supabase.table("user_profiles").insert(profile_data).execute()

                # 4. 사용된 코드 만료 등 필요 시 처리 (여기서는 여러번 쓸 수 있게 두거나, 만료시킬 수 있음)
                # supabase.table("invite_codes").update({"is_active": False}).eq("code", invite_code).execute()

                st.success("회원가입이 완료되었습니다. 이제 로그인 탭에서 로그인해주세요.")
            except Exception as e:
                st.error(f"회원가입 중 오류가 발생했습니다: {e}")

# ---------------------------------------------------------
# [3] 네이버 커머스 API 연동
# ---------------------------------------------------------
def get_naver_token(client_id, client_secret):
    """
    네이버 커머스 API 인증 토큰 발급
    필요 패키지: bcrypt
    """
    if client_id == "mock-api":
        time.sleep(1)
        return "mock-token-12345"
    
    timestamp = str(int((time.time() - 3) * 1000))
    pwd = f"{client_id}_{timestamp}"
    hashed_pwd = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
    client_secret_sign = urllib.parse.quote(
        base64.b64encode(hashed_pwd).decode('utf-8')
    )

    url = "https://api.commerce.naver.com/external/v1/oauth2/token"
    data = {
        "client_id": client_id,
        "timestamp": timestamp,
        "client_secret_sign": client_secret_sign,
        "grant_type": "client_credentials",
        "type": "SELF"
    }
    
    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.error(f"네이버 토큰 발급 실패: {response.text}")
        return None

def upload_to_naver_smartstore(token, category_id, product_name, html_content):
    """
    네이버 커머스 API를 통한 상품 등록 (초안)
    주의: 이 함수는 네이버 API 명세에 명확히 맞춰야 실제 등록이 가능합니다.
    """
    url = "https://api.commerce.naver.com/external/v2/products"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    # 네이버 상품 등록 필수 페이로드 (예시)
    payload = {
        "originProduct": {
            "statusType": "WAIT",
            "saleType": "NEW",
            "leafCategoryId": category_id,
            "name": product_name,
            "detailContent": html_content,
            "images": {
                "representativeImage": {
                    "url": "https://via.placeholder.com/1000" # 임시 이미지 (필수)
                }
            },
            "salePrice": 10000,
            "stockQuantity": 999
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response

# ---------------------------------------------------------
# [4] 대시보드 (직원/사장 공용)
# ---------------------------------------------------------
def fetch_api_key(service="openai"):
    res = supabase.table("api_keys").select("api_key").eq("service_name", service).execute()
    if res.data:
        return res.data[0]["api_key"]
    return None

def generate_detail_page(api_key, prod_name, template_used, ref_urls, additional_desc):
    # 가짜 모드(Mock)인 경우 더미 텍스트 반환
    if api_key == "mock-api":
        time.sleep(2)
        return f"""# 🛍️ {prod_name} 완벽 상세페이지 (미리보기)

> 이 페이지는 API 연결 전 테스트용 가짜 텍스트(Mock Data)입니다!

## ✨ {template_used}의 감성을 담은 최고의 선택!
참고하신 레퍼런스 `{ref_urls}` 를 분석하여 최적의 카피를 도출했습니다.

### 📌 체크포인트
- ✅ 소구점 1: {additional_desc if additional_desc else '엄청난 장점 1'}
- ✅ 소구점 2: 확실한 품질 보증
- ✅ 소구점 3: 빠른 배송과 안전한 포장

*버튼을 눌러 네이버 스마트스토어 API 연동을 바로 테스트 해볼 수 있습니다!*
"""

    client = OpenAI(api_key=api_key)
    prompt = f"""당신은 네이버 스마트스토어의 최고급 상세페이지 기획자이자 마케터입니다.
다음 상품의 판매를 극대화할 수 있는 완벽한 상세페이지 기획안(카피 및 설명 포함)을 마크다운 포맷으로 작성해주세요.

[상품정보]
- 상품명: {prod_name}
- 템플릿 양식: {template_used}
- 참고 URL (레퍼런스): {ref_urls}
- 추가 강조사항: {additional_desc}

[요구사항]
1. 시선을 끄는 메인카피와 서브카피
2. 상품의 차별성과 장점 (체크포인트 형식)
3. {template_used} 스타일에 맞춰 구매 소구점을 자극하는 상세 설명 작성
4. 신뢰성을 주는 FAQ 내용 작성
각 항목을 직관적이고 가독성 좋게 적절한 이모지와 함께 구성해주세요."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a highly skilled copywriter for e-commerce products."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=2500,
    )
    return response.choices[0].message.content

def render_dashboard():
    st.header("✨ 스마트스토어 상세페이지 생성 작업실")
    st.write(f"안녕하세요, **{st.session_state.profile.get('name', '사용자')}**님!")

    # ── 대표 이미지 업로드 (form 밖에 있어야 안정적) ──
    st.subheader("📸 대표 이미지 업로드")
    uploaded_img = st.file_uploader(
        "대표 이미지를 선택해주세요 (JPG, PNG, WEBP)",
        type=["jpg", "jpeg", "png", "webp"],
        key="product_image"
    )
    if uploaded_img:
        st.image(uploaded_img, caption="업로드된 대표 이미지", width=300)
        st.session_state["uploaded_img"] = uploaded_img
        st.success("✅ 이미지 업로드 완료!")
    
    st.divider()
    
    with st.form("generate_form"):
        col1, col2 = st.columns(2)
        with col1:
            prod_name = st.text_input("상품명 (필수)", placeholder="예: 무소음 무선 마우스 사무용")
            template_used = st.selectbox("템플릿 양식", ["기본 양식", "감성 양식", "전문가 양식"])
        with col2:
            ref_urls = st.text_area("참고 URL / 레퍼런스", placeholder="경쟁사 링크 또는 참고할 상품 주소", height=100)
            
        additional_desc = st.text_area("상품 특징 및 추가 요청사항", placeholder="소음이 없고 그립감이 좋음. 1년 무상 A/S 강조.")
        
        submitted = st.form_submit_button("🤖 봇에게 상세페이지 생성 요청", type="primary")

    if submitted:
        if not prod_name:
            st.warning("상품명은 필수 입력입니다.")
            return
        
        openai_key = fetch_api_key("openai")
        if not openai_key:
            st.error("시스템에 OpenAI API Key가 등록되지 않았습니다. 관리자에게 문의하세요.")
            return

        with st.spinner("최고의 마케팅 카피를 작성하는 중입니다... (최대 1분 소요)"):
            try:
                result_text = generate_detail_page(openai_key, prod_name, template_used, ref_urls, additional_desc)
                
                # DB 저장 (job_history)
                supabase.table("job_history").insert({
                    "user_id": st.session_state.user.id,
                    "product_name": prod_name,
                    "reference_url": ref_urls,
                    "template_used": template_used,
                    "generated_html": result_text,
                    "status": "completed"
                }).execute()
                
                st.success("생성 완료!")
                st.session_state["last_generated"] = result_text
                st.session_state["last_prod_name"] = prod_name

            except Exception as e:
                st.error(f"생성 중 에러 발생: {e}")
                # st.code(traceback.format_exc()) # 로깅용

    if "last_generated" in st.session_state:
        st.subheader("📄 생성 결과 미리보기")
        st.markdown(st.session_state["last_generated"])
        
        col_dl, col_nv = st.columns(2)
        with col_dl:
            st.download_button(
                label="마크다운 파일로 다운로드",
                data=st.session_state["last_generated"],
                file_name=f"{st.session_state.get('last_prod_name', '상품')}_상세페이지.md",
                mime="text/markdown"
            )
            
        with col_nv:
            if st.button("네이버 스마트스토어 임시저장 (API 연동)", type="primary"):
                naver_id = fetch_api_key("naver_client_id")
                naver_secret = fetch_api_key("naver_client_secret")
                
                if not (naver_id and naver_secret):
                    st.error("관리자 패널에서 네이버 API 정보를 먼저 등록해주세요.")
                else:
                    with st.spinner("네이버 연동 중..."):
                        token = get_naver_token(naver_id, naver_secret)
                        if token or isinstance(supabase, MockSupabase):
                            # 가짜 모드 일경우 강제로 성공 처리
                            if isinstance(supabase, MockSupabase):
                                time.sleep(1)
                                st.success("테스트 모드: 네이버 스마트스토어에 상품이 성공적으로 등록(임시저장) 되었습니다!")
                            else:
                                # 카테고리 ID 확보가 필요하나, 이 예제에서는 더미 값(50000000: 전체) 사용
                                res = upload_to_naver_smartstore(
                                    token, 
                                    "50000000", 
                                    st.session_state.get("last_prod_name", "스마트스토어 자동 상품"),
                                    st.session_state["last_generated"]
                                )
                                if res.status_code == 200:
                                    st.success("네이버 스마트스토어에 상품이 성공적으로 등록(임시저장) 되었습니다!")
                                    # 상태 업데이트 가능
                                else:
                                    st.error(f"등록 실패: {res.status_code} - {res.text}")
        
    st.divider()
    st.subheader("📚 최근 작업 내역")
    try:
        jobs_res = supabase.table("job_history").select("product_name, status, created_at").eq("user_id", st.session_state.user.id).order("created_at", desc=True).limit(5).execute()
        if jobs_res.data:
            st.dataframe(jobs_res.data, use_container_width=True)
        else:
            st.info("아직 생성한 내역이 없습니다.")
    except Exception as e:
        st.warning("작업 내역을 불러올 수 없습니다.")


# ---------------------------------------------------------
# [4] 관리자 패널 (admin 전용)
# ---------------------------------------------------------
def render_admin_panel():
    st.header("🛠️ 관리자 패널")
    
    tab1, tab2, tab3 = st.tabs(["API 키 설정", "초대 코드 관리", "사용자 조회"])

    # --- 1. API 키 관리 ---
    with tab1:
        st.subheader("글로벌 API Key 설정")
        
        # OpenAI
        current_openai = fetch_api_key("openai")
        st.info(f"OpenAI API Key 상태: **{'등록됨 (****)' if current_openai else '미등록'}**")
        new_openai = st.text_input("새로운 OpenAI API Key 입력", type="password", key="new_openai")
        
        st.divider()
        # Naver
        current_naver_id = fetch_api_key("naver_client_id")
        current_naver_secret = fetch_api_key("naver_client_secret")
        st.info(f"Naver Client ID 상태: **{'등록됨 (****)' if current_naver_id else '미등록'}**")
        new_naver_id = st.text_input("새로운 Naver Client ID 입력", type="password", key="naver_id")
        new_naver_secret = st.text_input("새로운 Naver Client Secret 입력", type="password", key="naver_sec")

        if st.button("API Key 저장 및 갱신", type="primary"):
            try:
                if new_openai:
                    try:
                        supabase.table("api_keys").insert({"service_name": "openai", "api_key": new_openai}).execute()
                    except:
                        supabase.table("api_keys").update({"api_key": new_openai}).eq("service_name", "openai").execute()
                
                if new_naver_id:
                    try:
                        supabase.table("api_keys").insert({"service_name": "naver_client_id", "api_key": new_naver_id}).execute()
                    except:
                        supabase.table("api_keys").update({"api_key": new_naver_id}).eq("service_name", "naver_client_id").execute()
                        
                if new_naver_secret:
                    try:
                        supabase.table("api_keys").insert({"service_name": "naver_client_secret", "api_key": new_naver_secret}).execute()
                    except:
                        supabase.table("api_keys").update({"api_key": new_naver_secret}).eq("service_name", "naver_client_secret").execute()
                
                st.success("API Key가 업데이트 되었습니다.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"업데이트 실패: {e}")

    # --- 2. 초대 코드 관리 ---
    with tab2:
        st.subheader("신규 초대 코드 발급")
        col_c1, col_c2 = st.columns([3,1])
        with col_c1:
            new_code_memo = st.text_input("메모 (초대 발송 대상 등)")
        with col_c2:
            st.write("")
            st.write("")
            if st.button("신규 발급", use_container_width=True):
                # 6자리 랜덤 텍스트 기반이거나 Supabase gen_random_uuid로 생성
                short_code = str(uuid.uuid4())[:8].upper()
                try:
                    supabase.table("invite_codes").insert({
                        "code": short_code,
                        "description": new_code_memo
                    }).execute()
                    st.success(f"생성 완료: {short_code}")
                except Exception as e:
                    st.error("생성 실패")
        
        st.divider()
        st.markdown("**(현재 발급된 초대 코드 목록)**")
        code_res = supabase.table("invite_codes").select("*").order("created_at", desc=True).limit(10).execute()
        if code_res.data:
            st.dataframe(code_res.data)

    # --- 3. 사용자 관리 ---
    with tab3:
        st.subheader("등록된 사용자 목록")
        user_res = supabase.table("user_profiles").select("email, name, role, created_at").execute()
        if user_res.data:
            st.dataframe(user_res.data, use_container_width=True)


# ---------------------------------------------------------
# [5] 메인 라우팅 (Single Page)
# ---------------------------------------------------------
def main():
    if not st.session_state.user:
        # 비로그인 상태
        render_auth_page()
    else:
        # 로그인 상태
        st.sidebar.title("메뉴")
        st.sidebar.write(f"접속자: {st.session_state.profile.get('name','')}")
        
        # 관리자일 경우 메뉴 선택 가능하도록 세팅
        pages = ["상세페이지 생성 작업실"]
        is_admin = st.session_state.profile.get("role") == "admin"
        if is_admin:
            pages.append("관리자 패널")
            
        choice = st.sidebar.radio("이동", pages)
        
        if st.sidebar.button("로그아웃"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.session_state.profile = None
            st.rerun()

        # 라우팅
        if choice == "상세페이지 생성 작업실":
            render_dashboard()
        elif choice == "관리자 패널" and is_admin:
            render_admin_panel()

if __name__ == "__main__":
    main()
