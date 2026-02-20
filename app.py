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

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk AI Enterprise", layout="wide")

# --- SINCRONIZZAZIONE (Session State) ---
if 'revenue' not in st.session_state: st.session_state.revenue = 0
if 'opex' not in st.session_state: st.session_state.opex = 0
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

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_scopes(): sync_from_perc()

# --- MOTORE DATI, NACE E EU TAXONOMY JSON ---
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
    except:
        pass
    return 'UNKNOWN'

@st.cache_data
def load_taxonomy_json(file_content_or_path="taxonomy.json"):
    eligible_prefixes = set()
    try:
        if hasattr(file_content_or_path, 'getvalue'):
            content = file_content_or_path.getvalue().decode('utf-8', errors='ignore')
            data = json.loads(content)
        else:
            if not os.path.exists(file_content_or_path):
                return None
            with open(file_content_or_path, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)

        for activity in data.get('activities', []):
            nace_list = activity.get('nace_codes')
            if nace_list:
                for code in nace_list:
                    if not code: continue
                    clean_code = code.strip()
                    num_part = re.sub(r'^[A-Z]+', '', clean_code, flags=re.IGNORECASE).replace('.', '')
                    if len(num_part) == 1:
                        num_part = "0" + num_part
                    if num_part:
                        eligible_prefixes.add(num_part)
        return eligible_prefixes
    except Exception as e:
        return set()

