import streamlit as st
import os
import pathlib
import json
import datetime
import tempfile
import cryptography.fernet
from google import genai

try:
    import openai
except ImportError:
    openai = None

# ==========================================
# 1. 설정 및 데이터 관리 로직 (기존과 동일하게 연동)
# ==========================================
import platform
if platform.system() == "Windows":
    DATA_DIR = pathlib.Path(os.environ['LOCALAPPDATA']) / "GeminiFileAnalyzer"
else:
    DATA_DIR = pathlib.Path.home() / ".local" / "share" / "GeminiFileAnalyzer"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "config.dat"
KEY_FILE = DATA_DIR / "enc.key"
HISTORY_FILE = DATA_DIR / "history.json" 
MODELS_FILE = DATA_DIR / "models.json"   

DEFAULT_MODELS = {
    "Gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.1-pro-preview"],
    "OpenAI": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    "Ollama": ["llama3", "llama3:8b", "mistral"]
}

DEFAULT_PROMPT = """너는 15년 차 국방 분야 품질 관리(QA) 전문가야. [파일 1]의 양식을 기준으로 [파일 2]를 엄격히 검토한 후, 결과를 서술형 보고서로 작성해 줘.
(※ 만약 기준 파일이 제공되지 않았다면, 일반적인 국방 규격(MIL-SPEC)과 보편적인 QA 기준에 입각하여 [파일 2]를 독립적으로 검토할 것.)

[검토 지침]
- 양식 준수: [파일 1]의 체계와 서식을 [파일 2]가 완벽히 따르는지 대조. (기준 파일이 없으면 자체 양식의 일관성 확인)
- 교정 및 가독성: 맞춤법, 띄어쓰기, 오타를 교정하고, 비문을 다듬어 문서의 명확성 확보.
- 논리 및 정밀성: 수치 오류나 논리적 허점을 짚어내고, 국방 규격(MIL-SPEC) 수준의 단호하고 엄격한 톤 유지.

[출력 형식]
서론(총평) - 본론(기준 준수, 기초 교정, 논리/수치 등 항목별 상세 수정 권고) - 결론(최종 의견) 구조를 갖추고, 단순 나열이 아닌 전문가의 서술형 문장으로 답변할 것."""

# 보안 키 로드
@st.cache_resource
def get_fernet():
    if KEY_FILE.exists():
        with open(KEY_FILE, "rb") as kf:
            key = kf.read()
    else:
        key = cryptography.fernet.Fernet.generate_key()
        with open(KEY_FILE, "wb") as kf:
            kf.write(key)
        if platform.system() == "Windows":
            import subprocess
            subprocess.run(["attrib", "+H", str(KEY_FILE)])
    return cryptography.fernet.Fernet(key)

fernet = get_fernet()

def load_config():
    if not DB_FILE.exists():
        return {"provider": "Gemini", "keys": {}}
    try:
        with open(DB_FILE, "rb") as f:
            encrypted_data = f.read()
        decrypted_str = fernet.decrypt(encrypted_data).decode('utf-8')
        data = json.loads(decrypted_str)
        if "keys" not in data:
            migrated = {"provider": data.get("provider", "Gemini"), "keys": {}}
            migrated["keys"][data.get("provider", "Gemini")] = {
                "api_key": data.get("api_key", ""),
                "base_url": data.get("base_url", "")
            }
            return migrated
        return data
    except:
        return {"provider": "Gemini", "keys": {}}

def save_config(config_data):
    try:
        json_str = json.dumps(config_data)
        encrypted_data = fernet.encrypt(json_str.encode('utf-8'))
        if platform.system() == "Windows" and DB_FILE.exists():
            import subprocess
            subprocess.run(["attrib", "-H", str(DB_FILE)])
        with open(DB_FILE, "wb") as f:
            f.write(encrypted_data)
        if platform.system() == "Windows":
            import subprocess
            subprocess.run(["attrib", "+H", str(DB_FILE)])
        return True
    except Exception as e:
        st.error(f"설정 저장 중 오류: {e}")
        return False

def load_models():
    if MODELS_FILE.exists():
        try:
            with open(MODELS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list): return DEFAULT_MODELS
                return data
        except:
            pass
    return DEFAULT_MODELS

def save_models(models_dict):
    with open(MODELS_FILE, "w", encoding="utf-8") as f:
        json.dump(models_dict, f, ensure_ascii=False, indent=2)

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def add_history(prompt, result):
    history = load_history()
    record = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prompt": prompt,
        "result": result
    }
    history.insert(0, record) 
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def read_text_from_upload(uploaded_file):
    try:
        return uploaded_file.getvalue().decode('utf-8')
    except UnicodeDecodeError:
        try:
            return uploaded_file.getvalue().decode('cp949')
        except:
            return f"[{uploaded_file.name}: 텍스트로 읽을 수 없는 파일입니다.]"

