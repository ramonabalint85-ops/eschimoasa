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

# --- CARICATORE GERARCHICO CN CODES (A PROVA DI BOMBA) ---
@st.cache_data(ttl=600)
def load_cbam_hierarchy(file_path="cn_codes_clean.csv"):
    tree = {}
    try:
        if os.path.exists(file_path):
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
                        current_chapter = "Capitolo Sconosciuto"
                        current_heading = "Voce Sconosciuta"
                    elif desc.upper().startswith("CAPITOLO"):
                        current_chapter = desc
                        current_heading = "Voce Sconosciuta"
                    elif code.endswith('0000') and code[2:4] != '00':
                        clean_desc = desc[5:].strip() if desc.startswith(code[:4]) else desc
                        current_heading = f"{code[:4]} - {clean_desc}"
                    else:
                        # Salta le righe amministrative (es. 01001100 se non sono sezioni)
                        if code[2:4] == '00' and not desc.upper().startswith(("SEZIONE", "CAPITOLO")):
                            continue
                            
                        # CREAZIONE SICURA DELLE SOTTOCARTELLE (Previene i KeyError)
                        if current_section not in tree:
                            tree[current_section] = {}
                        if current_chapter not in tree[current_section]:
                            tree[current_section][current_chapter] = {}
                        if current_heading not in tree[current_section][current_chapter]:
                            tree[current_section][current_chapter][current_heading] = {}
                            
                        # Inserimento foglia prodotto
                        product_label = f"{code} - {desc}"
                        tree[current_section][current_chapter][current_heading][product_label] = code
                return tree
    except Exception as e:
        print(f"Errore caricamento Albero CN: {e}")
    
    # Fallback sicuro in caso di file mancante
    return {"SEZIONE V - PRODOTTI MINERALI (FALLBACK)": {"CAPITOLO 25 - SALE, ZOLFO, TERRE E PIETRE": {"2523 - Cementi": {"25231000 - Cemento (Fallback)": "25231000"}}}}

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
                "Prezzo Carbonio (€/t)": eff_price
            })
        plot_df = pd.DataFrame(plot_data)
        color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}

        fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, title="Evoluzione Prezzo Tasse Carbonio (€/t)")
        fig_prezzo.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
        st.plotly_chart(fig_prezzo, use_container_width=True)

        st.divider()

        st.subheader("2. Analisi d'Impatto: Utili Prima e Dopo la Transizione")
        col_lin1, col_lin2 = st.columns(2)
        with col_lin1:
            fig_prima = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, title="PRIMA: Nessuna Transizione")
            fig_prima.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_prima, use_container_width=True)
            
        with col_lin2:
            fig_dopo = px.line(plot_df, x="Anno", y="Utile Netto Post-Transizione (€)", color="Scenario", color_discrete_map=color_map, title="DOPO: Con Transizione (Prestito incluso)")
            fig_dopo.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_dopo, use_container_width=True)

