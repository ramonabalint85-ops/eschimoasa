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

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk AI Enterprise", layout="wide")

# --- DATABASE GICS (Global Industry Classification Standard) ---
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

# --- SINCRONIZZAZIONE (Session State) ---
st.session_state.setdefault('sector', 'Industrials')
st.session_state.setdefault('industry', 'Machinery')
st.session_state.setdefault('selected_country', 'Italia')
st.session_state.setdefault('revenue', 0)
st.session_state.setdefault('opex', 0)
st.session_state.setdefault('totale_attivo', 0)
st.session_state.setdefault('dipendenti', 0)
st.session_state.setdefault('quotata', False)
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
st.session_state.setdefault('materiality_scores', {
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
})

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_scopes(): sync_from_perc()
def sync_revenue_from_triage(): st.session_state.revenue = st.session_state.rev_triage_widget

# --- SCALE DI VALUTAZIONE (READINESS E MATERIALITÀ) ---
SCALE_OPTIONS = [
    "Per niente (0% - Nessuna azione intrapresa)",
    "In fase iniziale (Attività pianificata o discussa)",
    "Parzialmente (Policy esistente, implementazione frammentaria)",
    "In gran parte (Processo attivo, non ancora auditabile)",
    "Quasi completamente (Manca solo verifica finale o XBRL)",
    "Completamente (100% - Allineato a ESRS e verificabile)"
]

SCALE_VALUES = {
    "Per niente (0% - Nessuna azione intrapresa)": 0,
    "In fase iniziale (Attività pianificata o discussa)": 1,
    "Parzialmente (Policy esistente, implementazione frammentaria)": 2,
    "In gran parte (Processo attivo, non ancora auditabile)": 3,
    "Quasi completamente (Manca solo verifica finale o XBRL)": 4,
    "Completamente (100% - Allineato a ESRS e verificabile)": 5
}

# --- MOTORE DATI, PREZZI LIVE E TASSONOMIA ---
@st.cache_data(ttl=3600)
def get_live_eu_ets_price():
    try:
        ticker = yf.Ticker("KEZ=F")
        hist = ticker.history(period="1d")
        if not hist.empty: return round(float(hist['Close'].iloc[-1]), 2)
    except: pass
    return 70.00

def get_nace_section(d_code):
    try:
        d = int(d_code)
        if 1 <= d <= 3: return 'A'
        if 5 <= d <= 9: return 'B'
        if 10 <= d <= 33: return 'C'
        if d == 35: return 'D'
        if 36 <= d <= 39: return 'E'
        if 41 <= d <= 43: return 'F'
        if 45 <= d <= 47: return 'G'
        if 49 <= d <= 53: return 'H'
        if 55 <= d <= 56: return 'I'
        if 58 <= d <= 63: return 'J'
        if 64 <= d <= 66: return 'K'
        if d == 68: return 'L'
        if 69 <= d <= 75: return 'M'
        if 77 <= d <= 82: return 'N'
        if d == 84: return 'O'
        if d == 85: return 'P'
        if 86 <= d <= 88: return 'Q'
        if 90 <= d <= 93: return 'R'
        if 94 <= d <= 96: return 'S'
        if 97 <= d <= 98: return 'T'
        if d >= 99: return 'U'
    except: pass
    return 'UNKNOWN'

@st.cache_data
def load_taxonomy_json(file_content_or_path="taxonomy.json"):
    eligible_prefixes = set()
    try:
        if hasattr(file_content_or_path, 'getvalue'):
            data = json.loads(file_content_or_path.getvalue().decode('utf-8', errors='ignore'))
        else:
            if not os.path.exists(file_content_or_path): return set()
            with open(file_content_or_path, 'r', encoding='utf-8', errors='ignore') as f: data = json.load(f)
        for activity in data.get('activities', []):
            for code in activity.get('nace_codes', []):
                if not code: continue
                num_part = re.sub(r'^[A-Z]+', '', code.strip(), flags=re.IGNORECASE).replace('.', '')
                if len(num_part) == 1: num_part = "0" + num_part
                if num_part: eligible_prefixes.add(num_part)
        return eligible_prefixes
    except: return set()

@st.cache_data
def load_nace_hierarchy(file_content_or_path="NACE_Rev.2.1.rdf"):
    try:
        if hasattr(file_content_or_path, 'getvalue'): content = file_content_or_path.getvalue().decode('utf-8', errors='ignore')
        else:
            if not os.path.exists(file_content_or_path): return {}
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

        for d_code, d_data in divisions.items():
            s_code = get_nace_section(d_code)
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
                if 'Net Zero' in s: p = (y - 2020) * 12
                elif 'Transizione Ritardata' in s: p = 10 if y < 2030 else (y - 2030) * 20 + 20 
                else: p = (y - 2020) * 2
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

