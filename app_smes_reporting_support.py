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
from openai import OpenAI
from geopy.geocoders import Nominatim
import os
import re
import requests
from datetime import datetime, timedelta
from functools import lru_cache

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="SMEs Reporting Support", layout="wide")

# --- CACHE PERSISTENTE E THROTTLING (Anti-Rate-Limiting) ---
CACHE_DIR = ".yfinance_cache"
CACHE_TIMEOUT_HOURS = 24
THROTTLE_DELAY = 2

os.makedirs(CACHE_DIR, exist_ok=True)

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
VSME_SCALE_OPTIONS = ["Yes", "Yes, but integration needed", "No, but planned", "No"]
VSME_DEFAULT_FILE = "Gap Analysis Template_VSME_Standard_Tool v3.xlsx"

def load_vsme_checklist_from_excel(file_path=VSME_DEFAULT_FILE):
    """Carica le domande del checklist VSME dal file Excel."""
    try:
        import openpyxl
        # Carica il workbook con data_only=True per ottenere valori calcolati, non formule
        wb = openpyxl.load_workbook(file_path, data_only=True)

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
                    checklist_data['base'][pillar].append(label_base)
                
                # Column H = documento comprehensive, Column J = datapoints comprehensive
                if cell_h and isinstance(cell_h, str) and cell_h.strip():
                    datapoints_comp = parse_datapoints(cell_j)
                    label_comp = f"{cell_h.strip()} ({datapoints_comp} datapoints)"
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
st.session_state.setdefault('portfolio_df', pd.DataFrame())
st.session_state.setdefault('impresa_area', 'UE')
st.session_state.setdefault('sucursale_eu_200', 'No')
st.session_state.setdefault('hq_address', '')
st.session_state.setdefault('hq_geocoded_address', '')
st.session_state.setdefault('hq_lat', None)
st.session_state.setdefault('hq_lon', None)

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

    # Scelta UE o Extra-UE
    if 'impresa_area' not in st.session_state:
        st.session_state.impresa_area = 'UE'
    
    impresa_area = st.radio("Sede Legale", ["UE", "Extra-UE"], key='impresa_area', horizontal=True)
    st.text_input("Indirizzo sede", key="hq_address", placeholder="Es. Via Roma 1, Milano, Italia")
    
    # Campi condizionali per UE
    if st.session_state.impresa_area == "UE":
        st.session_state.dipendenti = st.number_input("Numero dipendenti", value=st.session_state.dipendenti, step=10)
        st.session_state.revenue = st.number_input("Fatturato netto (€)", value=st.session_state.revenue, step=1000000)

        ue_esrs = st.session_state.dipendenti > 1000 and st.session_state.revenue > 450000000
        if ue_esrs:
            st.session_state.status_normativo = "CSRD_GRANDE"
            st.error("**Esito:** OBBLIGO ESRS (Grande Impresa UE: Dipendenti > 1.000 e fatturato netto > 450M €)", icon="⚖️")
        else:
            st.session_state.status_normativo = "VSME"
            st.success("**Esito:** Rendicontazione VSME (dipendenti <= 1.000 e fatturato netto <= 450M €)")
    
    # Campi condizionali per Extra-UE
    elif st.session_state.impresa_area == "Extra-UE":
        st.session_state.revenue = st.number_input("Fatturato netto in UE (€)", value=st.session_state.revenue, step=1000000)
        sucursale_eu_200 = st.radio(
            "Sucursale UE con fatturato netto > 200 mln €?",
            ["Sì", "No"],
            key='sucursale_eu_200',
            horizontal=True
        )

        extra_ue_esrs = st.session_state.revenue > 450000000 and sucursale_eu_200 == "Sì"
        if extra_ue_esrs:
            st.session_state.status_normativo = "CSRD_GRANDE"
            st.error("**Esito:** OBBLIGO ESRS (Impresa Extra-UE: Fatturato netto in UE > 450M € e sucursale UE > 200 mln €)", icon="⚖️")
        else:
            st.session_state.status_normativo = "VSME"
            st.success("**Esito:** Rendicontazione VSME (fatturato netto in UE <= 450M € oppure sucursale UE > 200 mln € = No)")

    st.divider()

    st.subheader("AI Data Extraction (PDF)")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password", help="Inserisci la chiave segreta fornita dalla piattaforma OpenAI.")
    uploaded_pdf = st.file_uploader("Carica Bilancio CEE", type="pdf")
    if uploaded_pdf and st.button("Analizza con AI"):
        with st.spinner("Elaborazione testo tramite AI in corso..."):
            time.sleep(2)
            st.session_state.totale_attivo = 32_000_000
            st.session_state.revenue = 65_000_000
            st.session_state.dipendenti = 310
            st.session_state.opex = 40_000_000
            st.session_state.capex_totale = 15_000_000
            st.session_state.sector = "Utilities"
            st.session_state.industry = "Renewable Electricity"
            st.session_state.quotata = False
            st.success("SIMULAZIONE AI COMPLETATA! Dati caricati.")
            time.sleep(1)
            st.rerun()

