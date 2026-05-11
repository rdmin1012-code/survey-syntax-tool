import streamlit as st

# --- 1. 비밀번호 설정 (원하는 비밀번호로 수정하세요) ---
PASSWORD = "mysecret123" 

def check_password():
    """비밀번호가 맞는지 확인하는 함수"""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 접근 제한")
        user_password = st.text_input("비밀번호를 입력해야 도구를 사용할 수 있습니다.", type="password")
        if st.button("접속하기"):
            if user_password == PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    return True

# --- 2. 메인 실행부 ---
if check_password():
    # 여기서부터 기존 코드가 시작됩니다.
    st.title("📝 ISAS5 신텍스 생성기")
    # ... (기존의 process_html_content 함수와 UI 코드들)
import streamlit as st
import re
from bs4 import BeautifulSoup
import io

# --- [기존 로직 함수들] ---
def clean_text_fully(text):
    if not text: return ""
    cleaned = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
    return re.sub(r'\s+', '', cleaned)

def clean_logic_text(logic_str):
    if not logic_str: return ""
    logic_str = re.sub(r'ID:\s*\d+,\s*Logic:', '', logic_str, flags=re.I)
    return " ".join(logic_str.split()).strip()

def replace_vars_in_logic(logic_raw, q_map):
    if not logic_raw: return ""
    sorted_oids = sorted(q_map.keys(), key=len, reverse=True)
    def subst_func(match):
        oid, suffix, op, val = match.groups()
        rid = q_map.get(oid, oid)
        if suffix and "RK" in suffix.upper():
            rk_num = re.search(r'\d+', suffix)
            return f"{rid}_{rk_num.group() if rk_num else '1'}{op}{val}"
        return f"{rid}{op}{val}"
    pattern = rf"({'|'.join(sorted_oids)})(SA|MA|TN|RK\d+)?(\s*[=<>!]+\s*)(\d+)?"
    return re.sub(pattern, subst_func, logic_raw, flags=re.I)

def get_logic_area_text(node, stop_node):
    txts = [node.get_text()]
    curr = node.next_sibling
    while curr and curr != stop_node:
        if hasattr(curr, 'get_text'): txts.append(curr.get_text())
        curr = curr.next_sibling
    return clean_text_fully("".join(txts))