# --- FUNZIONE MAPPA RISCHIO FISICO CENTRALINE CSV ---
@st.cache_data
def load_plants_csv():
    file_path = "it_en centrali produzione energia.xls - Sheet1.csv"
    if not os.path.exists(file_path):
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(file_path, skiprows=1)
        df = df.dropna(subset=['Operator', 'Installation name', 'Address'])
        df['Allocation'] = pd.to_numeric(df['Allocation total (per installation) '], errors='coerce').fillna(1000)
        
        # Geocodifica Approssimativa sulle province per velocità UI
        prov_dict = {
            'TO': (45.07, 7.68), 'VC': (45.32, 8.42), 'NO': (45.32, 8.42), 'CN': (44.38, 7.54),
            'AT': (44.90, 8.20), 'AL': (44.91, 8.61), 'BI': (45.32, 8.42), 'VB': (45.92, 8.55),
            'AO': (45.73, 8.32), 'MI': (45.46, 9.19), 'BG': (45.69, 9.67), 'BS': (45.54, 10.21),
            'CO': (45.80, 9.08), 'CR': (45.13, 10.02), 'MN': (45.13, 10.02), 'LC': (43.84, 10.50), 
            'LO': (45.85, 9.39), 'MB': (45.15, 10.79), 'PV': (45.31, 9.50), 'SO': (46.17, 9.87), 
            'VA': (45.82, 8.82), 'BZ': (46.49, 11.35), 'TN': (46.06, 11.12), 'VR': (45.43, 10.99), 
            'VI': (45.54, 11.53), 'BL': (46.14, 12.21), 'TV': (45.66, 12.24), 'VE': (45.43, 12.33), 
            'PD': (45.40, 11.87), 'RO': (45.07, 11.79), 'UD': (45.40, 11.87), 'PN': (45.95, 12.66), 
            'GO': (45.94, 13.62), 'TS': (45.64, 13.77), 'GE': (44.40, 8.94), 'SV': (44.30, 8.48), 
            'IM': (44.30, 8.48), 'SP': (44.10, 9.82), 'PR': (44.80, 10.32), 'PC': (44.80, 10.32), 
            'RE': (44.69, 10.63), 'MO': (45.15, 10.79), 'BO': (44.49, 11.34), 'FE': (44.83, 11.61), 
            'RA': (44.41, 12.19), 'FC': (44.83, 11.61), 'RN': (44.06, 12.56), 'FI': (43.76, 11.25), 
            'MS': (44.03, 10.13), 'LU': (43.84, 10.50), 'PI': (43.71, 10.40), 'LI': (43.71, 10.40), 
            'AR': (43.46, 11.88), 'SI': (43.31, 11.33), 'GR': (42.76, 11.11), 'PG': (43.11, 12.39), 
            'TR': (42.56, 12.64), 'PU': (43.91, 12.91), 'AN': (43.61, 13.51), 'MC': (43.30, 13.45), 
            'AP': (42.85, 13.57), 'RM': (41.90, 12.49), 'VT': (42.42, 11.87), 'RI': (42.42, 11.87), 
            'FR': (41.64, 13.34), 'LT': (41.46, 12.90), 'AQ': (42.35, 13.39), 'TE': (42.66, 13.70), 
            'PE': (42.46, 14.21), 'CH': (41.34, 14.37), 'CB': (41.56, 14.66), 'IS': (41.59, 14.23), 
            'NA': (40.85, 14.26), 'CE': (41.07, 14.33), 'BN': (41.11, 14.78), 'AV': (40.91, 14.78), 
            'SA': (40.68, 14.76), 'FG': (41.46, 15.54), 'BA': (41.11, 16.87), 'TA': (40.47, 17.24), 
            'BR': (40.63, 17.93), 'LE': (40.35, 18.17), 'MT': (40.66, 16.60), 'PZ': (40.63, 15.80), 
            'CS': (39.30, 16.25), 'CZ': (39.30, 16.25), 'KR': (38.90, 16.59), 'VV': (38.67, 16.10), 
            'RC': (38.11, 15.64), 'PA': (38.11, 13.36), 'TP': (38.01, 12.53), 'AG': (37.31, 13.58), 
            'CL': (37.49, 14.06), 'EN': (37.56, 14.27), 'CT': (37.50, 15.09), 'SR': (37.07, 15.28), 
            'RG': (37.07, 15.28), 'ME': (38.19, 15.55), 'CA': (39.22, 9.11),  'SS': (40.72, 8.55),  
            'NU': (40.32, 9.32),  'OR': (39.90, 8.58),  'SU': (40.72, 8.55)
        }
        
        lats, lons, risks = [], [], []
        
        for i, row in df.iterrows():
            addr = str(row['Address'])
            match = re.search(r'\(([A-Z]{2})\)', addr)
            prov = match.group(1) if match else None
            
            base_lat, base_lon = prov_dict.get(prov, (41.87, 12.56))
            
            # Leggera dispersione (jitter) per evitare sovrapposizioni assolute
            np.random.seed(hash(str(row['Installation ID'])) % (2**32))
            lats.append(base_lat + np.random.uniform(-0.15, 0.15))
            lons.append(base_lon + np.random.uniform(-0.15, 0.15))
            
            # Calcolo Risk Score simulato (Sud Italia / Coste = Più a rischio idrogeologico/termico)
            risk = int(np.clip(100 - (base_lat - 36) * 7 + np.random.randint(-10, 20), 10, 100))
            risks.append(risk)
            
        df['Lat'] = lats
        df['Lon'] = lons
        df['Risk_Score'] = risks
        return df
    except:
        return pd.DataFrame()


