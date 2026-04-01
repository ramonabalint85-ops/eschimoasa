import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yfinance as yf
from fpdf import FPDF
import time
import numpy as np
import PyPDF2
import json
import base64
from openai import OpenAI
from geopy.geocoders import Nominatim
import os
import re
import requests
from datetime import datetime, timedelta
from functools import lru_cache

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Supporto alla Rendicontazione PMI", layout="wide")

# --- CACHE PERSISTENTE E THROTTLING (Anti-Rate-Limiting) ---
CACHE_DIR = ".yfinance_cache"
CACHE_TIMEOUT_HOURS = 24
THROTTLE_DELAY = 2
PROJECTS_DIR = ".saved_projects"

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(PROJECTS_DIR, exist_ok=True)

PROJECT_STATE_KEYS = [
    'revenue', 'opex', 'totale_attivo', 'dipendenti', 'company_name', 'quotata',
    'sector', 'industry', 'selected_country', 'scope1', 'scope2', 'scope3',
    'perc_red', 'em_final', 'rata_prestito', 'policy_multiplier', 'capex_totale',
    'tax_portfolio', 'cbam_portfolio', 'gap_answers', 'impresa_area',
    'sucursale_eu_200', 'hq_address', 'hq_geocoded_address', 'hq_lat', 'hq_lon',
    'status_normativo', 'vsme_module_choice', 'deliverable_type',
    'b1_info_omesse', 'b1_info_omesse_quali', 'b1_perimetro',
    'ragione_sociale', 'codice_nace_ateco', 'b1_paese_operazioni_asset_significativi'
]


def sanitize_project_name(project_name):
    sanitized = re.sub(r'[^A-Za-z0-9._ -]+', '', str(project_name)).strip()
    sanitized = re.sub(r'\s+', '_', sanitized)
    return sanitized[:80] or f"progetto_{int(time.time())}"


def get_project_file(project_name):
    return os.path.join(PROJECTS_DIR, f"{sanitize_project_name(project_name)}.json")


def format_unbounded_number(value):
    if value in (None, ""):
        return "0"
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric_value.is_integer():
        return f"{int(numeric_value):,}".replace(",", ".")

    formatted = f"{numeric_value:,.2f}"
    integer_part, decimal_part = formatted.split(".")
    integer_part = integer_part.replace(",", ".")
    decimal_part = decimal_part.rstrip('0')
    if not decimal_part:
        return integer_part
    return f"{integer_part},{decimal_part}"


