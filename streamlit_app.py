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
# [0] 글로벌 설정 (데모 모드)
# ---------------------------------------------------------
USE_NAVER_API = False # 데모 버전에서는 False로 설정

# ---------------------------------------------------------
# [0] 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="스마트스토어 상세페이지 자동화",
    page_icon="🛍️",
    layout="wide",
)

# --- Premium UI/UX Styling (Nano Banana 스타일) ---
st.markdown("""
<style>
    .stImage img {
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }
    h1 { color: #1E1E1E; font-weight: 800; }
    h2 { color: #333; font-weight: 700; }
    .stMarkdown { line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

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

# ---------------------------------------------------------
# [2] 인증 화면 로직 (로그인 / 회원가입)
# ---------------------------------------------------------
def render_auth_page():
    st.title("🛍️ 스마트스토어 상세페이지 자동화 시스템")
    st.info("⚠️ **무료 단계(Free Tier) 전용**: 이 시스템은 현재 무료 API(Gemini Free 등)를 우선 사용하도록 설정되어 있습니다. 예기치 않은 비용 발생을 방지하기 위해 유료 결제 전환 시 주의해 주세요.")
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
    client_secret_sign = base64.b64encode(hashed_pwd).decode('utf-8')

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

def upload_naver_image(token, file_buffer):
    """
    네이버 서버에 이미지를 업로드하고 URL을 반환받음
    """
    url = "https://api.commerce.naver.com/external/v1/product-images/upload"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    # Streamlit UploadedFile 객체에서 바이너리 읽기
    files = {
        "imageFiles": (file_buffer.name, file_buffer.getvalue(), file_buffer.type)
    }
    
    try:
        response = requests.post(url, headers=headers, files=files)
        if response.status_code == 200:
            res_data = response.json()
            # 첫 번째 이미지 URL 반환
            if res_data.get("images"):
                return res_data["images"][0]["url"]
        return None
    except Exception:
        return None

def upload_to_naver_smartstore(token, category_id, product_name, html_content, image_url=None):
    """
    네이버 커머스 API v2를 통한 상품 등록
    """
    if not image_url:
        # 이미지가 없으면 기본 플레이스홀더라도 사용 (네이버에서 거절될 수 있음)
        image_url = "https://shop1.phinf.naver.net/20260127_90/1769489464863JnBex_PNG/103622289056824682_205746319.png"

    url = "https://api.commerce.naver.com/external/v2/products"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 네이버 v2 상품 등록 페이로드 (최종 검증된 구조)
    payload = {
        "originProduct": {
            "statusType": "SALE",
            "saleType": "NEW",
            "leafCategoryId": category_id,
            "name": product_name,
            "detailContent": html_content,
            "images": {
                "representativeImage": {
                    "url": image_url
                }
            },
            "salePrice": 10000,
            "stockQuantity": 999,
            "detailAttribute": {
                "originAreaInfo": {
                    "originAreaCode": "0200037" # 국내(기타)
                },
                "minorPurchasable": True,
                "afterServiceInfo": {
                    "afterServiceInformationDescription": "상세페이지 참조",
                    "afterServiceTelephoneNumber": "010-0000-0000"
                }
            }
        },
        "smartstoreChannelProduct": {
            "channelProductDisplayStatusType": "SUSPENSION" # 테스트를 위해 '전시중지' 상태로 등록
        }
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response

# ---------------------------------------------------------
# [4] 대시보드 (직원/사장 공용)
# ---------------------------------------------------------
def fetch_api_key(service="openai"):
    # 1. secrets.toml 우선 확인
    keys_to_check = [service.upper(), f"{service.upper()}_API_KEY", f"NAVER_{service.upper()}"]
    if service == "naver_client_id": keys_to_check = ["NAVER_CLIENT_ID"]
    if service == "naver_client_secret": keys_to_check = ["NAVER_CLIENT_SECRET"]
    
    for k in keys_to_check:
        if k in st.secrets:
            return st.secrets[k]

    # 2. Supabase DB 확인
    try:
        res = supabase.table("api_keys").select("api_key").eq("service_name", service).execute()
        if res.data:
            return res.data[0]["api_key"]
    except:
        pass
    return None

def generate_detail_page_openai(api_key, prod_name, ref_urls):
    client = OpenAI(api_key=api_key)
    prompt = f"""당신은 네이버 스마트스토어의 최고급 상세페이지 기획자이자 마케터입니다.
다음 상품의 판매를 극대화할 수 있는 완벽한 상세페이지 기획안(카피 및 설명 포함)을 마크다운 포맷으로 작성해주세요.

[상품정보]
- 상품명: {prod_name}
- 참고 URL (레퍼런스): {ref_urls}

[요구사항]
1. 먼저 상품명과 레퍼런스를 분석하여 이 상품에 가장 잘 어울리는 템플릿 양식(감성형, 전문직형, 기본형 등)을 스스로 선택하여 그 컨셉에 맞춰 작성하세요.
2. 시선을 끄는 메인카피와 서브카피
3. 상품의 차별성과 장점 (체크포인트 형식)
4. 구매 소구점을 자극하는 상세 설명 작성
5. 신뢰성을 주는 FAQ 내용 작성
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

def generate_detail_page_gemini(api_key, prod_name, ref_urls):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""당신은 네이버 스마트스토어의 최고급 상세페이지 기획자이자 마케터입니다.
다음 상품의 판매를 극대화할 수 있는 완벽한 상세페이지 기획안(카피 및 설명 포함)을 마크다운 포맷으로 작성해주세요.

[상품정보]
- 상품명: {prod_name}
- 참고 URL (레퍼런스): {ref_urls}

[요구사항]
1. 먼저 상품명과 레퍼런스를 분석하여 이 상품에 가장 잘 어울리는 템플릿 양식(감성형, 전문직형, 기본형 등)을 스스로 선택하여 그 컨셉에 맞춰 작성하세요.
2. 시선을 끄는 메인카피와 서브카피
3. 상품의 차별성과 장점 (체크포인트 형식)
4. 구매 소구점을 자극하는 상세 설명 작성
5. 신뢰성을 주는 FAQ 내용 작성
각 항목을 직관적이고 가독성 좋게 적절한 이모지와 함께 구성해주세요."""

    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        res_json = response.json()
        return res_json['candidates'][0]['content']['parts'][0]['text']
    else:
        raise Exception(f"Gemini API Error: {response.status_code} - {response.text}")

def generate_detail_page(prod_name, ref_urls):
    # 가짜 모드(Mock)인 경우 더미 텍스트 반환
    if _is_mock_mode():
        time.sleep(1.5)
        return f"""# 🚨 품질 대란! 품절 임박!
## "{prod_name}" - 드디어 공개되는 역대급 진정 솔루션

[IMAGE:HERO]

---

### 🤔 지속되는 피부 고민? 아직도 해결 못하셨나요?
- [ ] 특정 시기에 꼭 트러블이 올라와요.
- [ ] 뭘 발라도 피부가 울퉁불퉁해요. 🧴
- [ ] 피부가 쉽게 붉어지고, 건조해져요. 🏜️

**위 사항 중 하나라도 해당된다면, 이 상세페이지를 끝까지 봐주세요!**

---

### 🍯 진정 시너지 성분을 그대로!
## '시카마누 바이옴™ (Cicamanu Biome)'
파넬만의 독자 성분인 시카마누 바이옴은 피부 진정, 보습에 특화된 최적의 성분으로 외부 자극에 의해 자극받은 피부를 즉각 진정시켜줍니다.

[IMAGE:POINT1]

---

### ✨ POINT 1. 독보적인 진정+보습 레시피
- 뉴질랜드산 꿀추출물 함유 🐝
- 마데카소사이드의 강력한 진정 효과 🌿
- 락토바실러스 발효물로 강화되는 피부 장벽

[IMAGE:POINT2]

### ✨ POINT 2. 끈적임 없는 꿀광 광채
무겁고 답답한 제형은 이제 그만! 바르는 순간 스며들어 속보습은 채우고 겉은 산뜻하게 마무리됩니다.

---

### ✅ 4주 사용 후 놀라운 변화
#### "#4주진정솔루션"
- 피부 진정 효과 테스트 완료 ⭕
- 피지량 개선 효과 확인 ⭕
- 피부 수분량 200% 증가 ⭕

*데모 버전입니다. 생성된 상세페이지를 기반으로 네이버 스마트스토어 등록을 테스트해보세요!*
"""

    openai_key = fetch_api_key("openai")
    gemini_key = fetch_api_key("gemini")
    
    if openai_key:
        try:
            return generate_detail_page_openai(openai_key, prod_name, ref_urls)
        except Exception as e:
            if "insufficient_quota" in str(e).lower() or "429" in str(e):
                if gemini_key:
                    st.info("OpenAI 할당량이 부족하여 Gemini로 대체 생성을 시도합니다.")
                    return generate_detail_page_gemini(gemini_key, prod_name, ref_urls)
            raise e
    elif gemini_key:
        return generate_detail_page_gemini(gemini_key, prod_name, ref_urls)
    else:
        raise Exception("사용 가능한 AI API Key가 없습니다.")

def render_dashboard():
    st.header("✨ 스마트스토어 상세페이지 생성 작업실")
    
    # [A] 입력 섹션
    with st.expander("📝 상품 정보 입력", expanded=True):
        prod_name = st.text_input("상품명", placeholder="예: 달바 퍼스트 스프레이 세럼 100ml")
        ref_urls = st.text_area("참고 URL (레퍼런스)", placeholder="참고할 상세페이지 주소를 입력하세요 (여러 개 가능)")
        
        uploaded_file = st.file_uploader("대표 이미지 업로드 (선택)", type=["jpg", "png", "jpeg"])
        if uploaded_file:
            st.session_state["uploaded_img"] = uploaded_file
            st.image(uploaded_file, caption="업로드된 이미지 미리보기", width=200)

        if st.button("🚀 상세페이지 생성", type="primary", use_container_width=True):
            if not prod_name:
                st.warning("상품명을 입력해주세요.")
            else:
                try:
                    with st.spinner("AI가 상세페이지를 마법처럼 생성 중입니다..."):
                        generated_content = generate_detail_page(prod_name, ref_urls)
                        st.session_state["last_generated"] = generated_content
                        st.session_state["last_prod_name"] = prod_name
                        st.success("상세페이지 생성이 완료되었습니다!")
                except Exception as e:
                    st.error(f"생성 중 에러 발생: {e}")

    # [B] 결과 및 데모 섹션
    if st.session_state.get("last_generated"):
        st.divider()
        st.subheader("👀 생성 결과 미리보기 및 검토")
        st.info("AI가 생성한 기획안입니다. 확인 후 필요 시 다운로드하거나 데모 등록을 시도해보세요.")
        
        # --- 리치 렌더링 (이미지 포함) ---
        content = st.session_state["last_generated"]
        image_map = {
            "[IMAGE:HERO]": "assets/hero_refined.png",
            "[IMAGE:POINT1]": "assets/point1.png",
            "[IMAGE:POINT2]": "assets/point2_refined.png"
        }
        
        # 섹션별 렌더링
        import os
        parts = [content]
        for key in image_map.keys():
            new_parts = []
            for p in parts:
                if key in p:
                    splits = p.split(key)
                    # p1, key, p2
                    new_parts.append(splits[0])
                    new_parts.append(key)
                    new_parts.append(splits[1])
                else:
                    new_parts.append(p)
            parts = new_parts
            
        for p in parts:
            if p in image_map:
                img_path = image_map[p]
                if os.path.exists(img_path):
                    st.image(img_path, use_container_width=True)
                else:
                    st.caption(f" (이미지 준비 중: {img_path}) ")
            else:
                if p.strip():
                    st.markdown(p)
        
        col_dl, col_nv = st.columns(2)
        with col_dl:
            st.download_button(
                label="📄 마크다운 파일로 다운로드",
                data=st.session_state["last_generated"],
                file_name=f"{st.session_state.get('last_prod_name', '상품')}_상세페이지.md",
                mime="text/markdown",
                use_container_width=True
            )
            
        with col_nv:
            # --- 데모 로직 적용 ---
            if st.button("🧪 스마트스토어 등록 (데모)", type="primary", use_container_width=True):
                with st.spinner("데모 등록 처리 중..."):
                    time.sleep(1.5)
                    
                    st.balloons()
                    st.toast("🎉 데모 등록 완료!", icon="✅")
                    st.success("✅ 데모: 상품이 스마트스토어에 등록된 것처럼 처리되었습니다!")

                    # 가짜 결과 출력
                    with st.expander("📦 등록 정보 확인 (데모)", expanded=True):
                        st.info(f"**상품명**: {st.session_state.get('last_prod_name', '상품')}")
                        if "uploaded_img" in st.session_state:
                            st.image(st.session_state["uploaded_img"], caption="대표 이미지 (데모)", width=300)
                        
                        st.markdown("---")
                        st.markdown("### 📄 상세페이지 본문 (HTML 변환 가정)")
                        # 마크다운을 그대로 보여주거나 HTML 프리뷰라고 가정
                        st.code(st.session_state.get("last_generated", "")[:500] + "...", language="html")

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

                # Gemini
                new_gemini = st.text_input("새로운 Gemini API Key 입력 (선택)", type="password", key="new_gemini")
                if new_gemini:
                    try:
                        supabase.table("api_keys").insert({"service_name": "gemini", "api_key": new_gemini}).execute()
                    except:
                        supabase.table("api_keys").update({"api_key": new_gemini}).eq("service_name", "gemini").execute()
                
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
    init_session_state()

    # ---------------------------------------------------------
    # [로그인 우회] 항상 관리자 권한으로 시작
    # ---------------------------------------------------------
    if not st.session_state.user:
        class MockUser:
            id = "test-user-id"
            email = "s12ancio@gmail.com"
        st.session_state.user = MockUser()
        st.session_state.profile = {
            "name": "운영자(s12ancio)",
            "role": "admin",
            "email": "s12ancio@gmail.com"
        }

    # 사이드바 메뉴
    st.sidebar.title("🛠️ 메뉴")
    pages = ["상세페이지 생성 작업실", "관리자 패널"]
    choice = st.sidebar.radio("이동", pages)
    
    st.sidebar.divider()
    if st.sidebar.button("새로고침"):
        st.rerun()

    # 라우팅
    if choice == "상세페이지 생성 작업실":
        render_dashboard()
    elif choice == "관리자 패널":
        render_admin_panel()

if __name__ == "__main__":
    main()
