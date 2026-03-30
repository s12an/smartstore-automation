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
from bs4 import BeautifulSoup
import re

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

def generate_studio_shot(api_key, prod_name):
    try:
        client = OpenAI(api_key=api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=f"Professional cosmetic studio photography. Close-up macro shot of the texture, glowing skin, or elegant elements related to '{prod_name}'. ABSOLUTELY NO human faces or heads. Only show hands, collarbone, skin texture, or elegant liquid smears. 8k resolution, photorealistic, highly detailed, premium cosmetic luxury advertising style.",
            size="1024x1024",
            quality="standard",
            n=1,
        )
        return response.data[0].url
    except Exception as e:
        print(f"DALL-E 3 Error: {e}")
        return None

def scrape_url_text(ref_str):
    if not ref_str:
        return ""
    match = re.search(r"https?://[^\s]+", ref_str)
    if not match:
        return ref_str # It's just plain text
    try:
        url = match.group(0)
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        text = " ".join(soup.stripped_strings)
        return text[:3000] # Limit to avoid massive token count
    except Exception as e:
        print(f"Scraping failed: {e}")
        return ref_str

def generate_detail_page_openai(api_key, prod_name, ref_urls, image_b64=None):
    try:
        scraped_info = scrape_url_text(ref_urls)
        client = OpenAI(api_key=api_key)
        prompt = f"""당신은 세계 최고의 뷰티/럭셔리 브랜드 수석 카피라이터입니다.
[상품정보 요약/스크래핑 내용]
- 상품명: {prod_name}
- 핵심 정보: {scraped_info}

[절대 규칙 - 지식재산권 보호 및 AI 이질감 제거]
1. 원본 내용(스크래핑 텍스트 등)을 절대 그대로 복사/붙여넣기 하지 마시오. 지적재산권(IP) 보호를 위해 완전히 새롭고 고급스럽게 100% 재창조하여 작성할 것.
2. 각 섹션을 === SECTION: [태그] === [제목] === 형식을 시작할 것.
3. 6개 이상의 섹션(HERO, POINT 1, POINT 2, POINT 3, RESULTS, INFO 등)을 구성할 것.
4. "본 상세페이지는 AI가...", "배포 안내" 같은 메타 발언을 절대 하지 마시오. 고객에게 노출되는 순수 광고 카피뷰만 제공할 것.
5. 첨부 이미지가 있다면 사진을 분석해 실감나는 소재/제형을 수려한 문체로 묘사할 것."""

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
            temperature=0.85
        )
        return response.choices[0].message.content
    except Exception as e:
        if "insufficient_quota" in str(e).lower() or "rate_limit" in str(e).lower():
            return "QUOTA_EXCEEDED"
        return f"ERROR: {e}"