# --- CORPO PRINCIPALE E TABS ---
st.title("🌍 SMEs Reporting Support")

def summarize_gap_answers(module_prefixes=None):
    rows = []
    for key, data in st.session_state.get("gap_answers", {}).items():
        if module_prefixes and not any(key.startswith(prefix) for prefix in module_prefixes):
            continue

        answer = str(data.get("ans", "")).strip()
        question = re.sub(r'\s*\(\d+ datapoints\)$', '', str(data.get("q", "")).strip())
        if not answer:
            continue

        normalized_answer = answer.lower()
        if normalized_answer == "yes":
            status = "ready"
            severity = 0
        elif "integration" in normalized_answer:
            status = "partial"
            severity = 1
        elif normalized_answer.startswith("no"):
            status = "missing"
            severity = 2
        else:
            status = "partial"
            severity = 1

        rows.append({
            "question": question,
            "answer": answer,
            "status": status,
            "severity": severity,
        })

    total = len(rows)
    ready = sum(1 for row in rows if row["status"] == "ready")
    partial = sum(1 for row in rows if row["status"] == "partial")
    missing = sum(1 for row in rows if row["status"] == "missing")
    coverage = ((ready + partial) / total * 100) if total else 0.0

    top_gaps = []
    seen_questions = set()
    for row in sorted(rows, key=lambda item: (-item["severity"], item["question"])):
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
            for i, q in enumerate(questions):
                # Creare colonne: selectbox + bottone PDF allineati
                col_q, col_pdf = st.columns([4, 1], vertical_alignment="bottom")
                
                with col_q:
                    val = st.selectbox(
                        f"{i+1}. {q}",
                        scale_options,
                        key=f"{prefix}_{pillar_code}_{i}"
                    )
                    st.session_state.gap_answers[f"{prefix}_{pillar_code}_{i}"] = {
                        "ans": val,
                        "pillar": pillar_code,
                        "q": q,
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
        if err:
            st.warning(f"WARNING: {err}. Uso le domande VSME predefinite.")
            checklist_data = None
            vsme_scale_options = VSME_SCALE_OPTIONS

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
            "Yes": "#2ecc71",
            "Yes, but integration needed": "#f39c12",
            "No, but planned": "#3498db",
            "No": "#e74c3c",
        }
        default_palette = ["#2ecc71", "#f39c12", "#3498db", "#e74c3c", "#9b59b6", "#16a085"]
        for idx, option in enumerate(vsme_scale_options):
            response_colors.setdefault(option, default_palette[idx % len(default_palette)])

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
            
            pillar_totals = {pillar: {option: 0 for option in scale_options} for pillar in pillar_titles}
            pillar_details = {pillar: [] for pillar in pillar_titles}
            for key, data in st.session_state.gap_answers.items():
                if key not in valid_keys:
                    continue
                pillar = data.get("pillar")
                answer = data.get("ans")
                question = data.get("q", "")
                module_name = key_to_module.get(key, "")
                match = re.search(r'\((\d+) datapoints\)', question)
                datapoints = int(match.group(1)) if match else 0
                clean_question = re.sub(r'\s*\(\d+ datapoints\)$', '', question).strip()
                if pillar in pillar_totals and answer in pillar_totals[pillar]:
                    pillar_totals[pillar][answer] += datapoints
                if pillar in pillar_details:
                    pillar_details[pillar].append({
                        "Modulo": module_name,
                        "Checklist": pillar_titles.get(pillar, pillar),
                        "Domanda": clean_question,
                        "Risposta": answer,
                        "Datapoints": datapoints,
                    })

            per_pillar_summary = {}
            per_pillar_details = {}
            stacked_rows = []
            all_rows = []
            for pillar, title in pillar_titles.items():
                total_datapoints = sum(pillar_totals[pillar].values())
                summary_rows = []
                detail_rows = []
                for option in scale_options:
                    datapoints = pillar_totals[pillar][option]
                    pct = (datapoints / total_datapoints * 100) if total_datapoints else 0.0
                    summary_row = {
                        "Checklist": title,
                        "Risposta": option,
                        "Datapoints": datapoints,
                        "% sul totale checklist": pct,
                    }
                    summary_rows.append(summary_row)
                    stacked_rows.append(summary_row)
                for row in pillar_details[pillar]:
                    detail_row = row.copy()
                    detail_row["% sul totale checklist"] = (
                        detail_row["Datapoints"] / total_datapoints * 100 if total_datapoints else 0.0
                    )
                    detail_rows.append(detail_row)
                    all_rows.append(detail_row)
                df_summary = pd.DataFrame(summary_rows)
                df_summary["% sul totale checklist"] = df_summary["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
                df_details = pd.DataFrame(detail_rows)
                if len(df_details) > 0:
                    df_details["% sul totale checklist"] = df_details["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
                per_pillar_summary[pillar] = df_summary
                per_pillar_details[pillar] = df_details

            df_stacked = pd.DataFrame(stacked_rows)
            if len(df_stacked) > 0:
                df_stacked["% sul totale checklist"] = df_stacked["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
            df_all_details = pd.DataFrame(all_rows)
            if len(df_all_details) > 0:
                df_all_details["% sul totale checklist"] = df_all_details["% sul totale checklist"].apply(lambda x: f"{x:.2f}%")
            
            return {
                "summary": per_pillar_summary,
                "details": per_pillar_details,
                "stacked": df_stacked,
                "all_details": df_all_details,
            }

        tab_summary = None
        if selected_mode in ["base", "comprehensive"]:
            module_questions = questions_by_module[selected_mode]
            module_prefix = f"vsme_{selected_mode}"

            tab_gen, c_v_E, c_v_S, c_v_G, tab_summary = st.tabs(["Informazioni generali", "Ambiente", "Sociale", "Governance", "Sintesi diagnosi"])
            if module_questions["GEN"]:
                render_gap_list(module_questions["GEN"], "GEN", tab_gen, vsme_scale_options, module_prefix)
            render_gap_list(module_questions["E"], "E", c_v_E, vsme_scale_options, module_prefix)
            render_gap_list(module_questions["S"], "S", c_v_S, vsme_scale_options, module_prefix)
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
            if gap_summary["coverage"] >= 80 and gap_summary["missing"] == 0:
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

            df_stacked = results["stacked"]
            fig_stacked = px.bar(
                df_stacked,
                x="Checklist",
                y="% sul totale checklist",
                color="Risposta",
                barmode="stack",
                text=df_stacked["% sul totale checklist"],
                color_discrete_map=response_colors,
                category_orders={"Checklist": list(pillar_titles.values())},
            )
            fig_stacked.update_layout(
                yaxis_title="Percentuale sul totale datapoints",
                xaxis_title="Checklist",
                legend_title="Risposta",
            )
            st.plotly_chart(fig_stacked, width='stretch', key=f"vsme_stacked_{selected_mode}")

            st.subheader("📋 Checklist completa")
            st.dataframe(results["all_details"], width='stretch', hide_index=True)

        if selected_mode in ["base", "comprehensive"]:
            tab_mapping = {
                "GEN": tab_gen,
                "E": c_v_E,
                "S": c_v_S,
                "G": c_v_G,
            }

            for pillar, tab in tab_mapping.items():
                with tab:
                    df_summary = results["summary"][pillar]
                    df_details = results["details"][pillar]
                    st.subheader(f"📊 {pillar_titles[pillar]}")
                    fig = px.bar(
                        df_summary,
                        x="Risposta",
                        y="% sul totale checklist",
                        color="Risposta",
                        text=df_summary["% sul totale checklist"],
                        color_discrete_map=response_colors,
                    )
                    fig.update_layout(
                        showlegend=False,
                        yaxis_title="Percentuale sul totale datapoints",
                        xaxis_title="Risposta",
                    )
                    st.plotly_chart(fig, width='stretch', key=f"vsme_bar_{selected_mode}_{pillar}")
                    st.dataframe(df_details, width='stretch', hide_index=True)

# =====================================================================
# TAB 2: ANALISI RISCHI (MAPPA FISICA, IPCC E NGFS)
# =====================================================================
with t_rischi:
    st.caption("Percorso 2 di 3")
    st.subheader("Piano di azione & rischi")
    st.write("Qui trasformi la diagnosi in un piano operativo, aggiungi le sedi rilevanti e valuti il profilo di rischio climatico e di transizione.")
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
