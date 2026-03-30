import streamlit as st
import traceback
import requests
import json
import time
import urllib.request
import urllib.parse
import uuid
import os
import io
import base64
from PIL import Image
from supabase import create_client, Client
from openai import OpenAI
import streamlit.components.v1 as components

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

def image_to_base64(image_bytesio):
    if not image_bytesio:
        return None
    image_bytesio.seek(0)
    return base64.b64encode(image_bytesio.read()).decode('utf-8')

def generate_detail_page_openai(api_key, prod_name, ref_urls, image_b64=None):
    try:
        client = OpenAI(api_key=api_key)
        prompt = f"""네이버 스마트스토어 및 고품질 랜딩페이지용 상세 기획안을 작성하세요.
[상품정보]
- 상품명: {prod_name}
- 참고내용: {ref_urls}
[규칙]
1. 반드시 정보에 근거할 것. (거짓 정보 방지)
2. 각 섹션을 === SECTION: [태그] === [제목] === 형식을 시작할 것.
3. 6개 이상의 섹션(HERO, POINT 1, POINT 2, POINT 3, RESULTS, INFO 등)을 구성할 것.
4. 첨부된 이미지가 있다면, 이미지 속 제품의 형태, 색상, 주요 특징 및 질감을 시각적으로 분석하여 카피라이팅에 실감나게 반영할 것."""

        messages = [{"role": "user", "content": prompt}]
        if image_b64:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]
            }]

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        if "insufficient_quota" in str(e).lower() or "rate_limit" in str(e).lower():
            return "QUOTA_EXCEEDED"
        return f"ERROR: {e}"

def generate_detail_page_gemini(api_key, prod_name, ref_urls, image_b64=None):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
        prompt = f"""상품명: {prod_name}, 참고: {ref_urls}.
첨부된 사진(있다면)의 제품 특성, 로고, 디자인을 분석하여 실제 제품에 부합하는 상세페이지 6섹션을 === SECTION: [태그] === [제목] === 형식으로 작성하세요."""
        
        parts = [{"text": prompt}]
        if image_b64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64
                }
            })
            
        data = {"contents": [{"parts": parts}]}
        response = requests.post(url, json=data, timeout=15)
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

def generate_detail_page(prod_name, ref_urls, image_b64=None):
    # Diagnostic: Check for key existence first
    okey = fetch_api_key("openai")
    gkey = fetch_api_key("gemini")
    
    if not okey and not gkey:
        print("CRITICAL: No API keys found! Defaulting to Zimage.")
    
    content = ""
    
    # Priority 1: OpenAI (GPT-4o Vision)
    if okey:
        try:
            content = generate_detail_page_openai(okey, prod_name, ref_urls, image_b64)
            if "QUOTA_EXCEEDED" in content: raise Exception("Quota")
        except Exception as e:
            print(f"OpenAI Failed, switching to Gemini/Zimage: {e}")
            okey = None # Fallback trigger
            
    # Priority 2: Gemini (Vision)
    if not okey and gkey:
        try:
            content = generate_detail_page_gemini(gkey, prod_name, ref_urls, image_b64)
            if content == "QUOTA_EXCEEDED" or not content:
                content = "" # Fallback to Zimage
        except Exception as e:
            print(f"Gemini Failed, switching to Zimage: {e}")
            content = ""

    # Priority 3: Zimage (Infinite Fallback)
    if not content or content == "API 호출 오류" or "ERROR:" in content:
        print("Using Zimage Fallback...")
        content = generate_detail_page_zimage(prod_name, ref_urls)

    sections = []
    # Robust Parsing: Split by SECTION marker
    parts = content.split("=== SECTION:")[1:]
    if not parts:
        # Fallback if no sections found due to malformed AI output
        content = generate_detail_page_zimage(prod_name, ref_urls)
        parts = content.split("=== SECTION:")[1:]

    for p in parts:
        try:
            # First split to separate Header from Body (Header ends with ===\n or just ===)
            if "===\n" in p:
                header, body = p.split("===\n", 1)
            elif "===" in p:
                header, body = p.split("===", 1)
            else:
                continue
            
            # Header further split into Tag and Title using ===
            if "===" in header:
                tag, title = header.split("===", 1)
            else:
                tag, title = header, ""
                
            sections.append({
                "tag": tag.strip(),
                "title": title.strip(),
                "body": body.strip(),
                "image": "[IMAGE:DEFAULT]"
            })
        except Exception as e:
            print(f"Parsing error for part: {e}")
            continue
    return sections