# ==========================================
# 2. 웹페이지 UI (Streamlit)
# ==========================================
st.set_page_config(page_title="AI 질의/응답 프로그램", page_icon="🧠", layout="wide")

# 세션 상태 초기화
if "prompt_text" not in st.session_state:
    st.session_state["prompt_text"] = DEFAULT_PROMPT

config = load_config()
saved_keys = config.get("keys", {})
current_provider = config.get("provider", "Gemini")

all_models = load_models()

# --- 사이드바: 설정 및 이력 관리 ---
with st.sidebar:
    st.title("⚙️ 설정 및 이력")
    
    st.subheader("1. API 설정")
    provider_options = ["Gemini", "OpenAI", "Ollama"]
    sel_provider = st.selectbox("AI 공급자", provider_options, index=provider_options.index(current_provider))
    
    # 공급자가 변경되면 기본값 불러오기
    provider_config = saved_keys.get(sel_provider, {})
    default_key = provider_config.get("api_key", "")
    default_url = provider_config.get("base_url", "")
    
    if sel_provider == "Ollama" and not default_url:
        default_url = "http://localhost:11434/v1"
        default_key = "ollama"

    api_key = st.text_input("API Key", value=default_key, type="password")
    base_url = st.text_input("Base URL (선택)", value=default_url)
    
    if st.button("설정 저장", use_container_width=True):
        saved_keys[sel_provider] = {"api_key": api_key, "base_url": base_url}
        config["provider"] = sel_provider
        config["keys"] = saved_keys
        save_config(config)
        st.success("저장 완료!")
        st.rerun()

    st.divider()

    st.subheader("2. AI 모델 관리")
    current_models_list = all_models.get(sel_provider, DEFAULT_MODELS.get(sel_provider, []))
    new_model = st.text_input(f"{sel_provider} 새 모델 추가:")
    if st.button("추가하기"):
        if new_model and new_model not in current_models_list:
            current_models_list.append(new_model)
            all_models[sel_provider] = current_models_list
            save_models(all_models)
            st.success("추가됨")
            st.rerun()
            
    st.divider()

    st.subheader("3. 이전 분석 이력")
    history_data = load_history()
    if history_data:
        # 전체 이력 다운로드
        full_history_text = "========== [ AI 질의/응답 프로그램 전체 분석 이력 ] ==========\n\n"
        for item in reversed(history_data):
            full_history_text += f"[실행 일시: {item['timestamp']}]\n[명령 프롬프트]\n{item['prompt']}\n\n{'-'*50}\n[분석 결과]\n{item['result']}\n{'='*60}\n\n"
        
        today_str = datetime.datetime.now().strftime("%y%m%d")
        st.download_button("📑 전체 이력 다운로드", data=full_history_text, file_name=f"{today_str}_전체 검토 결과 파일.txt", use_container_width=True)
        
        # 개별 이력 확인
        history_options = ["선택 안함"] + [f"{h['timestamp']} | {h['prompt'][:25]}..." for h in history_data]
        sel_history = st.selectbox("이력 열람", history_options)
        
        if sel_history != "선택 안함":
            idx = history_options.index(sel_history) - 1
            selected_h = history_data[idx]
            hist_date = datetime.datetime.strptime(selected_h['timestamp'], "%Y-%m-%d %H:%M:%S").strftime("%y%m%d")
            
            st.text_area("당시 프롬프트", selected_h['prompt'], height=100, disabled=True)
            st.markdown(f"**결과 요약:** {selected_h['result'][:100]}...")
            
            detail_content = f"[실행 일시: {selected_h['timestamp']}]\n\n[명령 프롬프트]\n{selected_h['prompt']}\n\n{'-'*50}\n[분석 결과]\n{selected_h['result']}"
            st.download_button("💾 이 이력 다운로드", data=detail_content, file_name=f"{hist_date}_선택 이력 검토 결과 파일.txt", use_container_width=True)

# --- 메인 화면 ---
st.title("🧠 AI 질의/응답 프로그램 via Gemini")

col1, col2 = st.columns([1, 2])

with col1:
    st.markdown(f"**현재 공급자:** `{sel_provider}`")
    sel_model = st.selectbox("AI 모델 선택", current_models_list)

use_files = st.toggle("분석할 파일 선택 (끄면 첨부파일 없이 프롬프트만 실행)", value=True)

file1, file2 = None, None
if use_files:
    st.markdown("### 📂 파일 업로드")
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        file1 = st.file_uploader("파일 1 (기준 파일, 선택)", type=["pdf", "docx", "pptx", "xlsx", "txt", "csv"])
    with f_col2:
        file2 = st.file_uploader("파일 2 (검토 파일, 필수)", type=["pdf", "docx", "pptx", "xlsx", "txt", "csv"])

