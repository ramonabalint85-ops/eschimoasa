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
if 'revenue' not in st.session_state: st.session_state.revenue = 0
if 'opex' not in st.session_state: st.session_state.opex = 0
if 'totale_attivo' not in st.session_state: st.session_state.totale_attivo = 0
if 'dipendenti' not in st.session_state: st.session_state.dipendenti = 0
if 'quotata' not in st.session_state: st.session_state.quotata = False
if 'scope1' not in st.session_state: st.session_state.scope1 = 0
if 'scope2' not in st.session_state: st.session_state.scope2 = 0
if 'scope3' not in st.session_state: st.session_state.scope3 = 0
if 'perc_red' not in st.session_state: st.session_state.perc_red = 0
if 'em_final' not in st.session_state: st.session_state.em_final = 0
if 'sbti_approved' not in st.session_state: st.session_state.sbti_approved = False
if 'rata_prestito' not in st.session_state: st.session_state.rata_prestito = 0
if 'ammortamenti' not in st.session_state: st.session_state.ammortamenti = 0
if 'policy_multiplier' not in st.session_state: st.session_state.policy_multiplier = 1.0
if 'capex_totale' not in st.session_state: st.session_state.capex_totale = 0
if 'tax_portfolio' not in st.session_state: st.session_state.tax_portfolio = []
if 'cbam_portfolio' not in st.session_state: st.session_state.cbam_portfolio = [] 
if 'gap_answers' not in st.session_state: st.session_state.gap_answers = {}

# Inizializzazione punteggi Doppia Materialità
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

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_scopes(): sync_from_perc()

def sync_revenue_from_triage():
    st.session_state.revenue = st.session_state.rev_triage_widget

# --- MOTORE DATI E PREZZI LIVE ---
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

# --- SIDEBAR GLOBALE (ACQUISIZIONE DATI) ---
with st.sidebar:
    st.title("⚙️ Acquisizione Dati")
    
    st.header("1. Inserimento Manuale")
    st.selectbox("Paese Sede Legale", df_base['Paese'].unique(), index=3, key='selected_country') 
    st.session_state.totale_attivo = st.number_input("Attivo Patrimoniale (€)", value=st.session_state.totale_attivo, step=1000000)
    st.session_state.revenue = st.number_input("Ricavi Netti / Turnover (€)", value=st.session_state.revenue, step=1000000)
    st.session_state.dipendenti = st.number_input("Numero Dipendenti", value=st.session_state.dipendenti, step=10)
    st.session_state.quotata = st.checkbox("Quotata su mercato europeo?", value=st.session_state.quotata)
    st.session_state.capex_totale = st.number_input("CapEx Totale (€)", value=st.session_state.capex_totale, step=1000000)
    st.session_state.opex = st.number_input("OpEx Totale (€)", value=st.session_state.opex, step=1000000)
    
    st.divider()
    st.header("2. Sincronizzazione API (YFinance)")
    st.markdown("Estrae Fatturato, Attivo, Dipendenti, CapEx e OpEx direttamente dai bilanci depositati in borsa.")
    ticker = st.text_input("Ticker Aziendale (es. ENEL.MI)")
    
    if st.button("Sincronizza da Yahoo Finance"):
        with st.spinner("Scansione bilanci in corso..."):
            if not ticker: 
                st.warning("Inserisci un Ticker.")
            else:
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    fins = stock.financials
                    cf = stock.cash_flow
                    
                    # 1. Base Info
                    new_rev = info.get('totalRevenue') if info else None
                    new_assets = info.get('totalAssets') if info else None
                    new_emps = info.get('fullTimeEmployees') if info else None
                    
                    # 2. Ricerca Ricavi nei Financials se .info fallisce
                    if not new_rev and not fins.empty and 'Total Revenue' in fins.index:
                        new_rev = fins.loc['Total Revenue'].dropna().iloc[0]
                        
                    # 3. Estrazione OpEx (Operating Expenses)
                    new_opex = None
                    if not fins.empty:
                        if 'Operating Expense' in fins.index:
                            new_opex = fins.loc['Operating Expense'].dropna().iloc[0]
                        elif 'Total Operating Expenses' in fins.index:
                            new_opex = fins.loc['Total Operating Expenses'].dropna().iloc[0]
                        elif new_rev and 'Operating Income' in fins.index:
                            op_inc = fins.loc['Operating Income'].dropna().iloc[0]
                            new_opex = new_rev - op_inc
                            
                    # 4. Estrazione CapEx dal Cash Flow (Valore assoluto, poiché è uscita di cassa)
                    new_capex = None
                    if not cf.empty:
                        if 'Capital Expenditure' in cf.index:
                            new_capex = abs(cf.loc['Capital Expenditure'].dropna().iloc[0])
                        elif 'Purchases Of Property Plant And Equipment' in cf.index:
                            new_capex = abs(cf.loc['Purchases Of Property Plant And Equipment'].dropna().iloc[0])
                    
                    if new_rev:
                        st.session_state.revenue = int(new_rev)
                        st.session_state.totale_attivo = int(new_assets) if new_assets else int(new_rev * 1.5)
                        st.session_state.dipendenti = int(new_emps) if new_emps else max(50, int(new_rev / 500000))
                        if new_opex and not pd.isna(new_opex): st.session_state.opex = int(new_opex)
                        if new_capex and not pd.isna(new_capex): st.session_state.capex_totale = int(new_capex)
                        st.session_state.quotata = True
                        
                        st.success(f"✅ Dati finanziari (Inclusi CapEx/OpEx) estratti per {ticker.upper()}!")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.warning("⚠️ Dati non disponibili. Il ticker potrebbe essere errato o bloccato da Yahoo.")
                except Exception as e:
                    st.error("❌ Connessione rifiutata da Yahoo (Rate Limit). Inserisci i dati manualmente o usa l'AI.")

    st.divider()
    st.header("3. AI Data Extraction (PDF)")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password")
    uploaded_pdf = st.file_uploader("Carica Bilancio (PDF)", type="pdf")
    if uploaded_pdf and st.button("Analizza con AI"):
        with st.spinner("Estrazione dati con AI in corso..."):
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
                    prompt = f"""Estrai come JSON: "attivo" (intero), "revenue" (intero), "dipendenti" (intero), "opex" (intero), "capex" (intero). Testo: {testo[:15000]}"""
                    res = client.chat.completions.create(model="gpt-3.5-turbo-0125", messages=[{"role": "user", "content": prompt}], response_format={ "type": "json_object" })
                    dati = json.loads(res.choices[0].message.content)
                    st.session_state.totale_attivo = dati.get("attivo", 0)
                    st.session_state.revenue = dati.get("revenue", 0)
                    st.session_state.dipendenti = dati.get("dipendenti", 0)
                    st.session_state.opex = dati.get("opex", 0)
                    st.session_state.capex_totale = dati.get("capex", 0)
                    st.success("Dati estratti dal PDF!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore AI: {e}")