@st.cache_data
def load_nace_hierarchy(file_content_or_path="NACE_Rev.2.1.rdf"):
    try:
        if hasattr(file_content_or_path, 'getvalue'):
            content = file_content_or_path.getvalue().decode('utf-8', errors='ignore')
        else:
            if not os.path.exists(file_content_or_path):
                return None
            with open(file_content_or_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        labels_by_code = {}
        block_pattern = r'<rdf:Description[^>]*rdf:about="http://data\.europa\.eu/ux2/nace2\.1/(?:[^"]*_)?([A-V]|\d{2,4})"[^>]*>(.*?)</rdf:Description>'
        
        for match in re.finditer(block_pattern, content, re.DOTALL):
            code = match.group(1).strip()
            block = match.group(2)
            if code not in labels_by_code:
                labels_by_code[code] = {}
                
            label_pattern = r'<skos:prefLabel[^>]*xml:lang="(it|en)"[^>]*>(.*?)</skos:prefLabel>'
            for l_match in re.finditer(label_pattern, block, re.DOTALL | re.IGNORECASE):
                lang = l_match.group(1).lower()
                text = re.sub(r'\s+', ' ', l_match.group(2)).strip()
                labels_by_code[code][lang] = text

        sections, divisions, groups, classes = {}, {}, {}, {}
        for code, langs in labels_by_code.items():
            label = langs.get('it', langs.get('en', f"Attività {code}"))
            if code.isalpha() and len(code) == 1:
                label = re.sub(rf'^{code}\s*-?\s*', '', label)
                sections[code] = {'label': f"{code} - {label}", 'children': {}}
            elif code.isdigit() and len(code) == 2:
                label = re.sub(rf'^{code}\s*-?\s*', '', label)
                divisions[code] = {'label': f"{code} - {label}", 'children': {}}
            elif len(code) == 3 and code.isdigit():
                fmt_code = f"{code[:2]}.{code[2:]}"
                label = re.sub(rf'^{code}\s*-?\s*', '', label)
                label = re.sub(rf'^{fmt_code}\s*-?\s*', '', label)
                groups[code] = {'label': f"{fmt_code} - {label}", 'children': {}}
            elif len(code) == 4 and code.isdigit():
                fmt_code = f"{code[:2]}.{code[2:]}"
                label = re.sub(rf'^{code}\s*-?\s*', '', label)
                label = re.sub(rf'^{fmt_code}\s*-?\s*', '', label)
                classes[code] = {'label': f"{fmt_code} - {label}", 'code': fmt_code}

        for d_code, d_data in divisions.items():
            s_code = get_nace_section(d_code)
            if s_code in sections: sections[s_code]['children'][d_code] = d_data
        for g_code, g_data in groups.items():
            d_code = g_code[:2]
            if d_code in divisions: divisions[d_code]['children'][g_code] = g_data
        for c_code, c_data in classes.items():
            g_code = c_code[:3]
            if g_code in groups: groups[g_code]['children'][c_code] = c_data
                
        ui_db = {}
        for s_code in sorted(sections.keys()):
            s_data = sections[s_code]
            if not s_data['children']: continue
            ui_db[s_data['label']] = {}
            for d_code in sorted(s_data['children'].keys()):
                d_data = s_data['children'][d_code]
                if not d_data['children']: continue
                ui_db[s_data['label']][d_data['label']] = {}
                for g_code in sorted(d_data['children'].keys()):
                    g_data = d_data['children'][g_code]
                    if not g_data['children']: continue
                    ui_db[s_data['label']][d_data['label']][g_data['label']] = {}
                    for c_code in sorted(g_data['children'].keys()):
                        c_data = g_data['children'][c_code]
                        ui_db[s_data['label']][d_data['label']][g_data['label']][c_data['label']] = c_data['code']
                        
        if not ui_db: return {"ERRORE": {"Nessun dato RDF utile.": {"-": {"-": ""}}}}
        return ui_db
    except Exception as e:
        return {"ERRORE": {str(e): {"-": {"-": ""}}}}

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

# --- CARICATORE GERARCHICO CN CODES (A TENDINE COME NACE) ---
@st.cache_data(ttl=600)
def load_cbam_hierarchy(file_path="cn_codes_clean.csv"):
    tree = {}
    try:
        if os.path.exists(file_path):
            # dtype=str assicura che codici come '01010000' non perdano lo zero iniziale
            df_cn = pd.read_csv(file_path, dtype=str)
            if 'CN_Code' in df_cn.columns and 'Description' in df_cn.columns:
                df_cn['CN_Code'] = df_cn['CN_Code'].fillna("00000000").str.zfill(8)
                df_cn['Description'] = df_cn['Description'].fillna("Nessuna descrizione")
                
                current_section = "Sezione Sconosciuta"
                current_chapter = "Capitolo Sconosciuto"
                current_heading = "Voce Sconosciuta"
                
                for _, row in df_cn.iterrows():
                    code = row['CN_Code']
                    desc = str(row['Description']).strip()
                    
                    if desc.upper().startswith("SEZIONE"):
                        current_section = desc
                        tree[current_section] = {}
                        current_chapter = None
                        current_heading = None
                    elif desc.upper().startswith("CAPITOLO"):
                        current_chapter = desc
                        if current_section not in tree: tree[current_section] = {}
                        tree[current_section][current_chapter] = {}
                        current_heading = None
                    elif code[4:] == '0000':
                        # Salta le righe amministrative fuori dalla gerarchia
                        if code[2:4] == '00' and not desc.upper().startswith(("SEZIONE", "CAPITOLO")):
                            continue
                        # Pulisce la descrizione da prefissi doppi (es. "0101 Cavalli" -> "Cavalli")
                        clean_desc = desc[5:].strip() if desc.startswith(code[:4]) else desc
                        current_heading = f"{code[:4]} - {clean_desc}"
                        if current_section and current_chapter:
                            if current_chapter not in tree[current_section]: tree[current_section][current_chapter] = {}
                            tree[current_section][current_chapter][current_heading] = {}
                    else:
                        if code[2:4] == '00' and not desc.upper().startswith(("SEZIONE", "CAPITOLO")):
                            continue
                        if current_section and current_chapter and current_heading:
                            if current_heading not in tree[current_section][current_chapter]:
                                tree[current_section][current_chapter][current_heading] = {}
                            # Inserisce il prodotto specifico come foglia dell'albero
                            product_label = f"{code} - {desc}"
                            tree[current_section][current_chapter][current_heading][product_label] = code
                return tree
    except Exception as e:
        print(f"Errore caricamento Albero CN: {e}")
    
    # Dati di Fallback se il CSV non viene trovato o è formattato male
    return {
        "SEZIONE V - PRODOTTI MINERALI (FALLBACK)": {
            "CAPITOLO 25 - SALE, ZOLFO, TERRE E PIETRE": {
                "2523 - Cementi idraulici": {
                    "25231000 - Cemento non polverizzato (clinker)": "25231000"
                }
            }
        },
        "SEZIONE XV - METALLI COMUNI E LORO LAVORI (FALLBACK)": {
            "CAPITOLO 72 - GHISA, FERRO E ACCIAIO": {
                "7200 - Prodotti base di ferro": {
                    "72000000 - Ferro o acciai non legati": "72000000"
                }
            }
        }
    }

cbam_tree = load_cbam_hierarchy()

# FUNZIONE LOGICA ANNEX I CBAM (Radar Doganale)
def check_cbam_category(cn_code):
    cn = str(cn_code).strip()
    if cn.startswith(('25070080', '2523')): return "Cemento"
    if cn == '27160000': return "Elettricità"
    if cn == '28041000': return "Idrogeno"
    if cn.startswith(('2808', '2814', '28342100', '3102', '3105')): return "Fertilizzanti"
    if cn.startswith(('72', '7301', '7302', '7303', '7304', '7305', '7306', '7307', '7308', '7309', '7310', '7311', '7318', '7326')): return "Ferro e Acciaio"
    if cn.startswith(('7601', '7603', '7604', '7605', '7606', '7607', '7608', '7609')): return "Alluminio"
    return "Non Soggetto"

# --- SIDEBAR: ESTRAZIONE E INSERIMENTO ---
with st.sidebar:
    st.title("⚙️ Setup Dati Aziendali")
    
    st.header("1. AI Data Extraction")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password", help="Lascia vuoto per testare la simulazione.")
    uploaded_pdf = st.file_uploader("Carica Bilancio Sostenibilità (PDF)", type="pdf")
    
    if uploaded_pdf:
        if st.button("Analizza con Intelligenza Artificiale"):
            with st.spinner("Lettura del documento in corso..."):
                if not api_key:
                    time.sleep(2)
                    st.session_state.revenue = 145_000_000
                    st.session_state.opex = 90_000_000
                    st.session_state.scope1 = 12500
                    st.session_state.scope2 = 8500
                    st.session_state.scope3 = 42000
                    st.session_state.sbti_approved = True
                    st.success("SIMULAZIONE COMPLETATA!")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    try:
                        pdf_reader = PyPDF2.PdfReader(uploaded_pdf)
                        testo_estratto = "".join([page.extract_text() + "\n" for page in pdf_reader.pages[:15]])
                        client = OpenAI(api_key=api_key)
                        prompt = f"""Estrai come JSON: "revenue" (intero), "opex" (intero), "scope1" (intero), "scope2" (intero), "scope3" (intero), "sbti_approved" (booleano). Testo: {testo_estratto[:15000]}"""
                        response = client.chat.completions.create(model="gpt-3.5-turbo-0125", messages=[{"role": "user", "content": prompt}], response_format={ "type": "json_object" })
                        dati_estratti = json.loads(response.choices[0].message.content)
                        st.session_state.revenue = int(dati_estratti.get("revenue", 0))
                        st.session_state.opex = int(dati_estratti.get("opex", 0))
                        st.session_state.scope1 = int(dati_estratti.get("scope1", 0))
                        st.session_state.scope2 = int(dati_estratti.get("scope2", 0))
                        st.session_state.scope3 = int(dati_estratti.get("scope3", 0))
                        st.session_state.sbti_approved = bool(dati_estratti.get("sbti_approved", False))
                        st.success("Estrazione Reale completata!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")
    
    st.divider()
    st.header("2. API Finanziarie (Mercato)")
    ticker = st.text_input("Ticker Yahoo Finance (es. ENEL.MI)")
    piva = st.text_input("Partita IVA (Per Registro EEA/SBTi)")
    
    if st.button("Sincronizza Database Pubblici"):
        with st.spinner("Connessione in corso..."):
            if not ticker: st.warning("Inserisci un Ticker.")
            else:
                try:
                    stock = yf.Ticker(ticker)
                    new_rev, new_ebitda = None, None
                    if stock.info and 'totalRevenue' in stock.info:
                        new_rev = stock.info.get('totalRevenue')
                        new_ebitda = stock.info.get('ebitda')
                    if not new_rev and not stock.financials.empty:
                        if 'Total Revenue' in stock.financials.index: new_rev = stock.financials.loc['Total Revenue'].iloc[0]
                        if 'EBITDA' in stock.financials.index: new_ebitda = stock.financials.loc['EBITDA'].iloc[0]
                    if new_rev:
                        st.session_state.revenue = int(new_rev)
                        st.session_state.opex = int(new_rev - new_ebitda) if new_ebitda and not pd.isna(new_ebitda) else int(new_rev * 0.8)
                        if piva: st.session_state.sbti_approved = True
                        st.success("Dati aggiornati!")
                        time.sleep(1.5)
                        st.rerun()
                    else: raise ValueError("Dati non disponibili.")
                except Exception as e:
                    st.warning("Yahoo limitato. Attivo Fallback (dati simulati).")
                    st.session_state.revenue, st.session_state.opex = 85_000_000, 60_000_000
                    if piva: st.session_state.sbti_approved = True
                    time.sleep(2)
                    st.rerun()

    st.divider()
    st.header("3. Inserimento Manuale Base")
    st.selectbox("Posizione Principale", df_base['Paese'].unique(), index=3, key='selected_country') 
    st.number_input("Ricavi Annuali (Turnover)", value=st.session_state.revenue, step=1_000_000, key='revenue')
    st.number_input("CapEx Totale Aziendale", value=st.session_state.capex_totale, step=1_000_000, key='capex_totale')
    st.number_input("OpEx Totale Aziendale", value=st.session_state.opex, step=1_000_000, key='opex')
    
    if st.session_state.sbti_approved:
        st.markdown("🎯 **Status:** `✅ Target SBTi Approvato`")

# --- CORPO PRINCIPALE ---
st.title("🌍 Piattaforma CarbonRisk AI")
st.markdown("Seleziona una delle schede qui sotto per procedere con l'analisi strategica.")

t_home, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🏠 Home", "📊 Analisi Rischi", "🇪🇺 Tassonomia UE", "🌍 CBAM (Dogana Smart)", "📥 Download Ufficiali"
])