def process_html_content(content, q_map_option=True):
    soup = BeautifulSoup(content, 'html.parser')
    q_map, page_logic = {}, {}
    
    # 1. 사이드바 매핑
    sidebar = soup.find('ul', id='syncTreeview')
    if sidebar:
        for li in sidebar.find_all('li'):
            link = li.find('a', href=True)
            if not link: continue
            tid = link.get('href').split('#')[-1]
            q_span = li.find('span', class_='questionNumberInformation2') or li.find('span', class_='questionNumberInformation')
            if q_span:
                m = re.search(r'Q(\d+)', q_span.get_text())
                if m: q_map[tid] = f"Q{m.group(1)}"

    # 2. 로직 레이어 수집
    for layer in soup.find_all('fieldset', class_='logicLayer'):
        for item in layer.find_all(['dd', 'div', 'p', 'dt']):
            match = re.search(r'Logic:\s*(.*?)\s*=>\s*Page:\s*(\d+)', item.get_text(), flags=re.I)
            if match: page_logic[match.group(2)] = clean_logic_text(match.group(1))

    # 3. 문항 처리
    final_syntax_omc, final_syntax_cmc = [], []
    items = soup.find_all('div', class_='ISAS5')
    processed_q_ids = set()

    for i, q_div in enumerate(items):
        orig_id = q_div.get('id', '')
        if orig_id in processed_q_ids or not q_map.get(orig_id): continue
        
        q_reordered = q_map[orig_id]
        q_type = str(q_div.get('questtype', '')).strip()
        q_text_div = q_div.find('div', class_='survey_Q')
        q_text = q_text_div.get_text(strip=True) if q_text_div else ""
        name_match = re.search(r'^([A-Z0-9\-]+)', q_text)
        orig_name = name_match.group(1) if name_match else q_reordered

        base_str = ""
        prev_p = q_div.find_previous('span', id=re.compile(r'^P\d+'))
        if prev_p:
            p_num = prev_p.get('id').replace('P', '')
            p_cond = page_logic.get(p_num)
            if p_cond: base_str = f"BASE=({replace_vars_in_logic(p_cond, q_map)}) "

        ts_in = q_div.find_all('input', casetype=re.compile(r'TS', re.I))
        rk_in = q_div.find_all('input', casetype=re.compile(r'RK', re.I))
        textareas = q_div.find_all('textarea')

        # [0순위: 상기도 결합]
        next_q_marker = items[i+1] if i+1 < len(items) else None
        current_logic_area = get_logic_area_text(q_div, next_q_marker)

        if "최초상기" in current_logic_area:
            combined_vars = []
            f_count = max(1, len(ts_in))
            for k in range(f_count): combined_vars.append(f"{q_reordered}_{k+1}")
            j = i + 1
            while j < len(items):
                target_q = items[j]
                nn_item = items[j+1] if j+1 < len(items) else None
                if "비보조상기" in get_logic_area_text(target_q, nn_item):
                    t_rid = q_map.get(target_q.get('id', ''))
                    if t_rid:
                        ts_next = target_q.find_all('input', casetype=re.compile(r'TS', re.I))
                        for k in range(max(1, len(ts_next))): combined_vars.append(f"{t_rid}_{k+1}")
                        processed_q_ids.add(target_q.get('id'))
                    j += 1
                else: break
            final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={' '.join(combined_vars)}.")
            continue

        # 오픈 응답 없는 문항 제외
        if not ts_in and not textareas: continue

        # 일반 단답형 (칸 1개 제외)
        if ts_in and not rk_in and not textareas and q_type not in ["311", "221", "121"]:
            if len(ts_in) >= 2:
                v_list = " ".join([f"{q_reordered}_{k+1}" for k in range(len(ts_in))])
                final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={v_list}.")
            continue

        # 기타 타입 (오픈응답 있을 때만)
        if rk_in: # 순위형
            v_list = " ".join([f"{q_reordered}_{k+1}" for k in range(len(rk_in))])
            final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={v_list}.")
        elif q_type in ["311", "221"] or len(textareas) > 0: # 서술형
            num = len(textareas) or len(ts_in)
            for f_idx in range(1, num + 1):
                final_syntax_omc.append(f"*{q_reordered}({orig_name}) - {f_idx}번.\n!OMC2 {base_str}V={q_reordered}_{f_idx}_1 {q_reordered}_{f_idx}_2 {q_reordered}_{f_idx}_3.")
        elif q_type == "121" and ts_in: # 모두선택형 주관식
            ma_val = ""
            for ts in ts_in:
                parent = ts.find_parent('label')
                linked = parent.find('input', casetype=re.compile(r'MA', re.I)) if parent else None
                if linked: ma_val = linked.get('value', '')
            if ma_val:
                v_ma = " ".join([f"{q_reordered}_{m.get('value')}" for m in q_div.find_all('input', casetype=re.compile(r'MA', re.I))])
                final_syntax_cmc.append(f"*{q_reordered}({orig_name}).\n!CMC2 ETC={q_reordered}_{ma_val} V={v_ma}.")

    res = "*=== [OMC2 SYNTAX] ===.\n\n" + "\n\n".join(final_syntax_omc)
    if final_syntax_cmc:
        res += "\n\n\n*=== [CMC2 SYNTAX] ===.\n\n" + "\n\n".join(final_syntax_cmc)
    return res

# --- [Streamlit 웹 UI 영역] ---
st.set_page_config(page_title="ISAS5 HTML to SPSS Syntax", page_icon="📝")

st.title("📝 ISAS5 신텍스 생성기")
st.markdown("HTML 설문 파일을 업로드하면 **오픈 응답용 SPSS 신텍스**를 즉시 생성합니다.")

uploaded_file = st.file_uploader("HTML 파일을 선택하세요", type=['html', 'htm'])

if uploaded_file is not None:
    # 인코딩 처리
    bytes_data = uploaded_file.read()
    content = None
    for enc in ['euc-kr', 'cp949', 'utf-8-sig', 'utf-8']:
        try:
            content = bytes_data.decode(enc)
            if "ISAS5" in content:
                st.success(f"성공: {enc} 인코딩으로 파일을 읽었습니다.")
                break
        except: continue
    
    if content:
        if st.button("신텍스 생성하기"):
            result_text = process_html_content(content)
            
            st.subheader("생성된 신텍스")
            st.code(result_text, language='text')
            
            # 다운로드 버튼
            st.download_button(
                label="결과 파일 다운로드 (.txt)",
                data=result_text,
                file_name=f"syntax_{uploaded_file.name.split('.')[0]}.txt",
                mime="text/plain"
            )
    else:
        st.error("파일을 읽을 수 없거나 올바른 ISAS5 HTML 파일이 아닙니다.")