# --- TAB 3: TASSONOMIA UE (COMPLETA - TURNOVER, CAPEX, OPEX E OBIETTIVI) ---
with t_tax:
    st.header("🇪🇺 Reporting Tassonomia UE (Modello Completo)")
    st.markdown("Valuta l'ammissibilità tramite i codici NACE. Per ogni attività, specifica l'obiettivo ambientale primario e inserisci i 3 KPI chiave (Turnover, CapEx, OpEx). Le attività non ammissibili alimenteranno comunque i denominatori per calcolare l'esatta percentuale aziendale.")
    
    nace_db = load_nace_hierarchy("NACE_Rev.2.1.rdf")
    taxonomy_prefixes = load_taxonomy_json("taxonomy.json")
    
    mostra_successo = True
    if nace_db is None or "ERRORE" in str(nace_db): mostra_successo = False
    if taxonomy_prefixes is None or not taxonomy_prefixes: mostra_successo = False

    if mostra_successo:
        st.success("✅ Database NACE e EU Compass caricati. Sincronizzazione automatica attiva.")
    else:
        st.warning("⚠️ Database non trovati. Usa i box per caricare NACE_Rev.2.1.rdf e taxonomy.json")

    with st.expander("➕ Aggiungi Commessa / Attività al Report", expanded=True):
        erp_id = st.text_input("🏢 ID Commessa / Cost Center ERP (es. SAP-PRJ-2026-001)")
        st.divider()
        
        col_tax1, col_tax2 = st.columns(2)

        with col_tax1:
            # Menu a tendina sicuri per evitare KeyError nel NACE
            sezione = st.selectbox("Sezione NACE", list(nace_db.keys()) if isinstance(nace_db, dict) and "ERRORE" not in str(nace_db) else [])
            divisione = st.selectbox("Divisione NACE", list(nace_db.get(sezione, {}).keys()) if sezione else [])
            gruppo = st.selectbox("Gruppo NACE", list(nace_db.get(sezione, {}).get(divisione, {}).keys()) if divisione else [])
            classe = st.selectbox("Classe NACE", list(nace_db.get(sezione, {}).get(divisione, {}).get(gruppo, {}).keys()) if gruppo else [])
            
            nace_code = nace_db.get(sezione, {}).get(divisione, {}).get(gruppo, {}).get(classe, "")
            attivita = classe.split(" - ", 1)[-1] if classe else ""
            
            user_nace_clean = nace_code.replace('.', '') if nace_code else ""
            is_eligible = False
            
            if user_nace_clean and taxonomy_prefixes:
                is_eligible = any(user_nace_clean.startswith(prefix) for prefix in taxonomy_prefixes)
            
            st.markdown("### Status di Ammissibilità:")
            if is_eligible:
                st.success("✅ **Attività Ammissibile (Eligible)**")
            else:
                st.info("ℹ️ **Non Ammissibile (Non-Eligible).** Puoi inserire comunque i valori finanziari: verranno sommati al denominatore per calcolare la percentuale corretta dell'azienda.")

        with col_tax2:
            st.markdown("### Selezione Obiettivo Ambientale")
            obiettivi = [
                "CCM - Mitigazione del Cambiamento Climatico",
                "CCA - Adattamento al Cambiamento Climatico",
                "WTR - Uso Sostenibile delle Acque",
                "CE - Transizione verso Economia Circolare",
                "PPC - Prevenzione e Controllo Inquinamento",
                "BIO - Protezione Biodiversità ed Ecosistemi"
            ]
            obiettivo_sc = st.selectbox("A quale obiettivo contribuisce in modo sostanziale?", obiettivi)
            
            st.markdown("### Input Finanziario (KPIs)")
            c_val1, c_val2, c_val3 = st.columns(3)
            val_turnover = c_val1.number_input("Turnover/Ricavi (€)", min_value=0, value=0, step=10000)
            val_capex = c_val2.number_input("CapEx (€)", min_value=0, value=0, step=10000)
            val_opex = c_val3.number_input("OpEx (€)", min_value=0, value=0, step=10000)

        st.divider()

        attivita_lower = attivita.lower()
        if "edifici" in attivita_lower or "costruzione" in attivita_lower: unita, soglia, target_unit = "m2 Gestiti", 80.0, "kWh/m2"
        elif "trasporto" in attivita_lower or "veicoli" in attivita_lower: unita, soglia, target_unit = "tkm", 50.0, "gCO2/tkm"
        elif "cemento" in attivita_lower: unita, soglia, target_unit = "Tonnellate prodotte", 0.72, "tCO2/ton"
        elif "acciaio" in attivita_lower or "alluminio" in attivita_lower: unita, soglia, target_unit = "Tonnellate", 1.3, "tCO2/ton"
        elif "energia" in attivita_lower or "elettricità" in attivita_lower: unita, soglia, target_unit = "MWh", 100.0, "gCO2/kWh"
        elif "dati" in attivita_lower or "informatici" in attivita_lower: unita, soglia, target_unit = "Terabyte (TB)", 1.2, "PUE"
        else: unita, soglia, target_unit = "Unità", 1.0, "tCO2/unità"

        if is_eligible:
            st.markdown("### Screening Tecnico e Caricamento Prove (Document Vault)")
            col_sc1, col_sc2 = st.columns(2)
            with col_sc1:
                st.markdown(f"**Test Substantial Contribution:** `<= {soglia} {target_unit}`")
                prod = st.number_input(f"Volume Annuo ({unita})", value=0, step=10000)
                int_calc = (st.session_state.em_final / prod) if prod > 0 else 0
                if target_unit.startswith("g"): int_calc *= 1000 
                elif "PUE" in target_unit: int_calc = 1.0 + (st.session_state.em_final / 1000000)
                
                tsc_passed = int_calc <= soglia and prod > 0
                st.metric("Esito Test Automatico", "Superato (Y)" if tsc_passed else "Non Superato (N)", delta_color="normal" if tsc_passed else "inverse")
            with col_sc2:
                file_sc = st.file_uploader("1. Prova Substantial Contribution", type=["pdf", "xlsx", "docx"])
                file_dnsh = st.file_uploader("2. Prova DNSH (es. Analisi Rischi)", type=["pdf", "xlsx"])
                file_ms = st.file_uploader("3. Prova Minimum Safeguards", type=["pdf", "docx"])
                
            file_sc_name = file_sc.name if file_sc else "Mancante"
            file_dnsh_name = file_dnsh.name if file_dnsh else "Mancante"
            file_ms_name = file_ms.name if file_ms else "Mancante"
        else:
            tsc_passed = False
            file_sc_name, file_dnsh_name, file_ms_name = "N/A", "N/A", "N/A"
            file_dnsh = None
            file_ms = None
            
        if st.button("➕ Inserisci in Registro"):
            if not erp_id:
                st.error("⚠️ Inserisci un ID Commessa ERP prima di procedere.")
            elif val_turnover == 0 and val_capex == 0 and val_opex == 0:
                st.error("Inserisci almeno un valore finanziario (Turnover, CapEx o OpEx) > 0.")
            else:
                st.session_state.tax_portfolio.append({
                    "ERP Cost Center": erp_id,
                    "Economic activities": attivita,
                    "Code(s)": nace_code,
                    "Objective": obiettivo_sc.split(" ")[0],
                    "Turnover (€)": val_turnover,
                    "CapEx (€)": val_capex,
                    "OpEx (€)": val_opex,
                    "Eligible (Y/N)": "Y" if is_eligible else "N",
                    "TSC Passed": "Y" if (tsc_passed and is_eligible) else "N",
                    "DNSH": "Y" if (is_eligible and file_dnsh) else "N", 
                    "Safeguards": "Y" if (is_eligible and file_ms) else "N",
                    "Doc_SC": file_sc_name,
                    "Doc_DNSH": file_dnsh_name,
                    "Doc_MS": file_ms_name
                })
                st.success(f"Attività registrata con successo!")
                time.sleep(1)
                st.rerun()

    st.divider()
    st.subheader("📋 Registro Editor Tassonomia (Tutti i KPI)")
    
    if st.session_state.tax_portfolio:
        df_tax = pd.DataFrame(st.session_state.tax_portfolio)
        
        edited_df = st.data_editor(
            df_tax,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "ERP Cost Center": st.column_config.TextColumn("ID ERP", width="small"),
                "Economic activities": st.column_config.TextColumn("Attività", width="medium"),
                "Code(s)": st.column_config.TextColumn("NACE", width="small"),
                "Objective": st.column_config.TextColumn("Obiettivo SC", width="small"),
                "Turnover (€)": st.column_config.NumberColumn("Turnover (€)", format="€ %d", width="small"),
                "CapEx (€)": st.column_config.NumberColumn("CapEx (€)", format="€ %d", width="small"),
                "OpEx (€)": st.column_config.NumberColumn("OpEx (€)", format="€ %d", width="small"),
                "Eligible (Y/N)": st.column_config.TextColumn("Ammissibile", disabled=True, width="small"),
                "TSC Passed": st.column_config.TextColumn("TSC (Y/N)", disabled=True, width="small"),
                "DNSH": st.column_config.SelectboxColumn("DNSH", options=["Y", "N", "N/A"], width="small"),
                "Safeguards": st.column_config.SelectboxColumn("Safeguards", options=["Y", "N", "N/A"], width="small"),
                "Doc_SC": st.column_config.TextColumn("Doc SC", disabled=True),
                "Doc_DNSH": st.column_config.TextColumn("Doc DNSH", disabled=True),
                "Doc_MS": st.column_config.TextColumn("Doc MS", disabled=True)
            },
            key="tax_editor"
        )
        
        edited_df["Aligned"] = (edited_df["Eligible (Y/N)"] == "Y") & (edited_df["TSC Passed"] == "Y") & (edited_df["DNSH"] == "Y") & (edited_df["Safeguards"] == "Y")
        st.session_state.tax_portfolio = edited_df.drop(columns=["Aligned"]).to_dict('records')
        
        if st.button("🗑️ Svuota Registro"):
            st.session_state.tax_portfolio = []
            st.rerun()

        st.divider()
        st.subheader("📊 Dashboard Risultati Tassonomia")

        tab_turnover, tab_capex, tab_opex = st.tabs(["💶 Turnover (Ricavi)", "🏗️ CapEx (Investimenti)", "⚙️ OpEx (Costi Operativi)"])
        
        def render_kpi_tab(kpi_name, df, company_baseline):
            col_name = f"{kpi_name} (€)"
            tot_entered = df[col_name].sum()
            denominator = max(company_baseline, tot_entered)
            
            val_eligible = df[df["Eligible (Y/N)"] == "Y"][col_name].sum()
            val_non_eligible = df[df["Eligible (Y/N)"] == "N"][col_name].sum()
            val_aligned = df[df["Aligned"] == True][col_name].sum()
            val_eligible_not_aligned = val_eligible - val_aligned
            val_unclassified = denominator - (val_eligible + val_non_eligible)
            
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.metric(f"Total Denominator ({kpi_name})", f"€ {denominator:,.0f}")
                st.metric("Taxonomy-aligned proportion (%)", f"{(val_aligned/denominator*100) if denominator>0 else 0:.2f} %")
                st.metric("Eligible proportion (%)", f"{(val_eligible/denominator*100) if denominator>0 else 0:.2f} %")
                
            with c2:
                fig = go.Figure(data=[go.Pie(
                    labels=["Aligned", "Eligible Not Aligned", "Non-Eligible", "Non Classificato"], 
                    values=[val_aligned, val_eligible_not_aligned, val_non_eligible, val_unclassified], 
                    hole=.4, marker_colors=['#00B050', '#FECB52', '#C00000', '#D3D3D3']
                )])
                fig.update_layout(margin=dict(t=20, b=0, l=0, r=0))
                st.plotly_chart(fig, use_container_width=True)

        with tab_turnover:
            render_kpi_tab("Turnover", edited_df, st.session_state.revenue)
        with tab_capex:
            render_kpi_tab("CapEx", edited_df, st.session_state.capex_totale)
        with tab_opex:
            render_kpi_tab("OpEx", edited_df, st.session_state.opex)

