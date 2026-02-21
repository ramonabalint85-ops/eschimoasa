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

# --- SINCRONIZZAZIONE (Session State) ---
st.session_state.setdefault('revenue', 0)
st.session_state.setdefault('opex', 0)
st.session_state.setdefault('totale_attivo', 0)
st.session_state.setdefault('dipendenti', 0)
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
st.session_state.setdefault('portfolio_df', pd.DataFrame())

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

# --- FUNZIONI DI ELABORAZIONE MAPPA E DATI (PULIZIA NLP + JITTERING) ---
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
        # JITTERING: Dispersione spaziale per evitare sovrapposizioni esatte
        np.random.seed(42)
        df['Lat'] = df['Lat'].astype(float) + np.random.uniform(-0.02, 0.02, size=len(df))
        df['Lon'] = df['Lon'].astype(float) + np.random.uniform(-0.02, 0.02, size=len(df))
    else:
        st.error("Il file deve contenere colonne 'Lat' e 'Lon'.")
        return pd.DataFrame()

    if 'Name' not in df.columns: df['Name'] = "Impianto " + df.index.astype(str)
    if 'ID' not in df.columns: df['ID'] = df.index.astype(str)
    if 'Address' not in df.columns: df['Address'] = "Indirizzo non disponibile"
    
    # NLP CLEANING: Normalizzazione Operatori (maiuscolo, rimuove punti/virgole)
    if 'Operator' not in df.columns: 
        df['Operator'] = "Operatore Non Specificato"
    else:
        df['Operator'] = df['Operator'].astype(str).str.upper()
        df['Operator'] = df['Operator'].str.replace(r'[^\w\s]', '', regex=True)
        df['Operator'] = df['Operator'].str.replace(r'\s+', ' ', regex=True).str.strip()

    alloc_col = next((c for c in df.columns if 'alloc' in c.lower() or 'capacit' in c.lower()), None)
    if alloc_col:
        df['Size'] = pd.to_numeric(df[alloc_col], errors='coerce').fillna(5000)
    else:
        df['Size'] = 5000
    
    max_size = df['Size'].max()
    if max_size > 0:
        df['Display_Size'] = (df['Size'] / max_size) * 30 + 5
    else:
        df['Display_Size'] = 10
    
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

# --- SIDEBAR GLOBALE ---
with st.sidebar:
    st.title("⚙️ Acquisizione Dati Base")
    
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
                        if opex_keys: new_opex = fins.loc[opex_keys[0]].dropna().iloc[0]
                        else:
                            op_inc_keys = [k for k in fins.index if 'operating income' in str(k).lower()]
                            if new_rev and op_inc_keys: new_opex = new_rev - fins.loc[op_inc_keys[0]].dropna().iloc[0]

                    if not cf.empty:
                        capex_keys = [k for k in cf.index if 'capital' in str(k).lower() and 'expenditure' in str(k).lower()]
                        if not capex_keys: capex_keys = [k for k in cf.index if 'property' in str(k).lower() and 'plant' in str(k).lower()]
                        if capex_keys: new_capex = abs(cf.loc[capex_keys[0]].dropna().iloc[0])
                    
                    if new_rev:
                        st.session_state.revenue = int(new_rev)
                        st.session_state.totale_attivo = int(new_assets) if new_assets else int(new_rev * 1.5)
                        st.session_state.dipendenti = int(new_emps) if new_emps else max(50, int(new_rev / 500000))
                        if new_opex and not pd.isna(new_opex): st.session_state.opex = int(new_opex)
                        if new_capex and not pd.isna(new_capex): st.session_state.capex_totale = int(new_capex)
                        st.session_state.quotata = True
                        
                        if new_sec:
                            if new_sec not in st.session_state.gics_sectors: st.session_state.gics_sectors[new_sec] = []
                            if new_ind and new_ind not in st.session_state.gics_sectors[new_sec]: st.session_state.gics_sectors[new_sec].append(new_ind)
                            st.session_state.sector = new_sec; st.session_state.industry = new_ind
                            
                        if new_country:
                            cmap = {'Italy': 'Italia', 'United States': 'Stati Uniti', 'China': 'Cina', 'Germany': 'Germania', 'India': 'India'}
                            if new_country in cmap: st.session_state.selected_country = cmap[new_country]
                        
                        st.success(f"✅ Dati estratti per {ticker.upper()}!")
                        time.sleep(1.5)
                        st.rerun()
                    else: st.warning("⚠️ Yahoo Finance non ha restituito dati utili.")
                except Exception as e: st.error("❌ Connessione bloccata da Yahoo (Rate Limit).")

    st.divider()
    
    st.header("2. Inserimento Manuale")
    st.selectbox("Paese Sede Legale", df_base['Paese'].unique(), index=list(df_base['Paese'].unique()).index(st.session_state.selected_country) if st.session_state.selected_country in df_base['Paese'].unique() else 3, key='selected_country') 
    
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

    st.header("3. AI Data Extraction (PDF)")
    st.caption("👑 Riservato agli Utenti Premium (Costo API)")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password")
    uploaded_pdf = st.file_uploader("Carica Bilancio CEE", type="pdf")
    if uploaded_pdf and st.button("Analizza con AI"):
        st.success("SIMULAZIONE AI COMPLETATA!")
        time.sleep(1)