# --- SIDEBAR GLOBALE (ACQUISIZIONE DATI ORDINATA) ---
with st.sidebar:
    st.title("⚙️ Acquisizione Dati Base")
    
    # 1. YFINANCE
    st.header("1. Sincronizzazione API (YFinance)")
    ticker = st.text_input("Ticker Aziendale (es. ENEL.MI)")
    
    if st.button("Estrai Dati da Yahoo Finance"):
        with st.spinner("Scaricando dati dal mercato..."):
            if not ticker: 
                st.warning("⚠️ Inserisci un Ticker valido.")
            else:
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    fins = stock.financials
                    cf = stock.cash_flow
                    
                    new_rev, new_assets, new_emps = None, None, None
                    new_opex, new_capex = None, None
                    new_sec, new_ind, new_country = "", "", ""
                    
                    if info:
                        new_rev = info.get('totalRevenue')
                        new_assets = info.get('totalAssets')
                        new_emps = info.get('fullTimeEmployees')
                        new_sec = info.get('sector', '')
                        new_ind = info.get('industry', '')
                        new_country = info.get('country', '')

                    if not fins.empty:
                        if not new_rev:
                            rev_keys = [k for k in fins.index if 'revenue' in str(k).lower()]
                            if rev_keys: new_rev = fins.loc[rev_keys[0]].dropna().iloc[0]
                        
                        opex_keys = [k for k in fins.index if 'operating' in str(k).lower() and 'expense' in str(k).lower()]
                        if opex_keys:
                            new_opex = fins.loc[opex_keys[0]].dropna().iloc[0]
                        else:
                            op_inc_keys = [k for k in fins.index if 'operating income' in str(k).lower()]
                            if new_rev and op_inc_keys:
                                new_opex = new_rev - fins.loc[op_inc_keys[0]].dropna().iloc[0]

                    if not cf.empty:
                        capex_keys = [k for k in cf.index if 'capital' in str(k).lower() and 'expenditure' in str(k).lower()]
                        if not capex_keys: 
                            capex_keys = [k for k in cf.index if 'property' in str(k).lower() and 'plant' in str(k).lower()]
                        if capex_keys:
                            new_capex = abs(cf.loc[capex_keys[0]].dropna().iloc[0])
                    
                    if new_rev:
                        st.session_state.revenue = int(new_rev)
                        st.session_state.totale_attivo = int(new_assets) if new_assets else int(new_rev * 1.5)
                        st.session_state.dipendenti = int(new_emps) if new_emps else max(50, int(new_rev / 500000))
                        if new_opex and not pd.isna(new_opex): st.session_state.opex = int(new_opex)
                        if new_capex and not pd.isna(new_capex): st.session_state.capex_totale = int(new_capex)
                        st.session_state.quotata = True
                        
                        if new_sec:
                            if new_sec not in st.session_state.gics_sectors:
                                st.session_state.gics_sectors[new_sec] = []
                            if new_ind and new_ind not in st.session_state.gics_sectors[new_sec]:
                                st.session_state.gics_sectors[new_sec].append(new_ind)
                            st.session_state.sector = new_sec
                            st.session_state.industry = new_ind
                            
                        if new_country:
                            cmap = {'Italy': 'Italia', 'United States': 'Stati Uniti', 'China': 'Cina', 'Germany': 'Germania', 'India': 'India'}
                            if new_country in cmap:
                                st.session_state.selected_country = cmap[new_country]
                        
                        st.success(f"✅ Dati finanziari, settore e paese estratti per {ticker.upper()}!")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.warning("⚠️ Yahoo Finance non ha restituito dati utili.")
                except Exception as e:
                    st.error("❌ Connessione bloccata da Yahoo (Rate Limit).")

    st.divider()
    
    # 2. MANUALE
    st.header("2. Inserimento Manuale")
    st.selectbox("Paese Sede Legale", df_base['Paese'].unique(), key='selected_country') 
    
    curr_sec_idx = list(st.session_state.gics_sectors.keys()).index(st.session_state.sector) if st.session_state.sector in st.session_state.gics_sectors else 0
    sel_sec = st.selectbox("Settore GICS", list(st.session_state.gics_sectors.keys()), index=curr_sec_idx)
    st.session_state.sector = sel_sec
    
    inds = st.session_state.gics_sectors[st.session_state.sector]
    curr_ind_idx = inds.index(st.session_state.industry) if st.session_state.industry in inds else 0
    sel_ind = st.selectbox("Industria Specifica", inds, index=curr_ind_idx)
    st.session_state.industry = sel_ind
    
    st.session_state.totale_attivo = st.number_input("Attivo Patrimoniale (€)", value=st.session_state.totale_attivo, step=1000000)
    st.session_state.revenue = st.number_input("Ricavi Netti / Turnover (€)", value=st.session_state.revenue, step=1000000)
    st.session_state.dipendenti = st.number_input("Numero Dipendenti", value=st.session_state.dipendenti, step=10)
    st.session_state.quotata = st.checkbox("Quotata su mercato europeo?", value=st.session_state.quotata)
    st.session_state.capex_totale = st.number_input("CapEx Totale (€)", value=st.session_state.capex_totale, step=1000000)
    st.session_state.opex = st.number_input("OpEx Totale (€)", value=st.session_state.opex, step=1000000)
    
    st.divider()

    # 3. OPEN AI
    st.header("3. AI Data Extraction (PDF)")
    st.caption("👑 Riservato agli Utenti Premium (Costo API applicato)")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password")
    uploaded_pdf = st.file_uploader("Carica Bilancio CEE (PDF)", type="pdf")
    
    if uploaded_pdf and st.button("Analizza con AI"):
        with st.spinner("Elaborazione testo tramite AI in corso..."):
            if not api_key:
                time.sleep(2)
                st.session_state.totale_attivo = 32_000_000
                st.session_state.revenue = 65_000_000
                st.session_state.dipendenti = 310
                st.session_state.opex = 40_000_000
                st.session_state.capex_totale = 15_000_000
                st.session_state.quotata = False
                st.success("SIMULAZIONE AI COMPLETATA! Dati caricati.")
                time.sleep(1)
                st.rerun()
            else:
                try:
                    pdf_reader = PyPDF2.PdfReader(uploaded_pdf)
                    testo = "".join([page.extract_text() + "\n" for page in pdf_reader.pages[:15]])
                    client = OpenAI(api_key=api_key)
                    prompt = f"""Estrai come JSON: "attivo" (intero), "revenue" (intero), "dipendenti" (intero), "opex" (intero), "capex" (intero), "sector" (stringa in inglese es. Energy). Testo: {testo[:15000]}"""
                    res = client.chat.completions.create(model="gpt-3.5-turbo-0125", messages=[{"role": "user", "content": prompt}], response_format={ "type": "json_object" })
                    dati = json.loads(res.choices[0].message.content)
                    st.session_state.totale_attivo = dati.get("attivo", 0)
                    st.session_state.revenue = dati.get("revenue", 0)
                    st.session_state.dipendenti = dati.get("dipendenti", 0)
                    st.session_state.opex = dati.get("opex", 0)
                    st.session_state.capex_totale = dati.get("capex", 0)
                    
                    new_sec = dati.get("sector", "")
                    if new_sec:
                        if new_sec not in st.session_state.gics_sectors: st.session_state.gics_sectors[new_sec] = ["Generico"]
                        st.session_state.sector = new_sec
                        st.session_state.industry = st.session_state.gics_sectors[new_sec][0]
                        
                    st.success("Dati estratti dal PDF!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore AI: {e}")


# --- CORPO PRINCIPALE E TABS ---
st.title("🌍 CarbonRisk AI Enterprise")

t_triage, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🧭 Triage, Gap & Materialità", "📊 Analisi Rischi (IPCC & Mappa)", "🇪🇺 Tassonomia UE", "🌍 CBAM (Dogana)", "📥 Report & Export"
])