# --- CORPO PRINCIPALE E TABS ---
st.title("🌍 CarbonRisk AI Enterprise")

t_triage, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🧭 Triage & Materialità", "📊 Analisi Rischi (IPCC)", "🇪🇺 Tassonomia UE", "🌍 CBAM (Dogana Smart)", "📥 Report & Export"
])

# =====================================================================
# TAB 0: TRIAGE NORMATIVO, GAP ANALYSIS E DOPPIA MATERIALITÀ
# =====================================================================
with t_triage:
    st.header("🧭 1. Test di Assoggettabilità (CSRD vs VSME)")
    st.markdown("Il sistema valuta l'obbligo normativo basandosi sui dati inseriti nella Sidebar (Attivo, Ricavi, Dipendenti, Quotazione).")

    # ALGORITMO DI TRIAGE
    soglia_attivo = st.session_state.totale_attivo > 25000000
    soglia_ricavi = st.session_state.revenue > 50000000
    soglia_dip = st.session_state.dipendenti > 250
    
    score_grandi = sum([soglia_attivo, soglia_ricavi, soglia_dip])
    
    st.info(f"**Dati Baseline:** Attivo: {st.session_state.totale_attivo/1e6:.1f}M € | Ricavi: {st.session_state.revenue/1e6:.1f}M € | Dipendenti: {st.session_state.dipendenti} | Quotata: {'Sì' if st.session_state.quotata else 'No'}")
    
    if score_grandi >= 2:
        status_normativo = "CSRD_GRANDE"
        st.error("### 🏢 ESITO: OBBLIGO CSRD (Grande Impresa)")
        st.markdown("L'azienda supera 2 dei 3 limiti dimensionali. È obbligatorio redigere il report di sostenibilità secondo gli standard completi **ESRS**.")
    elif st.session_state.quotata:
        status_normativo = "CSRD_PMI"
        st.warning("### 📈 ESITO: OBBLIGO CSRD (PMI Quotata)")
        st.markdown("In quanto PMI quotata, l'azienda è soggetta alla CSRD (standard proporzionato **LSME**).")
    else:
        status_normativo = "VSME"
        st.success("### 🌱 ESITO: PERCORSO VOLONTARIO (PMI - EFRAG VSME)")
        st.markdown("L'azienda **NON è obbligata** alla CSRD. Verrà utilizzato il framework semplificato **EFRAG VSME**.")

    st.divider()
    
    # ---------------------------------------------------------
    # 2. GAP ANALYSIS DINAMICA
    # ---------------------------------------------------------
    st.header("🔍 2. Readiness & Gap Analysis")
    st.markdown("Valuta lo stato attuale dei processi aziendali rispetto allo standard individuato.")

    def render_gap_question(qid, text, pillar):
        ans = st.radio(f"**[{pillar}]** {text}", ["Sì (Documentato)", "In Corso (Informale)", "No"], horizontal=True, key=f"gap_{qid}")
        st.session_state.gap_answers[qid] = {"ans": ans, "pillar": pillar}

    if status_normativo == "VSME":
        c_v1, c_v2, c_v3 = st.tabs(["🌍 Ambiente (E)", "👥 Sociale (S)", "⚖️ Governance (G)"])
        with c_v1:
            render_gap_question("v_e1", "Tracciate accuratamente i consumi totali di energia (gas, luce, carburante)?", "E")
            render_gap_question("v_e2", "Calcolate le emissioni dirette (Scope 1) e indirette da energia (Scope 2)?", "E")
            render_gap_question("v_e3", "Monitorate i volumi di rifiuti prodotti e la loro destinazione?", "E")
        with c_v2:
            render_gap_question("v_s1", "Tenete un registro formale degli infortuni sul lavoro?", "S")
            render_gap_question("v_s2", "Applicate politiche per garantire parità di trattamento tra generi?", "S")
        with c_v3:
            render_gap_question("v_g1", "Avete un Codice Etico comunicato ai dipendenti?", "G")
            render_gap_question("v_g2", "Avete stabilito target misurabili per il futuro (es. -10% CO2)?", "G")
            
    else: # ESRS
        c_e1, c_e2, c_e3 = st.tabs(["🌍 Ambiente (ESRS E)", "👥 Sociale (ESRS S)", "⚖️ Governance (ESRS G)"])
        with c_e1:
            render_gap_question("e_e1", "Avete un Piano di Transizione Climatico allineato a 1.5°C?", "E")
            render_gap_question("e_e2", "Misurate le emissioni Scope 3 (catena di fornitura)?", "E")
            render_gap_question("e_e3", "Rendicontate l'allineamento dei vostri ricavi alla Tassonomia UE?", "E")
        with c_e2:
            render_gap_question("e_s1", "Pubblicate il Gender Pay Gap?", "S")
            render_gap_question("e_s2", "Avete mappato i rischi sui diritti umani lungo la catena del valore?", "S")
        with c_e3:
            render_gap_question("e_g1", "Il CdA supervisiona ufficialmente i temi ESG?", "G")
            render_gap_question("e_g2", "La remunerazione dei dirigenti è legata a target di sostenibilità?", "G")

    if st.button("Calcola Readiness % e Profilo di Rischio", use_container_width=True):
        scores = {'E': 0, 'S': 0, 'G': 0}; max_scores = {'E': 0, 'S': 0, 'G': 0}
        for q_id, data in st.session_state.gap_answers.items():
            val = 1.0 if "Sì" in data["ans"] else (0.5 if "In Corso" in data["ans"] else 0.0)
            scores[data["pillar"]] += val
            max_scores[data["pillar"]] += 1
            
        tot_score = sum(scores.values()); tot_max = sum(max_scores.values())
        readiness_pct = (tot_score / tot_max * 100) if tot_max > 0 else 0
        
        st.subheader("📊 Esito Audit Simulato")
        col_res1, col_res2 = st.columns([1, 2])
        with col_res1:
            st.metric("Readiness Globale", f"{readiness_pct:.1f}%")
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

    # ---------------------------------------------------------
    # 3. DOPPIA MATERIALITÀ (SOLO SE CSRD)
    # ---------------------------------------------------------
    if status_normativo in ["CSRD_GRANDE", "CSRD_PMI"]:
        st.divider()
        st.header("🎯 3. Analisi di Doppia Materialità (DMA)")
        st.markdown("La CSRD impone di valutare quali temi rendicontare. Rispondi per determinare la materialità.")

        col_dma1, col_dma2 = st.columns([1.2, 1])

        with col_dma1:
            options_dict = {"1 - Nullo/Non Rilevante": 1, "2 - Basso": 2, "3 - Medio": 3, "4 - Alto": 4, "5 - Critico/Severo": 5}
            
            with st.container(height=600):
                for topic, scores in st.session_state.materiality_scores.items():
                    with st.expander(f"**[{scores['pilastro']}]** {topic}"):
                        q_imp = st.selectbox("Qual è la gravità degli impatti dell'azienda su ambiente/persone?", 
                                             list(options_dict.keys()), index=scores["impatto"]-1, key=f"q_imp_{topic}")
                        
                        q_fin = st.selectbox("Qual è l'entità dei rischi/opportunità finanziarie derivanti da questo tema?", 
                                             list(options_dict.keys()), index=scores["finanza"]-1, key=f"q_fin_{topic}")
                        
                        st.session_state.materiality_scores[topic]["impatto"] = options_dict[q_imp]
                        st.session_state.materiality_scores[topic]["finanza"] = options_dict[q_fin]

        with col_dma2:
            dma_data = []
            for topic, scores in st.session_state.materiality_scores.items():
                is_material = scores["impatto"] >= 3 or scores["finanza"] >= 3
                dma_data.append({
                    "Tema": topic, "Pilastro": scores["pilastro"],
                    "Impatto": scores["impatto"], "Finanza": scores["finanza"],
                    "Status": "Materiale" if is_material else "Non Materiale",
                    "Dim": 20 if is_material else 10
                })
                
            df_dma = pd.DataFrame(dma_data)
            fig_dma = px.scatter(
                df_dma, x="Finanza", y="Impatto", color="Pilastro",
                color_discrete_map={'E': '#00B050', 'S': '#00B0F0', 'G': '#0070C0'},
                size="Dim", hover_name="Tema", text="Tema",
                range_x=[0.5, 5.5], range_y=[0.5, 5.5], title="Matrice di Doppia Materialità ESRS"
            )
            fig_dma.add_hline(y=2.95, line_dash="dash", line_color="red")
            fig_dma.add_vline(x=2.95, line_dash="dash", line_color="red")
            fig_dma.update_traces(textposition='top center', textfont_size=10)
            fig_dma.update_layout(height=500, xaxis_title="Rilevanza Finanziaria", yaxis_title="Rilevanza d'Impatto")
            fig_dma.add_shape(type="rect", x0=2.95, y0=2.95, x1=5.5, y1=5.5, fillcolor="rgba(255,0,0,0.1)", line_width=0, layer="below")
            st.plotly_chart(fig_dma, use_container_width=True)
            
            temi_mat = df_dma[df_dma["Status"] == "Materiale"]["Tema"].tolist()
            if temi_mat:
                st.success(f"📌 **Temi Obbligatori ({len(temi_mat)}/10):** " + ", ".join(temi_mat))