# --- CORPO PRINCIPALE E TABS ---
st.title("🌍 CarbonRisk AI Enterprise")

t_triage, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🧭 Triage, Gap & Materialità", "📊 Analisi Rischi & Mappe", "🇪🇺 Tassonomia UE", "🌍 CBAM (Dogana)", "📥 Report & Export"
])

# =====================================================================
# TAB 0: TRIAGE NORMATIVO E GAP ANALYSIS
# =====================================================================
with t_triage:
    st.header("🧭 1. Test di Assoggettabilità")
    
    soglia_attivo = st.session_state.totale_attivo > 25000000
    soglia_ricavi = st.session_state.revenue > 50000000
    soglia_dip = st.session_state.dipendenti > 250
    score_grandi = sum([soglia_attivo, soglia_ricavi, soglia_dip])
    
    st.info(f"**Dati Attuali:** Attivo: {st.session_state.totale_attivo/1e6:.1f}M € | Ricavi: {st.session_state.revenue/1e6:.1f}M € | Dipendenti: {st.session_state.dipendenti} | Quotata: {'Sì' if st.session_state.quotata else 'No'} | Settore: {st.session_state.sector} - {st.session_state.industry}")
    
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
    
    def render_gap_list(questions, pillar_code, tab_context, prefix="gap"):
        with tab_context:
            for i, q in enumerate(questions):
                val = st.selectbox(f"{i+1}. {q}", SCALE_OPTIONS, key=f"{prefix}_{pillar_code}_{i}")
                st.session_state.gap_answers[f"{prefix}_{pillar_code}_{i}"] = {"ans": val, "pillar": pillar_code}

    if status_normativo == "VSME":
        st.header("🔍 2. Readiness Data Availability (VSME)")
        st.markdown("Per le PMI, lo standard VSME non richiede la Doppia Materialità. Valuta la disponibilità dei tuoi dati primari.")
        
        st.radio("Livello di Ambizione VSME:", ["Modulo Base", "Modulo Narrativo (PAT)", "Modulo Business Partner"], horizontal=True)
        
        vsme_qs_E = ["Consumi Energetici suddivisi (rinnovabili vs fossili)?", "Emissioni GHG Scope 1 e Scope 2 misurate?", "Registro dei rifiuti aggiornato?"]
        vsme_qs_S = ["Dati organico per genere, contratto e orario?", "Monitoraggio infortuni sul lavoro?", "Ore di formazione medie annue calcolate?"]
        vsme_qs_G = ["Policy scritta su etica e diritti umani?", "Referente interno per la sostenibilità?"]
        
        c_v_E, c_v_S, c_v_G = st.tabs(["🌍 Ambiente (E)", "👥 Sociale (S)", "⚖️ Governance (G)"])
        render_gap_list(vsme_qs_E, "E", c_v_E, "vsme")
        render_gap_list(vsme_qs_S, "S", c_v_S, "vsme")
        render_gap_list(vsme_qs_G, "G", c_v_G, "vsme")
        
        if st.button("Calcola Readiness VSME", use_container_width=True):
            scores = [SCALE_VALUES[data["ans"]] for k, data in st.session_state.gap_answers.items() if k.startswith("vsme")]
            avg_score = sum(scores)/len(scores) if scores else 0
            
            c1, c2 = st.columns([1, 2])
            c1.metric("Punteggio Qualità Dato", f"{avg_score:.1f} / 5.0")
            with c2:
                if avg_score < 2.0: st.error("🔴 Non pronti per il Modulo Base. Inizia a raccogliere bollette e dati HR.")
                elif avg_score < 4.0: st.warning("🟡 Pronti per il Modulo Base. Migliora tracciabilità per il Modulo PAT.")
                else: st.success("🟢 Pronti per Modulo PAT o Business Partner. Ottimo posizionamento bancario!")

    else:
        st.header("🔍 2. Readiness & Gap Analysis (ESRS)")
        gap_qs_E = ["Piano di transizione 1.5°C?", "Scope 1 e 2 completi?", "Scope 3 mappato?", "Rischi fisici in ERM?", "Target ambientali misurabili?", "Economia circolare integrata?", "Impatto biodiversità valutato?", "Monitoraggio idrico attivo?", "CapEx per sostenibilità?", "Controlli inquinanti?"]
        gap_qs_S = ["Due diligence diritti umani?", "Monitoraggio pay gap genere?", "Gestione salute e sicurezza?", "Formazione continua?", "Dialogo coi lavoratori?", "Living wage verificato?", "Politiche di inclusione?", "Impatto su comunità locali?", "Protezione privacy?", "Work-life balance?"]
        gap_qs_G = ["Codice Etico comunicato?", "Incentivi ESG ai dirigenti?", "Whistleblowing anonimo?", "Criteri ESG per fornitori?", "Lobbying trasparente?", "Report fiscale pubblico?", "Controlli interni dati ESG?", "Gestione crisi reputazionali?", "CdA con competenze ESG?", "Strategia approvata?"]

        c_g_E, c_g_S, c_g_G = st.tabs(["🌍 Ambiente", "👥 Sociale", "⚖️ Governance"])
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
                
            tot_score = sum(scores.values()); tot_max = sum(max_scores.values())
            readiness_pct = (tot_score / tot_max * 100) if tot_max > 0 else 0
            
            st.subheader("📊 Esito Audit Simulato")
            col_res1, col_res2 = st.columns([1, 2])
            with col_res1:
                st.metric("Readiness Globale", f"{readiness_pct:.1f}%")
                if readiness_pct < 40: st.error("🔴 Laggard (Alto Rischio). Gravi lacune normative.")
                elif readiness_pct < 75: st.warning("🟡 In Transizione (Rischio Moderato).")
                else: st.success("🟢 Leader (Pronto per Audit). Alta conformità.")
            with col_res2:
                df_radar = pd.DataFrame(dict(
                    r=[(scores['E']/max_scores['E'])*100 if max_scores['E']>0 else 0, (scores['S']/max_scores['S'])*100 if max_scores['S']>0 else 0, (scores['G']/max_scores['G'])*100 if max_scores['G']>0 else 0],
                    theta=['Ambiente (E)', 'Sociale (S)', 'Governance (G)']
                ))
                fig_radar = px.line_polar(df_radar, r='r', theta='theta', line_close=True, range_r=[0,100])
                fig_radar.update_traces(fill='toself', line_color='#00B050' if readiness_pct > 50 else '#EF553B')
                st.plotly_chart(fig_radar, use_container_width=True)

        st.divider()
        st.header("🎯 3. Analisi di Doppia Materialità (DMA)")
        dma_questions_dict = {
            "E": {
                "E1 - Cambiamento Climatico": [("Danni da eventi estremi?", "F"), ("Impatto finanziario green tax?", "F"), ("Impatto su emissioni globali?", "I")],
                "E2 - Inquinamento": [("Impatti da rilascio inquinanti?", "I"), ("Dipendenza da chimica pericolosa?", "F"), ("Inquinamento acustico/luminoso?", "I")],
                "E3 - Risorse Idriche": [("Siti in aree a stress idrico?", "F"), ("Influenza scarichi su falde?", "I"), ("Dipendenza da risorse marine?", "I")],
                "E4 - Biodiversità": [("Siti vicino ad aree protette?", "I"), ("Rischio deforestazione supply chain?", "I"), ("Dipendenza da ecosistemi?", "F")],
                "E5 - Economia Circolare": [("Scarsità materie prime?", "F"), ("Impatto gestione rifiuti?", "I"), ("Capacità di riciclo prodotti?", "I")]
            },
            "S": {
                "S1 - Forza Lavoro": [("Impatto su salute dipendenti?", "I"), ("Rischio discriminazione?", "I"), ("Living wage?", "I")],
                "S2 - Catena Valore": [("Lavoro forzato/minorile fornitori?", "I"), ("Fornitori in paesi a rischio?", "F"), ("Whistleblowing supply chain?", "I")],
                "S3 - Comunità": [("Impatto siti su popolazioni locali?", "I"), ("Diritti popolazioni indigene?", "I"), ("Gestione lamentele comunità?", "I")],
                "S4 - Consumatori": [("Impatti salute da uso prodotti?", "I"), ("Rischi privacy dati?", "F"), ("Impatto socio-economico marketing?", "I")]
            },
            "G": {
                "G1 - Condotta Affari": [("Analisi rischi corruzione?", "F"), ("Trasparenza lobbying?", "I"), ("Protezione whistleblower?", "I")]
            }
        }

        t_dma_e, t_dma_s, t_dma_g, t_dma_all = st.tabs(["🌍 Ambiente", "👥 Sociale", "⚖️ Governance", "📈 Matrice Finale (DMA)"])
        
        calculated_dma_scores = {}
        def render_dma_questions(pillar_dict, pillar_code, tab_context):
            with tab_context:
                for topic, questions in pillar_dict.items():
                    with st.expander(f"Valuta: {topic}"):
                        imp_sc, fin_sc = [], []
                        for idx, (q_text, q_type) in enumerate(questions):
                            ans = st.selectbox(f"[{'Impatto' if q_type == 'I' else 'Finanza'}] {q_text}", SCALE_OPTIONS, key=f"dma_{pillar_code}_{topic}_{idx}")
                            if q_type == 'I': imp_sc.append(SCALE_VALUES[ans])
                            else: fin_sc.append(SCALE_VALUES[ans])
                        
                        avg_imp = sum(imp_sc)/len(imp_sc) if imp_sc else (sum(fin_sc)/len(fin_sc) if fin_sc else 0)
                        avg_fin = sum(fin_sc)/len(fin_sc) if fin_sc else avg_imp
                        calculated_dma_scores[topic] = {"pilastro": pillar_code, "impatto": avg_imp, "finanza": avg_fin}

        render_dma_questions(dma_questions_dict["E"], "E", t_dma_e)
        render_dma_questions(dma_questions_dict["S"], "S", t_dma_s)
        render_dma_questions(dma_questions_dict["G"], "G", t_dma_g)

        with t_dma_all:
            dma_data = []
            for topic, scores in calculated_dma_scores.items():
                is_material = scores["impatto"] >= 2.5 or scores["finanza"] >= 2.5
                dma_data.append({"Tema": topic, "Pilastro": scores["pilastro"], "Impatto": scores["impatto"], "Finanza": scores["finanza"], "Status": "Materiale" if is_material else "Non Materiale", "Dim": 20 if is_material else 10})
                
            if dma_data:
                df_dma = pd.DataFrame(dma_data)
                fig_dma = px.scatter(df_dma, x="Finanza", y="Impatto", color="Pilastro", color_discrete_map={'E': '#00B050', 'S': '#00B0F0', 'G': '#0070C0'}, size="Dim", hover_name="Tema", text="Tema", range_x=[-0.5, 5.5], range_y=[-0.5, 5.5], title="Matrice Doppia Materialità")
                fig_dma.add_hline(y=2.45, line_dash="dash", line_color="red")
                fig_dma.add_vline(x=2.45, line_dash="dash", line_color="red")
                fig_dma.update_traces(textposition='top center', textfont_size=10)
                st.plotly_chart(fig_dma, use_container_width=True)