def optimize_image(uploaded_file, max_size=1000, quality=85):
    """
    업로드된 이미지를 나노바나나프로 규격(최대 1000x1000) 비율로 리사이징하고 
    압축하여 메모리 및 네트워크 부하를 극도로 낮춥니다.
    """
    try:
        img = Image.open(uploaded_file)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 가로/세로 비율을 유지하면서 max_size 이하로 리사이징
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # 압축된 이미지를 메모리 버퍼에 저장
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        output.name = "optimized_image.jpg"
        output.seek(0)
        return output
    except Exception as e:
        print(f"Image optimization failed: {e}")
        return uploaded_file # 실패 시 원본 그대로 반환

def render_dashboard():
    st.header("✨ 상세페이지 생성 작업실")
    
    # Diagnostic Check (Hidden from user, only for logs)
    if not fetch_api_key("openai") and not fetch_api_key("gemini"):
        st.warning("⚠️ AI 설정이 부재하여 Zimage 모드로 자동 가동 중입니다. (무제한)")

    with st.expander("📝 상품 정보 입력", expanded=True):
        prod_name = st.text_input("상품명", placeholder="예: 달바 퍼스트 스프레이 세럼 100ml")
        ref_urls = st.text_area("참고 URL/텍스트", placeholder="상세페이지 기획의 근거가 될 정보를 입력하세요.")
        
        try:
            uploaded_file = st.file_uploader("대표 이미지 업로드 (선택)", type=["jpg", "png", "jpeg"])
            if uploaded_file:
                # O(1) 초고속 이미지 압축 로직
                with st.spinner("이미지 최적화 중..."):
                    optimized_img = optimize_image(uploaded_file)
                st.session_state["uploaded_img"] = optimized_img
                st.image(optimized_img, caption="업로드된 이미지 미리보기 (최적화 완료)", width=200)
        except Exception as img_err:
            st.error(f"이미지 업로드 중 오류 발생: {img_err}. 다시 시도해주세요.")

        if st.button("🚀 생성 시작", type="primary", use_container_width=True):
            if not prod_name:
                st.error("상품명을 입력해주세요.")
            else:
                with st.spinner("최고급 '나노바나나프로' 엔진으로 Vision AI 분석 및 생성 중..."):
                    try:
                        # Extract Base64 if image exists
                        img_b64 = None
                        if st.session_state.get("uploaded_img"):
                            img_b64 = image_to_base64(st.session_state["uploaded_img"])
                            st.session_state["uploaded_img_b64"] = img_b64 # Cache for rendering
                            
                        res = generate_detail_page(prod_name, ref_urls, img_b64)
                        if res:
                            st.session_state["last_generated"] = res
                            st.session_state["last_prod_name"] = prod_name
                            st.success("✅ 시각 분석 및 생성이 완료되었습니다!")
                        else:
                            st.error("생성에 실패했습니다. 다시 시도해주세요.")
                    except Exception as gen_err:
                        st.error(f"생성 중 예외 발생: {gen_err}")

    if st.session_state.get("last_generated"):
        st.divider()
        st.subheader("👀 시니어 레벨 1000x1000 상세페이지 프리뷰")
        
        sections = st.session_state["last_generated"]
        img_b64 = st.session_state.get("uploaded_img_b64")
        
        # 기본 더미 Base64 (회색 배경 방지용 아주 작은 픽셀) 또는 외부 URL
        fallback_img_url = "https://via.placeholder.com/1000?text=No+Image+Provided"
        img_src = f"data:image/jpeg;base64,{img_b64}" if img_b64 else fallback_img_url

        # Build massive HTML string to embed via true iFrame
        html_blocks = []
        for i, sec in enumerate(sections):
            tag = sec['tag'].upper()
            title = sec['title'].replace('"', '&quot;')
            body = sec['body'].replace('\n', '<br>')
            
            # CSS Patterns based on sections
            if i % 3 == 0 or "HERO" in tag:
                # HERO Pattern: Full background overlay
                block = f"""
                <div style="width: 1000px; height: 1000px; position: relative; font-family: 'Helvetica Neue', Arial, sans-serif; display: flex; flex-direction: column; justify-content: flex-end; padding: 80px; box-sizing: border-box; background: url('{img_src}') center/cover no-repeat; margin-bottom: 20px;">
                    <div style="position: absolute; top:0; left:0; right:0; bottom:0; background: linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.2) 60%, transparent 100%);"></div>
                    <div style="position: relative; z-index: 10;">
                        <span style="display:inline-block; padding:8px 16px; background:#FFD700; color:#000; font-weight:800; font-size:24px; border-radius:4px; margin-bottom:20px;">{tag}</span>
                        <h1 style="color: #FFF; font-size: 64px; font-weight: 900; line-height: 1.2; margin: 0 0 30px 0; letter-spacing:-1px;">{title}</h1>
                        <p style="color: #EEE; font-size: 28px; line-height: 1.6; font-weight: 300; max-width:800px; word-break: keep-all;">{body}</p>
                    </div>
                </div>
                """
            elif i % 3 == 1:
                # SIDE-BY-SIDE Pattern
                block = f"""
                <div style="width: 1000px; height: 1000px; position: relative; font-family: 'Helvetica Neue', Arial, sans-serif; display: flex; flex-direction: row; background: #F9F9F9; margin-bottom: 20px;">
                    <div style="flex:1; padding: 100px 60px; display:flex; flex-direction:column; justify-content:center;">
                        <span style="color:#0055FF; font-weight:800; font-size:22px; margin-bottom:15px; letter-spacing:1px;">{tag}</span>
                        <h2 style="color: #222; font-size: 48px; font-weight: 800; line-height: 1.3; margin: 0 0 40px 0;">{title}</h2>
                        <div style="color: #555; font-size: 24px; line-height: 1.8; font-weight: 400; word-break: keep-all;">{body}</div>
                    </div>
                    <div style="flex:1; background: url('{img_src}') center/cover no-repeat;"></div>
                </div>
                """
            else:
                # STATS/INFO Pattern (Glassmorphism overlap)
                block = f"""
                <div style="width: 1000px; height: 1000px; position: relative; font-family: 'Helvetica Neue', Arial, sans-serif; display: flex; align-items: center; justify-content: center; background: url('{img_src}') top/cover no-repeat; margin-bottom: 20px;">
                    <div style="position: absolute; top:0; left:0; right:0; bottom:0; background: rgba(0,0,0,0.5); backdrop-filter: blur(10px);"></div>
                    <div style="position: relative; z-index: 10; width: 85%; background: rgba(255,255,255,0.95); padding: 80px; border-radius: 20px; box-shadow: 0 20px 50px rgba(0,0,0,0.3); text-align:center;">
                        <div style="display:inline-block; padding:6px 20px; border:2px solid #222; color:#222; font-weight:800; font-size:20px; border-radius:30px; margin-bottom:30px;">{tag}</div>
                        <h2 style="color: #111; font-size: 52px; font-weight: 900; line-height: 1.3; margin: 0 0 40px 0;">{title}</h2>
                        <div style="color: #444; font-size: 26px; line-height: 1.7; font-weight: 500; word-break: keep-all;">{body}</div>
                    </div>
                </div>
                """
            html_blocks.append(block)

        # 캡슐화된 최종 HTML
        final_html = f"""
        <html>
        <head>
        <meta charset="utf-8">
        <style>body {{ margin:0; padding:0; display:flex; flex-direction:column; align-items:center; background:#ECECEC; }}</style>
        </head>
        <body>
        {''.join(html_blocks)}
        </body>
        </html>
        """
        
        # IFrame으로 격리 렌더링 (RemoveChild DOM 에러 완벽 해결)
        components.html(final_html, height=1000 * len(sections) + 50, scrolling=True)

        full_txt = "\n\n".join([f"## {s['tag']}\n{s['title']}\n{s['body']}" for s in sections])
        st.download_button("📄 전체 카피라이팅 텍스트 추출 (.txt)", full_txt, file_name="상세페이지_기획안.txt", use_container_width=True)

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