# =====================================================================
# TAB 0: TRIAGE NORMATIVO E GAP ANALYSIS
# =====================================================================
with t_triage:
    st.header("🧭 1. Test di Assoggettabilità")
    st.markdown("Il sistema valuta l'obbligo normativo basandosi sui dati inseriti nella Sidebar (Attivo, Ricavi, Dipendenti, Quotazione).")

    # ALGORITMO DI TRIAGE
    soglia_attivo = st.session_state.totale_attivo > 25000000
    soglia_ricavi = st.session_state.revenue > 50000000
    soglia_dip = st.session_state.dipendenti > 250
    score_grandi = sum([soglia_attivo, soglia_ricavi, soglia_dip])
    
    st.info(f"**Dati Attuali:** Attivo: {st.session_state.totale_attivo/1e6:.1f}M € | Ricavi: {st.session_state.revenue/1e6:.1f}M € | Dipendenti: {st.session_state.dipendenti} | Quotata: {'Sì' if st.session_state.quotata else 'No'} | Settore: {st.session_state.sector} - {st.session_state.industry} | Paese: {st.session_state.selected_country}")
    
    if score_grandi >= 2:
        status_normativo = "CSRD_GRANDE"
        st.error("### 🏢 ESITO: OBBLIGO CSRD (Grande Impresa)")
    elif st.session_state.quotata:
        status_normativo = "CSRD_PMI"
        st.warning("### 📈 ESITO: OBBLIGO CSRD (PMI Quotata)")
    else:
        status_normativo = "VSME"
        st.success("### 🌱 ESITO: PERCORSO VOLONTARIO (PMI - EFRAG VSME)")

    st.divider()
    
    # ---------------------------------------------------------
    # 2. GAP ANALYSIS E READINESS (SEPARATA PER VSME O CSRD)
    # ---------------------------------------------------------
    def render_gap_list(questions, pillar_code, tab_context, prefix="gap"):
        with tab_context:
            for i, q in enumerate(questions):
                val = st.selectbox(f"{i+1}. {q}", SCALE_OPTIONS, key=f"{prefix}_{pillar_code}_{i}")
                st.session_state.gap_answers[f"{prefix}_{pillar_code}_{i}"] = {"ans": val, "pillar": pillar_code}

    if status_normativo == "VSME":
        st.header("🔍 2. Readiness Data Availability (VSME)")
        st.markdown("Per le PMI, lo standard VSME non richiede la Doppia Materialità ma la rendicontazione di dati base in 3 moduli. Valuta la disponibilità del dato nella tua azienda.")
        
        modulo_scelto = st.radio("Quale Modulo VSME intendi rendicontare?", 
                                 ["Modulo Base (Solo indicatori KPI quantitativi)", 
                                  "Modulo Narrativo - PAT (Politiche, Azioni e Target)", 
                                  "Modulo Business Partner (Richiesto da Banche o Capofila)"], horizontal=True)
        
        vsme_qs_E = [
            "Consumi Energetici: Siete in grado di rendicontare il consumo totale di energia suddiviso per fonti (rinnovabili vs fossili)?",
            "Emissioni GHG: Avete calcolato le emissioni Scope 1 e Scope 2 (usando le bollette energetiche)?",
            "Rifiuti: Esiste un registro dei rifiuti che distingue tra pericolosi, non pericolosi e destinati al riciclo?"
        ]
        vsme_qs_S = [
            "Organico: Avete i dati pronti su numero di dipendenti per genere, tipo di contratto (determinato/indeterminato) e orario?",
            "Salute e Sicurezza: Monitorate il numero di infortuni sul lavoro e i giorni di assenza correlati?",
            "Formazione: Siete in grado di fornire il numero medio di ore di formazione annue per dipendente?"
        ]
        vsme_qs_G = [
            "Politiche: Esiste un documento scritto (anche semplice) su etica, corruzione o diritti umani?",
            "Responsabilità: È stato identificato un referente interno (anche il titolare) responsabile delle decisioni ESG?"
        ]
        
        c_v_E, c_v_S, c_v_G = st.tabs(["🌍 Ambiente (E)", "👥 Sociale (S)", "⚖️ Governance (G)"])
        render_gap_list(vsme_qs_E, "E", c_v_E, "vsme")
        render_gap_list(vsme_qs_S, "S", c_v_S, "vsme")
        render_gap_list(vsme_qs_G, "G", c_v_G, "vsme")
        
        if st.button("Calcola Readiness VSME", use_container_width=True):
            scores = []
            for k, data in st.session_state.gap_answers.items():
                if k.startswith("vsme"):
                    scores.append(SCALE_VALUES[data["ans"]])
            
            avg_score = sum(scores)/len(scores) if scores else 0
            
            st.subheader("📊 Data Availability Matrix (VSME)")
            c1, c2 = st.columns([1, 2])
            c1.metric("Punteggio Medio Qualità Dato", f"{avg_score:.1f} / 5.0")
            
            with c2:
                if avg_score < 2.0:
                    st.error("🔴 **Non pronti per il Modulo Base.** Il dato non esiste o non è tracciato.")
                    st.markdown("*Suggerimento:* Inizia a raccogliere le bollette energetiche e organizza i dati HR (dipendenti per genere/contratto).")
                elif avg_score < 4.0:
                    st.warning("🟡 **Pronti per il Modulo Base.** Il dato esiste ma potrebbe essere parziale.")
                    st.markdown("*Suggerimento:* Puoi pubblicare il tuo primo report volontario focalizzato sui KPI. Migliora la tracciabilità per passare al Modulo PAT.")
                else:
                    st.success("🟢 **Pronti per Modulo PAT o Business Partner.** Il dato è pronto, calcolato e documentato.")
                    st.markdown("*Suggerimento:* Ottimo posizionamento! Hai i requisiti per rispondere con successo ai questionari di sostenibilità delle Banche e della GDO.")
            
            st.info("💡 **Passaggio da VSME a CSRD:** Aumentando la maturità della raccolta dati (es. includendo lo Scope 3 e la Doppia Materialità), l'azienda potrà effettuare l'upgrade allo standard ESRS preparandosi alle normative future o richieste di Capogruppo strutturate.")

    else:
        # PERCORSO CSRD (GRANDI E PMI QUOTATE)
        st.header("🔍 2. Readiness & Gap Analysis (ESRS)")
        st.markdown("Valuta lo stato attuale dei processi aziendali. Seleziona il livello di maturità per ogni processo.")

        gap_qs_E = [
            "L'azienda ha definito un piano di transizione climatica allineato al target di 1.5°C?",
            "Il calcolo delle emissioni Scope 1 e 2 è completo e basato su dati primari?",
            "È stata effettuata una mappatura completa delle emissioni Scope 3 lungo la catena del valore?",
            "I rischi fisici e di transizione legati al clima sono integrati nel sistema di gestione rischi (ERM)?",
            "Esistono target ambientali misurabili, approvati dalla direzione e con scadenze definite?",
            "I processi aziendali integrano principi di economia circolare e gestione dei rifiuti?",
            "È stata eseguita una valutazione degli impatti sulla biodiversità e sugli ecosistemi nelle aree operative?",
            "Il monitoraggio del consumo idrico e degli scarichi è attivo e documentato?",
            "Il budget degli investimenti (CapEx) è stanziato per obiettivi di sostenibilità ambientale?",
            "Esistono controlli rigorosi per eliminare o ridurre l'emissione di sostanze inquinanti?"
        ]
        gap_qs_S = [
            "Esiste una procedura di 'due diligence' attiva per i diritti umani in tutta la catena di fornitura?",
            "L'azienda monitora e pubblica il divario retributivo di genere (pay gap) con piani di azione correttivi?",
            "Il sistema di gestione della salute e sicurezza copre tutti i lavoratori, inclusi i somministrati?",
            "Viene garantito un piano di formazione continua su competenze chiave per ogni dipendente?",
            "Esistono meccanismi formali di dialogo e consultazione con le rappresentanze dei lavoratori?",
            "Il rispetto del salario dignitoso (living wage) è verificato per tutti i dipendenti e fornitori critici?",
            "Sono attive politiche di inclusione che garantiscono pari opportunità per minoranze e categorie protette?",
            "L'azienda valuta regolarmente l'impatto sociale delle sue attività sulle comunità locali?",
            "Esistono protocolli per garantire la massima protezione dei dati e della privacy dei consumatori?",
            "Il sistema di welfare aziendale risponde ai bisogni reali di equilibrio vita-lavoro (work-life balance)?"
        ]
        gap_qs_G = [
            "Il Codice Etico e le politiche anti-corruzione sono stati comunicati e formati a tutti i livelli?",
            "Gli incentivi economici dei dirigenti sono legati al raggiungimento di obiettivi ESG specifici?",
            "Il canale di whistleblowing è esterno, anonimo e accessibile a tutti gli stakeholder?",
            "I criteri di sostenibilità sono vincolanti per la selezione e la qualifica dei fornitori?",
            "Esiste una politica trasparente riguardante le attività di lobbying e l'impegno politico?",
            "L'azienda pubblica la rendicontazione fiscale dettagliata per ogni paese in cui opera?",
            "I dati di sostenibilità sono sottoposti agli stessi controlli interni dei dati finanziari?",
            "Esiste una procedura strutturata per la gestione e comunicazione di incidenti o crisi reputazionali?",
            "La composizione del Consiglio di Amministrazione garantisce competenze ESG adeguate e diversità?",
            "La strategia di sostenibilità è approvata e revisionata annualmente dall'organo di governo?"
        ]

        c_g_E, c_g_S, c_g_G = st.tabs(["🌍 Ambiente (E)", "👥 Sociale (S)", "⚖️ Governance (G)"])
        render_gap_list(gap_qs_E, "E", c_g_E, "csrd")
        render_gap_list(gap_qs_S, "S", c_g_S, "csrd")
        render_gap_list(gap_qs_G, "G", c_g_G, "csrd")

        if st.button("Calcola Livello di Readiness ESRS", use_container_width=True):
            scores = {'E': 0, 'S': 0, 'G': 0}
            max_scores = {'E': 0, 'S': 0, 'G': 0}
            
            for q_id, data in st.session_state.gap_answers.items():
                if q_id.startswith("csrd"):
                    val_num = SCALE_VALUES[data["ans"]]
                    scores[data["pillar"]] += val_num
                    max_scores[data["pillar"]] += 5 
                
            tot_score = sum(scores.values())
            tot_max = sum(max_scores.values())
            readiness_pct = (tot_score / tot_max * 100) if tot_max > 0 else 0
            
            st.subheader("📊 Esito Audit Simulato")
            col_res1, col_res2 = st.columns([1, 2])
            with col_res1:
                st.metric("Readiness Globale", f"{readiness_pct:.1f}%")
                if readiness_pct < 40: st.error("🔴 **Laggard (Alto Rischio).** Gravi lacune normative.")
                elif readiness_pct < 75: st.warning("🟡 **In Transizione (Rischio Moderato).** Necessario formalizzare i processi.")
                else: st.success("🟢 **Leader (Pronto per Audit).** Alta conformità ai requisiti EFRAG.")
                    
                st.markdown("#### Completamento per Pilastro")
                for p, name in [('E', 'Ambiente'), ('S', 'Sociale'), ('G', 'Governance')]:
                    p_pct = (scores[p] / max_scores[p] * 100) if max_scores[p] > 0 else 0
                    st.progress(p_pct/100, text=f"{name}: {p_pct:.0f}%")
            with col_res2:
                df_radar = pd.DataFrame(dict(
                    r=[(scores['E']/max_scores['E'])*100 if max_scores['E']>0 else 0, (scores['S']/max_scores['S'])*100 if max_scores['S']>0 else 0, (scores['G']/max_scores['G'])*100 if max_scores['G']>0 else 0],
                    theta=['Ambiente (E)', 'Sociale (S)', 'Governance (G)']
                ))
                fig_radar = px.line_polar(df_radar, r='r', theta='theta', line_close=True, range_r=[0,100], title="Profilo di Maturità ESG")
                fig_radar.update_traces(fill='toself', line_color='#00B050' if readiness_pct > 50 else '#EF553B')
                st.plotly_chart(fig_radar, use_container_width=True)

        st.divider()
        st.header("🎯 3. Analisi di Doppia Materialità (DMA)")
        st.markdown("L'azienda deve valutare ogni tema ESRS. Il sistema calcola le coordinate per la Matrice facendo la media delle risposte alle domande specifiche (Asse X = Finanziario, Asse Y = Impatto).")

        dma_questions_dict = {
            "E": {
                "E1 - Cambiamento Climatico": [
                    ("L'azienda ha analizzato come l'aumento delle temperature o eventi meteo estremi possano danneggiare i propri asset fisici?", "F"),
                    ("È stato valutato l'impatto finanziario derivante dall'introduzione di tasse sulle emissioni o regolamentazioni green più stringenti?", "F"),
                    ("Esiste una valutazione dell'impatto prodotto dalle attività aziendali sulle emissioni globali di gas serra (GHG)?", "I")
                ],
                "E2 - Inquinamento": [
                    ("Sono stati identificati gli impatti (effettivi o potenziali) del rilascio di sostanze inquinanti in aria, acqua e suolo?", "I"),
                    ("L'azienda ha valutato la propria dipendenza da sostanze chimiche pericolose soggette a restrizioni normative?", "F"),
                    ("È stata analizzata la rilevanza dell'inquinamento acustico o luminoso prodotto dai siti produttivi sulle aree circostanti?", "I")
                ],
                "E3 - Risorse Idriche e Marine": [
                    ("È stata mappata la presenza di siti produttivi in aree ad alto stress idrico per valutarne la vulnerabilità operativa?", "F"),
                    ("L'azienda ha analizzato come i propri scarichi idrici influenzino la qualità delle falde acquifere o dei corpi idrici locali?", "I"),
                    ("È stato valutato l'impatto o la dipendenza aziendale dalle risorse marine (es. materie prime oceaniche)?", "I")
                ],
                "E4 - Biodiversità ed Ecosistemi": [
                    ("L'azienda ha valutato se le proprie attività avvengono in prossimità di aree protette o ad alta biodiversità?", "I"),
                    ("È stato analizzato il rischio di contribuire alla deforestazione tramite la propria supply chain?", "I"),
                    ("Esiste una valutazione della dipendenza dell'azienda dai 'servizi ecosistemici' (es. impollinazione)?", "F")
                ],
                "E5 - Economia Circolare": [
                    ("L'azienda ha analizzato i rischi legati alla scarsità di materie prime vergini necessarie per la produzione?", "F"),
                    ("È stato valutato l'impatto ambientale derivante dalla gestione dei rifiuti prodotti?", "I"),
                    ("È stata analizzata la capacità dei prodotti aziendali di essere riutilizzati, riparati o riciclati a fine vita?", "I")
                ]
            },
            "S": {
                "S1 - Forza Lavoro Propria": [
                    ("È stato analizzato l'impatto delle politiche aziendali sulla salute, sicurezza e benessere dei dipendenti diretti?", "I"),
                    ("L'azienda ha valutato il rischio di discriminazione nei processi di selezione e promozione?", "I"),
                    ("Esiste una valutazione sulla congruità dei salari rispetto al costo della vita (living wage)?", "I")
                ],
                "S2 - Lavoratori Catena Valore": [
                    ("L'azienda ha mappato il rischio di lavoro forzato o minorile presso i propri fornitori?", "I"),
                    ("È stata analizzata la dipendenza da fornitori in paesi con scarse tutele dei diritti umani?", "F"),
                    ("Esistono canali di segnalazione (whistleblowing) accessibili anche ai lavoratori esterni?", "I")
                ],
                "S3 - Comunità Interessate": [
                    ("È stato valutato l'impatto (rumore, traffico, inquinamento) dei siti aziendali sulle popolazioni locali?", "I"),
                    ("L'azienda ha analizzato come le proprie attività influenzano i diritti delle popolazioni indigene?", "I"),
                    ("Esiste un processo per gestire le lamentele provenienti dalle comunità dove l'azienda opera?", "I")
                ],
                "S4 - Consumatori ed Utenti": [
                    ("È stato valutato il rischio di impatti negativi sulla salute o sicurezza derivanti dall'uso dei prodotti?", "I"),
                    ("L'azienda ha analizzato i rischi legati alla privacy e alla protezione dei dati dei clienti?", "F"),
                    ("Viene monitorato l'impatto socio-economico del marketing sui consumatori vulnerabili?", "I")
                ]
            },
            "G": {
                "G1 - Condotta negli Affari": [
                    ("È stata effettuata un'analisi dei rischi di corruzione (attiva e passiva) nelle geografie in cui l'azienda opera?", "F"),
                    ("L'azienda ha valutato la trasparenza e l'etica dei propri processi di lobbying?", "I"),
                    ("È stato analizzato il livello di protezione garantito ai whistleblower all'interno dell'organizzazione?", "I")
                ]
            }
        }

        t_dma_e, t_dma_s, t_dma_g, t_dma_all = st.tabs(["🌍 Ambiente (E)", "👥 Sociale (S)", "⚖️ Governance (G)", "📈 Matrice Finale (DMA)"])
        
        calculated_dma_scores = {}

        def render_dma_questions(pillar_dict, pillar_code, tab_context):
            with tab_context:
                for topic, questions in pillar_dict.items():
                    with st.expander(f"Valuta Tema: {topic}"):
                        topic_imp_scores = []
                        topic_fin_scores = []
                        
                        for idx, (q_text, q_type) in enumerate(questions):
                            st.markdown(f"**[{'Impatto' if q_type == 'I' else 'Finanziario'}]** {q_text}")
                            ans = st.selectbox(
                                "Maturità Analisi:", 
                                SCALE_OPTIONS, 
                                key=f"dma_{pillar_code}_{topic}_{idx}", 
                                label_visibility="collapsed"
                            )
                            val_num = SCALE_VALUES[ans]
                            
                            if q_type == 'I': topic_imp_scores.append(val_num)
                            else: topic_fin_scores.append(val_num)
                        
                        avg_imp = sum(topic_imp_scores)/len(topic_imp_scores) if topic_imp_scores else (sum(topic_fin_scores)/len(topic_fin_scores) if topic_fin_scores else 0)
                        avg_fin = sum(topic_fin_scores)/len(topic_fin_scores) if topic_fin_scores else avg_imp
                        
                        calculated_dma_scores[topic] = {"pilastro": pillar_code, "impatto": avg_imp, "finanza": avg_fin}
                        st.info(f"**Score Calcolato (0-5):** Impatto: {avg_imp:.1f} | Finanziario: {avg_fin:.1f}")

        render_dma_questions(dma_questions_dict["E"], "E", t_dma_e)
        render_dma_questions(dma_questions_dict["S"], "S", t_dma_s)
        render_dma_questions(dma_questions_dict["G"], "G", t_dma_g)

        with t_dma_all:
            st.subheader("Matrice di Doppia Materialità")
            
            dma_data = []
            for topic, scores in calculated_dma_scores.items():
                is_material = scores["impatto"] >= 2.5 or scores["finanza"] >= 2.5
                dma_data.append({
                    "Tema": topic, "Pilastro": scores["pilastro"],
                    "Impatto": scores["impatto"], "Finanza": scores["finanza"],
                    "Status": "Materiale" if is_material else "Non Materiale",
                    "Dim": 20 if is_material else 10
                })
                
            if dma_data:
                df_dma = pd.DataFrame(dma_data)
                fig_dma = px.scatter(
                    df_dma, x="Finanza", y="Impatto", color="Pilastro",
                    color_discrete_map={'E': '#00B050', 'S': '#00B0F0', 'G': '#0070C0'},
                    size="Dim", hover_name="Tema", text="Tema",
                    range_x=[-0.5, 5.5], range_y=[-0.5, 5.5], title="Distribuzione Temi ESRS"
                )
                
                fig_dma.add_hline(y=2.45, line_dash="dash", line_color="red", annotation_text="Soglia Impatto")
                fig_dma.add_vline(x=2.45, line_dash="dash", line_color="red", annotation_text="Soglia Finanza")
                fig_dma.update_traces(textposition='top center', textfont_size=10)
                fig_dma.update_layout(height=600, xaxis_title="Materialità Finanziaria (Outside-In)", yaxis_title="Materialità d'Impatto (Inside-Out)")
                
                fig_dma.add_shape(type="rect", x0=2.45, y0=-0.5, x1=5.5, y1=5.5, fillcolor="rgba(255,0,0,0.05)", line_width=0, layer="below")
                fig_dma.add_shape(type="rect", x0=-0.5, y0=2.45, x1=5.5, y1=5.5, fillcolor="rgba(255,0,0,0.05)", line_width=0, layer="below")
                
                st.plotly_chart(fig_dma, use_container_width=True)
                
                temi_mat = df_dma[df_dma["Status"] == "Materiale"]["Tema"].tolist()
                if temi_mat:
                    st.success(f"📌 **Temi Obbligatori da Rendicontare ({len(temi_mat)}/10):** " + ", ".join(temi_mat))
            else:
                st.info("Compila i questionari nei tab (E, S, G) per generare la matrice.")