# =====================================================================
# TAB 2: ANALISI RISCHI (IPCC, NGFS, FATTORI DI EMISSIONE)
# =====================================================================
with t_rischi:
    rt_fisico, rt_transizione, rt_credito = st.tabs(["🛰️ Rischio Fisico (IPCC)", "🔄 Rischio di Transizione (GHG)", "💰 Stress Test Finanziario (NGFS)"])
    
    with rt_fisico:
        st.subheader("Modellazione Climatica ERA5 (10km) & Scenari IPCC 2050")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            indirizzo = st.text_input("Inserisci Indirizzo o Asset", "Via del Corso, Roma")
        with col_f2:
            ipcc_scenario = st.selectbox("Scenario IPCC (Orizzonte 2050)", ["SSP1-2.6 (Sostenibilità)", "SSP2-4.5 (Intermedio)", "SSP5-8.5 (Fossile)"], index=1)
            
        if st.button("📡 Esegui Simulazione Geospaziale"):
            with st.spinner("Interrogazione satellite Copernicus..."):
                geolocator = Nominatim(user_agent="CarbonApp")
                try:
                    loc = geolocator.geocode(indirizzo)
                    lat, lon = (loc.latitude, loc.longitude) if loc else (41.90, 12.49)
                    
                    fig_map = px.scatter_mapbox(pd.DataFrame({"Lat":[lat],"Lon":[lon],"L":["Asset"]}), lat="Lat", lon="Lon", zoom=12, height=300)
                    fig_map.update_layout(mapbox_style="carto-positron", margin={"r":0,"t":0,"l":0,"b":0})
                    st.plotly_chart(fig_map, use_container_width=True)
                    
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
        st.subheader("1. Protocollo GHG (Inventario Emissioni)")
        
        with st.expander("🧮 Calcolatore da Consumi Reali (Database ISPRA/DEFRA)", expanded=True):
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