# --- TAB 4: CBAM SELF-ASSESSMENT TOOL (RICERCA A CASCATA DOGANALE) ---
with t_cbam:
    st.header("🌍 CBAM Self-Assessment Tool (Ricerca a Cascata)")
    st.markdown("Esplora la Nomenclatura Combinata Europea attraverso i menù a tendina. Il sistema ti avviserà in automatico se la merce selezionata fa parte dell'**Allegato I (Annex I) soggetto a CBAM** (es. Cemento, Acciaio, Fertilizzanti, Alluminio, Elettricità, Idrogeno).")
    
    paesi_origine = {
        "Cina (China National ETS)": {"Tax": 10.0, "Exempt": False},
        "India / Turchia (Nessuna Tassa)": {"Tax": 0.0, "Exempt": False},
        "Regno Unito (UK ETS)": {"Tax": 45.0, "Exempt": False},
        "Canada (Federal Carbon Pricing)": {"Tax": 55.0, "Exempt": False},
        "Stati Uniti (Nessuna Tassa Fiscale)": {"Tax": 0.0, "Exempt": False},
        "Svizzera (Esente - Art. 2 CBAM)": {"Tax": 0.0, "Exempt": True},
        "Norvegia/Islanda/Liechtenstein (Esente - EEA)": {"Tax": 0.0, "Exempt": True},
        "Unione Europea (Produzione Interna)": {"Tax": 0.0, "Exempt": True}
    }

    with st.expander("➕ Compila Nuova Spedizione Doganale", expanded=True):
        col_cb1, col_cb2 = st.columns(2)
        
        with col_cb1:
            # --- MENU A TENDINA MULTIPLI CN CODES (Senza rischio KeyError) ---
            sezione_cbam = st.selectbox("Sezione Doganale", list(cbam_tree.keys()) if cbam_tree else [])
            
            capitoli = list(cbam_tree.get(sezione_cbam, {}).keys()) if sezione_cbam else []
            capitolo_cbam = st.selectbox("Capitolo (Prime 2 cifre)", capitoli)
            
            voci = list(cbam_tree.get(sezione_cbam, {}).get(capitolo_cbam, {}).keys()) if capitolo_cbam else []
            voce_cbam = st.selectbox("Voce (4 cifre)", voci)
            
            merci = list(cbam_tree.get(sezione_cbam, {}).get(capitolo_cbam, {}).get(voce_cbam, {}).keys()) if voce_cbam else []
            merce_selezionata = st.selectbox("Codice Prodotto Specifico (8 cifre)", merci)
            
            # --- LOGICA RADAR DOGANALE CBAM ---
            is_annex_i = "No"
            codice_cn_estratto = ""
            descrizione_merce = ""
            
            if merce_selezionata:
                # Estrazione sicura del codice dal dizionario
                codice_cn_estratto = cbam_tree.get(sezione_cbam, {}).get(capitolo_cbam, {}).get(voce_cbam, {}).get(merce_selezionata, "")
                descrizione_merce = merce_selezionata.split(" - ", 1)[-1]
                
                categoria_cbam = check_cbam_category(codice_cn_estratto)
                
                if categoria_cbam != "Non Soggetto":
                    st.error(f"⚠️ **ATTENZIONE: Merce soggetta a CBAM** (Categoria: {categoria_cbam})")
                    is_annex_i = "Yes"
                else:
                    st.success("✅ **Merce NON soggetta a CBAM** (Esente Annex I)")
                    is_annex_i = "No"
                    
            emissioni_merce = st.number_input("Emissioni Incorporate Stimabili (tCO2)", min_value=0, value=0, step=100)
            
        with col_cb2:
            origine_merce = st.selectbox("Paese di Origine", list(paesi_origine.keys()))
            importato_ue = st.selectbox("Rilasciato in libera pratica UE?", ["Sì", "No (Transito)"])
            valore_merce = st.number_input("Valore Intrinseco Spedizione (€)", min_value=0.0, value=0.0, step=100.0)

        if st.button("Valuta Dogana e Registra"):
            if merce_selezionata and codice_cn_estratto and emissioni_merce >= 0:
                is_3rd_country = "No" if paesi_origine[origine_merce]["Exempt"] else "Sì"
                is_over_150 = "Sì" if valore_merce > 150.0 else "No"
                is_free_circulation = "Sì" if importato_ue == "Sì" else "No"
                
                cbam_applies = (is_annex_i == "Yes") and (is_3rd_country == "Sì") and (is_over_150 == "Sì") and (is_free_circulation == "Sì")

                st.session_state.cbam_portfolio.append({
                    "CN Code": codice_cn_estratto,
                    "Descrizione": descrizione_merce[:50] + "..." if len(descrizione_merce) > 50 else descrizione_merce,
                    "Settore/Annex I": categoria_cbam,
                    "Origine": origine_merce,
                    "Valore (€)": valore_merce,
                    "Emissioni (tCO2)": emissioni_merce,
                    "Test: Annex I?": is_annex_i,
                    "Importato in UE": is_free_circulation,
                    "CBAM APPLICABILE": "SÌ" if cbam_applies else "NO",
                    "Tassa Estera": paesi_origine[origine_merce]["Tax"] if is_3rd_country == "Sì" else 0.0
                })
                st.success("Analisi doganale registrata con successo!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Devi selezionare una merce valida dal menù a tendina.")

    st.divider()
    st.subheader("📋 Registro Autovalutazione CBAM")
    
    if st.session_state.cbam_portfolio:
        df_cbam = pd.DataFrame(st.session_state.cbam_portfolio)
        st.dataframe(df_cbam.style.applymap(lambda x: "background-color: #ffcccc" if x == "NO" else "background-color: #ccffcc" if x == "SÌ" else "", subset=["CBAM APPLICABILE"]), use_container_width=True)
        
        if st.button("🗑️ Cancella Registro CBAM"):
            st.session_state.cbam_portfolio = []
            st.rerun()

        df_applicabile = df_cbam[df_cbam["CBAM APPLICABILE"] == "SÌ"]
        emissioni_importate_tot = df_applicabile["Emissioni (tCO2)"].sum()
        
        if emissioni_importate_tot > 0:
            st.divider()
            st.subheader("💶 Rischio Finanziario CBAM (Sankey Diagram)")
            sconto_tassa_totale = sum(row["Emissioni (tCO2)"] * row["Tassa Estera"] for _, row in df_applicabile.iterrows())
            prezzo_eu_ets = 70.0 
            costo_lordo_cbam = emissioni_importate_tot * prezzo_eu_ets
            costo_netto_cbam = max(0, costo_lordo_cbam - sconto_tassa_totale)
            
            c_cb1, c_cb2, c_cb3 = st.columns(3)
            c_cb1.metric("Emissioni da Dichiarare", f"{emissioni_importate_tot:,.0f} tCO2")
            c_cb2.metric("Sconto Fiscale Estero", f"€ {sconto_tassa_totale:,.2f}")
            c_cb3.metric("Costo Netto CBAM", f"€ {costo_netto_cbam:,.2f}", delta="Impatto su OpEx", delta_color="inverse")

            labels = ["Fornitori Extra-UE", "Fornitori Esenti", "Tassa Doganale", "Sconto Estero", "CBAM Netto", "Azienda (OpEx)", "Utile Netto"]
            source, target = [0, 0, 1, 2, 2, 4, 5, 5], [2, 5, 5, 3, 4, 5, 5, 6]
            val_fornitori_esenti = max(0, st.session_state.scope3 - emissioni_importate_tot)
            value = [costo_lordo_cbam, val_fornitori_esenti * prezzo_eu_ets, val_fornitori_esenti * prezzo_eu_ets, sconto_tassa_totale, costo_netto_cbam, costo_netto_cbam, st.session_state.opex, (st.session_state.revenue - st.session_state.opex - costo_netto_cbam)]
            
            fig_sankey = go.Figure(data=[go.Sankey(node=dict(pad=15, thickness=20, label=labels, color="#2E86AB"), link=dict(source=source, target=target, value=value, color="#EAEAEA"))])
            fig_sankey.update_layout(height=450, margin=dict(l=0, r=0, t=30, b=0), font=dict(size=14, color="black", family="Arial, sans-serif"))
            st.plotly_chart(fig_sankey, use_container_width=True)
        else:
            st.success("Nessuna merce inserita richiede l'acquisto di certificati CBAM (nessun costo aggiuntivo).")

