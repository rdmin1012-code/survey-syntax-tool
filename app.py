import streamlit as st
import re
from bs4 import BeautifulSoup
import io

# --- [1. 보안 및 UI 설정] ---
st.set_page_config(page_title="OMC2 CMC2 신텍스 생성", page_icon="📝")

# 비밀번호 설정
PASSWORD = "1234" 

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        st.title("🔒 OMC2 CMC2 신텍스 생성기")
        user_password = st.text_input("비밀번호를 입력해 주세요.", type="password")
        if st.button("접속하기"):
            if user_password == PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다.")
        return False
    return True

# --- [2. 데이터 처리 핵심 로직] ---
def clean_text_fully(text):
    if not text: return ""
    cleaned = text.replace('\xa0', ' ').replace('&nbsp;', ' ')
    return re.sub(r'\s+', '', cleaned)

def clean_logic_text(logic_str):
    if not logic_str: return ""
    logic_str = re.sub(r'ID:\s*\d+,\s*Logic:', '', logic_str, flags=re.I)
    logic_str = re.sub(r'Logic:', '', logic_str, flags=re.I)
    return " ".join(logic_str.split()).strip()

def replace_vars_in_logic(logic_raw, q_map):
    if not logic_raw: return ""
    sorted_oids = sorted(q_map.keys(), key=len, reverse=True)
    def subst_func(match):
        oid, suffix, op, val = match.groups()
        rid = q_map.get(oid, oid)
        if suffix and "MA" in suffix.upper() and val:
            return f"{rid}_{val}{op}{val}"
        elif suffix and "RK" in suffix.upper():
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

def process_html_content(content):
    soup = BeautifulSoup(content, 'html.parser')
    q_map, page_logic = {}, {}
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
    for layer in soup.find_all('fieldset', class_='logicLayer'):
        for item in layer.find_all(['dd', 'div', 'p', 'dt']):
            match = re.search(r'Logic:\s*(.*?)\s*=>\s*Page:\s*(\d+)', item.get_text(), flags=re.I)
            if match: page_logic[match.group(2)] = clean_logic_text(match.group(1))

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
        next_q_marker = items[i+1] if i+1 < len(items) else None
        current_logic_area = get_logic_area_text(q_div, next_q_marker)

        if "최초상기" in current_logic_area:
            combined_vars = []
            for k in range(max(1, len(ts_in))): combined_vars.append(f"{q_reordered}_{k+1}")
            j = i + 1
            while j < len(items):
                target_q = items[j]; nn_item = items[j+1] if j+1 < len(items) else None
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

        if not ts_in and not textareas: continue

        if ts_in and not rk_in and not textareas and q_type not in ["311", "221", "121"]:
            if len(ts_in) >= 2:
                v_list = " ".join([f"{q_reordered}_{k+1}" for k in range(len(ts_in))])
                final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={v_list}.")
            continue

        if rk_in:
            v_list = " ".join([f"{q_reordered}_{k+1}" for k in range(len(rk_in))])
            final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={v_list}.")
            continue

        # --- [서술형(311, 221) 문항 개수별 변수명 로직 수정] ---
        if q_type in ["311", "221"] or len(textareas) > 0:
            num = len(textareas) or len(ts_in)
            if num == 1:
                # 서술형 칸이 하나인 경우 (Q120_1 Q120_2 Q120_3)
                final_syntax_omc.append(f"*{q_reordered}({orig_name}).\n!OMC2 {base_str}V={q_reordered}_1 {q_reordered}_2 {q_reordered}_3.")
            else:
                # 서술형 칸이 여러 개인 경우 (Q120_1_1 Q120_1_2 Q120_1_3...)
                for f_idx in range(1, num + 1):
                    final_syntax_omc.append(f"*{q_reordered}({orig_name}) - {f_idx}번.\n!OMC2 {base_str}V={q_reordered}_{f_idx}_1 {q_reordered}_{f_idx}_2 {q_reordered}_{f_idx}_3.")
            continue

        if q_type == "121" and ts_in:
            ma_val = ""
            for ts in ts_in:
                parent = ts.find_parent('label'); linked = parent.find('input', casetype=re.compile(r'MA', re.I)) if parent else None
                if linked: ma_val = linked.get('value', '')
            if ma_val:
                v_ma = " ".join([f"{q_reordered}_{m.get('value')}" for m in q_div.find_all('input', casetype=re.compile(r'MA', re.I))])
                final_syntax_cmc.append(f"*{q_reordered}({orig_name}).\n!CMC2 ETC={q_reordered}_{ma_val} V={v_ma}.")

    res = "*=== [OMC2 SYNTAX] ===.\n\n" + "\n\n".join(final_syntax_omc)
    if final_syntax_cmc: res += "\n\n\n*=== [CMC2 SYNTAX] ===.\n\n" + "\n\n".join(final_syntax_cmc)
    return res

# --- [3. 메인 실행부] ---
if check_password():
    st.title("📝 OMC2 CMC2 신텍스 생성")
    uploaded_file = st.file_uploader("HTML 파일을 선택하세요", type=['html', 'htm'])
    if uploaded_file is not None:
        bytes_data = uploaded_file.read()
        content = None
        for enc in ['euc-kr', 'cp949', 'utf-8-sig', 'utf-8']:
            try:
                content = bytes_data.decode(enc)
                if "ISAS5" in content: break
            except: continue
        if content:
            with st.spinner('신텍스를 생성 중입니다...'):
                result_text = process_html_content(content)
            st.divider()
            st.subheader("✅ 생성 완료")
            st.code(result_text, language='text')
            st.download_button(label="📄 신텍스 파일 다운로드 (.txt)", data=result_text, file_name=f"syntax_{uploaded_file.name.split('.')[0]}.txt", mime="text/plain")
        else: st.error("올바른 ISAS5 HTML 파일이 아닙니다.")