# =====================================================================
# TAB 2: ANALISI RISCHI E MAPPATura ASSET
# =====================================================================
with t_rischi:
    rt_fisico, rt_transizione, rt_credito = st.tabs(["🛰️ Mappa Asset & Rischio Fisico", "🔄 Transizione (GHG)", "💰 Stress Test (NGFS)"])
    
    with rt_fisico:
        st.subheader("1. Mappatura Rischio Portfolio Asset")
        
        if st.session_state.portfolio_df.empty and os.path.exists("centrali_geolocalizzate.csv"):
            try:
                df_map = pd.read_csv("centrali_geolocalizzate.csv")
                st.session_state.portfolio_df = process_portfolio_dataframe(df_map)
            except: pass
                
        with st.expander("🔄 Carica un portfolio impianti diverso (Upload / GitHub)"):
            col_m1, col_m2 = st.columns([1, 1])
            with col_m1: uploaded_portfolio = st.file_uploader("Carica File CSV", type=['csv'])
            with col_m2:
                github_url = st.text_input("URL GitHub Raw")
                use_github = st.checkbox("Usa link GitHub")

            if st.button("Genera Mappa da nuovo file"):
                df_map = pd.DataFrame()
                if uploaded_portfolio and not use_github: df_map = pd.read_csv(uploaded_portfolio)
                elif use_github and github_url:
                    try: df_map = pd.read_csv(github_url)
                    except: st.error("Errore download da GitHub.")
                
                if not df_map.empty:
                    st.session_state.portfolio_df = process_portfolio_dataframe(df_map)

        if not st.session_state.portfolio_df.empty:
            df_render = st.session_state.portfolio_df.copy()
            
            st.markdown("### 🌍 Selezione Scenario Climatico (IPCC AR6)")
            ipcc_scenario_mappa = st.radio(
                "Proiezione climatica al 2050:",
                ["SSP1-2.6 (+1.5°C)", "SSP2-4.5 (+2.4°C)", "SSP5-8.5 (+4.0°C)"],
                horizontal=True
            )
            
            np.random.seed(42) 
            base_risk = np.clip(100 - (df_render['Lat'] - 35) * 6 + np.random.randint(-10, 15, size=len(df_render)), 10, 100)
            if "SSP1" in ipcc_scenario_mappa: risk_multiplier = 0.7
            elif "SSP2" in ipcc_scenario_mappa: risk_multiplier = 1.1
            else: risk_multiplier = 1.6
            df_render['Risk_Score'] = np.clip(base_risk * risk_multiplier, 10, 100).astype(int)

            st.markdown("### 🏭 Filtro Impianti (Drill-Down)")
            col_f1, col_f2 = st.columns(2)
            
            if 'Operator' in df_render.columns:
                ops = ["Tutti gli Operatori"] + sorted(df_render['Operator'].dropna().astype(str).unique().tolist())
                with col_f1: scelta_op = st.selectbox("1. Seleziona Operatore:", ops)
                
                if scelta_op != "Tutti gli Operatori":
                    df_render = df_render[df_render['Operator'] == scelta_op]
                    if 'Name' in df_render.columns:
                        centrali = ["Tutte le centrali"] + sorted(df_render['Name'].dropna().astype(str).unique().tolist())
                        with col_f2: scelta_centrale = st.selectbox("2. Seleziona Centrale:", centrali)
                        
                        if scelta_centrale != "Tutte le centrali":
                            df_render = df_render[df_render['Name'] == scelta_centrale]
                else:
                    with col_f2: st.selectbox("2. Seleziona Centrale:", ["Seleziona prima un operatore"], disabled=True)

            st.markdown(f"#### 🔴 Livello di Rischio Fisico: {ipcc_scenario_mappa}")
            fig_portfolio = px.scatter_mapbox(
                df_render, lat="Lat", lon="Lon", hover_name="Name",
                hover_data={"Lat": False, "Lon": False, "ID": True, "Operator": True, "Address": True, "Risk_Score": True, "Size": True, "Display_Size": False},
                color="Risk_Score", size="Display_Size", color_continuous_scale=px.colors.diverging.RdYlGn_r,
                range_color=[10, 100], size_max=25, zoom=4.5 if len(df_render) > 1 else 10, mapbox_style="carto-positron", height=600
            )
            fig_portfolio.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
            st.plotly_chart(fig_portfolio, use_container_width=True)
            
            with st.expander("Mostra dati tabellari"):
                st.dataframe(df_render[['ID', 'Name', 'Operator', 'Address', 'Lat', 'Lon', 'Risk_Score']], use_container_width=True)
        else:
            st.info("Nessun dato geolocalizzato trovato in automatico. Assicurati di avere 'centrali_geolocalizzate.csv' nella cartella.")

    with rt_transizione:
        st.subheader("Calcolatore GHG (Fattori ISPRA/DEFRA)")
        
        EMISSION_FACTORS = {
            "Scope 1 - Gas Naturale": {"scope": "scope1", "unita": {"Metri Cubi (Sm3)": 1.98}},
            "Scope 1 - Gasolio": {"scope": "scope1", "unita": {"Litri (L)": 2.68}},
            "Scope 2 - Elettricità (Mix Italia)": {"scope": "scope2", "unita": {"MWh": 259.0}},
            "Scope 3 - Trasporto Merci": {"scope": "scope3", "unita": {"Tonnellate-km": 0.11}}
        }
        
        c_calc1, c_calc2, c_calc3 = st.columns([2, 1, 1])
        fonte_sel = c_calc1.selectbox("Categoria Consumo", list(EMISSION_FACTORS.keys()))
        unita_sel = c_calc2.selectbox("Unità", list(EMISSION_FACTORS[fonte_sel]["unita"].keys()))
        fattore = EMISSION_FACTORS[fonte_sel]["unita"][unita_sel]
        scope_target = EMISSION_FACTORS[fonte_sel]["scope"]
        consumo = c_calc1.number_input("Volume Annuo", min_value=0.0, step=100.0)
        co2_calc = (consumo * fattore) / 1000 
        
        c_calc3.metric("Emissioni", f"{co2_calc:,.2f} tCO2", help=f"Fattore: {fattore}")
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
        with c_cred1: st.number_input("Rata Prestito Transizione (€)", value=st.session_state.rata_prestito, step=100000, key='rata_prestito')
        with c_cred2: st.slider("Severità Policy", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier')

        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            profit = st.session_state.revenue - st.session_state.opex - (eff_price * st.session_state.em_final) - st.session_state.rata_prestito
            plot_data.append({"Anno": row['Anno'], "Utile Netto (€)": profit, "Scenario": row['Scenario']})
        
        st.plotly_chart(px.line(pd.DataFrame(plot_data), x="Anno", y="Utile Netto (€)", color="Scenario", title="EBITDA Netto post-Carbon Tax"), use_container_width=True)

# =====================================================================
# TAB 3 E 4: TASSONOMIA E CBAM
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
    if st.button("🪄 Genera Report Direzionale (PDF)"):
        pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", 'B', 18); pdf.cell(200, 15, txt="ESG Report", ln=True, align='C')
        st.download_button("Scarica PDF", pdf.output(dest='S').encode('latin-1'), "ESG_Report.pdf")