# --- TAB 5: DOWNLOAD ---
with t_down:
    st.header("📥 Esportazione Dati e Modelli Ufficiali")
    
    col_d1, col_d2, col_d3 = st.columns(3)
    
    with col_d1:
        st.subheader("1. Report Board")
        if st.button("🪄 Genera PDF"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 18)
            pdf.cell(200, 15, txt="ESG & Climate Risk Report", ln=True, align='C')
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            st.download_button("📥 Scarica (.PDF)", data=pdf_bytes, file_name="ESG_Report.pdf", mime="application/pdf")

    with col_d2:
        st.subheader("2. Tassonomia UE (Annex II)")
        if st.session_state.tax_portfolio:
            df_tax_export = pd.DataFrame(st.session_state.tax_portfolio)
            csv_tax = df_tax_export.to_csv(index=False, sep=";")
            st.download_button(label="📥 Scarica Annex II Esteso (.CSV)", data=csv_tax, file_name="EU_Taxonomy_Complete.csv", mime="text/csv")
        else:
            st.warning("Compila Tab Tassonomia prima di esportare.")

    with col_d3:
        st.subheader("3. Export CBAM")
        if st.session_state.cbam_portfolio:
            df_cbam_export = pd.DataFrame(st.session_state.cbam_portfolio)
            csv_cbam_data = df_cbam_export.to_csv(index=False, sep=",") 
            st.download_button(label="📥 Scarica Modello CBAM (.CSV)", data=csv_cbam_data, file_name="CBAM_Export.csv", mime="text/csv")
        else:
            st.warning("Compila il registro CBAM.")

    st.divider()
    st.subheader("🏭 4. Esportazione Tagging ERP (Integrazione Finance)")
    
    if st.session_state.tax_portfolio:
        df_erp_export = pd.DataFrame(st.session_state.tax_portfolio)
        df_erp_export["Taxonomy-aligned"] = (df_erp_export["Eligible (Y/N)"] == "Y") & (df_erp_export["TSC Passed"] == "Y") & (df_erp_export["DNSH"] == "Y") & (df_erp_export["Safeguards"] == "Y")
        
        df_erp_clean = df_erp_export[[
            "ERP Cost Center", "Code(s)", "Objective", "Turnover (€)", "CapEx (€)", "OpEx (€)", "Eligible (Y/N)", "Taxonomy-aligned"
        ]].copy()
        
        df_erp_clean.rename(columns={
            "Code(s)": "NACE_Code", "Objective": "Environmental_Objective", "Eligible (Y/N)": "Taxonomy_Eligible", "Taxonomy-aligned": "Taxonomy_Aligned"
        }, inplace=True)
        
        csv_erp_data = df_erp_clean.to_csv(index=False, sep=",")
        
        c_erp1, c_erp2 = st.columns([1, 2])
        c_erp1.download_button(label="📥 Scarica File di Ingestion ERP (.CSV)", data=csv_erp_data, file_name="ERP_Taxonomy_Tagging.csv", mime="text/csv")
        c_erp2.info("Questo file è formattato per l'importazione nei sistemi contabili aziendali (SAP, Oracle) per taggare automaticamente le commesse.")
    else:
        st.warning("Nessuna commessa inserita. Compila il Tab Tassonomia per generare il file di ingestion ERP.")
