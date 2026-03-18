# 스마트스토어 상세페이지 자동화 시스템

이 프로젝트는 2인(사장님, 직원)이 함께 사용할 수 있는 프라이빗 웹 서비스입니다. Streamlit 단일 앱으로 구성되어 있으며, 데이터베이스 및 인증은 Supabase를 활용합니다. 상품의 기본 정보만 입력하면 OpenAI API를 통해 스마트스토어 상세페이지 에 사용할 마크다운/HTML을 자동 생성합니다.

## 시스템 요구사항
- Python 3.9+
- [Supabase](https://supabase.com/) 계정 및 프로젝트

## 로컬 실행 방법
1. 필요 패키지 설치:
   ```bash
   pip install -r requirements.txt
   ```
2. 시크릿 설정 파일 이름 변경 및 값 기입:
   - `.streamlit/secrets.example.toml` 파일을 `.streamlit/secrets.toml` 로 복사합니다.
   - Supabase 대시보드에서 발급받은 `URL` 및 `anon API Key`를 입력합니다.
3. Streamlit 앱 실행:
   ```bash
   streamlit run main.py
   ```

## Supabase 초기 셋업 (스키마)

Supabase 프로젝트를 생성한 후 **SQL Editor**에 다음 SQL을 복사하여 실행하세요.

```sql
-- 사용자 프로필 테이블 (Supabase Auth와 연동)
CREATE TABLE IF NOT EXISTS public.user_profiles (
  id UUID REFERENCES auth.users(id) PRIMARY KEY,
  email TEXT,
  name TEXT,
  role TEXT DEFAULT 'user', -- 'admin' 또는 'user'
  created_at TIMESTAMP DEFAULT NOW(),
  last_login TIMESTAMP,
  is_active BOOLEAN DEFAULT TRUE
);

-- 작업 내역 테이블
CREATE TABLE IF NOT EXISTS public.job_history (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id),
  product_name TEXT,
  reference_url TEXT,
  template_used TEXT,
  status TEXT DEFAULT 'pending',
  generated_html TEXT,
  ai_image_url TEXT,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  is_shared BOOLEAN DEFAULT FALSE
);

-- API 키 저장 테이블 (공통, 관리자만 수정 가능)
CREATE TABLE IF NOT EXISTS public.api_keys (
  id SERIAL PRIMARY KEY,
  service_name TEXT UNIQUE, -- 'naver', 'openai'
  api_key TEXT, -- 암호화 저장
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 초대 코드 저장 테이블 (간단히 하나만 사용)
CREATE TABLE IF NOT EXISTS public.invite_codes (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE,
  description TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);
-- 기본 초대 코드 삽입 (예: 'SMART123')
INSERT INTO public.invite_codes (code, description) VALUES ('SMART123', '사장님 초대 코드');
```

## Streamlit Community Cloud 배포
1. 깃허브 저장소에 코드를 Push합니다. (주의: `secrets.toml`은 올리지 마세요.)
2. [Streamlit Community Cloud](https://share.streamlit.io/)에 로그인하여 `New app`을 생성합니다.
3. 해당 저장소와 `main.py` 리포지토리를 연결하고, **Advanced settings**의 **Secrets** 란에 `.streamlit/secrets.toml` 내용을 그대로 붙여넣습니다.
4. Deploy 버튼을 눌러 배포를 완료합니다.
