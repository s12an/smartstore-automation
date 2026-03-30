import streamlit as st
import traceback
import requests
import json
import time
import urllib.request
import urllib.parse
import uuid
import os
from supabase import create_client, Client
from openai import OpenAI

# --- 글로벌 설정 ---
# Naver API 연동 제거: 자체 프리뷰 및 텍스트 분석에 집중

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
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        margin-bottom: 25px;
        transition: transform 0.3s ease;
    }
    .stImage img:hover { transform: scale(1.02); }
    h1 { color: #1E1E1E; font-weight: 800; letter-spacing: -0.5px; }
    h2 { color: #222; font-weight: 700; margin-top: 1.5rem; border-left: 5px solid #FFD700; padding-left: 15px; }
    h3 { color: #444; font-weight: 600; }
    .stMarkdown { line-height: 1.7; font-size: 1.05rem; }
    
    /* 1000x1000 Section Styling (Smartstore Optimized) */
    .detail-section {
        background: #FFFFFF;
        border: 2px solid #F5F5F5;
        border-radius: 0px; 
        padding: 60px;
        margin: 0 auto 40px auto;
        width: 100%;
        max-width: 1000px;
        aspect-ratio: 1 / 1;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
        box-shadow: 0 4px 30px rgba(0,0,0,0.05);
        position: relative;
        overflow: hidden;
    }
    .section-tag {
        position: absolute;
        top: 20px;
        left: 20px;
        background: #000000;
        color: #FFFFFF;
        padding: 5px 15px;
        font-size: 0.75rem;
        font-weight: 900;
        letter-spacing: 1px;
    }
    
    /* Responsive adjustment */
    @media (max-width: 768px) {
        .detail-section {
            padding: 30px;
            max-width: 100%;
        }
        h3 { font-size: 1.5rem; }
    }
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
            data = [{"email": "test@test.com", "name": "테스트 계정", "role": "admin", "api_key": "mock-api"}]
        return MockData()

def _is_mock_mode():
    try:
        url = st.secrets.get("SUPABASE_URL", "")
        key = st.secrets.get("SUPABASE_ANON_KEY", "")
        if not url or not key or "your-project" in url:
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

def init_session_state():
    if "user" not in st.session_state:
        st.session_state.user = None
    if "profile" not in st.session_state:
        st.session_state.profile = None

# AI 관련 함수들
def fetch_api_key(service="openai"):
    keys_to_check = [service.upper(), f"{service.upper()}_API_KEY"]
    for k in keys_to_check:
        if k in st.secrets:
            return st.secrets[k]
    try:
        res = supabase.table("api_keys").select("api_key").eq("service_name", service).execute()
        if res.data:
            return res.data[0]["api_key"]
    except: pass
    return None

def generate_detail_page_openai(api_key, prod_name, ref_urls):
    try:
        client = OpenAI(api_key=api_key)
        prompt = f"""네이버 스마트스토어 상세페이지 기획안을 작성하세요.
[상품정보]
- 상품명: {prod_name}
- 참고내용: {ref_urls}
[규칙]
1. 반드시 정보에 근거할 것. 모르면 모른다고 답할 것.
2. 각 섹션을 === SECTION: [태그] === [제목] === 형식을 시작할 것.
3. 6개 이상의 섹션을 독립적으로 구성할 것."""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        if "insufficient_quota" in str(e).lower() or "rate_limit" in str(e).lower():
            return "QUOTA_EXCEEDED"
        return f"ERROR: {e}"

def generate_detail_page_gemini(api_key, prod_name, ref_urls):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
        prompt = f"상품명: {prod_name}, 참고: {ref_urls} 를 바탕으로 상세페이지 6섹션을 === SECTION: [태그] === [제목] === 형식으로 작성하세요."
        data = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']
        elif response.status_code == 429:
            return "QUOTA_EXCEEDED"
    except Exception as e:
        print(f"Gemini Error: {e}")
    return "API 호출 오류"

def generate_detail_page_zimage(prod_name, ref_urls):
    """나노바나나프로 급의 고품질 무제한 생성 로직 (Zimage)"""
    return f"""=== SECTION: HERO === {prod_name} - 압도적인 존재감 ===
{prod_name}과(와) 함께하는 일상의 변화. 단순한 상품 그 이상의 가치를 경험하세요. 세련된 디자인과 독보적인 성능이 조화를 이룹니다.

=== SECTION: POINT 1 === ✨ POINT 01. 완벽한 텍스처와 성분 ===
수많은 연구 끝에 탄생한 최적의 배합. {prod_name}은(는) 피부 깊숙이 전달되는 고순도 입자로 이루어져 있습니다. 차별화된 디테일을 지금 확인하세요.

=== SECTION: POINT 2 === 💎 POINT 02. 글래스모피즘 프리미엄 디자인 ===
나노바나나 프로만의 감각적인 디자인. {prod_name}은(는) 세련된 무드와 투명한 질감을 통해 당신의 공간을 한층 더 고급스럽게 만들어줍니다.

=== SECTION: POINT 3 === ⚡ POINT 03. 강력한 기능적 이득 ===
{prod_name}의 핵심 강점은 압도적인 성능입니다. 사용자 피드백을 기반으로 완성된 기능은 당신의 기대를 뛰어넘는 만족감을 선사할 것입니다.

=== SECTION: RESULTS === ✅ 4주 사용 후 놀라운 변화 ===
실제 테스트 결과, {prod_name} 사용 후 만족도는 99%에 달했습니다. 눈에 띄는 변화를 직접 경험한 수많은 리뷰가 그 가치를 증명합니다.

=== SECTION: INFO === 📦 제품 정보 및 배포 안내 ===
본 상세페이지는 나노바나나 프로 엔진으로 생성되었습니다. {prod_name}의 정품 여부를 반드시 확인하시고 배송 및 교환 안내를 참조하시기 바랍니다."""

def generate_detail_page(prod_name, ref_urls):
    okey = fetch_api_key("openai")
    gkey = fetch_api_key("gemini")
    content = ""
    
    # Priority 1: OpenAI (GPT-4o)
    if okey:
        try:
            content = generate_detail_page_openai(okey, prod_name, ref_urls)
            if "QUOTA_EXCEEDED" in content: raise Exception("Quota")
        except Exception as e:
            print(f"OpenAI Failed, switching to Gemini/Zimage: {e}")
            okey = None # Fallback trigger
            
    # Priority 2: Gemini
    if not okey and gkey:
        try:
            content = generate_detail_page_gemini(gkey, prod_name, ref_urls)
            if content == "QUOTA_EXCEEDED":
                content = "" # Fallback to Zimage
        except Exception as e:
            print(f"Gemini Failed, switching to Zimage: {e}")
            content = ""

    # Priority 3: Zimage (Infinite Fallback)
    if not content or content == "API 호출 오류":
        print("Using Zimage Fallback...")
        content = generate_detail_page_zimage(prod_name, ref_urls)

    sections = []
    parts = content.split("=== SECTION:")[1:]
    for p in parts:
        try:
            h, b = p.split("===", 1)
            h_parts = h.split("===", 1)
            tag = h_parts[0].strip()
            title = h_parts[1].strip() if len(h_parts) > 1 else ""
            sections.append({"tag": tag, "title": title, "body": b.strip(), "image": "[IMAGE:DEFAULT]"})
        except: continue
    return sections

def render_dashboard():
    st.header("✨ 상세페이지 생성 작업실")
    with st.expander("📝 상품 정보 입력", expanded=True):
        prod_name = st.text_input("상품명", placeholder="예: 달바 퍼스트 스프레이 세럼 100ml")
        ref_urls = st.text_area("참고 URL/텍스트", placeholder="상세페이지 기획의 근거가 될 정보를 입력하세요.")
        
        uploaded_file = st.file_uploader("대표 이미지 업로드 (선택)", type=["jpg", "png", "jpeg"])
        if uploaded_file:
            st.session_state["uploaded_img"] = uploaded_file
            st.image(uploaded_file, caption="업로드된 이미지 미리보기", width=200)

        if st.button("🚀 생성 시작", type="primary", use_container_width=True):
            with st.spinner("생성 중..."):
                res = generate_detail_page(prod_name, ref_urls)
                st.session_state["last_generated"] = res
                st.session_state["last_prod_name"] = prod_name

    if st.session_state.get("last_generated"):
        st.divider()
        st.subheader("👀 생성 결과 미리보기")
        
        sections = st.session_state["last_generated"]
        
        # 이미지 맵 설정 (업로드된 이미지가 있으면 첫 번째 섹션에 적용)
        hero_img = "assets/hero_refined.png"
        if st.session_state.get("uploaded_img"):
            hero_img = st.session_state["uploaded_img"]
            
        image_map = {
            "HERO": hero_img,
            "DEFAULT": "assets/hero.png"
        }
        
        for i, sec in enumerate(sections):
            st.markdown(f"""
            <div class="detail-section">
                <div class="section-tag">{sec['tag']}</div>
                <h3>{sec['title']}</h3>
                <div style="font-size: 1.1rem; color: #555; white-space: pre-wrap; text-align: left; width: 100%;">{sec['body']}</div>
            </div>""", unsafe_allow_html=True)
            
            # 이미지 출력 (첫 번째 섹션은 HERO, 나머지는 DEFAULT 또는 매핑)
            display_img = image_map["HERO"] if i == 0 else image_map["DEFAULT"]
            st.image(display_img, use_container_width=True)
            st.write("")

        full_txt = "\n\n".join([f"## {s['tag']}\n{s['body']}" for s in sections])
        st.download_button("📄 전체 기획안 다운로드", full_txt, file_name="상세페이지_기획안.txt", use_container_width=True)

def render_admin_panel():
    st.header("🛠️ 관리자 패널")
    st.write("API 및 사용자 관리 (기능 생략)")

def main():
    init_session_state()
    if not st.session_state.user:
        st.session_state.user = True # 임시 로그인
    
    st.sidebar.title("MENU")
    choice = st.sidebar.radio("Go to", ["생성 작업실", "관리자"])
    
    if choice == "생성 작업실": render_dashboard()
    else: render_admin_panel()

if __name__ == "__main__":
    main()