# =====================================================================
# TAB 2: ANALISI RISCHI E MAPPATURA ASSET
# =====================================================================
with t_rischi:
    rt_mappa, rt_fisico, rt_transizione, rt_credito = st.tabs([
        "🏭 Mappatura Asset", "🛰️ Simulazione Geospaziale", "🔄 GHG & Consumi", "💰 Stress Test (NGFS)"
    ])
    
    with rt_mappa:
        st.subheader("Mappatura Rischio Impianti Energetici")
        st.markdown("Visualizzazione centrali dal database. Il colore rappresenta la stima di rischio, la dimensione l'allocazione.")
        
        df_plants = load_plants_csv()
        if not df_plants.empty:
            operatori = ["Tutti"] + sorted(df_plants['Operator'].unique().tolist())
            selezionato = st.selectbox("Filtra mappa per Operatore:", operatori)
            
            df_mappa = df_plants if selezionato == "Tutti" else df_plants[df_plants['Operator'] == selezionato]
            
            fig_map = px.scatter_mapbox(
                df_mappa, lat="Lat", lon="Lon", hover_name="Installation name",
                hover_data={"Lat": False, "Lon": False, "Installation ID": True, "Address": True, "Risk_Score": True, "Allocation": True},
                color="Risk_Score", size="Allocation", color_continuous_scale=px.colors.diverging.RdYlGn_r,
                size_max=15, zoom=4.5, mapbox_style="carto-positron"
            )
            fig_map.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
            st.plotly_chart(fig_map, use_container_width=True)
            st.dataframe(df_mappa[['Installation ID', 'Installation name', 'Operator', 'Address', 'Risk_Score']], use_container_width=True)
        else:
            st.warning("⚠️ Carica il file CSV degli impianti nel sistema per visualizzare la mappa.")

    with rt_fisico:
        st.subheader("Modellazione Climatica ERA5 (10km) & Scenari IPCC 2050")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            indirizzo = st.text_input("Inserisci Indirizzo o Asset", "Via del Corso, Roma")
        with col_f2:
            ipcc_scenario = st.selectbox("Scenario IPCC (Orizzonte 2050)", ["SSP1-2.6 (Sostenibilità)", "SSP2-4.5 (Intermedio)", "SSP5-8.5 (Fossile)"], index=1)
            
        if st.button("📡 Esegui Simulazione"):
            with st.spinner("Interrogazione satellite Copernicus..."):
                geolocator = Nominatim(user_agent="CarbonApp")
                try:
                    loc = geolocator.geocode(indirizzo)
                    lat, lon = (loc.latitude, loc.longitude) if loc else (41.90, 12.49)
                    
                    fig_map_singolo = px.scatter_mapbox(pd.DataFrame({"Lat":[lat],"Lon":[lon],"L":["Asset"]}), lat="Lat", lon="Lon", zoom=12, height=300)
                    fig_map_singolo.update_layout(mapbox_style="carto-positron", margin={"r":0,"t":0,"l":0,"b":0})
                    st.plotly_chart(fig_map_singolo, use_container_width=True)
                    
                    url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2023-01-01&end_date=2023-12-31&daily=temperature_2m_max,precipitation_sum&timezone=auto"
                    data = requests.get(url).json()
                    
                    if "daily" in data:
                        temp_max_daily = np.array(data["daily"]["temperature_2m_max"])
                        precip_daily = np.array(data["daily"]["precipitation_sum"])
                        
                        baseline_days = np.sum(temp_max_daily >= 35.0)
                        baseline_precip = np.nansum(precip_daily)
                        
                        if "SSP1" in ipcc_scenario: delta_t, delta_p, risk_mult = 1.2, 1.05, 1.2
                        elif "SSP2" in ipcc_scenario: delta_t, delta_p, risk_mult = 2.4, 1.15, 1.8
                        else: delta_t, delta_p, risk_mult = 4.2, 1.30, 3.5
                            
                        future_temp = temp_max_daily + delta_t
                        future_days = np.sum(future_temp >= 35.0)
                        base_flood = 5.0 if baseline_precip < 800 else (15.0 if baseline_precip < 1200 else 30.0)
                        future_flood = base_flood * delta_p * risk_mult
                        danno_atteso = (future_flood / 100) * (st.session_state.revenue * 0.1) * 0.05
                        
                        c1, c2, c3 = st.columns(3)
                        c1.metric("🌊 Rischio Allagamento Annuo", f"{min(future_flood, 99.9):.1f}%", delta=f"+{future_flood - base_flood:.1f}%", delta_color="inverse")
                        c2.metric("🌡️ Stress Termico (> 35°C)", f"{future_days} gg/anno", delta=f"+{future_days - baseline_days} gg", delta_color="inverse")
                        c3.metric("📉 Danno Economico Atteso", f"€ {danno_atteso:,.0f}")
                except: st.error("Errore di geolocalizzazione.")

    with rt_transizione:
        st.subheader("Calcolatore GHG da Consumi Reali (ISPRA/DEFRA)")
        
        EMISSION_FACTORS = {
            "Scope 1 - Gas Naturale (Riscaldamento)": {"scope": "scope1", "unita": {"Metri Cubi (Sm3)": 1.98, "GigaJoule (GJ)": 56.1}},
            "Scope 1 - Gasolio (Riscaldamento/Motori)": {"scope": "scope1", "unita": {"Litri (L)": 2.68, "Tonnellate (t)": 3150.0}},
            "Scope 1 - Carbone (Produzione energia)": {"scope": "scope1", "unita": {"Tonnellate (t)": 2335.0, "Chilogrammi (kg)": 2.335}},
            "Scope 1 - Benzina (Flotta)": {"scope": "scope1", "unita": {"Litri (L)": 2.31}},
            "Scope 1 - Gas Refrigeranti (Fughe R410a)": {"scope": "scope1", "unita": {"Chilogrammi (kg)": 2088.0}},
            "Scope 2 - Elettricità (Mix Italia)": {"scope": "scope2", "unita": {"kWh": 0.259, "MWh": 259.0}},
            "Scope 2 - Elettricità (100% Rinnovabile GO)": {"scope": "scope2", "unita": {"kWh": 0.0, "MWh": 0.0}},
            "Scope 3 - Trasporto Merci (Camion)": {"scope": "scope3", "unita": {"Tonnellate-km (tkm)": 0.11}},
            "Scope 3 - Voli Aerei (Passeggeri)": {"scope": "scope3", "unita": {"Passeggeri-km (pkm)": 0.15}},
            "Scope 3 - Rifiuti Indifferenziati": {"scope": "scope3", "unita": {"Tonnellate (t)": 450.0}}
        }
        
        c_calc1, c_calc2, c_calc3 = st.columns([2, 1, 1])
        fonte_sel = c_calc1.selectbox("Categoria Consumo", list(EMISSION_FACTORS.keys()))
        unita_disp = list(EMISSION_FACTORS[fonte_sel]["unita"].keys())
        unita_sel = c_calc2.selectbox("Unità di Misura", unita_disp)
        fattore = EMISSION_FACTORS[fonte_sel]["unita"][unita_sel]
        scope_target = EMISSION_FACTORS[fonte_sel]["scope"]
        consumo = c_calc1.number_input(f"Volume Annuo ({unita_sel})", min_value=0.0, step=100.0)
        co2_calc = (consumo * fattore) / 1000 
        
        c_calc3.metric("Emissioni Generate", f"{co2_calc:,.2f} tCO2", help=f"Fattore: {fattore} kgCO2/{unita_sel}")
        
        if st.button(f"➕ Somma allo {scope_target.capitalize()}"):
            if co2_calc > 0:
                st.session_state[scope_target] += int(co2_calc)
                sync_from_scopes()
                st.success(f"Aggiunte {int(co2_calc)} tCO2!")
                time.sleep(1)
                st.rerun()

        st.divider()
        c_ghg1, c_ghg2 = st.columns(2)
        with c_ghg1:
            st.number_input("Scope 1 (tCO2)", value=st.session_state.scope1, step=500, key='scope1', on_change=sync_from_scopes)
            st.number_input("Scope 2 (tCO2)", value=st.session_state.scope2, step=500, key='scope2', on_change=sync_from_scopes)
            st.number_input("Scope 3 (tCO2)", value=st.session_state.scope3, step=500, key='scope3', on_change=sync_from_scopes)
        with c_ghg2:
            st.info(f"### Impronta Lorda\n# {get_tot_emissions():,} tCO2")
            st.slider("Efficacia Decarbonizzazione (%)", 0, 100, key='perc_red', on_change=sync_from_perc)
            st.success(f"**Emissioni Nette:** {st.session_state.em_final:,} tCO2")

    with rt_credito:
        st.subheader("Stress Test Finanziario (Scenari NGFS)")
        c_cred1, c_cred2 = st.columns(2)
        with c_cred1:
            st.number_input("Rata Prestito Transizione (€)", value=st.session_state.rata_prestito, step=100000, key='rata_prestito')
        with c_cred2:
            st.slider("Severità Policy Locali", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier')

        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            profit = st.session_state.revenue - st.session_state.opex - (eff_price * st.session_state.em_final) - st.session_state.rata_prestito
            plot_data.append({"Anno": row['Anno'], "Utile Netto (€)": profit, "Scenario": row['Scenario'], "Price": eff_price})
        
        df_plot = pd.DataFrame(plot_data)
        st.plotly_chart(px.line(df_plot, x="Anno", y="Utile Netto (€)", color="Scenario", title="EBITDA Netto post-Carbon Tax"), use_container_width=True)

# =====================================================================
# TAB 3: TASSONOMIA UE
# =====================================================================
with t_tax:
    st.header("🇪🇺 Reporting Tassonomia UE")
    nace_db = load_nace_hierarchy("NACE_Rev.2.1.rdf")
    tax_pref = load_taxonomy_json("taxonomy.json")

    with st.expander("➕ Aggiungi Commessa / Attività", expanded=True):
        erp_id = st.text_input("🏢 ID Commessa ERP")
        col_tax1, col_tax2 = st.columns(2)
        with col_tax1:
            sez = st.selectbox("Sezione NACE", list(nace_db.keys()) if nace_db else [])
            div = st.selectbox("Divisione NACE", list(nace_db.get(sez, {}).keys()) if sez else [])
            grp = st.selectbox("Gruppo NACE", list(nace_db.get(sez, {}).get(div, {}).keys()) if div else [])
            cls = st.selectbox("Classe NACE", list(nace_db.get(sez, {}).get(div, {}).get(grp, {}).keys()) if grp else [])
            
            nace_code = nace_db.get(sez, {}).get(div, {}).get(grp, {}).get(cls, "")
            is_eligible = False
            if nace_code and tax_pref:
                is_eligible = any(nace_code.replace('.','').startswith(p) for p in tax_pref)
            
            st.markdown(f"**Status:** {'✅ Ammissibile' if is_eligible else 'ℹ️ Non Ammissibile'}")

        with col_tax2:
            obj_sc = st.selectbox("Obiettivo", ["CCM", "CCA", "WTR", "CE", "PPC", "BIO"])
            val_t = st.number_input("Turnover (€)", step=10000)
            val_c = st.number_input("CapEx (€)", step=10000)
            val_o = st.number_input("OpEx (€)", step=10000)

        if st.button("Inserisci in Registro"):
            st.session_state.tax_portfolio.append({
                "ERP": erp_id, "Attività": cls.split(" - ")[-1] if cls else "", "NACE": nace_code,
                "Obiettivo": obj_sc, "Turnover (€)": val_t, "CapEx (€)": val_c, "OpEx (€)": val_o,
                "Eligible (Y/N)": "Y" if is_eligible else "N", "Aligned": False 
            })
            st.rerun()

    if st.session_state.tax_portfolio:
        df_tax = pd.DataFrame(st.session_state.tax_portfolio)
        edited_df = st.data_editor(df_tax, num_rows="dynamic", key="tax_editor")
        st.session_state.tax_portfolio = edited_df.to_dict('records')
        
        if st.button("Svuota Registro Tassonomia"): st.session_state.tax_portfolio = []; st.rerun()

        st.subheader("Dashboard")
        den_turnover = max(st.session_state.revenue, edited_df["Turnover (€)"].sum())
        val_aligned = edited_df[edited_df["Aligned"] == True]["Turnover (€)"].sum()
        
        c1, c2 = st.columns(2)
        c1.metric("Fatturato Allineato (%)", f"{(val_aligned/den_turnover*100) if den_turnover>0 else 0:.2f}%")
        c2.plotly_chart(go.Figure(data=[go.Pie(labels=["Aligned", "Not Aligned"], values=[val_aligned, den_turnover-val_aligned], hole=.4)]), use_container_width=True)

# =====================================================================
# TAB 4: CBAM DOGANA
# =====================================================================
with t_cbam:
    st.header("🌍 CBAM Self-Assessment Tool")
    cbam_tree = load_cbam_hierarchy()
    paesi = {"Cina": 10.0, "India": 0.0, "UK": 45.0, "USA": 0.0, "UE": 0.0}

    with st.expander("➕ Compila Spedizione Doganale", expanded=True):
        col_cb1, col_cb2 = st.columns(2)
        with col_cb1:
            sez_cb = st.selectbox("Sezione", list(cbam_tree.keys()))
            cap_cb = st.selectbox("Capitolo", list(cbam_tree.get(sez_cb, {}).keys()) if sez_cb else [])
            voc_cb = st.selectbox("Voce", list(cbam_tree.get(sez_cb, {}).get(cap_cb, {}).keys()) if cap_cb else [])
            mer_cb = st.selectbox("Prodotto", list(cbam_tree.get(sez_cb, {}).get(cap_cb, {}).get(voc_cb, {}).keys()) if voc_cb else [])
            cod_cn = cbam_tree.get(sez_cb, {}).get(cap_cb, {}).get(voc_cb, {}).get(mer_cb, "")
            
        with col_cb2:
            orig = st.selectbox("Origine", list(paesi.keys()))
            em_cb = st.number_input("Emissioni (tCO2)", min_value=0.00, step=10.0)
            val_cb = st.number_input("Valore (€)", min_value=0.00, step=100.0)

        if st.button("Valuta e Registra"):
            cat = check_cbam_category(cod_cn)
            applies = "SÌ" if (cat != "Non Soggetto" and val_cb > 150 and orig != "UE") else "NO"
            st.session_state.cbam_portfolio.append({
                "Codice": cod_cn, "Merce": mer_cb[:40], "Origine": orig,
                "Valore (€)": round(val_cb, 2), "Emissioni (tCO2)": round(em_cb, 2),
                "CBAM APPLICABILE": applies, "Tax Estera": paesi[orig]
            })
            st.rerun()

    if st.session_state.cbam_portfolio:
        df_cbam = pd.DataFrame(st.session_state.cbam_portfolio)
        st.dataframe(df_cbam, use_container_width=True, column_config={
            "Emissioni (tCO2)": st.column_config.NumberColumn(format="%.2f"),
            "Valore (€)": st.column_config.NumberColumn(format="%.2f")
        })

        if st.button("Svuota CBAM"): st.session_state.cbam_portfolio = []; st.rerun()

        df_app = df_cbam[df_cbam["CBAM APPLICABILE"] == "SÌ"]
        tot_em = df_app["Emissioni (tCO2)"].sum()
        if tot_em > 0:
            st.divider()
            live_price = get_live_eu_ets_price()
            ets = st.number_input("Prezzo EU ETS (€/tCO2)", value=float(live_price))
            
            sconto = sum(row["Emissioni (tCO2)"] * row["Tax Estera"] for _, row in df_app.iterrows())
            costo = max(0, (tot_em * ets) - sconto)
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Emissioni", f"{tot_em:.2f} tCO2")
            c2.metric("Sconto Estero", f"€ {sconto:.2f}")
            c3.metric("Costo CBAM", f"€ {costo:.2f}", delta="Impatto OpEx", delta_color="inverse")

# =====================================================================
# TAB 5: DOWNLOAD
# =====================================================================
with t_down:
    st.header("📥 Esportazione Dati")
    if st.button("🪄 Genera PDF"):
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 18); pdf.cell(200, 15, txt="ESG Report", ln=True, align='C')
        st.download_button("Scarica PDF", pdf.output(dest='S').encode('latin-1'), "ESG_Report.pdf")