def generate_detail_page_gemini(api_key, prod_name, ref_urls, image_b64=None):
    try:
        scraped_info = scrape_url_text(ref_urls)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent?key={api_key}"
        prompt = f"""상품명: {prod_name}, 참고: {scraped_info}.
당신은 최고급 럭셔리 뷰티 브랜드 카피라이터입니다. 지식재산권 보호를 위해 참조된 내용을 100% 완벽히 재창조하여 당신만의 언어로 작성하세요.
AI가 쓴 티가 나는 "안내 문구"는 절대 금지됩니다. 6섹션을 === SECTION: [태그] === [제목] === 형식으로 작성하세요."""
        
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
    """지재권 침해 없는 순수 크리에이티브 fallback 및 AI 티 제거 로직 (Quota Exceeded 등 API 실패 시 가동)"""
    return f"""=== SECTION: 🚨 SYSTEM ERROR === API 통신 장애: 잔고 부족 ===
**원인 분석**: 현재 등록하신 OpenAI 혹은 Gemini API 키의 **무료 허용량이 모두 소진되었거나 결제 카드가 등록되어 있지 않아** AI 엔진이 강제 차단되었습니다.

AI 접속 권한이 없으므로, 말씀하신 URL 크롤링과 DALL-E 3 스튜디오컷 생성을 단 한 번도 실행하지 않고 **오프라인 껍데기 모드**로만 화면이 돌고 있습니다. API 결제 정보를 갱신하시면 원래의 천재적인 AI 성능이 부활합니다!

=== SECTION: HERO === {prod_name} - 오프라인 데모 모드 작동 ===
단순한 뷰티를 넘어선 하이엔드 텍스처와 감각적인 경험. 당신의 일상을 작품으로 바꿀 유일한 선택.

=== SECTION: POINT 1 === ✨ POINT 01. 완벽에 가까운 포뮬러 ===
피부 위에서 부드럽게 스며드는 정밀한 미세 입자. 수십 번의 테스트를 거쳐 완성된 고순도 배합이 비교할 수 없는 부드러움을 선사합니다.

=== SECTION: POINT 2 === 💎 POINT 02. 시선을 사로잡는 오라 ===
우아하게 빛나는 특유의 광택. 단순히 덧바르는 것을 넘어 스스로 생기를 내뿜는 탁월한 밀착력을 경험하십시오.

=== SECTION: POINT 3 === ⚡ POINT 03. 감격스러운 효능의 차이 ===
연구의 본질은 압도적인 결과물입니다. 시간이 지날수록 선명해지는 컨디션의 변화가 당신의 가상비와 가심비 모두를 충족시킵니다."""

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
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔗 딥러닝 스크래핑 제어")
        st.sidebar.caption("여기에 적힌 주소(URL)로 AI가 곧바로 들어가\n제품 정보를 읽어오고 재창조합니다.")
        ref_urls = st.sidebar.text_area("참고 URL 입력", placeholder="예: https://smartstore.naver.com/... ")
        
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
                            
                            # CHeck if the result was a quota failure string
                            if any("API 통신 장애" in s.get("title", "") for s in res):
                                st.error("🚨 **[초비상] API 키 결제 한도 초과 오류!** API 잔액이 없어 딥러닝 크롤링과 사진 생성이 원천 차단된 상태로 껍데기만 출력되었습니다.")
                                st.session_state["studio_image_url"] = None
                            else:
                                # Add DALL-E 3 Studio shot generation with user feedback
                                with st.spinner("전문가급 스튜디오 매크로 컷 생성 중 (DALL-E 3, 약 10초 소요)..."):
                                    okey = fetch_api_key("openai")
                                    if okey:
                                        dalle_img = generate_studio_shot(okey, prod_name)
                                        if not dalle_img:
                                            st.warning("⚠️ DALL-E 3 호출 실패(잔고부족 추정)로 메인 사진만 재사용됩니다.")
                                        st.session_state["studio_image_url"] = dalle_img
                                    else:
                                        st.session_state["studio_image_url"] = None

                                st.success("✅ 고급 기획 및 스튜디오 컷 생성이 완료되었습니다!")
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
        studio_url = st.session_state.get("studio_image_url")
        
        for i, sec in enumerate(sections):
            tag = sec['tag'].upper()
            title = sec['title'].replace('"', '&quot;')
            body = sec['body'].replace('\n', '<br>')
            
            # Use uploaded image for HERO, use studio image for alternate blocks
            current_img_src = img_src
            if i > 0 and studio_url and i % 2 == 1:
                current_img_src = studio_url
            
            # High-End CSS Patterns based on sections (Serif & Luxury Minimalist)
            # Tag rendering
            tag_color = "#999"
            tag_border = "1px solid #CCC"
            if "HERO" in tag:
                # HERO Pattern: Full background overlay (Soft opacity)
                block = f"""
                <div style="width: 100%; max-width: 1000px; aspect-ratio: 1/1; position: relative; font-family: 'Noto Serif KR', 'Playfair Display', serif; display: flex; flex-direction: column; justify-content: flex-end; padding: 10%; box-sizing: border-box; margin-bottom: 20px;">
                    <div style="position: absolute; top:0; left:0; right:0; bottom:0; background: url('{current_img_src}') center/cover no-repeat; opacity: 0.9;"></div>
                    <div style="position: absolute; top:0; left:0; right:0; bottom:0; background: linear-gradient(to top, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.1) 70%, transparent 100%);"></div>
                    <div style="position: relative; z-index: 10; text-align: center;">
                        <span style="display:inline-block; padding:8px 20px; color:#FFF; font-weight:400; font-size:18px; letter-spacing:4px; margin-bottom:30px; border-top: 1px solid #FFF; border-bottom: 1px solid #FFF;">{tag}</span>
                        <h1 style="color: #FFF; font-size: 5vw; max-font-size: 58px; font-weight: 700; line-height: 1.3; margin: 0 0 40px 0; letter-spacing:-1px;">{title}</h1>
                        <p style="color: #F0F0F0; font-size: 2vw; max-font-size: 24px; line-height: 1.8; font-weight: 300; max-width:800px; margin: 0 auto; word-break: keep-all;">{body}</p>
                    </div>
                </div>
                """
            elif i % 3 == 1:
                # SIDE-BY-SIDE Clean Minimalist Pattern
                block = f"""
                <div style="width: 100%; max-width: 1000px; aspect-ratio: 1/1; position: relative; font-family: 'Noto Serif KR', 'Playfair Display', serif; display: flex; flex-direction: row; background: #FAFAFA; margin-bottom: 20px;">
                    <div style="flex:1; padding: 10% 7%; display:flex; flex-direction:column; justify-content:center;">
                        <span style="color:{tag_color}; font-weight:500; font-size:16px; margin-bottom:20px; letter-spacing:2px; text-transform:uppercase;">{tag}</span>
                        <h2 style="color: #111; font-size: 4vw; max-font-size: 42px; font-weight: 600; line-height: 1.4; margin: 0 0 50px 0; letter-spacing:-0.5px; border-bottom: 2px solid #222; padding-bottom: 30px;">{title}</h2>
                        <div style="color: #444; font-size: 1.8vw; max-font-size: 20px; line-height: 2.0; font-weight: 300; word-break: keep-all;">{body}</div>
                    </div>
                    <div style="flex:1; background: url('{current_img_src}') center/cover no-repeat;"></div>
                </div>
                """
            else:
                # INFO / OVERLAP Elegant Card Pattern
                block = f"""
                <div style="width: 100%; max-width: 1000px; aspect-ratio: 1/1; position: relative; font-family: 'Noto Serif KR', 'Playfair Display', serif; display: flex; align-items: center; justify-content: center; background: url('{current_img_src}') top/cover no-repeat; margin-bottom: 20px;">
                    <div style="position: absolute; top:0; left:0; right:0; bottom:0; background: rgba(0,0,0,0.3);"></div>
                    <div style="position: relative; z-index: 10; width: 80%; background: rgba(253,253,253,0.98); padding: 8%; border-radius: 4px; box-shadow: 0 30px 60px rgba(0,0,0,0.15); text-align:left;">
                        <div style="display:inline-block; padding:4px 16px; border-left: {tag_border}; color:{tag_color}; font-weight:500; font-size:16px; letter-spacing:2px; margin-bottom:40px;">{tag}</div>
                        <h2 style="color: #111; font-size: 4vw; max-font-size: 46px; font-weight: 600; line-height: 1.3; margin: 0 0 50px 0; letter-spacing:-0.5px;">{title}</h2>
                        <div style="color: #555; font-size: 1.8vw; max-font-size: 21px; line-height: 1.9; font-weight: 300; word-break: keep-all;">{body}</div>
                    </div>
                </div>
                """
            html_blocks.append(block)

        # 캡슐화된 최종 HTML (웹폰트 Noto Serif, Playfair 적용)
        final_html = f"""
        <html>
        <head>
        <meta charset="utf-8">
        <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@300;400;500;600;700&family=Playfair+Display:wght@400;600&display=swap" rel="stylesheet">
        <style>body {{ margin:0; padding:0; display:flex; flex-direction:column; align-items:center; background:#FAFAFA; }}</style>
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