st.markdown("### 📝 명령 프롬프트")
def reset_prompt():
    st.session_state["prompt_text"] = DEFAULT_PROMPT

st.button("초기화", on_click=reset_prompt)
user_prompt = st.text_area("명령을 입력하세요:", value=st.session_state["prompt_text"], height=200)

if st.button("🚀 명령 프롬프트 실행", type="primary", use_container_width=True):
    if use_files and file2 is None:
        st.warning("파일 2(검토 파일)는 필수입니다. 파일을 업로드해주세요.")
        st.stop()
        
    if sel_provider in ["OpenAI", "Ollama"] and openai is None:
        st.error("OpenAI 패키지가 설치되지 않았습니다. 터미널에서 'pip install openai'를 실행하세요.")
        st.stop()

    with st.spinner("AI가 분석을 진행 중입니다. 잠시만 기다려주세요..."):
        try:
            # 공급자 설정 및 인증
            if sel_provider == "Gemini":
                api_client = genai.Client(api_key=api_key)
            else:
                key = api_key if api_key else "dummy-key"
                client_args = {"api_key": key}
                if base_url: client_args["base_url"] = base_url
                api_client = openai.OpenAI(**client_args)

            # 프롬프트 지침 설정 (데스크톱 버전과 동일)
            if sel_provider == "Ollama":
                system_instruction = "You are an expert QA specialist. You MUST provide your complete response in English first, and then provide a complete Korean translation below it."
                enforcement_text = "\n\n[최종 중요 지침: 위에서 요청한 모든 분석 결과와 보고서 내용을 먼저 '영어(English)' 원문으로 상세히 작성하고, 그 아래에 '한국어(Korean)' 번역본을 함께 제공해 주세요.]"
            else:
                system_instruction = "You are an expert QA specialist. You MUST respond entirely in Korean. Never use English for your explanations or reports."
                enforcement_text = "\n\n[최종 중요 지침: 위에서 요청한 모든 분석 결과와 보고서 내용은 반드시 '한국어(Korean)'로만 번역 및 작성해 주세요. 절대 영어로 답변하지 마세요.]"

            final_user_prompt = user_prompt + enforcement_text
            response_text = ""

            # API 호출 로직
            if sel_provider == "Gemini":
                payload = [system_instruction + "\n\n" + final_user_prompt]
                tmp_files = []
                
                # Gemini는 파일을 임시로 로컬에 저장 후 업로드해야 함
                if use_files:
                    for f_obj in [file1, file2]:
                        if f_obj is not None:
                            suffix = os.path.splitext(f_obj.name)[1]
                            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                                tmp.write(f_obj.getvalue())
                                tmp_files.append(tmp.name)
                                uploaded = api_client.files.upload(file=tmp.name)
                                payload.append(uploaded)
                
                response = api_client.models.generate_content(model=sel_model, contents=payload)
                response_text = response.text
                
                # 임시 파일 정리
                for tmp_file in tmp_files:
                    try:
                        os.remove(tmp_file)
                    except:
                        pass

            elif sel_provider in ["OpenAI", "Ollama"]:
                if use_files:
                    file_texts = ""
                    if file1: file_texts += f"\n\n--- [파일 1 내용] ---\n{read_text_from_upload(file1)}"
                    if file2: file_texts += f"\n\n--- [파일 2 내용] ---\n{read_text_from_upload(file2)}"
                    final_user_prompt += file_texts
                
                response = api_client.chat.completions.create(
                    model=sel_model,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": final_user_prompt}
                    ]
                )
                response_text = response.choices[0].message.content

            # 결과 처리 및 저장
            st.success("분석이 완료되었습니다!")
            add_history(user_prompt, response_text)
            
            st.markdown("### 📊 분석 결과")
            st.info(response_text)
            
            # 단일 결과 다운로드
            today = datetime.datetime.now().strftime("%y%m%d")
            st.download_button("💾 결과 파일로 저장", data=response_text, file_name=f"{today}_분석 검토 결과 파일.txt", type="primary")

        except Exception as e:
            error_msg = str(e)
            if "404" in error_msg and "not found" in error_msg.lower():
                error_msg += f"\n\n💡 팁: 컴퓨터에 '{sel_model}' 모델이 설치되지 않았습니다. 터미널에 'ollama pull {sel_model}'를 입력하세요."
            elif "Connection error" in error_msg or "Failed to connect" in error_msg:
                error_msg += "\n\n💡 팁: Ollama 프로그램이 켜져 있는지 확인하세요."
            st.error(f"오류 발생: {error_msg}")