def parse_unbounded_number(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return 0

    cleaned = re.sub(r"[€\s_]", "", text)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        integer_part, decimal_part = cleaned.rsplit(",", 1)
        if decimal_part.isdigit() and len(decimal_part) <= 2:
            cleaned = f"{integer_part}.{decimal_part}"
        else:
            cleaned = cleaned.replace(",", "")

    try:
        numeric_value = float(cleaned)
    except ValueError:
        return None

    if numeric_value.is_integer():
        return int(numeric_value)
    return numeric_value


def sync_formatted_number_input(display_key, value_key, allow_float):
    parsed_value = parse_unbounded_number(st.session_state.get(display_key, ""))
    if parsed_value is None:
        return

    if not allow_float:
        parsed_value = int(parsed_value)

    st.session_state[value_key] = parsed_value
    st.session_state[display_key] = format_unbounded_number(parsed_value)


def unbounded_number_input(label, value_key, display_key, help=None, placeholder=None, allow_float=True):
    current_value = st.session_state.get(value_key, 0)
    formatted_value = format_unbounded_number(current_value)
    if display_key not in st.session_state:
        st.session_state[display_key] = "" if current_value == 0 else formatted_value
    else:
        parsed_display_value = parse_unbounded_number(st.session_state[display_key])
        if parsed_display_value == current_value and st.session_state[display_key] != formatted_value:
            st.session_state[display_key] = "" if current_value == 0 else formatted_value

    st.text_input(
        label,
        key=display_key,
        help=help,
        placeholder=placeholder,
        on_change=sync_formatted_number_input,
        args=(display_key, value_key, allow_float),
    )
    return st.session_state.get(value_key, 0)


def _to_json_safe(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def serialize_dataframe(df):
    if df is None:
        return {"columns": [], "records": []}
    safe_df = df.copy()
    for column in safe_df.columns:
        safe_df[column] = safe_df[column].map(_to_json_safe)
    return {
        "columns": list(safe_df.columns),
        "records": safe_df.to_dict(orient='records')
    }


def deserialize_dataframe(payload):
    if not payload:
        return pd.DataFrame()
    records = payload.get("records", [])
    columns = payload.get("columns", [])
    if not records and columns:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(records, columns=columns or None)


def serialize_gap_documents(documents):
    serialized = {}
    for key, doc in (documents or {}).items():
        if not isinstance(doc, dict):
            continue
        binary_data = doc.get('data', b'') or b''
        if isinstance(binary_data, str):
            binary_data = binary_data.encode('utf-8')
        serialized[key] = {
            'filename': doc.get('filename', ''),
            'timestamp': doc.get('timestamp', ''),
            'data_b64': base64.b64encode(binary_data).decode('ascii') if binary_data else '',
        }
    return serialized


def deserialize_gap_documents(payload):
    documents = {}
    for key, doc in (payload or {}).items():
        if not isinstance(doc, dict):
            continue
        encoded_data = doc.get('data_b64', '')
        documents[key] = {
            'filename': doc.get('filename', ''),
            'timestamp': doc.get('timestamp', ''),
            'data': base64.b64decode(encoded_data) if encoded_data else b'',
        }
    return documents


def serialize_vsme_disclosure_tables(tables):
    return {
        key: serialize_dataframe(df)
        for key, df in (tables or {}).items()
        if isinstance(df, pd.DataFrame)
    }


def deserialize_vsme_disclosure_tables(payload):
    return {
        key: deserialize_dataframe(df_payload)
        for key, df_payload in (payload or {}).items()
    }


def build_project_payload(project_name):
    state = {key: _to_json_safe(st.session_state.get(key)) for key in PROJECT_STATE_KEYS}
    state['portfolio_df'] = serialize_dataframe(st.session_state.get('portfolio_df', pd.DataFrame()))
    state['gap_documents'] = serialize_gap_documents(st.session_state.get('gap_documents', {}))
    state['vsme_disclosure_tables'] = serialize_vsme_disclosure_tables(st.session_state.get('vsme_disclosure_tables', {}))
    return {
        'project_name': project_name,
        'saved_at': datetime.now().isoformat(),
        'state': state,
    }


def normalize_project_payload(payload, fallback_name=None):
    state = payload.get('state', {}) if isinstance(payload, dict) else {}
    project_name = payload.get('project_name') if isinstance(payload, dict) else None
    normalized_name = project_name or fallback_name or f"progetto_{int(time.time())}"
    return {
        'project_name': normalized_name,
        'saved_at': (payload.get('saved_at') if isinstance(payload, dict) else None) or datetime.now().isoformat(),
        'state': state,
    }


def project_signature_from_payload(payload):
    return json.dumps(payload.get('state', {}), ensure_ascii=False, sort_keys=True)


def register_saved_project(payload):
    st.session_state['current_project_name'] = payload.get('project_name', '')
    st.session_state['last_project_saved_at'] = payload.get('saved_at', '')
    st.session_state['project_name_input'] = st.session_state['current_project_name']
    st.session_state['last_project_signature'] = project_signature_from_payload(payload)


def save_project_payload(payload):
    normalized_payload = normalize_project_payload(payload)
    with open(get_project_file(normalized_payload['project_name']), 'w', encoding='utf-8') as handle:
        json.dump(normalized_payload, handle, ensure_ascii=False, indent=2)
    register_saved_project(normalized_payload)
    return normalized_payload


def save_project(project_name):
    payload = build_project_payload(project_name)
    return save_project_payload(payload)


def list_saved_projects():
    projects = []
    for filename in sorted(os.listdir(PROJECTS_DIR)):
        if not filename.endswith('.json'):
            continue
        file_path = os.path.join(PROJECTS_DIR, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            projects.append({
                'label': payload.get('project_name') or filename[:-5],
                'file_path': file_path,
                'saved_at': payload.get('saved_at', ''),
            })
        except Exception:
            projects.append({
                'label': filename[:-5],
                'file_path': file_path,
                'saved_at': '',
            })
    return projects


def load_project_payload(payload, fallback_name=None):
    normalized_payload = normalize_project_payload(payload, fallback_name=fallback_name)
    state = normalized_payload.get('state', {})
    for key in PROJECT_STATE_KEYS:
        if key in state:
            st.session_state[key] = state[key]

    loaded_portfolio_df = deserialize_dataframe(state.get('portfolio_df'))
    if not loaded_portfolio_df.empty:
        st.session_state['portfolio_df'] = process_portfolio_dataframe(
            loaded_portfolio_df.drop(columns=['Display_Size', 'Risk_Score'], errors='ignore')
        )
    else:
        st.session_state['portfolio_df'] = pd.DataFrame()
    st.session_state['gap_documents'] = deserialize_gap_documents(state.get('gap_documents'))
    st.session_state['vsme_disclosure_tables'] = deserialize_vsme_disclosure_tables(state.get('vsme_disclosure_tables'))
    register_saved_project(normalized_payload)

    for key in list(st.session_state.keys()):
        if key.startswith('editor_vsme_table_') or key.startswith('show_pdf_'):
            del st.session_state[key]

    for answer_key, answer_data in st.session_state.get('gap_answers', {}).items():
        if isinstance(answer_data, dict) and 'ans' in answer_data:
            st.session_state[answer_key] = answer_data['ans']


def load_project(project_option):
    with open(project_option['file_path'], 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    load_project_payload(payload, fallback_name=project_option['label'])


def import_project(uploaded_file):
    raw_payload = json.loads(uploaded_file.getvalue().decode('utf-8'))
    fallback_name = os.path.splitext(uploaded_file.name)[0]
    normalized_payload = normalize_project_payload(raw_payload, fallback_name=fallback_name)
    saved_payload = save_project_payload(normalized_payload)
    load_project_payload(saved_payload, fallback_name=saved_payload['project_name'])
    return saved_payload


def autosave_project_if_needed(project_name):
    if not st.session_state.get('project_autosave_enabled', True):
        return False
    normalized_name = sanitize_project_name(project_name)
    if not normalized_name:
        return False

    payload = build_project_payload(project_name)
    current_signature = project_signature_from_payload(payload)
    if current_signature == st.session_state.get('last_project_signature'):
        return False

    save_project_payload(payload)
    return True


def delete_project(project_option):
    if os.path.exists(project_option['file_path']):
        os.remove(project_option['file_path'])

def get_cache_file(ticker):
    """Restituisce il percorso del file cache per un ticker"""
    return os.path.join(CACHE_DIR, f"{ticker.upper()}_cache.json")

def is_cache_valid(ticker):
    """Controlla se la cache è ancora valida"""
    cache_file = get_cache_file(ticker)
    if not os.path.exists(cache_file):
        return False
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            timestamp = datetime.fromisoformat(cache_data.get('timestamp', '2020-01-01'))
            age_hours = (datetime.now() - datetime.fromisoformat(cache_data.get('timestamp'))).total_seconds() / 3600
            return age_hours < CACHE_TIMEOUT_HOURS
    except:
        return False

def load_from_cache(ticker):
    """Carica dati dalla cache locale"""
    cache_file = get_cache_file(ticker)
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)['data']
    except:
        return None

def save_to_cache(ticker, data):
    """Salva dati nella cache locale"""
    cache_file = get_cache_file(ticker)
    cache_data = {
        'ticker': ticker.upper(),
        'timestamp': datetime.now().isoformat(),
        'data': data
    }
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except:
        pass

def retry_with_backoff(func, ticker, max_retries=3):
    """Riprova con exponential backoff"""
    for attempt in range(max_retries):
        try:
            time.sleep(THROTTLE_DELAY)
            result = func(ticker)
            if result:
                return result
        except requests.exceptions.ConnectionError:
            wait_time = (2 ** attempt)
            if attempt < max_retries - 1:
                st.info(f"⏳ Tentativo {attempt + 1}/{max_retries}... (attesa {wait_time}s)")
                time.sleep(wait_time)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

# --- FUNZIONI YFINANCE CON CACHE ---
@lru_cache(maxsize=128)
def _fetch_from_yfinance(ticker):
    """Fetch da yfinance (interno, con caching LRU)"""
    try:
        company = yf.Ticker(ticker)
        info = company.info
        
        data = {
            'ticker': ticker.upper(),
            'company_name': info.get('longName', 'N/A'),
            'country': info.get('country', 'N/A'),
            'sector': info.get('sector', 'N/A'),
            'industry': info.get('industry', 'N/A'),
            'website': info.get('website', 'N/A'),
            'total_assets': info.get('totalAssets', 0),
            'revenue': info.get('totalRevenue', 0),
            'operating_expense': info.get('operatingExpense', 0),
            'capex': info.get('capitalExpenditure', 0),
            'employees': info.get('fullTimeEmployees', 0),
            'margin': info.get('operatingMargins', 0),
            'currency': info.get('currency', 'EUR'),
            'source': 'yfinance'
        }
        return data
    except Exception as e:
        return None

def get_company_info(ticker):
    """Recupera i dati dell'azienda con cache e retry"""
    ticker = ticker.upper()
    
    # 1. Prova cache locale
    if is_cache_valid(ticker):
        cached_data = load_from_cache(ticker)
        if cached_data:
            return cached_data
    
    # 2. Prova a scaricare da yfinance con retry
    result = retry_with_backoff(_fetch_from_yfinance, ticker)
    
    if result:
        save_to_cache(ticker, result)
        return result
    
    # 3. Fallback a cache anche se scaduta
    cached_data = load_from_cache(ticker)
    if cached_data:
        return cached_data
    
    return None

# --- CONFIGURAZIONE PAGINA (originale) ---

# --- COSTANTI VSME ---
VSME_SCALE_OPTIONS = ["Sì", "Sì, ma con integrazione necessaria", "No, ma pianificato", "No"]
VSME_PLOT_RESPONSE_ORDER = ["SI", "Si, ma necessita", "No ma pianificato", "No"]


def to_vsme_plot_response_label(answer):
    normalized = str(answer or "").strip().lower()
    if normalized in {"sì", "si", "yes"}:
        return "SI"
    if "integrazione" in normalized or "integration" in normalized:
        return "Si, ma necessita"
    if normalized.startswith("no") and ("pianific" in normalized or "planned" in normalized):
        return "No ma pianificato"
    if normalized.startswith("no"):
        return "No"
    return str(answer or "").strip()
VSME_DEFAULT_FILE = "Gap Analysis Template_VSME_Standard_Tool v3.xlsx"
VSME_DATA_COLLECTION_FILE = "Raccolta dati VSME_Template app.xlsx"
VSME_DISCLOSURE_PILLARS = {
    "GEN": ["B1", "B2", "C1", "C2"],
    "E": ["B3", "B4", "B5", "B6", "B7", "C3", "C4"],
    "S": ["B8", "B9", "B10", "C5", "C6", "C7"],
    "G": ["B11", "C8", "C9"],
}


def _vsme_code_sort_key(code):
    match = re.match(r'([BC])(\d+)', str(code).strip())
    if not match:
        return (99, str(code))
    module_rank = 0 if match.group(1) == "B" else 1
    return (module_rank, int(match.group(2)))


def _extract_excel_preview(ws, start_row=1, end_row=None, max_cols=12, max_rows=None):
    if end_row is None:
        end_row = ws.max_row

    row_values = []
    for row_idx in range(start_row, end_row + 1):
        values = [ws.cell(row_idx, col_idx).value for col_idx in range(1, max_cols + 1)]
        if any(value not in (None, "") for value in values):
            row_values.append(values)

    if not row_values:
        return pd.DataFrame()

    max_non_empty_col = 0
    for values in row_values:
        for idx, value in enumerate(values, start=1):
            if value not in (None, ""):
                max_non_empty_col = max(max_non_empty_col, idx)

    trimmed_rows = []
    visible_rows = row_values if max_rows is None else row_values[:max_rows]
    for values in visible_rows:
        trimmed_rows.append([
            "" if value is None else str(value).strip()
            for value in values[:max_non_empty_col]
        ])

    column_labels = [chr(64 + idx) for idx in range(1, max_non_empty_col + 1)]
    return pd.DataFrame(trimmed_rows, columns=column_labels)


def _extract_disclosure_preview(ws, code, max_cols=12, max_rows=None):
    code_starts = {}
    for row_idx in range(1, min(ws.max_row, 200) + 1):
        for col_idx in range(1, 4):
            value = ws.cell(row_idx, col_idx).value
            if not isinstance(value, str):
                continue
            match = re.match(r'^([BC]\d+)(?:\b|[\s\-.])', value.strip())
            if match and match.group(1) not in code_starts:
                code_starts[match.group(1)] = row_idx

    if code in code_starts:
        start_row = code_starts[code]
        following_starts = [row for item_code, row in code_starts.items() if item_code != code and row > start_row]
        end_row = min(following_starts) - 1 if following_starts else ws.max_row
        return _extract_excel_preview(ws, start_row=start_row, end_row=end_row, max_cols=max_cols, max_rows=max_rows)

    return _extract_excel_preview(ws, max_cols=max_cols, max_rows=max_rows)


@st.cache_data
def load_vsme_disclosure_reference(gap_file_path=VSME_DEFAULT_FILE, data_collection_path=VSME_DATA_COLLECTION_FILE):
    try:
        import openpyxl

        gap_wb = openpyxl.load_workbook(gap_file_path, data_only=True)
        data_wb = openpyxl.load_workbook(data_collection_path, data_only=True)

        disclosure_catalog = {pillar: [] for pillar in VSME_DISCLOSURE_PILLARS}
        section_names = {
            "GEN": {"general information", "general information "},
            "E": {"envi metrics", "environmental"},
            "S": {"social metrics", "social"},
            "G": {"governance metrics", "governance"},
        }

        sheet2 = gap_wb["Sheet2"]
        for pillar, codes in VSME_DISCLOSURE_PILLARS.items():
            code_details = {}
            for row in sheet2.iter_rows(min_row=2, values_only=True):
                _, _, section, disclosure_code, disclosure_title, item_type = row[:6]
                if not section or not disclosure_code or str(disclosure_code).strip() not in codes:
                    continue

                normalized_section = re.sub(r'\s+', ' ', str(section).strip().lower())
                if normalized_section not in section_names[pillar]:
                    continue

                code = str(disclosure_code).strip()
                item = code_details.setdefault(code, {
                    "code": code,
                    "title": str(disclosure_title).strip(),
                    "datapoints": 0,
                })
                if str(item_type).strip().lower() == "datapoint":
                    item["datapoints"] += 1

            for code in codes:
                if code not in code_details:
                    continue

                sheet_names = []
                for sheet_name in data_wb.sheetnames:
                    if re.search(rf'^{re.escape(code)}(?:$|[-_])', sheet_name, flags=re.IGNORECASE):
                        sheet_names.append(sheet_name)

                tables = []
                for sheet_name in sheet_names:
                    preview = _extract_disclosure_preview(data_wb[sheet_name], code)
                    if preview.empty:
                        continue
                    tables.append({
                        "sheet_name": sheet_name,
                        "data": preview,
                    })

                disclosure_catalog[pillar].append({
                    "code": code,
                    "title": code_details[code]["title"],
                    "datapoints": code_details[code]["datapoints"],
                    "sheet_names": sheet_names,
                    "tables": tables,
                })

            disclosure_catalog[pillar] = sorted(
                disclosure_catalog[pillar],
                key=lambda item: _vsme_code_sort_key(item["code"]),
            )

        return disclosure_catalog, None
    except Exception as exc:
        return {pillar: [] for pillar in VSME_DISCLOSURE_PILLARS}, str(exc)

def load_vsme_checklist_from_excel(file_path=VSME_DEFAULT_FILE):
    """Carica le domande del checklist VSME dal file Excel."""
    try:
        import openpyxl
        # Carica il workbook con data_only=True per ottenere valori calcolati, non formule
        wb = openpyxl.load_workbook(file_path, data_only=True)
        excluded_questions = set()

        def parse_datapoints(value):
            if value is None or value == "":
                return 0
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                cleaned = value.strip().replace(",", ".")
                try:
                    return int(float(cleaned))
                except ValueError:
                    return 0
            return 0

        vsme_scale_options = VSME_SCALE_OPTIONS
        if "Support" in wb.sheetnames:
            ws_support = wb["Support"]
            excel_scale = []
            for row_idx in range(1, 10):
                value = ws_support.cell(row_idx, 1).value
                if value and isinstance(value, str) and value.strip():
                    excel_scale.append(value.strip())
                elif excel_scale:
                    break
            if len(excel_scale) >= 2:
                vsme_scale_options = excel_scale
        
        sheet_map = {
            'GEN': 'Checklist_General_Information',
            'E': 'Checklist_Environment',
            'S': 'Checklist_Social',
            'G': 'Checklist_Governance',
        }
        
        checklist_data = {'base': {}, 'comprehensive': {}}
        
        for pillar, sheet_name in sheet_map.items():
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            checklist_data['base'][pillar] = []
            checklist_data['comprehensive'][pillar] = []
            
            # Leggi da riga 4 (indice 3) in poi
            for row_idx in range(4, ws.max_row + 1):
                cell_b = ws.cell(row_idx, 2).value
                cell_c = ws.cell(row_idx, 3).value
                cell_h = ws.cell(row_idx, 8).value
                cell_j = ws.cell(row_idx, 10).value
                
                # Column B = documento base, Column D = datapoints base
                if cell_b and isinstance(cell_b, str) and cell_b.strip():
                    datapoints_base = parse_datapoints(ws.cell(row_idx, 4).value)
                    if datapoints_base == 0:
                        # Fallback su colonna C per compatibilita con eventuali template legacy.
                        datapoints_base = parse_datapoints(cell_c)
                    label_base = f"{cell_b.strip()} ({datapoints_base} datapoints)"
                    if cell_b.strip().lower() not in excluded_questions:
                        checklist_data['base'][pillar].append(label_base)
                
                # Column H = documento comprehensive, Column J = datapoints comprehensive
                if cell_h and isinstance(cell_h, str) and cell_h.strip():
                    datapoints_comp = parse_datapoints(cell_j)
                    label_comp = f"{cell_h.strip()} ({datapoints_comp} datapoints)"
                    if cell_h.strip().lower() not in excluded_questions:
                        checklist_data['comprehensive'][pillar].append(label_comp)
        
        return checklist_data, vsme_scale_options, None
    except Exception as e:
        return None, VSME_SCALE_OPTIONS, str(e)

# --- SINCRONIZZAZIONE (Session State) ---
st.session_state.setdefault('revenue', 0)
st.session_state.setdefault('opex', 0)
st.session_state.setdefault('totale_attivo', 0)
st.session_state.setdefault('dipendenti', 0)
st.session_state.setdefault('company_name', '')
st.session_state.setdefault('ragione_sociale', '')
st.session_state.setdefault('codice_nace_ateco', '')
st.session_state.setdefault('quotata', False)
st.session_state.setdefault('sector', 'Industrials')
st.session_state.setdefault('industry', 'Machinery')
st.session_state.setdefault('selected_country', 'Italia')
st.session_state.setdefault('scope1', 0)
st.session_state.setdefault('scope2', 0)
st.session_state.setdefault('scope3', 0)
st.session_state.setdefault('perc_red', 0)
st.session_state.setdefault('em_final', 0)
st.session_state.setdefault('rata_prestito', 0)
st.session_state.setdefault('policy_multiplier', 1.0)
st.session_state.setdefault('capex_totale', 0)
st.session_state.setdefault('tax_portfolio', [])
st.session_state.setdefault('cbam_portfolio', [])
st.session_state.setdefault('gap_answers', {})
st.session_state.setdefault('gap_documents', {})
st.session_state.setdefault('vsme_disclosure_tables', {})
st.session_state.setdefault('portfolio_df', pd.DataFrame())
st.session_state.setdefault('impresa_area', 'UE')
st.session_state.setdefault('sucursale_eu_200', 'No')
st.session_state.setdefault('hq_address', '')
st.session_state.setdefault('hq_geocoded_address', '')
st.session_state.setdefault('hq_lat', None)
st.session_state.setdefault('hq_lon', None)
st.session_state.setdefault('current_project_name', '')
st.session_state.setdefault('last_project_saved_at', '')
st.session_state.setdefault('last_project_signature', '')
st.session_state.setdefault('project_autosave_enabled', True)
st.session_state.setdefault('b1_info_omesse', 'No')
st.session_state.setdefault('b1_info_omesse_quali', '')
st.session_state.setdefault('b1_perimetro', 'Individuale')
st.session_state.setdefault('b1_paese_operazioni_asset_significativi', '')

if 'materiality_scores' not in st.session_state:
    st.session_state.materiality_scores = {
        "E1 - Cambiamento Climatico": {"pilastro": "E", "impatto": 1, "finanza": 1},
        "E2 - Inquinamento": {"pilastro": "E", "impatto": 1, "finanza": 1},
        "E3 - Risorse Idriche e Marine": {"pilastro": "E", "impatto": 1, "finanza": 1},
        "E4 - Biodiversità ed Ecosistemi": {"pilastro": "E", "impatto": 1, "finanza": 1},
        "E5 - Uso Risorse ed Economia Circolare": {"pilastro": "E", "impatto": 1, "finanza": 1},
        "S1 - Forza Lavoro Propria": {"pilastro": "S", "impatto": 1, "finanza": 1},
        "S2 - Lavoratori nella Catena del Valore": {"pilastro": "S", "impatto": 1, "finanza": 1},
        "S3 - Comunità Interessate": {"pilastro": "S", "impatto": 1, "finanza": 1},
        "S4 - Consumatori ed Utenti Finali": {"pilastro": "S", "impatto": 1, "finanza": 1},
        "G1 - Condotta Aziendale": {"pilastro": "G", "impatto": 1, "finanza": 1},
    }

if 'gics_sectors' not in st.session_state:
    st.session_state.gics_sectors = {
        "Industrials": ["Aerospace & Defense", "Building Products", "Construction & Engineering", "Electrical Equipment", "Industrial Conglomerates", "Machinery", "Commercial Services", "Transportation"],
        "Energy": ["Oil, Gas & Consumable Fuels", "Energy Equipment & Services"],
        "Materials": ["Chemicals", "Construction Materials", "Containers & Packaging", "Metals & Mining", "Paper & Forest Products"],
        "Consumer Discretionary": ["Automobiles & Components", "Consumer Durables & Apparel", "Consumer Services", "Retailing"],
        "Consumer Staples": ["Food & Staples Retailing", "Food, Beverage & Tobacco", "Household & Personal Products"],
        "Health Care": ["Health Care Equipment & Services", "Pharmaceuticals & Biotechnology"],
        "Financials": ["Banks", "Financial Services", "Insurance"],
        "Information Technology": ["Software & Services", "Technology Hardware & Equipment", "Semiconductors"],
        "Communication Services": ["Telecommunication Services", "Media & Entertainment"],
        "Utilities": ["Electric Utilities", "Gas Utilities", "Multi-Utilities", "Water Utilities", "Renewable Electricity"],
        "Real Estate": ["Equity REITs", "Real Estate Management & Development"],
        "Altro / Non Specificato": ["Altro"]
    }

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_scopes(): sync_from_perc()

# --- SCALE DI VALUTAZIONE ---
ESRS_SCALE_OPTIONS = [
    "Per niente (0% - Nessuna azione intrapresa)",
    "In fase iniziale (Attività pianificata o discussa)",
    "Parzialmente (Policy esistente, implementazione frammentaria)",
    "In gran parte (Processo attivo, non ancora auditabile)",
    "Quasi completamente (Manca solo verifica finale o XBRL)",
    "Completamente (100% - Allineato a ESRS e verificabile)"
]
ESRS_SCALE_VALUES = {
    "Per niente (0% - Nessuna azione intrapresa)": 0,
    "In fase iniziale (Attività pianificata o discussa)": 1,
    "Parzialmente (Policy esistente, implementazione frammentaria)": 2,
    "In gran parte (Processo attivo, non ancora auditabile)": 3,
    "Quasi completamente (Manca solo verifica finale o XBRL)": 4,
    "Completamente (100% - Allineato a ESRS e verificabile)": 5
}

# --- FUNZIONI DATI E MAPPA ---
def process_portfolio_dataframe(df):
    cols = [c.lower() for c in df.columns]
    
    if 'address' in cols: df.rename(columns={df.columns[cols.index('address')]: 'Address'}, inplace=True)
    if 'operator' in cols: df.rename(columns={df.columns[cols.index('operator')]: 'Operator'}, inplace=True)
    if 'installation name' in cols: df.rename(columns={df.columns[cols.index('installation name')]: 'Name'}, inplace=True)
    elif 'nome' in cols: df.rename(columns={df.columns[cols.index('nome')]: 'Name'}, inplace=True)
    if 'installation id' in cols: df.rename(columns={df.columns[cols.index('installation id')]: 'ID'}, inplace=True)
    
    lat_col = next((c for c in df.columns if c.lower() in ['lat', 'latitude', 'latitudine']), None)
    lon_col = next((c for c in df.columns if c.lower() in ['lon', 'lng', 'longitude', 'longitudine']), None)
    
    if lat_col and lon_col:
        df.rename(columns={lat_col: 'Lat', lon_col: 'Lon'}, inplace=True)
        df = df.dropna(subset=['Lat', 'Lon'])
    else:
        st.error("Il file deve contenere colonne 'Lat' e 'Lon'.")
        return pd.DataFrame()

    if 'Name' not in df.columns: df['Name'] = "Impianto " + df.index.astype(str)
    if 'ID' not in df.columns: df['ID'] = df.index.astype(str)
    if 'Address' not in df.columns: df['Address'] = "Indirizzo non disponibile"
    
    if 'Operator' not in df.columns: 
        df['Operator'] = "Operatore Non Specificato"
    else:
        df['Operator'] = df['Operator'].astype(str).str.upper()
        df['Operator'] = df['Operator'].str.replace(r'[^\w\s]', '', regex=True)
        df['Operator'] = df['Operator'].str.replace(r'\s+', ' ', regex=True).str.strip()

    alloc_col = next((c for c in df.columns if 'alloc' in c.lower() or 'capacit' in c.lower()), None)
    if alloc_col: df['Size'] = pd.to_numeric(df[alloc_col], errors='coerce').fillna(5000)
    else: df['Size'] = 5000
    
    max_size = df['Size'].max()
    if max_size > 0: df['Display_Size'] = (df['Size'] / max_size) * 30 + 5
    else: df['Display_Size'] = 10
    
    return df

@st.cache_data(ttl=3600)
def get_live_eu_ets_price():
    try: return round(float(yf.Ticker("KEZ=F").history(period="1d")['Close'].iloc[-1]), 2)
    except: return 70.00

@st.cache_data
def load_taxonomy_json(file_content_or_path="taxonomy.json"):
    eligible_prefixes = set()
    try:
        if os.path.exists(file_content_or_path):
            with open(file_content_or_path, 'r', encoding='utf-8', errors='ignore') as f: data = json.load(f)
            for activity in data.get('activities', []):
                for code in activity.get('nace_codes', []):
                    if code:
                        num_part = re.sub(r'^[A-Z]+', '', code.strip(), flags=re.IGNORECASE).replace('.', '')
                        if len(num_part) == 1: num_part = "0" + num_part
                        if num_part: eligible_prefixes.add(num_part)
        return eligible_prefixes
    except: return set()

@st.cache_data
def load_nace_hierarchy(file_content_or_path="NACE_Rev.2.1.rdf"):
    try:
        if os.path.exists(file_content_or_path):
            with open(file_content_or_path, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            labels_by_code = {}
            for match in re.finditer(r'<rdf:Description[^>]*rdf:about="http://data\.europa\.eu/ux2/nace2\.1/(?:[^"]*_)?([A-V]|\d{2,4})"[^>]*>(.*?)</rdf:Description>', content, re.DOTALL):
                code, block = match.group(1).strip(), match.group(2)
                if code not in labels_by_code: labels_by_code[code] = {}
                for l_m in re.finditer(r'<skos:prefLabel[^>]*xml:lang="(it|en)"[^>]*>(.*?)</skos:prefLabel>', block, re.DOTALL | re.IGNORECASE):
                    labels_by_code[code][l_m.group(1).lower()] = re.sub(r'\s+', ' ', l_m.group(2)).strip()

            sections, divisions, groups, classes = {}, {}, {}, {}
            for code, langs in labels_by_code.items():
                label = langs.get('it', langs.get('en', f"Attività {code}"))
                label = re.sub(rf'^{code}\s*-?\s*', '', label)
                if code.isalpha() and len(code) == 1: sections[code] = {'label': f"{code} - {label}", 'children': {}}
                elif code.isdigit() and len(code) == 2: divisions[code] = {'label': f"{code} - {label}", 'children': {}}
                elif len(code) == 3 and code.isdigit(): groups[code] = {'label': f"{code[:2]}.{code[2:]} - {label}", 'children': {}}
                elif len(code) == 4 and code.isdigit(): classes[code] = {'label': f"{code[:2]}.{code[2:]} - {label}", 'code': f"{code[:2]}.{code[2:]}"}

            def get_section(d):
                d = int(d)
                if 1<=d<=3: return 'A'
                if 5<=d<=9: return 'B'
                if 10<=d<=33: return 'C'
                if d==35: return 'D'
                if 36<=d<=39: return 'E'
                if 41<=d<=43: return 'F'
                if 45<=d<=47: return 'G'
                if 49<=d<=53: return 'H'
                if 55<=d<=56: return 'I'
                if 58<=d<=63: return 'J'
                if 64<=d<=66: return 'K'
                if d==68: return 'L'
                if 69<=d<=75: return 'M'
                if 77<=d<=82: return 'N'
                return 'UNKNOWN'

            for d_code, d_data in divisions.items():
                s_code = get_section(d_code)
                if s_code in sections: sections[s_code]['children'][d_code] = d_data
            for g_code, g_data in groups.items():
                if g_code[:2] in divisions: divisions[g_code[:2]]['children'][g_code] = g_data
            for c_code, c_data in classes.items():
                if c_code[:3] in groups: groups[c_code[:3]]['children'][c_code] = c_data
                    
            ui_db = {}
            for s in sections.values():
                if not s['children']: continue
                ui_db[s['label']] = {}
                for d in s['children'].values():
                    if not d['children']: continue
                    ui_db[s['label']][d['label']] = {}
                    for g in d['children'].values():
                        if not g['children']: continue
                        ui_db[s['label']][d['label']][g['label']] = {c['label']: c['code'] for c in g['children'].values()}
            return ui_db
    except: return {}

@st.cache_data
def generate_offline_data():
    data = []
    for c in ['Stati Uniti', 'Cina', 'Germania', 'Italia', 'India']:
        for s in ['Net Zero 2050 (Ordinata)', 'Transizione Ritardata (Shock)', 'Politiche Attuali (BAU)']:
            for y in range(2020, 2055, 5):
                p = (y - 2020) * 12 if 'Net Zero' in s else ((y - 2020) * 2 if 'BAU' in s else (10 if y < 2030 else (y - 2030) * 20 + 20))
                if c in ['Germania', 'Italia']: p *= 1.4 
                elif c in ['India', 'Cina']: p *= 0.5 
                data.append({'Scenario': s, 'Paese': c, 'Anno': y, 'Prezzo Carbonio Base': p})
    return pd.DataFrame(data)
df_base = generate_offline_data()

@st.cache_data(ttl=600)
def load_cbam_hierarchy(file_path="cn_codes_clean.csv"):
    tree = {}
    try:
        if os.path.exists(file_path):
            df_cn = pd.read_csv(file_path, dtype=str)
            df_cn['CN_Code'] = df_cn['CN_Code'].fillna("00000000").str.zfill(8)
            df_cn['Description'] = df_cn['Description'].fillna("Nessuna descrizione")
            cur_s, cur_c, cur_h = "Sconosciuta", "Sconosciuto", "Voce Sconosciuta"
            for _, row in df_cn.iterrows():
                code, desc = row['CN_Code'], str(row['Description']).strip()
                if desc.upper().startswith("SEZIONE"): cur_s, cur_c, cur_h = desc, "Sconosciuto", "Voce Sconosciuta"
                elif desc.upper().startswith("CAPITOLO"): cur_c, cur_h = desc, "Voce Sconosciuta"
                elif code.endswith('0000') and code[2:4] != '00': cur_h = f"{code[:4]} - {desc[5:].strip() if desc.startswith(code[:4]) else desc}"
                else:
                    if code[2:4] == '00' and not desc.upper().startswith(("SEZIONE", "CAPITOLO")): continue
                    if cur_s not in tree: tree[cur_s] = {}
                    if cur_c not in tree[cur_s]: tree[cur_s][cur_c] = {}
                    if cur_h not in tree[cur_s][cur_c]: tree[cur_s][cur_c][cur_h] = {}
                    tree[cur_s][cur_c][cur_h][f"{code} - {desc}"] = code
            return tree
    except: pass
    return {"SEZIONE V (FALLBACK)": {"CAPITOLO 25": {"2523 - Cementi": {"25231000 - Cemento": "25231000"}}}}
cbam_tree = load_cbam_hierarchy()
def check_cbam_category(cn_code):
    cn = str(cn_code).strip()
    if cn.startswith(('25070080', '2523')): return "Cemento"
    if cn == '27160000': return "Elettricità"
    if cn == '28041000': return "Idrogeno"
    if cn.startswith(('2808', '2814', '28342100', '3102', '3105')): return "Fertilizzanti"
    if cn.startswith(('72', '7301', '7302', '7303', '7304', '7305', '7306', '7307', '7308', '7309', '7310', '7311', '7318', '7326')): return "Ferro e Acciaio"
    if cn.startswith(('7601', '7603', '7604', '7605', '7606', '7607', '7608', '7609')): return "Alluminio"
    return "Non Soggetto"


# =====================================================================
# SIDEBAR GLOBALE (INPUT DATI AZIENDALI)
# =====================================================================
with st.sidebar:
    st.markdown("## Test di Assoggettabilità")

    st.session_state.company_name = st.text_input("Nome Azienda", value=st.session_state.get('company_name', ''))
    st.session_state.ragione_sociale = st.text_input("Ragione sociale", value=st.session_state.get('ragione_sociale', ''))
    st.session_state.codice_nace_ateco = st.text_input("Codice NACE/ATECO", value=st.session_state.get('codice_nace_ateco', ''))

    # Scelta UE o Extra-UE
    if 'impresa_area' not in st.session_state:
        st.session_state.impresa_area = 'UE'
    
    impresa_area = st.radio("Sede Legale", ["UE", "Extra-UE"], key='impresa_area', horizontal=True)
    st.text_input("Indirizzo sede", key="hq_address", placeholder="Es. Via Roma 1, Milano, Italia")
    
    # Campi condizionali per UE
    if st.session_state.impresa_area == "UE":
        st.session_state.dipendenti = unbounded_number_input(
            "Numero dipendenti",
            value_key="dipendenti",
            display_key="dipendenti_input",
            placeholder="0",
            allow_float=False,
        )
        st.session_state.revenue = unbounded_number_input(
            "Fatturato netto (€)",
            value_key="revenue",
            display_key="revenue_input",
            placeholder="0",
        )

        if st.session_state.dipendenti > 0 and st.session_state.revenue > 0:
            ue_esrs = st.session_state.dipendenti > 1000 and st.session_state.revenue > 450000000
            if ue_esrs:
                st.session_state.status_normativo = "CSRD_GRANDE"
                st.error("**Esito:** OBBLIGO ESRS (Grande Impresa UE: Dipendenti > 1.000 e fatturato netto > 450M €)", icon="⚖️")
            else:
                st.session_state.status_normativo = "VSME"
                st.success("**Esito:** Rendicontazione VSME (dipendenti <= 1.000 e fatturato netto <= 450M €)")
    
    # Campi condizionali per Extra-UE
    elif st.session_state.impresa_area == "Extra-UE":
        st.session_state.revenue = unbounded_number_input(
            "Fatturato netto in UE (€)",
            value_key="revenue",
            display_key="revenue_input",
            placeholder="0",
        )
        sucursale_eu_200 = st.radio(
            "Sucursale UE con fatturato netto > 200 mln €?",
            ["Sì", "No"],
            key='sucursale_eu_200',
            horizontal=True
        )

        if st.session_state.revenue > 0:
            extra_ue_esrs = st.session_state.revenue > 450000000 and sucursale_eu_200 == "Sì"
            if extra_ue_esrs:
                st.session_state.status_normativo = "CSRD_GRANDE"
                st.error("**Esito:** OBBLIGO ESRS (Impresa Extra-UE: Fatturato netto in UE > 450M € e sucursale UE > 200 mln €)", icon="⚖️")
            else:
                st.session_state.status_normativo = "VSME"
                st.success("**Esito:** Rendicontazione VSME (fatturato netto in UE <= 450M € oppure sucursale UE > 200 mln € = No)")
    project_name_input = st.text_input(
        "Salva progetto con nome",
        value=st.session_state.get('current_project_name', '') or st.session_state.get('company_name', ''),
        key="project_name_input"
    )
    effective_project_name = project_name_input.strip() or st.session_state.get('current_project_name', '').strip() or st.session_state.get('company_name', '').strip()
    if st.button("Salva", use_container_width=True):
        if not effective_project_name:
            st.warning("Inserisci un nome prima di salvare.")
        else:
            payload = save_project(effective_project_name)
            st.success(f"Progetto salvato: {payload['project_name']}")
            st.rerun()

    project_options = list_saved_projects()
    selected_project = st.selectbox(
        "Progetti salvati",
        options=project_options,
        format_func=lambda item: f"{item['label']} ({item['saved_at'][:16].replace('T', ' ')})" if item and item.get('saved_at') else item['label'],
        index=None,
        placeholder="Seleziona un progetto salvato",
        key="selected_saved_project_option"
    )

    c_avvia, c_cancella = st.columns(2)
    with c_avvia:
        if st.button("Avvia", use_container_width=True, disabled=selected_project is None):
            load_project(selected_project)
            st.success(f"Progetto avviato: {selected_project['label']}")
            st.rerun()
    with c_cancella:
        if st.button("Cancella", use_container_width=True, disabled=selected_project is None):
            deleted_label = selected_project['label']
            delete_project(selected_project)
            if st.session_state.get('current_project_name') == deleted_label:
                st.session_state['current_project_name'] = ''
                st.session_state['last_project_saved_at'] = ''
                st.session_state['last_project_signature'] = ''
            st.warning(f"Progetto eliminato: {deleted_label}")
            st.rerun()

    if st.session_state.get('current_project_name'):
        saved_at = st.session_state.get('last_project_saved_at', '')
        if saved_at:
            st.caption(f"Progetto corrente: {st.session_state['current_project_name']} | salvato il {saved_at[:16].replace('T', ' ')}")
        else:
            st.caption(f"Progetto corrente: {st.session_state['current_project_name']}")


# --- CORPO PRINCIPALE E TABS ---
st.title("🌍 Supporto alla Rendicontazione PMI")


def clean_question_label(question):
    return re.sub(r'\s*\(\d+ datapoints\)$', '', str(question or '').strip())


def is_interview_management_question(question):
    normalized_question = clean_question_label(question).lower()
    return "interview management esg" in normalized_question


def get_question_datapoints(question):
    if is_interview_management_question(question):
        return 4
    if is_balance_economics_question(question):
        return 4
    if is_hr_reporting_question(question):
        return 1
    if is_governance_overview_question(question):
        return 2
    if is_environmental_certifications_question(question):
        return 1
    if is_hse_action_plan_question(question):
        return 1
    if is_hse_policies_question(question):
        return 1
    if is_transition_plan_question(question):
        return 2
    match = re.search(r'\((\d+) datapoints\)', str(question or ''))
    return int(match.group(1)) if match else 0


def answer_to_status(answer):
    normalized_answer = str(answer or '').strip().lower()
    if normalized_answer in {'sì', 'si', 'yes'}:
        return 'ready', 0
    if 'integrazione' in normalized_answer or 'integration' in normalized_answer:
        return 'partial', 1
    if normalized_answer.startswith('no'):
        return 'missing', 2
    return 'partial', 1


def consolidated_table_completion_state():
    tables = st.session_state.get('vsme_disclosure_tables', {})
    df = tables.get('vsme_table_B1_consolidato')
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 'missing'

    normalized_df = df.where(pd.notna(df), '')
    total_cells = normalized_df.shape[0] * normalized_df.shape[1]
    if total_cells == 0:
        return 'missing'

    filled_cells = 0
    for value in normalized_df.to_numpy().flatten():
        if str(value).strip() != '':
            filled_cells += 1

    if filled_cells == 0:
        return 'missing'
    if filled_cells == total_cells:
        return 'full'
    return 'partial'


def interview_management_auto_answer(selected_mode):
    # Datapoint 1 (OPTION A/B) e datapoint 2-3 (informazioni omesse + perimetro)
    # sono sempre disponibili in app. Datapoint 4 dipende dalla tabella Consolidato.
    perimetro = st.session_state.get('b1_perimetro', 'Individuale')

    if perimetro != 'Consolidato':
        return 'Sì'

    table_state = consolidated_table_completion_state()
    if table_state == 'full':
        return 'Sì'
    if table_state == 'partial':
        return 'Sì, ma con integrazione necessaria'
    return None


def is_balance_economics_question(question):
    return "balance/economics" in clean_question_label(question).lower()


def balance_economics_auto_answer():
    # Datapoint 1: Ragione sociale (sidebar)
    # Datapoint 2: Codice NACE/ATECO (sidebar)
    # Datapoint 3: Totale degli attivi (tabella Dimensioni, riga 0)
    # Datapoint 4: Fatturato (tabella Dimensioni, riga 1)
    filled = 0

    if str(st.session_state.get('ragione_sociale', '')).strip():
        filled += 1
    if str(st.session_state.get('codice_nace_ateco', '')).strip():
        filled += 1

    tables = st.session_state.get('vsme_disclosure_tables', {})
    df = tables.get('vsme_table_B1_dimensioni')
    if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
        if df.shape[0] > 0:
            row0 = df.iloc[0]
            if any(str(row0.get(col, '')).strip() for col in ['2024', '2025']):
                filled += 1
        if df.shape[0] > 1:
            row1 = df.iloc[1]
            if any(str(row1.get(col, '')).strip() for col in ['2024', '2025']):
                filled += 1

    if filled == 4:
        return 'Sì'
    if filled > 0:
        return 'Sì, ma con integrazione necessaria'
    return None


def is_hr_reporting_question(question):
    return "hr reporting" in clean_question_label(question).lower()


def hr_reporting_auto_answer():
    # Datapoint: Numero di dipendenti (tabella Dimensioni, riga 2)
    tables = st.session_state.get('vsme_disclosure_tables', {})
    df = tables.get('vsme_table_B1_dimensioni')
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or df.shape[0] <= 2:
        return None

    row = df.iloc[2]
    val_2024 = str(row.get('2024', '')).strip()
    val_2025 = str(row.get('2025', '')).strip()

    if val_2024 and val_2025:
        return 'Sì'
    if val_2024 or val_2025:
        return 'Sì, ma con integrazione necessaria'
    return None


def is_governance_overview_question(question):
    return "governance overview" in clean_question_label(question).lower()


def governance_overview_auto_answer():
    # Datapoint 1: Paese delle principali operazioni e localizzazione degli asset significativi
    # Datapoint 2: Geolocalizzazione siti con coordinate GPS
    country_filled = bool(str(st.session_state.get('b1_paese_operazioni_asset_significativi', '')).strip())

    tables = st.session_state.get('vsme_disclosure_tables', {})
    geo_df = tables.get('vsme_table_B1_geolocalizzazione_siti')
    has_geo_full = False
    has_geo_partial = False

    if geo_df is not None and isinstance(geo_df, pd.DataFrame) and not geo_df.empty:
        normalized_df = geo_df.where(pd.notna(geo_df), '')
        for _, row in normalized_df.iterrows():
            site_name = str(row.get('Sito (di proprietà, in locazione o gestito)', '')).strip()
            gps_coords = str(row.get('Coordinate GPS', '')).strip()
            if site_name and gps_coords:
                has_geo_full = True
                break
            if site_name or gps_coords:
                has_geo_partial = True

    filled = int(country_filled) + int(has_geo_full)
    if filled == 2:
        return 'Sì'
    if filled > 0 or has_geo_partial:
        return 'Sì, ma con integrazione necessaria'
    return None


def is_environmental_certifications_question(question):
    normalized = clean_question_label(question).lower()
    return "environmental certifications" in normalized or "environmental certification" in normalized


def environmental_certifications_auto_answer():
    # Datapoint: presenza di almeno una certificazione/marchio sostenibilita con dati completi.
    tables = st.session_state.get('vsme_disclosure_tables', {})
    cert_df = tables.get('vsme_table_B1_certificazioni_sostenibilita')
    if cert_df is None or not isinstance(cert_df, pd.DataFrame) or cert_df.empty:
        return None

    has_full = False
    has_partial = False
    normalized_df = cert_df.where(pd.notna(cert_df), '')
    for _, row in normalized_df.iterrows():
        description = str(row.get('Breve descrizione', '')).strip()
        body = str(row.get('Organismo di certificazione', '')).strip()
        date_value = str(row.get('Data', '')).strip()
        score = str(row.get('Punteggio', '')).strip()
        filled_count = sum(bool(v) for v in [description, body, date_value, score])
        if filled_count == 4:
            has_full = True
            break
        if filled_count > 0:
            has_partial = True

    if has_full:
        return 'Sì'
    if has_partial:
        return 'Sì, ma con integrazione necessaria'
    return None


# ---------------------------------------------------------------
# B2 TABLE HELPERS
# ---------------------------------------------------------------

B2_TEMI = [
    "Cambiamento climatico",
    "Inquinamento",
    "Acqua e risorse marine",
    "Biodiversità ed ecosistemi",
    "Economia circolare",
    "Forza lavoro propria",
    "Lavoratori nella catena del valore",
    "Comunità interessate",
    "Consumatori e utenti finali",
    "Condotta aziendale",
]

B2_COLONNE = [
    "Esistono pratiche che affrontano dei temi di sostenibilità?",
    "Esistono politiche di sostenibilità che affrontano dei temi di sostenibilità?",
    "Le politiche sono disponibili pubblicamente?",
    "Le politiche hanno degli obiettivi?",
    "Esistono iniziative future che affrontano dei temi di sostenibilità?",
]


def get_b2_table():
    """Ritorna il DataFrame della tabella B2 dalla sessione, inizializzandolo se assente."""
    tables = st.session_state.get('vsme_disclosure_tables', {})
    key = 'vsme_table_B2_pratiche_politiche'
    all_cols = ["Tema"] + B2_COLONNE
    if key not in tables or not isinstance(tables[key], pd.DataFrame) or tables[key].empty:
        tables[key] = pd.DataFrame(
            [{"Tema": tema, **{col: "" for col in B2_COLONNE}} for tema in B2_TEMI]
        )
        st.session_state['vsme_disclosure_tables'] = tables
    else:
        df = tables[key].copy()
        for col in all_cols:
            if col not in df.columns:
                df[col] = ""
        # Converti NaN / None / 'nan' / 'None' in stringa vuota
        for col in B2_COLONNE:
            df[col] = df[col].fillna("").astype(str).replace({'nan': '', 'None': ''})
        tables[key] = df
    return tables[key]


def _b2_col_has_si(col_name):
    """Ritorna True se almeno una riga della colonna col_name ha valore 'Sì'."""
    df = get_b2_table()
    if col_name not in df.columns:
        return False
    return any(str(v).strip() == "Sì" for v in df[col_name])


def is_b2_checklist_question(question):
    """True per le domande auto-calcolate dalla tabella B2 (scope B2, non B1)."""
    return (
        is_hse_action_plan_question(question)
        or is_hse_policies_question(question)
        or is_transition_plan_question(question)
    )


def is_hse_action_plan_question(question):
    return "hse action plan" in clean_question_label(question).lower()


def hse_action_plan_auto_answer():
    pratiche_col = B2_COLONNE[0]
    if _b2_col_has_si(pratiche_col):
        return 'Sì'
    return None


def is_hse_policies_question(question):
    return "hse policies" in clean_question_label(question).lower()


def hse_policies_auto_answer():
    politiche_col = B2_COLONNE[1]
    if _b2_col_has_si(politiche_col):
        return 'Sì'
    return None


def is_transition_plan_question(question):
    return "transition plan" in clean_question_label(question).lower()


def transition_plan_auto_answer():
    # dp1: ≥1 Sì in colonna "obiettivi"
    # dp2: ≥1 Sì in colonna "iniziative future"
    obiettivi_col = B2_COLONNE[3]
    iniziative_col = B2_COLONNE[4]
    dp1 = _b2_col_has_si(obiettivi_col)
    dp2 = _b2_col_has_si(iniziative_col)
    if dp1 and dp2:
        return 'Sì'
    if dp1 or dp2:
        return 'Sì, ma con integrazione necessaria'
    return None


def summarize_gap_answers(module_prefixes=None):
    rows = []
    for key, data in st.session_state.get("gap_answers", {}).items():
        if module_prefixes and not any(key.startswith(prefix) for prefix in module_prefixes):
            continue

        answer = str(data.get("ans", "")).strip()
        question_raw = str(data.get("q", "")).strip()
        question = clean_question_label(question_raw)
        if not answer:
            continue

        status, severity = answer_to_status(answer)
        datapoints = get_question_datapoints(question_raw)

        rows.append({
            "question": question,
            "answer": answer,
            "status": status,
            "severity": severity,
            "datapoints": datapoints,
        })

    total = len(rows)
    ready = sum(1 for row in rows if row["status"] == "ready")
    partial = sum(1 for row in rows if row["status"] == "partial")
    missing = sum(1 for row in rows if row["status"] == "missing")

    total_datapoints = sum(row["datapoints"] for row in rows)
    ready_datapoints = sum(row["datapoints"] for row in rows if row["status"] == "ready")
    partial_datapoints = sum(row["datapoints"] for row in rows if row["status"] == "partial")
    missing_datapoints = sum(row["datapoints"] for row in rows if row["status"] == "missing")
    coverage = ((ready_datapoints + partial_datapoints) / total_datapoints * 100) if total_datapoints else 0.0

    top_gaps = []
    seen_questions = set()
    for row in sorted(rows, key=lambda item: (-item["severity"], -item["datapoints"], item["question"])):
        if row["status"] == "ready" or row["question"] in seen_questions:
            continue
        top_gaps.append(row["question"])
        seen_questions.add(row["question"])
        if len(top_gaps) == 5:
            break

    return {
        "total": total,
        "ready": ready,
        "partial": partial,
        "missing": missing,
        "total_datapoints": total_datapoints,
        "ready_datapoints": ready_datapoints,
        "partial_datapoints": partial_datapoints,
        "missing_datapoints": missing_datapoints,
        "coverage": coverage,
        "top_gaps": top_gaps,
    }

def build_priority_actions(max_risk_score=None, top_risk_asset=None):
    gap_summary = summarize_gap_answers(["vsme_base", "vsme_comprehensive"])
    actions = []

    if gap_summary["missing"] > 0:
        actions.append("Recuperare i dati VSME assenti con priorita alta, partendo dalle domande senza evidenze.")
    if gap_summary["partial"] > 0:
        actions.append("Consolidare i dati parziali con fonti interne e documenti di supporto caricati in app.")
    if not st.session_state.get("hq_address", "").strip():
        actions.append("Inserire l'indirizzo sede per completare l'inquadramento geografico di base.")
    if st.session_state.get("portfolio_df", pd.DataFrame()).empty:
        actions.append("Caricare almeno una sede o un portfolio asset per rendere utile la lettura del rischio fisico.")
    elif max_risk_score is not None and max_risk_score >= 70:
        asset_label = top_risk_asset or "piu esposto"
        actions.append(f"Approfondire l'asset {asset_label} con una verifica tecnica dedicata sul rischio fisico.")
    if get_tot_emissions() == 0:
        actions.append("Raccogliere i consumi energetici e logistici minimi per avviare una baseline GHG credibile.")
    elif st.session_state.get("perc_red", 0) < 20:
        actions.append("Definire un primo piano di riduzione emissioni per migliorare la resilienza allo scenario di transizione.")

    deduplicated_actions = []
    seen_actions = set()
    for action in actions:
        if action in seen_actions:
            continue
        deduplicated_actions.append(action)
        seen_actions.add(action)

    return deduplicated_actions[:5]

st.markdown(
    """
    <style>
    /* ---- Sticky tab bar (tutte le sezioni) ---- */
    [data-baseweb="tab-list"] {
        position: sticky !important;
        top: 0 !important;
        z-index: 100 !important;
        background: #ffffff !important;
        padding-top: 4px !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08) !important;
    }
    /* ---- Stili tab principali ---- */
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"] {
        font-size: 1rem;
        font-weight: 600;
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 0.95rem;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(1) {
        color: #1f4e79;
        background: #eaf3ff;
        border: 1px solid #bfd7f2;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(1) {
        color: #0f3554;
        background: #d6e9ff;
        border-bottom-color: #d6e9ff;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(2) {
        color: #2f6b3b;
        background: #e7f4ea;
        border: 1px solid #b9d8c0;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(2) {
        color: #214d2a;
        background: #d7eddc;
        border-bottom-color: #d7eddc;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(3) {
        color: #8a6a00;
        background: #fff4d6;
        border: 1px solid #ecd89b;
    }
    div[data-testid="stVerticalBlock"] > div:has(.app-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(3) {
        color: #6c5200;
        background: #f8e7b0;
        border-bottom-color: #f8e7b0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown("<div class='app-main-tabs-marker'></div>", unsafe_allow_html=True)
t_triage, t_rischi, t_down = st.tabs([
    "🔎 Diagnosi Azienda", "🗺️ Piano di Azione & Rischi", "📦 Deliverable"
])

# =====================================================================
# TAB 0: TRIAGE NORMATIVO, GAP ANALYSIS E DOPPIA MATERIALITÀ
# =====================================================================
with t_triage:
    status_normativo = st.session_state.get("status_normativo", "VSME")
    st.caption("Percorso 1 di 3")
    st.subheader("Diagnosi azienda")
    st.write("Questa sezione serve a inquadrare il caso, verificare cosa si applica e identificare i gap documentali e informativi piu rilevanti.")
    
    def render_gap_list(questions, pillar_code, tab_context, scale_options, prefix="gap"):
        with tab_context:
            valid_answer_keys = {f"{prefix}_{pillar_code}_{i}" for i in range(len(questions))}
            prefix_scope = f"{prefix}_{pillar_code}_"

            for key in list(st.session_state.get("gap_answers", {}).keys()):
                if key.startswith(prefix_scope) and key not in valid_answer_keys:
                    del st.session_state.gap_answers[key]

            for doc_key in list(st.session_state.get("gap_documents", {}).keys()):
                if doc_key.startswith(prefix_scope) and doc_key not in valid_answer_keys:
                    del st.session_state.gap_documents[doc_key]

            for state_key in list(st.session_state.keys()):
                if not state_key.startswith("show_pdf_"):
                    continue
                doc_key = state_key.replace("show_pdf_", "", 1)
                if doc_key.startswith(prefix_scope) and doc_key not in valid_answer_keys:
                    del st.session_state[state_key]

            b2_section_header_shown = False

            for i, q in enumerate(questions):
                # Mostra intestazione sezione B2 prima della prima domanda B2
                if is_b2_checklist_question(q) and not b2_section_header_shown:
                    st.markdown("---")
                    st.markdown(
                        "<p style='font-weight:600; font-size:0.95rem; color:#5f4b8b; margin-bottom:0.3rem;'>"
                        "📋 B2 – Pratiche, politiche e iniziative future</p>",
                        unsafe_allow_html=True,
                    )
                    b2_section_header_shown = True

                # Creare colonne: selectbox + bottone PDF allineati
                col_q, col_pdf = st.columns([4, 1], vertical_alignment="bottom")
                
                with col_q:
                    answer_key = f"{prefix}_{pillar_code}_{i}"
                    is_interview_row = is_interview_management_question(q)
                    is_balance_row = is_balance_economics_question(q)
                    is_hr_row = is_hr_reporting_question(q)
                    is_governance_row = is_governance_overview_question(q)
                    is_env_cert_row = is_environmental_certifications_question(q)
                    is_hse_ap_row = is_hse_action_plan_question(q)
                    is_hse_pol_row = is_hse_policies_question(q)
                    is_transition_row = is_transition_plan_question(q)
                    is_auto_row = (is_interview_row or is_balance_row or is_hr_row
                                   or is_governance_row or is_env_cert_row
                                   or is_hse_ap_row or is_hse_pol_row or is_transition_row)

                    if is_auto_row:
                        auto_datapoints = get_question_datapoints(q)
                        question_label = f"{i+1}. {clean_question_label(q)} ({auto_datapoints} datapoints)"
                        if is_interview_row:
                            auto_answer = interview_management_auto_answer(selected_mode)
                        elif is_balance_row:
                            auto_answer = balance_economics_auto_answer()
                        elif is_hr_row:
                            auto_answer = hr_reporting_auto_answer()
                        elif is_governance_row:
                            auto_answer = governance_overview_auto_answer()
                        elif is_env_cert_row:
                            auto_answer = environmental_certifications_auto_answer()
                        elif is_hse_ap_row:
                            auto_answer = hse_action_plan_auto_answer()
                        elif is_hse_pol_row:
                            auto_answer = hse_policies_auto_answer()
                        else:
                            auto_answer = transition_plan_auto_answer()

                        if auto_answer is not None:
                            st.session_state[answer_key] = auto_answer
                            val = st.selectbox(
                                question_label,
                                [auto_answer],
                                key=answer_key,
                                disabled=True,
                            )
                        else:
                            manual_options = ["No, ma pianificato", "No"]
                            if st.session_state.get(answer_key) not in manual_options:
                                st.session_state[answer_key] = manual_options[0]
                            val = st.selectbox(
                                question_label,
                                manual_options,
                                key=answer_key,
                            )

                        stored_question = f"{clean_question_label(q)} ({auto_datapoints} datapoints)"
                    else:
                        val = st.selectbox(
                            f"{i+1}. {q}",
                            scale_options,
                            key=answer_key
                        )
                        stored_question = q

                    st.session_state.gap_answers[answer_key] = {
                        "ans": val,
                        "pillar": pillar_code,
                        "q": stored_question,
                    }
                
                with col_pdf:
                    doc_key = f"{prefix}_{pillar_code}_{i}"
                    
                    # Determina il label del bottone in base allo stato
                    if doc_key in st.session_state.gap_documents and st.session_state.gap_documents[doc_key]:
                        btn_label = "PDF ✅"
                    else:
                        btn_label = "Carica PDF"
                    
                    # Bottone di caricamento PDF
                    if st.button(btn_label, key=f"btn_pdf_{prefix}_{pillar_code}_{i}", use_container_width=True):
                        st.session_state[f"show_pdf_{doc_key}"] = not st.session_state.get(f"show_pdf_{doc_key}", False)
                    
                    # Mostra uploader se bottone cliccato
                    if st.session_state.get(f"show_pdf_{doc_key}", False):
                        uploaded_file = st.file_uploader(
                            "Carica PDF",
                            type="pdf",
                            key=f"uploader_{prefix}_{pillar_code}_{i}"
                        )
                        if uploaded_file:
                            # Salva il file in memoria/session state
                            st.session_state.gap_documents[doc_key] = {
                                'filename': uploaded_file.name,
                                'data': uploaded_file.getvalue(),
                                'timestamp': datetime.now().isoformat()
                            }
                            st.success(f"✅ PDF caricato: {uploaded_file.name}")

    def render_vsme_disclosure_tables(pillar_code, selected_mode, tab_context, disclosure_reference):
        pillar_styles = {
            "GEN": {
                "tab_bg": "#eaf3ff",
                "tab_bg_selected": "#d6e9ff",
                "tab_border": "#bfd7f2",
                "tab_text": "#1f4e79",
                "tab_text_selected": "#0f3554",
                "badge_bg": "#d9ecff",
                "badge_text": "#1f4e79",
            },
            "E": {
                "tab_bg": "#e7f4ea",
                "tab_bg_selected": "#d7eddc",
                "tab_border": "#b9d8c0",
                "tab_text": "#2f6b3b",
                "tab_text_selected": "#214d2a",
                "badge_bg": "#dff1e3",
                "badge_text": "#2f6b3b",
            },
            "S": {
                "tab_bg": "#fde8e4",
                "tab_bg_selected": "#f9d7cf",
                "tab_border": "#f2c4ba",
                "tab_text": "#a54b3f",
                "tab_text_selected": "#7d362d",
                "badge_bg": "#fbe0db",
                "badge_text": "#a54b3f",
            },
            "G": {
                "tab_bg": "#fff4d6",
                "tab_bg_selected": "#f8e7b0",
                "tab_border": "#ecd89b",
                "tab_text": "#8a6a00",
                "tab_text_selected": "#6c5200",
                "badge_bg": "#fff0bf",
                "badge_text": "#8a6a00",
            },
        }
        style = pillar_styles.get(pillar_code, pillar_styles["GEN"])

        if selected_mode == "absolute":
            module_prefixes = ("B", "C")
        elif selected_mode == "base":
            module_prefixes = ("B",)
        elif selected_mode == "comprehensive":
            module_prefixes = ("B", "C")
        else:
            module_prefixes = ("C",)

        disclosures = [
            item for item in disclosure_reference.get(pillar_code, [])
            if item["code"].startswith(module_prefixes)
        ]

        if not disclosures:
            return

        marker_class = f"vsme-subtabs-marker-{pillar_code}-{selected_mode}"

        with tab_context:
            css_rules = [
                "font-size: 1rem;",
                "font-weight: 600;",
                f"color: {style['tab_text']} !important;",
                f"background: {style['tab_bg']} !important;",
                f"border: 1px solid {style['tab_border']} !important;",
                "border-radius: 8px 8px 0 0;",
                "padding: 0.45rem 0.9rem;",
            ]
            css_selected_rules = [
                f"color: {style['tab_text_selected']} !important;",
                f"background: {style['tab_bg_selected']} !important;",
                f"border-bottom-color: {style['tab_bg_selected']} !important;",
            ]

            st.markdown(
                f"""
                <style>
                div[data-testid="stVerticalBlock"] > div:has(.{marker_class}) ~ div div[data-baseweb="tab-list"] {{
                    position: sticky !important;
                    top: 2.5rem !important;
                    z-index: 90 !important;
                    background: #ffffff !important;
                    padding-top: 4px !important;
                    box-shadow: 0 2px 6px rgba(0,0,0,0.08) !important;
                }}
                div[data-testid="stVerticalBlock"] > div:has(.{marker_class}) ~ div div[data-baseweb="tab-list"] button[role="tab"] {{
                    {' '.join(css_rules)}
                }}
                div[data-testid="stVerticalBlock"] > div:has(.{marker_class}) ~ div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"] {{
                    {' '.join(css_selected_rules)}
                }}
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(f"<div class='{marker_class}'></div>", unsafe_allow_html=True)
            st.markdown(
                "<p style='font-size:1rem; font-weight:600; margin-bottom:0.45rem; color:#1f1f1f;'>Struttura dati da compilare</p>",
                unsafe_allow_html=True,
            )
            disclosure_tabs = st.tabs([f"{disclosure['code']}" for disclosure in disclosures])

            for disclosure_tab, disclosure in zip(disclosure_tabs, disclosures):
                with disclosure_tab:
                    st.markdown(
                        f"<p style='display:inline-block; font-size:1rem; font-weight:600; margin-bottom:0.45rem; padding:0.25rem 0.6rem; background:{style['badge_bg']}; color:{style['badge_text']}; border-radius:6px;'>{disclosure['code']} - {disclosure['title']}</p>",
                        unsafe_allow_html=True,
                    )

                    b1_is_custom = disclosure['code'] == "B1"
                    b2_is_custom = disclosure['code'] == "B2"
                    if b1_is_custom:
                        st.caption("Tabella di raccolta dati riferita alla Disclosure B1")
                        st.markdown("#### Basis for preparation")
                        st.radio(
                            'Informazioni omesse in quanto ritenute riservate o sensibili?',
                            ['Si', 'No'],
                            key='b1_info_omesse',
                            horizontal=True,
                        )
                        if st.session_state.b1_info_omesse == 'Si':
                            st.text_input('Quali?', key='b1_info_omesse_quali')

                        st.radio(
                            'Perimetro rendicontazione',
                            ['Individuale', 'Consolidato'],
                            key='b1_perimetro',
                            horizontal=True,
                        )

                        if st.session_state.b1_perimetro == 'Consolidato':
                            editor_storage_key = "vsme_table_B1_consolidato"
                            b1_default_columns = [
                                'Tipo sede (es. sede legale, magazzino, stabilimento industriale, ecc.)',
                                'N. siti',
                                'Indirizzo',
                                'Codice Postale',
                                'Città',
                                'Paese',
                            ]
                            if editor_storage_key not in st.session_state.vsme_disclosure_tables:
                                st.session_state.vsme_disclosure_tables[editor_storage_key] = pd.DataFrame([
                                    {col: '' for col in b1_default_columns}
                                    for _ in range(2)
                                ])
                            else:
                                existing_df = st.session_state.vsme_disclosure_tables[editor_storage_key].copy()
                                for col in b1_default_columns:
                                    if col not in existing_df.columns:
                                        existing_df[col] = ''
                                existing_df = existing_df[b1_default_columns]
                                if existing_df.empty:
                                    existing_df = pd.DataFrame([{col: '' for col in b1_default_columns} for _ in range(2)])
                                existing_df = existing_df.where(pd.notna(existing_df), '')
                                st.session_state.vsme_disclosure_tables[editor_storage_key] = existing_df

                            st.markdown(
                                """
                                <style>
                                div[data-testid="stDataEditor"] thead th,
                                div[data-testid="stDataFrame"] thead th {
                                    color: #000000 !important;
                                }
                                div[data-testid="stDataEditor"] [role="columnheader"] {
                                    color: #000000 !important;
                                }
                                </style>
                                """,
                                unsafe_allow_html=True,
                            )

                            edited_df = st.data_editor(
                                st.session_state.vsme_disclosure_tables[editor_storage_key],
                                key=f"editor_{editor_storage_key}",
                                width='stretch',
                                hide_index=True,
                                num_rows="fixed",
                            )
                            edited_df = edited_df.where(pd.notna(edited_df), '')
                            st.session_state.vsme_disclosure_tables[editor_storage_key] = edited_df

                            if st.button("+ Aggiungi riga", key="b1_add_row_btn"):
                                table_df = st.session_state.vsme_disclosure_tables[editor_storage_key].copy()
                                new_row = pd.DataFrame([{col: '' for col in b1_default_columns}])
                                table_df = pd.concat([table_df, new_row], ignore_index=True)
                                st.session_state.vsme_disclosure_tables[editor_storage_key] = table_df
                                st.rerun()

                        dimensioni_storage_key = "vsme_table_B1_dimensioni"
                        if dimensioni_storage_key not in st.session_state.vsme_disclosure_tables:
                            st.session_state.vsme_disclosure_tables[dimensioni_storage_key] = pd.DataFrame([
                                {"Dimensione": "Totale degli attivi", "2024": "", "2025": ""},
                                {"Dimensione": "Fatturato", "2024": "", "2025": ""},
                                {"Dimensione": "Numero di dipendenti", "2024": "", "2025": ""},
                            ])
                        else:
                            dim_df = st.session_state.vsme_disclosure_tables[dimensioni_storage_key].copy()
                            expected_columns = ["Dimensione", "2024", "2025"]
                            for col in expected_columns:
                                if col not in dim_df.columns:
                                    dim_df[col] = ""
                            dim_df = dim_df[expected_columns].where(pd.notna(dim_df[expected_columns]), '')
                            if dim_df.empty:
                                dim_df = pd.DataFrame([
                                    {"Dimensione": "Totale degli attivi", "2024": "", "2025": ""},
                                    {"Dimensione": "Fatturato", "2024": "", "2025": ""},
                                    {"Dimensione": "Numero di dipendenti", "2024": "", "2025": ""},
                                ])
                            st.session_state.vsme_disclosure_tables[dimensioni_storage_key] = dim_df

                        st.markdown("##### Dimensioni")
                        dim_edited_df = st.data_editor(
                            st.session_state.vsme_disclosure_tables[dimensioni_storage_key],
                            key=f"editor_{dimensioni_storage_key}",
                            width='stretch',
                            hide_index=True,
                            num_rows="fixed",
                            disabled=["Dimensione"],
                        )
                        dim_edited_df = dim_edited_df.where(pd.notna(dim_edited_df), '')
                        st.session_state.vsme_disclosure_tables[dimensioni_storage_key] = dim_edited_df

                        st.markdown("##### Paese")
                        st.caption("delle principali operazioni e localizzazione degli asset significativi")
                        st.text_input(
                            "Paese",
                            key='b1_paese_operazioni_asset_significativi',
                            label_visibility="collapsed",
                            placeholder="Inserisci il paese"
                        )

                        geoloc_storage_key = "vsme_table_B1_geolocalizzazione_siti"
                        geoloc_columns = ["Sito (di proprietà, in locazione o gestito)", "Coordinate GPS"]
                        if geoloc_storage_key not in st.session_state.vsme_disclosure_tables:
                            st.session_state.vsme_disclosure_tables[geoloc_storage_key] = pd.DataFrame([
                                {col: '' for col in geoloc_columns}
                            ])
                        else:
                            geo_df = st.session_state.vsme_disclosure_tables[geoloc_storage_key].copy()
                            legacy_site_col = "Sito (owned, leased or managed)"
                            new_site_col = "Sito (di proprietà, in locazione o gestito)"
                            if legacy_site_col in geo_df.columns and new_site_col not in geo_df.columns:
                                geo_df[new_site_col] = geo_df[legacy_site_col]
                            for col in geoloc_columns:
                                if col not in geo_df.columns:
                                    geo_df[col] = ''
                            geo_df = geo_df[geoloc_columns].where(pd.notna(geo_df[geoloc_columns]), '')
                            if geo_df.empty:
                                geo_df = pd.DataFrame([{col: '' for col in geoloc_columns}])
                            st.session_state.vsme_disclosure_tables[geoloc_storage_key] = geo_df

                        if st.session_state.b1_perimetro == 'Consolidato':
                            consolidato_df = st.session_state.vsme_disclosure_tables.get("vsme_table_B1_consolidato")
                            if consolidato_df is not None and isinstance(consolidato_df, pd.DataFrame) and not consolidato_df.empty:
                                site_col = 'Tipo sede (es. sede legale, magazzino, stabilimento industriale, ecc.)'
                                consolidato_sites = []
                                if site_col in consolidato_df.columns:
                                    for value in consolidato_df[site_col].tolist():
                                        site_name = str(value or '').strip()
                                        if site_name:
                                            consolidato_sites.append(site_name)

                                if consolidato_sites:
                                    current_geo = st.session_state.vsme_disclosure_tables[geoloc_storage_key].copy()
                                    existing_names = {
                                        str(v).strip().lower()
                                        for v in current_geo["Sito (di proprietà, in locazione o gestito)"].tolist()
                                        if str(v).strip()
                                    }
                                    sites_to_insert = [
                                        site for site in consolidato_sites
                                        if site.lower() not in existing_names
                                    ]
                                    site_col = "Sito (di proprietà, in locazione o gestito)"
                                    for idx, row in current_geo.iterrows():
                                        if not sites_to_insert:
                                            break
                                        current_value = str(row.get(site_col, '')).strip()
                                        if not current_value:
                                            current_geo.at[idx, site_col] = sites_to_insert.pop(0)
                                    if sites_to_insert:
                                        rows_to_add = [
                                            {site_col: site, "Coordinate GPS": ''}
                                            for site in sites_to_insert
                                        ]
                                        current_geo = pd.concat([current_geo, pd.DataFrame(rows_to_add)], ignore_index=True)
                                    st.session_state.vsme_disclosure_tables[geoloc_storage_key] = current_geo

                        st.markdown("##### Geolocalizzazione siti")
                        geo_edited_df = st.data_editor(
                            st.session_state.vsme_disclosure_tables[geoloc_storage_key],
                            key=f"editor_{geoloc_storage_key}",
                            width='stretch',
                            hide_index=True,
                            num_rows="fixed",
                        )
                        geo_edited_df = geo_edited_df.where(pd.notna(geo_edited_df), '')
                        st.session_state.vsme_disclosure_tables[geoloc_storage_key] = geo_edited_df

                        if st.button("+ Aggiungi riga sito", key="b1_add_row_geoloc_btn"):
                            geo_table_df = st.session_state.vsme_disclosure_tables[geoloc_storage_key].copy()
                            new_geo_row = pd.DataFrame([{col: '' for col in geoloc_columns}])
                            geo_table_df = pd.concat([geo_table_df, new_geo_row], ignore_index=True)
                            st.session_state.vsme_disclosure_tables[geoloc_storage_key] = geo_table_df
                            st.rerun()

                        cert_storage_key = "vsme_table_B1_certificazioni_sostenibilita"
                        cert_columns = ["Breve descrizione", "Organismo di certificazione", "Data", "Punteggio"]
                        if cert_storage_key not in st.session_state.vsme_disclosure_tables:
                            st.session_state.vsme_disclosure_tables[cert_storage_key] = pd.DataFrame([
                                {col: '' for col in cert_columns}
                            ])
                        else:
                            cert_df = st.session_state.vsme_disclosure_tables[cert_storage_key].copy()
                            for col in cert_columns:
                                if col not in cert_df.columns:
                                    cert_df[col] = ''
                            cert_df = cert_df[cert_columns].where(pd.notna(cert_df[cert_columns]), '')
                            if cert_df.empty:
                                cert_df = pd.DataFrame([{col: '' for col in cert_columns}])
                            st.session_state.vsme_disclosure_tables[cert_storage_key] = cert_df

                        st.markdown("##### Certificazioni o marchi relativi alla sostenibilità")
                        cert_edited_df = st.data_editor(
                            st.session_state.vsme_disclosure_tables[cert_storage_key],
                            key=f"editor_{cert_storage_key}",
                            width='stretch',
                            hide_index=True,
                            num_rows="fixed",
                        )
                        cert_edited_df = cert_edited_df.where(pd.notna(cert_edited_df), '')
                        st.session_state.vsme_disclosure_tables[cert_storage_key] = cert_edited_df

                        if st.button("+ Aggiungi riga certificazione", key="b1_add_row_cert_btn"):
                            cert_table_df = st.session_state.vsme_disclosure_tables[cert_storage_key].copy()
                            new_cert_row = pd.DataFrame([{col: '' for col in cert_columns}])
                            cert_table_df = pd.concat([cert_table_df, new_cert_row], ignore_index=True)
                            st.session_state.vsme_disclosure_tables[cert_storage_key] = cert_table_df
                            st.rerun()

                    elif b2_is_custom:
                        st.caption("Tabella di raccolta dati riferita alla Disclosure B2")
                        st.caption(
                            "Per ogni risposta **Sì**, dovrà essere compilata la sezione C2 del Modulo Completo."
                        )

                        b2_key = 'vsme_table_B2_pratiche_politiche'
                        b2_df = get_b2_table()
                        b2_df = b2_df.where(pd.notna(b2_df), '')
                        for col in B2_COLONNE:
                            if col in b2_df.columns:
                                b2_df[col] = b2_df[col].astype(str).replace({'None': '', 'nan': ''})

                        st.markdown(
                            """
                            <style>
                            div[data-testid="stDataEditor"] [role="columnheader"] div {
                                white-space: normal !important;
                                line-height: 1.2 !important;
                                text-wrap: balance;
                            }
                            </style>
                            """,
                            unsafe_allow_html=True,
                        )

                        column_config_b2 = {
                            "Tema": st.column_config.TextColumn("Tema", disabled=True, width="medium"),
                        }
                        si_no_options = ["", "Sì", "No"]
                        b2_header_map = {
                            B2_COLONNE[0]: "Pratiche\n(temi di sostenibilità)",
                            B2_COLONNE[1]: "Politiche\n(temi di sostenibilità)",
                            B2_COLONNE[2]: "Politiche\npubbliche",
                            B2_COLONNE[3]: "Politiche con\nobiettivi",
                            B2_COLONNE[4]: "Iniziative\nfuture",
                        }
                        for col in B2_COLONNE:
                            column_config_b2[col] = st.column_config.SelectboxColumn(
                                b2_header_map.get(col, col),
                                options=si_no_options,
                                required=False,
                                width="small",
                            )

                        b2_edited = st.data_editor(
                            b2_df,
                            key=f"editor_{b2_key}",
                            column_config=column_config_b2,
                            hide_index=True,
                            num_rows="fixed",
                            use_container_width=True,
                        )
                        b2_edited = b2_edited.where(pd.notna(b2_edited), '')
                        for col in B2_COLONNE:
                            if col in b2_edited.columns:
                                b2_edited[col] = b2_edited[col].astype(str).replace({'None': '', 'nan': ''})
                        st.session_state.vsme_disclosure_tables[b2_key] = b2_edited

                    if not b1_is_custom and not b2_is_custom:
                        if disclosure.get("tables"):
                            for table in disclosure["tables"]:
                                editor_storage_key = f"vsme_table_{pillar_code}_{selected_mode}_{disclosure['code']}_{table['sheet_name']}"
                                if editor_storage_key not in st.session_state.vsme_disclosure_tables:
                                    st.session_state.vsme_disclosure_tables[editor_storage_key] = table["data"].copy()

                                edited_df = st.data_editor(
                                    st.session_state.vsme_disclosure_tables[editor_storage_key],
                                    key=f"editor_{editor_storage_key}",
                                    width='stretch',
                                    hide_index=True,
                                    num_rows="dynamic",
                                )
                                st.session_state.vsme_disclosure_tables[editor_storage_key] = edited_df
                        else:
                            st.info("Nessuna tabella di raccolta dati trovata per questa disclosure nel file Excel caricato in workspace.")

            st.divider()

    if status_normativo != "VSME":
        st.info("La diagnosi VSME e disponibile solo con esito: Rendicontazione VSME.")
    else:
        module_labels = {
            "base": "Modulo Base",
            "comprehensive": "Modulo Completo",
            "absolute": "Analisi VSME Assoluta",
        }
        module_choice = st.radio(
            "Percorso di diagnosi VSME:",
            [module_labels["base"], module_labels["comprehensive"], module_labels["absolute"]],
            horizontal=True,
            key="vsme_module_choice",
        )
        selected_mode = next((k for k, v in module_labels.items() if v == module_choice), "base")

        checklist_data, vsme_scale_options, err = load_vsme_checklist_from_excel()
        disclosure_reference, disclosure_reference_err = load_vsme_disclosure_reference()
        if err:
            st.warning(f"WARNING: {err}. Uso le domande VSME predefinite.")
            checklist_data = None
            vsme_scale_options = VSME_SCALE_OPTIONS
        if disclosure_reference_err:
            st.warning(f"WARNING: impossibile leggere la raccolta dati VSME: {disclosure_reference_err}")

        # Se il caricamento è fallito o non ha dati, usa le domande predefinite.
        default_questions = {
            "GEN": ["Overview della Governance generale/sostenibilità presente?"],
            "E": [
                "Consumi Energetici suddivisi (rinnovabili vs fossili)?",
                "Emissioni GHG Scope 1 e Scope 2 misurate?",
                "Registro dei rifiuti aggiornato?",
            ],
            "S": [
                "Dati organico per genere, contratto e orario?",
                "Monitoraggio infortuni sul lavoro?",
                "Ore di formazione medie annue calcolate?",
            ],
            "G": ["Policy scritta su etica e diritti umani?", "Referente interno per la sostenibilità?"],
        }
        questions_by_module = {
            "base": {pillar: list(questions) for pillar, questions in default_questions.items()},
            "comprehensive": {pillar: list(questions) for pillar, questions in default_questions.items()},
        }

        if not checklist_data or not checklist_data.get('base'):
            pass
        else:
            questions_by_module = {
                "base": {
                    "GEN": checklist_data["base"].get("GEN", []),
                    "E": checklist_data["base"].get("E", []),
                    "S": checklist_data["base"].get("S", []),
                    "G": checklist_data["base"].get("G", []),
                },
                "comprehensive": {
                    "GEN": checklist_data["comprehensive"].get("GEN", []),
                    "E": checklist_data["comprehensive"].get("E", []),
                    "S": checklist_data["comprehensive"].get("S", []),
                    "G": checklist_data["comprehensive"].get("G", []),
                },
            }

        pillar_titles = {
            "GEN": "Informazioni generali",
            "E": "Ambiente",
            "S": "Sociale",
            "G": "Governance",
        }
        response_colors = {
            "SI": "#2ecc71",
            "Si, ma necessita": "#f39c12",
            "No ma pianificato": "#3498db",
            "No": "#e74c3c",
        }
        default_palette = ["#2ecc71", "#f39c12", "#3498db", "#e74c3c", "#9b59b6", "#16a085"]
        for idx, option in enumerate(vsme_scale_options):
            response_colors.setdefault(to_vsme_plot_response_label(option), default_palette[idx % len(default_palette)])

        def build_vsme_results(module_payloads, scale_options):
            valid_keys = set()
            key_to_module = {}
            for payload in module_payloads:
                prefix = payload["prefix"]
                module_name = payload["module_name"]
                questions = payload["questions"]
                for pillar in ["GEN", "E", "S", "G"]:
                    if pillar in questions:
                        for i in range(len(questions[pillar])):
                            key = f"{prefix}_{pillar}_{i}"
                            valid_keys.add(key)
                            key_to_module[key] = module_name

            # "B2" è un pillar virtuale per le domande HSE AP / HSE Policies / Transition Plan
            checklist_label_map = {
                "GEN": "Disclosure B1",
                "B2": "Disclosure B2",
                "E": pillar_titles["E"],
                "S": pillar_titles["S"],
                "G": pillar_titles["G"],
            }
            all_pillar_keys = list(pillar_titles.keys()) + ["B2"]

            ordered_options = [label for label in VSME_PLOT_RESPONSE_ORDER if label in response_colors]
            pillar_totals = {p: {option: 0 for option in ordered_options} for p in all_pillar_keys}
            pillar_details = {p: [] for p in all_pillar_keys}
            for key, data in st.session_state.gap_answers.items():
                if key not in valid_keys:
                    continue
                pillar = data.get("pillar")
                answer = data.get("ans")
                answer_label = to_vsme_plot_response_label(answer)
                question = data.get("q", "")
                module_name = key_to_module.get(key, "")
                datapoints = get_question_datapoints(question)
                clean_question = clean_question_label(question)
                # Domande B2 vengono assegnate al pillar virtuale "B2" invece di "GEN"
                effective_pillar = "B2" if (pillar == "GEN" and is_b2_checklist_question(question)) else pillar
                checklist_label = checklist_label_map.get(effective_pillar, pillar_titles.get(effective_pillar, effective_pillar))
                if effective_pillar in pillar_totals and answer_label in pillar_totals[effective_pillar]:
                    pillar_totals[effective_pillar][answer_label] += datapoints
                if effective_pillar in pillar_details:
                    pillar_details[effective_pillar].append({
                        "Modulo": module_name,
                        "Checklist": checklist_label,
                        "Domanda": clean_question,
                        "Risposta": answer_label,
                        "Datapoints": datapoints,
                    })

            global_total_datapoints = sum(sum(pillar_totals[p].values()) for p in all_pillar_keys)
            response_totals = {option: 0 for option in ordered_options}
            for p in all_pillar_keys:
                for option in ordered_options:
                    response_totals[option] += pillar_totals[p][option]

            response_distribution_rows = []
            for option in ordered_options:
                datapoints = response_totals[option]
                pct_dataset = (datapoints / global_total_datapoints * 100) if global_total_datapoints else 0.0
                response_distribution_rows.append({
                    "Risposta": option,
                    "Datapoints": datapoints,
                    "% sul totale dataset": pct_dataset,
                })

            # Titoli da usare nelle intestazioni dei grafici per-pillar
            pillar_display_title = {
                "GEN": "Informazioni generali – Disclosure B1",
                "B2": "Informazioni generali – Disclosure B2",
                "E": pillar_titles["E"],
                "S": pillar_titles["S"],
                "G": pillar_titles["G"],
            }

            per_pillar_summary = {}
            per_pillar_details = {}
            stacked_rows = []
            all_rows = []
            for p in all_pillar_keys:
                title = pillar_display_title.get(p, p)
                total_datapoints = sum(pillar_totals[p].values())
                summary_rows = []
                detail_rows = []
                for option in ordered_options:
                    datapoints = pillar_totals[p][option]
                    pct = (datapoints / total_datapoints * 100) if total_datapoints else 0.0
                    global_pct = (datapoints / global_total_datapoints * 100) if global_total_datapoints else 0.0
                    summary_row = {
                        "Checklist": title,
                        "Risposta": option,
                        "Datapoints": datapoints,
                        "% sul totale checklist": pct,
                        "% sul totale dataset": global_pct,
                    }
                    summary_rows.append(summary_row)
                    stacked_rows.append(summary_row)
                for row in pillar_details[p]:
                    detail_row = row.copy()
                    detail_row["% sul totale checklist"] = (
                        detail_row["Datapoints"] / total_datapoints * 100 if total_datapoints else 0.0
                    )
                    detail_row["% sul totale dataset"] = (
                        detail_row["Datapoints"] / global_total_datapoints * 100 if global_total_datapoints else 0.0
                    )
                    detail_rows.append(detail_row)
                    all_rows.append(detail_row)
                df_summary = pd.DataFrame(summary_rows)
                df_details = pd.DataFrame(detail_rows)
                per_pillar_summary[p] = df_summary
                per_pillar_details[p] = df_details

            df_stacked = pd.DataFrame(stacked_rows)
            df_all_details = pd.DataFrame(all_rows)
            df_response_distribution = pd.DataFrame(response_distribution_rows)

            return {
                "summary": per_pillar_summary,
                "details": per_pillar_details,
                "stacked": df_stacked,
                "all_details": df_all_details,
                "response_distribution": df_response_distribution,
                "pillar_display_title": pillar_display_title,
            }

        tab_summary = None
        if selected_mode in ["base", "comprehensive"]:
            module_questions = questions_by_module[selected_mode]
            module_prefix = f"vsme_{selected_mode}"

            st.markdown(
                """
                <style>
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"] {
                    font-size: 1rem;
                    font-weight: 600;
                    border-radius: 8px 8px 0 0;
                    padding: 0.5rem 0.95rem;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(1) {
                    color: #1f4e79;
                    background: #eaf3ff;
                    border: 1px solid #bfd7f2;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(1) {
                    color: #0f3554;
                    background: #d6e9ff;
                    border-bottom-color: #d6e9ff;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(2) {
                    color: #2f6b3b;
                    background: #e7f4ea;
                    border: 1px solid #b9d8c0;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(2) {
                    color: #214d2a;
                    background: #d7eddc;
                    border-bottom-color: #d7eddc;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(3) {
                    color: #a54b3f;
                    background: #fde8e4;
                    border: 1px solid #f2c4ba;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(3) {
                    color: #7d362d;
                    background: #f9d7cf;
                    border-bottom-color: #f9d7cf;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(4) {
                    color: #8a6a00;
                    background: #fff4d6;
                    border: 1px solid #ecd89b;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(4) {
                    color: #6c5200;
                    background: #f8e7b0;
                    border-bottom-color: #f8e7b0;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(5) {
                    color: #5f4b8b;
                    background: #efe7ff;
                    border: 1px solid #d6c7f3;
                }
                div[data-testid="stVerticalBlock"] > div:has(.vsme-main-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(5) {
                    color: #49366f;
                    background: #e2d6fb;
                    border-bottom-color: #e2d6fb;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown("<div class='vsme-main-tabs-marker'></div>", unsafe_allow_html=True)
            tab_gen, c_v_E, c_v_S, c_v_G, tab_summary = st.tabs(["Informazioni generali", "Ambiente", "Sociale", "Governance", "Sintesi diagnosi"])
            if module_questions["GEN"]:
                render_vsme_disclosure_tables("GEN", selected_mode, tab_gen, disclosure_reference)
                render_gap_list(module_questions["GEN"], "GEN", tab_gen, vsme_scale_options, module_prefix)
            else:
                render_vsme_disclosure_tables("GEN", selected_mode, tab_gen, disclosure_reference)
            render_vsme_disclosure_tables("E", selected_mode, c_v_E, disclosure_reference)
            render_gap_list(module_questions["E"], "E", c_v_E, vsme_scale_options, module_prefix)
            render_vsme_disclosure_tables("S", selected_mode, c_v_S, disclosure_reference)
            render_gap_list(module_questions["S"], "S", c_v_S, vsme_scale_options, module_prefix)
            render_vsme_disclosure_tables("G", selected_mode, c_v_G, disclosure_reference)
            render_gap_list(module_questions["G"], "G", c_v_G, vsme_scale_options, module_prefix)
        if selected_mode == "absolute":
            module_payloads = [
                {
                    "module_name": module_labels["base"],
                    "prefix": "vsme_base",
                    "questions": questions_by_module["base"],
                },
                {
                    "module_name": module_labels["comprehensive"],
                    "prefix": "vsme_comprehensive",
                    "questions": questions_by_module["comprehensive"],
                },
            ]
        else:
            module_payloads = [
                {
                    "module_name": module_labels[selected_mode],
                    "prefix": f"vsme_{selected_mode}",
                    "questions": questions_by_module[selected_mode],
                }
            ]

        results = build_vsme_results(module_payloads, vsme_scale_options)

        target_container = tab_summary if tab_summary is not None else st.container()
        with target_container:
            st.divider()
            module_prefixes = [payload["prefix"] for payload in module_payloads]
            gap_summary = summarize_gap_answers(module_prefixes)
            completeness_label = f"{gap_summary['coverage']:.0f}%"
            if gap_summary["coverage"] >= 80 and gap_summary["missing_datapoints"] == 0:
                readiness_label = "Alta"
            elif gap_summary["coverage"] >= 50:
                readiness_label = "Media"
            else:
                readiness_label = "Bassa"

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Esito", status_normativo)
            m2.metric("Percorso", module_labels[selected_mode])
            m3.metric("Preparazione", readiness_label)
            m4.metric("Completezza dati", completeness_label)

            c_diag1, c_diag2 = st.columns(2)
            with c_diag1:
                st.markdown("### Cosa si applica")
                st.write(f"Esito automatico: {status_normativo}")
                st.write(f"Domande valutate: {gap_summary['total']}")
                st.write(f"Risposte pronte o parziali: {gap_summary['ready'] + gap_summary['partial']}")
            with c_diag2:
                st.markdown("### Cosa ti manca")
                if gap_summary["top_gaps"]:
                    for idx, question in enumerate(gap_summary["top_gaps"], start=1):
                        st.write(f"{idx}. {question}")
                else:
                    st.write("Nessun gap prioritario rilevato al momento.")

            st.markdown("### Prossime azioni consigliate")
            for idx, action in enumerate(build_priority_actions(), start=1):
                st.write(f"{idx}. {action}")

            if selected_mode == "absolute":
                st.subheader("📊 Vista aggregata VSME")
                st.write("Confronto stacked per checklist aggregando Modulo Base e Modulo Completo.")
            else:
                st.subheader(f"📊 Riepilogo diagnosi - {module_labels[selected_mode]}")

            df_distribution = results["response_distribution"].copy()
            fig_distribution = px.bar(
                df_distribution,
                x="Risposta",
                y="% sul totale dataset",
                color="Risposta",
                text=df_distribution["% sul totale dataset"].apply(lambda x: f"{x:.2f}%"),
                color_discrete_map=response_colors,
                category_orders={"Risposta": VSME_PLOT_RESPONSE_ORDER},
            )
            fig_distribution.update_layout(
                title="Percentuale sul totale dataset",
                yaxis_title="Percentuale sul totale dataset",
                xaxis_title="Risposta",
                legend_title="Risposta",
                showlegend=False,
            )
            st.plotly_chart(fig_distribution, width='stretch', key=f"vsme_distribution_{selected_mode}")

            table_distribution = df_distribution.copy()
            if len(table_distribution) > 0:
                raw_percentages = table_distribution["% sul totale dataset"].fillna(0).astype(float).tolist()
                rounded_percentages = [round(value, 2) for value in raw_percentages]
                total_datapoints_distribution = float(table_distribution["Datapoints"].fillna(0).sum())

                # Con datapoints presenti, forza la somma visibile a 100% correggendo il delta di arrotondamento.
                if total_datapoints_distribution > 0:
                    rounding_delta = round(100.0 - sum(rounded_percentages), 2)
                    if abs(rounding_delta) >= 0.01:
                        pivot_idx = max(range(len(raw_percentages)), key=lambda idx: raw_percentages[idx])
                        rounded_percentages[pivot_idx] = round(rounded_percentages[pivot_idx] + rounding_delta, 2)

                table_distribution["% sul totale dataset"] = [f"{max(value, 0.0):.2f}%" for value in rounded_percentages]

            st.dataframe(table_distribution, width='stretch', hide_index=True)

            st.subheader("📋 Checklist completa")
            all_details_table = results["all_details"].copy()
            if len(all_details_table) > 0:
                all_details_table["% sul totale checklist"] = all_details_table["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
                details_columns_order = [
                    "Modulo",
                    "Checklist",
                    "Domanda",
                    "Datapoints",
                    "% sul totale checklist",
                    "Risposta",
                ]
                existing_order = [col for col in details_columns_order if col in all_details_table.columns]
                remaining_cols = [col for col in all_details_table.columns if col not in existing_order]
                remaining_cols = [col for col in remaining_cols if col != "% sul totale dataset"]
                all_details_table = all_details_table[existing_order + remaining_cols]
            st.dataframe(all_details_table, width='stretch', hide_index=True)

        if selected_mode in ["base", "comprehensive"]:
            tab_mapping = {
                "GEN": tab_gen,
                "B2": tab_gen,   # Disclosure B2 mostrata nello stesso tab Informazioni generali
                "E": c_v_E,
                "S": c_v_S,
                "G": c_v_G,
            }
            pillar_display_title = results.get("pillar_display_title", pillar_titles)

            for pillar, tab in tab_mapping.items():
                with tab:
                    df_summary = results["summary"].get(pillar, pd.DataFrame())
                    df_details = results["details"].get(pillar, pd.DataFrame())
                    if df_summary.empty:
                        continue
                    section_title = pillar_display_title.get(pillar, pillar_titles.get(pillar, pillar))
                    st.subheader(f"📊 {section_title}")
                    fig = px.bar(
                        df_summary,
                        x="Risposta",
                        y="% sul totale checklist",
                        color="Risposta",
                        text=df_summary["% sul totale checklist"].apply(lambda x: f"{x:.2f}%"),
                        color_discrete_map=response_colors,
                    )
                    fig.update_layout(
                        showlegend=False,
                        yaxis_title="Percentuale sul totale checklist",
                        xaxis_title="Risposta",
                    )
                    st.plotly_chart(fig, width='stretch', key=f"vsme_bar_{selected_mode}_{pillar}")
                    details_table = df_details.copy()
                    if len(details_table) > 0:
                        details_table["% sul totale checklist"] = details_table["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
                        details_columns_order = [
                            "Modulo",
                            "Checklist",
                            "Domanda",
                            "Datapoints",
                            "% sul totale checklist",
                            "Risposta",
                        ]
                        existing_order = [col for col in details_columns_order if col in details_table.columns]
                        remaining_cols = [col for col in details_table.columns if col not in existing_order]
                        remaining_cols = [col for col in remaining_cols if col != "% sul totale dataset"]
                        details_table = details_table[existing_order + remaining_cols]
                    st.dataframe(details_table, width='stretch', hide_index=True)

# =====================================================================
# TAB 2: ANALISI RISCHI (MAPPA FISICA, IPCC E NGFS)
# =====================================================================
with t_rischi:
    st.caption("Percorso 2 di 3")
    st.subheader("Piano di azione & rischi")
    st.write("Qui trasformi la diagnosi in un piano operativo, aggiungi le sedi rilevanti e valuti il profilo di rischio climatico e di transizione.")
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"] {
            font-size: 1rem;
            font-weight: 600;
            border-radius: 8px 8px 0 0;
            padding: 0.5rem 0.95rem;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(1) {
            color: #1f4e79;
            background: #eaf3ff;
            border: 1px solid #bfd7f2;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(1) {
            color: #0f3554;
            background: #d6e9ff;
            border-bottom-color: #d6e9ff;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(2) {
            color: #2f6b3b;
            background: #e7f4ea;
            border: 1px solid #b9d8c0;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(2) {
            color: #214d2a;
            background: #d7eddc;
            border-bottom-color: #d7eddc;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"]:nth-child(3) {
            color: #8a6a00;
            background: #fff4d6;
            border: 1px solid #ecd89b;
        }
        div[data-testid="stVerticalBlock"] > div:has(.risk-tabs-marker) + div div[data-baseweb="tab-list"] button[role="tab"][aria-selected="true"]:nth-child(3) {
            color: #6c5200;
            background: #f8e7b0;
            border-bottom-color: #f8e7b0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='risk-tabs-marker'></div>", unsafe_allow_html=True)
    rt_fisico, rt_transizione, rt_credito = st.tabs(["🗺️ Piano & Mappa Asset", "🔄 Emissioni & Transizione", "💰 Stress Test Finanziario"])
    
    with rt_fisico:
        def ensure_hq_asset_on_map():
            hq_address = st.session_state.get("hq_address", "").strip()
            current_assets = st.session_state.portfolio_df.drop(columns=["Display_Size"], errors="ignore")
            if not current_assets.empty and "ID" in current_assets.columns:
                current_assets = current_assets[current_assets["ID"] != "HQ-SEDE"]

            if not hq_address:
                st.session_state.portfolio_df = process_portfolio_dataframe(current_assets) if not current_assets.empty else pd.DataFrame()
                return

            if st.session_state.get("hq_geocoded_address") != hq_address or st.session_state.get("hq_lat") is None or st.session_state.get("hq_lon") is None:
                try:
                    geolocator = Nominatim(user_agent="smes-reporting-support-hq")
                    location = geolocator.geocode(hq_address, timeout=10)
                    if not location:
                        return
                    st.session_state.hq_geocoded_address = hq_address
                    st.session_state.hq_lat = float(location.latitude)
                    st.session_state.hq_lon = float(location.longitude)
                except Exception:
                    return

            hq_row = pd.DataFrame([{
                "Name": st.session_state.get("company_name", "Sede Legale") or "Sede Legale",
                "Address": hq_address,
                "Lat": float(st.session_state.hq_lat),
                "Lon": float(st.session_state.hq_lon),
                "Operator": "SEDE",
                "ID": "HQ-SEDE",
                "Size": 7000,
            }])

            combined_assets = pd.concat([current_assets, hq_row], ignore_index=True)
            st.session_state.portfolio_df = process_portfolio_dataframe(combined_assets)
        
        if st.session_state.portfolio_df.empty and os.path.exists("centrali_operative_esatte.csv"):
            try:
                df_map = pd.read_csv("centrali_operative_esatte.csv")
                st.session_state.portfolio_df = process_portfolio_dataframe(df_map)
            except: pass
            
        def load_portfolio_file(uploaded_file):
            """Carica file CSV, XLSX o XLS e ritorna un DataFrame."""
            try:
                if uploaded_file.name.endswith('.csv'):
                    return pd.read_csv(uploaded_file)
                elif uploaded_file.name.endswith(('.xlsx', '.xls')):
                    return pd.read_excel(uploaded_file)
                else:
                    st.error(f"Formato file non supportato: {uploaded_file.name}. Usa CSV, XLSX o XLS.")
                    return pd.DataFrame()
            except Exception as e:
                st.error(f"Errore nel caricamento del file: {str(e)}")
                return pd.DataFrame()
            
        ensure_hq_asset_on_map()

        if not st.session_state.portfolio_df.empty:
            df_render = st.session_state.portfolio_df.copy()

            np.random.seed(42)
            base_risk = np.clip(100 - (df_render['Lat'] - 35) * 6 + np.random.randint(-10, 15, size=len(df_render)), 10, 100)

            st.subheader(
                "🌍 Selezione Scenario Climatico (IPCC AR6)",
                help="I 3 scenari (Shared Socioeconomic Pathways) elaborati dalle Nazioni Unite. Più lo scenario è fossile (SSP5), più il rischio fisico calcolato per l'impianto aumenta."
            )
            ipcc_scenario_mappa = st.radio(
                "Scenario IPCC",
                ["SSP1-2.6 (+1.5°C)", "SSP2-4.5 (+2.4°C)", "SSP5-8.5 (+4.0°C)"],
                horizontal=True,
                label_visibility="collapsed"
            )

            if "SSP1" in ipcc_scenario_mappa: risk_multiplier = 0.7
            elif "SSP2" in ipcc_scenario_mappa: risk_multiplier = 1.1
            else: risk_multiplier = 1.6
            df_render['Risk_Score'] = np.clip(base_risk * risk_multiplier, 10, 100).astype(int)

            top_risk_row = df_render.sort_values("Risk_Score", ascending=False).iloc[0]
            top_risk_name = top_risk_row.get("Name", "Asset")
            top_risk_score = int(top_risk_row.get("Risk_Score", 0))

            st.markdown("### Azioni prioritarie")
            for idx, action in enumerate(build_priority_actions(top_risk_score, top_risk_name), start=1):
                st.write(f"{idx}. {action}")

            r1, r2, r3 = st.columns(3)
            r1.metric("Asset mappati", len(df_render))
            r2.metric("Asset piu esposto", top_risk_name)
            r3.metric("Rischio massimo", f"{top_risk_score}/100")

            fig_portfolio = px.scatter_mapbox(
                df_render, lat="Lat", lon="Lon", hover_name="Name",
                hover_data={"Lat": False, "Lon": False, "ID": True, "Operator": True, "Address": True, "Risk_Score": True, "Size": True, "Display_Size": False},
                color="Risk_Score", size="Display_Size", color_continuous_scale=px.colors.diverging.RdYlGn_r,
                range_color=[10, 100], size_max=25, zoom=4.5 if len(df_render) > 1 else 10, mapbox_style="carto-positron", height=600
            )
            fig_portfolio.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
            st.plotly_chart(fig_portfolio, use_container_width=True)
        with st.expander("🏠 Aggiungi immobile da indirizzo", expanded=False):
            with st.form("manual_asset_address_form"):
                c_addr1, c_addr2 = st.columns([2, 1])
                with c_addr1:
                    manual_address = st.text_input(
                        "Indirizzo immobile",
                        key="manual_asset_address",
                        placeholder="Es. Via Roma 1, Milano, Italia"
                    )
                with c_addr2:
                    manual_asset_name = st.text_input(
                        "Nome immobile (opzionale)",
                        key="manual_asset_name",
                        placeholder="Es. Sede Milano"
                    )

                submit_manual_address = st.form_submit_button("Aggiungi immobile in mappa")

            if submit_manual_address:
                if not manual_address or not manual_address.strip():
                    st.warning("Inserisci un indirizzo valido.")
                else:
                    try:
                        geolocator = Nominatim(user_agent="smes-reporting-support-map")
                        location = geolocator.geocode(manual_address.strip(), timeout=10)
                        if not location:
                            st.error("Indirizzo non trovato. Prova a inserire via, numero civico, citta e paese.")
                        else:
                            new_asset = pd.DataFrame([{
                                "Name": manual_asset_name.strip() if manual_asset_name and manual_asset_name.strip() else "Immobile",
                                "Address": manual_address.strip(),
                                "Lat": float(location.latitude),
                                "Lon": float(location.longitude),
                                "Operator": "IMMOBILE",
                                "ID": f"IMM-{int(time.time())}",
                                "Size": 5000,
                            }])

                            current_assets = st.session_state.portfolio_df.drop(columns=["Display_Size"], errors="ignore")
                            combined_assets = pd.concat([current_assets, new_asset], ignore_index=True)
                            st.session_state.portfolio_df = process_portfolio_dataframe(combined_assets)
                            st.success("Immobile aggiunto. Il punto e ora incluso nella mappa rischi IPCC.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Errore durante la geolocalizzazione: {e}")

        with st.expander("📍 Aggiungi immobile da coordinate GPS", expanded=False):
            with st.form("manual_asset_gps_form"):
                c_gps1, c_gps2, c_gps3 = st.columns([1, 1, 1])
                with c_gps1:
                    gps_lat = st.number_input("Latitudine", key="manual_asset_lat", format="%.6f")
                with c_gps2:
                    gps_lon = st.number_input("Longitudine", key="manual_asset_lon", format="%.6f")
                with c_gps3:
                    gps_name = st.text_input("Nome immobile", key="manual_asset_gps_name", placeholder="Es. Sede GPS")

                submit_manual_gps = st.form_submit_button("Aggiungi coordinate in mappa")

            if submit_manual_gps:
                if gps_lat == 0.0 and gps_lon == 0.0:
                    st.warning("Inserisci coordinate GPS valide.")
                else:
                    gps_asset = pd.DataFrame([{
                        "Name": gps_name.strip() if gps_name and gps_name.strip() else "Immobile GPS",
                        "Address": f"GPS: {gps_lat:.6f}, {gps_lon:.6f}",
                        "Lat": float(gps_lat),
                        "Lon": float(gps_lon),
                        "Operator": "IMMOBILE",
                        "ID": f"GPS-{int(time.time())}",
                        "Size": 5000,
                    }])
                    current_assets = st.session_state.portfolio_df.drop(columns=["Display_Size"], errors="ignore")
                    combined_assets = pd.concat([current_assets, gps_asset], ignore_index=True)
                    st.session_state.portfolio_df = process_portfolio_dataframe(combined_assets)
                    st.success("Immobile GPS aggiunto alla mappa rischi IPCC.")
                    st.rerun()

        with st.expander("🔄 Carica un portfolio impianti diverso (Upload file)"):
            uploaded_portfolio = st.file_uploader("Carica File (CSV, XLSX, XLS)", type=['csv', 'xlsx', 'xls'], help="Il file deve contenere colonne chiamate Lat e Lon.")

            if st.button("Genera Mappa da nuovo file"):
                df_map = pd.DataFrame()
                if uploaded_portfolio:
                    df_map = load_portfolio_file(uploaded_portfolio)
                
                if not df_map.empty:
                    st.session_state.portfolio_df = process_portfolio_dataframe(df_map)

        if not st.session_state.portfolio_df.empty:
            df_render_table = st.session_state.portfolio_df.copy()
            with st.expander("Mostra dati tabellari"):
                table_columns = ["ID", "Name", "Operator", "Address", "Lat", "Lon", "Risk_Score"]
                available_columns = [column for column in table_columns if column in df_render_table.columns]
                st.dataframe(df_render_table[available_columns], use_container_width=True)

    with rt_transizione:
        st.subheader("Calcolatore GHG (Fattori ISPRA/DEFRA)", help="Incrocia i dati di consumo grezzi (es. Metri cubi) con i 'Fattori di Emissione' approvati a livello ministeriale per dedurre in automatico l'impronta di carbonio (tCO2).")
        
        EMISSION_FACTORS = {
            "Scope 1 - Gas Naturale": {"scope": "scope1", "unita": {"Metri Cubi (Sm3)": 1.98}},
            "Scope 1 - Gasolio": {"scope": "scope1", "unita": {"Litri (L)": 2.68}},
            "Scope 2 - Elettricità (Mix Italia)": {"scope": "scope2", "unita": {"MWh": 259.0}},
            "Scope 3 - Trasporto Merci": {"scope": "scope3", "unita": {"Tonnellate-km": 0.11}}
        }
        
        c_calc1, c_calc2, c_calc3 = st.columns([2, 1, 1])
        fonte_sel = c_calc1.selectbox("Categoria Consumo", list(EMISSION_FACTORS.keys()), help="Suddivisione secondo lo standard globale 'GHG Protocol'.")
        unita_sel = c_calc2.selectbox("Unità", list(EMISSION_FACTORS[fonte_sel]["unita"].keys()))
        fattore = EMISSION_FACTORS[fonte_sel]["unita"][unita_sel]
        scope_target = EMISSION_FACTORS[fonte_sel]["scope"]
        consumo = c_calc1.number_input("Volume Annuo", min_value=0.0, step=100.0)
        co2_calc = (consumo * fattore) / 1000 
        
        c_calc3.metric("Emissioni", f"{co2_calc:,.2f} tCO2", help=f"Fattore: {fattore} kgCO2 per unità. Diviso 1000 per avere le tonnellate.")
        if st.button(f"➕ Somma allo {scope_target.capitalize()}"):
            if co2_calc > 0:
                st.session_state[scope_target] += int(co2_calc)
                sync_from_scopes()
                st.success("Aggiunte!")
                time.sleep(1)
                st.rerun()

        st.divider()
        c_ghg1, c_ghg2 = st.columns(2)
        with c_ghg1:
            st.number_input("Scope 1 (tCO2)", value=st.session_state.scope1, step=500, key='scope1', on_change=sync_from_scopes, help="Emissioni dirette da caldaie, forni, e auto aziendali.")
            st.number_input("Scope 2 (tCO2)", value=st.session_state.scope2, step=500, key='scope2', on_change=sync_from_scopes, help="Emissioni indirette dalla corrente elettrica acquistata.")
            st.number_input("Scope 3 (tCO2)", value=st.session_state.scope3, step=500, key='scope3', on_change=sync_from_scopes, help="Emissioni catena del valore (fornitori, logistica, uso dei prodotti).")
        with c_ghg2:
            st.info(f"### Impronta Lorda\n# {get_tot_emissions():,} tCO2")
            st.slider("Efficacia Decarbonizzazione (%)", 0, 100, key='perc_red', on_change=sync_from_perc, help="Simula una politica di riduzione (es. acquisto impianti green o quote compensative). Genera le Emissioni Nette, usate negli Stress Test finanziari.")
            st.success(f"**Emissioni Nette:** {st.session_state.em_final:,} tCO2")

    with rt_credito:
        st.subheader("Stress Test Finanziario (Scenari NGFS)", help="Interroga il database Network for Greening the Financial System (NGFS) che traccia il prezzo ombra del carbonio fino al 2050 diviso per paese e scenario.")
        c_cred1, c_cred2 = st.columns(2)
        with c_cred1: st.number_input("Rata Prestito Transizione (€)", value=st.session_state.rata_prestito, step=100000, key='rata_prestito', help="Sottrae un costo annuo fisso dal calcolo dell'EBITDA.")
        with c_cred2: st.slider("Severità Policy", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier', help="Moltiplica il prezzo base della Carbon Tax per simulare scenari normativi regionali estremamente restrittivi.")

        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            profit = st.session_state.revenue - st.session_state.opex - (eff_price * st.session_state.em_final) - st.session_state.rata_prestito
            plot_data.append({"Anno": row['Anno'], "Utile Netto (€)": profit, "Scenario": row['Scenario']})
        
        st.plotly_chart(px.line(pd.DataFrame(plot_data), x="Anno", y="Utile Netto (€)", color="Scenario", title="EBITDA Netto post-Carbon Tax"), use_container_width=True)

# =====================================================================
# TAB 5: DOWNLOAD
# =====================================================================
with t_down:
    st.caption("Percorso 3 di 3")
    st.subheader("Deliverable finale")
    st.write("Questa sezione prepara un output leggibile per management, consulenza operativa o uso tecnico interno.")

    report_type = st.radio(
        "Formato deliverable",
        ["Executive", "Operativo", "Tecnico"],
        horizontal=True,
        key="deliverable_type",
    )

    export_gap_summary = summarize_gap_answers(["vsme_base", "vsme_comprehensive"])
    export_actions = build_priority_actions()
    asset_count = 0 if st.session_state.portfolio_df.empty else len(st.session_state.portfolio_df)

    st.markdown("### Anteprima deliverable")
    preview_lines = []
    if report_type == "Executive":
        preview_lines = [
            f"Esito azienda: {st.session_state.get('status_normativo', 'VSME')}",
            f"Completezza dati stimata: {export_gap_summary['coverage']:.0f}%",
            f"Gap prioritari aperti: {export_gap_summary['missing']}",
            f"Asset o sedi considerate: {asset_count}",
        ]
    elif report_type == "Operativo":
        preview_lines = [
            f"Checklist valutate: {export_gap_summary['total']}",
            f"Risposte pronte: {export_gap_summary['ready']}",
            f"Risposte parziali: {export_gap_summary['partial']}",
            f"Risposte assenti: {export_gap_summary['missing']}",
        ]
    else:
        preview_lines = [
            f"Sedi o asset geolocalizzati: {asset_count}",
            f"Emissioni lorde stimate: {get_tot_emissions():,} tCO2",
            f"Emissioni nette stimate: {st.session_state.em_final:,} tCO2",
            f"Scenario policy multiplier: {st.session_state.policy_multiplier:.1f}x",
        ]

    for idx, line in enumerate(preview_lines, start=1):
        st.write(f"{idx}. {line}")

    st.markdown("### Azioni incluse nel report")
    for idx, action in enumerate(export_actions, start=1):
        st.write(f"{idx}. {action}")

    if st.button("🪄 Genera deliverable PDF", help="Compila un report PDF sintetico a partire dai dati gia inseriti nell'app."):
        report_titles = {
            "Executive": "Executive ESG Brief",
            "Operativo": "Operational ESG Action Plan",
            "Tecnico": "Technical ESG Output",
        }
        report_filenames = {
            "Executive": "Deliverable_Executive.pdf",
            "Operativo": "Deliverable_Operativo.pdf",
            "Tecnico": "Deliverable_Tecnico.pdf",
        }

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 18)
        pdf.cell(200, 15, txt=report_titles[report_type], ln=True, align='C')
        pdf.set_font("Arial", size=11)
        pdf.ln(4)
        pdf.multi_cell(0, 8, txt=f"Esito: {st.session_state.get('status_normativo', 'VSME')}")
        pdf.multi_cell(0, 8, txt=f"Completezza dati: {export_gap_summary['coverage']:.0f}%")
        pdf.multi_cell(0, 8, txt=f"Asset o sedi considerate: {asset_count}")
        pdf.ln(2)
        for idx, action in enumerate(export_actions, start=1):
            safe_action = action.encode('latin-1', 'ignore').decode('latin-1')
            pdf.multi_cell(0, 8, txt=f"{idx}. {safe_action}")

        st.download_button("Scarica PDF", pdf.output(dest='S').encode('latin-1'), report_filenames[report_type])

project_name_for_autosave = (
    st.session_state.get('project_name_input', '').strip()
    or st.session_state.get('current_project_name', '').strip()
    or st.session_state.get('company_name', '').strip()
)
if project_name_for_autosave:
    autosave_project_if_needed(project_name_for_autosave)