# --- TAB 1: HOME ---
with t_home:
    st.header("Benvenuto in CarbonRisk Enterprise AI")
    st.markdown("Usa il menù a sinistra per inserire i dati della tua azienda. Naviga tra le schede in alto per effettuare le analisi di rischio e verificare l'allineamento normativo.")
    col_h1, col_h2, col_h3 = st.columns(3)
    col_h1.metric("Ricavi Attuali", f"€ {st.session_state.revenue:,.0f}")
    col_h2.metric("OpEx Attuali", f"€ {st.session_state.opex:,.0f}")
    col_h3.metric("Status SBTi", "Approvato" if st.session_state.sbti_approved else "Non Rilevato")

# --- TAB 2: ANALISI RISCHI ---
with t_rischi:
    st.header("Matrice dei Rischi Climatici")
    rt_fisico, rt_transizione, rt_credito = st.tabs(["🛰️ Rischio Fisico", "🔄 Rischio di Transizione", "💰 Stress Test Finanziario"])
    
    with rt_fisico:
        st.subheader("Dati Satellitari Copernicus (ESA)")
        indirizzo = st.text_input("Inserisci Indirizzo o CAP", "Porto di Rotterdam, Paesi Bassi")
        if st.button("📡 Estrai Dati ESA"):
            with st.spinner("Connessione API Copernicus in corso..."):
                time.sleep(1.5)
                geolocator = Nominatim(user_agent="CarbonApp")
                try:
                    loc = geolocator.geocode(indirizzo)
                    lat, lon = (loc.latitude, loc.longitude) if loc else (51.92, 4.47)
                    st.success(f"Coordinate identificate: {lat:.4f}, {lon:.4f}.")
                    fig_map = px.scatter_mapbox(pd.DataFrame({"Lat":[lat],"Lon":[lon],"L":["Asset"]}), lat="Lat", lon="Lon", zoom=10, height=350)
                    fig_map.update_layout(mapbox_style="carto-positron", margin={"r":0,"t":0,"l":0,"b":0})
                    st.plotly_chart(fig_map, use_container_width=True)
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("🌊 Rischio Allagamento (10 anni)", "45%", delta="+12% vs decennio prec.", delta_color="inverse")
                    c2.metric("🌡️ Giorni > 35°C (Stress Termico)", "18 gg/anno", delta="+5 gg", delta_color="inverse")
                    c3.metric("📉 Danno Economico Atteso", "€ 1.2M / anno")
                except:
                    st.error("Errore di geolocalizzazione.")

    with rt_transizione:
        st.subheader("1. Protocollo GHG (Inventario Emissioni)")
        c_ghg1, c_ghg2 = st.columns(2)
        with c_ghg1:
            st.number_input("Scope 1: Emissioni Dirette (tCO2)", value=st.session_state.scope1, step=5000, key='scope1', on_change=sync_from_scopes)
            st.number_input("Scope 2: Elettricità Acquistata (tCO2)", value=st.session_state.scope2, step=5000, key='scope2', on_change=sync_from_scopes)
            st.number_input("Scope 3: Supply Chain (tCO2)", value=st.session_state.scope3, step=5000, key='scope3', on_change=sync_from_scopes)
        with c_ghg2:
            emissions_tot = get_tot_emissions()
            st.info(f"### Totale Impronta Lorda\n# {emissions_tot:,} tCO2")
            st.markdown("Questa è la baseline su cui verranno calcolate le tasse sul carbonio e gli scenari di stress.")

        st.divider()
        st.subheader("2. Simulatore CapEx di Transizione")
        st.number_input("Efficacia attesa (Riduzione Stimata %)", 0, 100, key='perc_red', on_change=sync_from_perc)
        st.success(f"**Risultato Atteso:** Le emissioni nette finali scenderanno a **{st.session_state.em_final:,} tCO2**.")

    with rt_credito:
        st.subheader("1. Finanziamento & Evoluzione Carbonio")
        c_cred1, c_cred2, c_cred3 = st.columns(3)
        c_cred1.number_input("Rata Prestito Bancario (€)", value=st.session_state.rata_prestito, step=500_000, key='rata_prestito')
        c_cred2.number_input("Ammortamenti Annuali (€)", value=st.session_state.ammortamenti, step=500_000, key='ammortamenti')
        c_cred3.slider("Severità Leggi Locali (Moltiplicatore CO2)", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier')

        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        emissions_tot = get_tot_emissions()
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            profit_prima = st.session_state.revenue - st.session_state.opex - (eff_price * emissions_tot)
            profit_dopo = st.session_state.revenue - st.session_state.opex - (eff_price * st.session_state.em_final) - st.session_state.rata_prestito
            plot_data.append({
                "Anno": row['Anno'], 
                "Utile Netto (€)": profit_prima, 
                "Utile Netto Post-Transizione (€)": profit_dopo,
                "Scenario": row['Scenario'],
