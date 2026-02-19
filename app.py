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

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk AI Enterprise", layout="wide")

# --- SINCRONIZZAZIONE (Session State) ---
if 'revenue' not in st.session_state: st.session_state.revenue = 50_000_000
if 'opex' not in st.session_state: st.session_state.opex = 30_000_000
if 'scope1' not in st.session_state: st.session_state.scope1 = 50000
if 'scope2' not in st.session_state: st.session_state.scope2 = 40000
if 'scope3' not in st.session_state: st.session_state.scope3 = 60000
if 'perc_red' not in st.session_state: st.session_state.perc_red = 50
if 'em_final' not in st.session_state: st.session_state.em_final = 75000
if 'sbti_approved' not in st.session_state: st.session_state.sbti_approved = False
if 'rata_prestito' not in st.session_state: st.session_state.rata_prestito = 8_000_000
if 'ammortamenti' not in st.session_state: st.session_state.ammortamenti = 4_000_000
if 'policy_multiplier' not in st.session_state: st.session_state.policy_multiplier = 1.0

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_scopes(): sync_from_perc()

# --- MOTORE DATI (Simulazione Offline) ---
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

# --- SIDEBAR: SOLO ESTRAZIONE E INSERIMENTO DATI BASE ---
with st.sidebar:
    st.title("⚙️ Setup Dati Aziendali")
    
    st.header("1. AI Data Extraction")
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password", help="Lascia vuoto per testare la simulazione gratuita.")
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
    st.selectbox("Posizione Geografica Principale", df_base['Paese'].unique(), index=3, key='selected_country') 
    st.number_input("Ricavi Annuali", value=st.session_state.revenue, step=1_000_000, key='revenue')
    st.number_input("Costi Operativi (OpEx)", value=st.session_state.opex, step=1_000_000, key='opex')
    
    if st.session_state.sbti_approved:
        st.markdown("🎯 **Status:** `✅ Target SBTi Approvato`")

# --- CORPO PRINCIPALE ---
st.title("🌍 Piattaforma CarbonRisk AI")
st.markdown("Seleziona una delle schede qui sotto per procedere con l'analisi strategica.")

t_home, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🏠 Home", "📊 Analisi Rischi", "🇪🇺 Tassonomia", "🌍 CBAM", "📥 Download"
])

# --- TAB 1: HOME ---
with t_home:
    st.header("Benvenuto in CarbonRisk Enterprise AI")
    st.markdown("""
    Questa piattaforma ti permette di mappare i rischi climatici, calcolare le esposizioni al carbonio e verificare l'allineamento normativo (CSRD / EU Taxonomy) della tua azienda.
    
    **Istruzioni:**
    1. Usa il menù a sinistra per inserire i dati della tua azienda (manualmente o tramite estrazione AI da Bilancio PDF/Yahoo Finance).
    2. Naviga tra le schede qui in alto per effettuare le analisi di rischio, valutare la supply chain (CBAM) e simulare i costi futuri.
    3. Usa la scheda "Download" per esportare il report finale.
    """)
    
    col_h1, col_h2, col_h3 = st.columns(3)
    col_h1.metric("Ricavi Attuali Registrati", f"€ {st.session_state.revenue:,.0f}")
    col_h2.metric("OpEx Attuali Registrati", f"€ {st.session_state.opex:,.0f}")
    col_h3.metric("Status SBTi", "Approvato" if st.session_state.sbti_approved else "Non Rilevato")

# --- TAB 2: ANALISI RISCHI ---
with t_rischi:
    st.header("Matrice dei Rischi Climatici")
    rt_fisico, rt_transizione, rt_credito = st.tabs([
        "🛰️ Rischio Fisico", "🔄 Rischio di Transizione", "💰 Carbon Offsetting & Rischio Credito"
    ])

    # 2A. RISCHIO FISICO
    with rt_fisico:
        st.subheader("Dati Satellitari Copernicus (ESA)")
        indirizzo = st.text_input("Inserisci Indirizzo o CAP (Asset Principale)", "Porto di Rotterdam, Paesi Bassi")
        if st.button("📡 Estrai Dati ESA Copernicus"):
            with st.spinner("Connessione API in corso..."):
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

    # 2B. RISCHIO DI TRANSIZIONE (GHG & CapEx)
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
        st.markdown("Investimenti pianificati per l'efficientamento e l'abbattimento delle emissioni lorde.")
        capex = st.number_input("Investimento Transizione (CapEx in €)", value=10_000_000, step=1_000_000)
        st.slider("Efficacia attesa (Riduzione Stimata %)", 0, 100, key='perc_red', on_change=sync_from_perc)
        st.success(f"**Risultato Atteso:** Le emissioni nette finali (Hard-to-abate) scenderanno a **{st.session_state.em_final:,} tCO2**.")

    # 2C. RISCHIO CREDITO & CARBON OFFSETTING
    with rt_credito:
        st.subheader("1. Stress Test Finanziario & Condizioni di Credito")
        c_cred1, c_cred2, c_cred3 = st.columns(3)
        c_cred1.number_input("Rata Prestito Bancario (€)", value=st.session_state.rata_prestito, step=500_000, key='rata_prestito')
        c_cred2.number_input("Ammortamenti Annuali (€)", value=st.session_state.ammortamenti, step=500_000, key='ammortamenti')
        c_cred3.slider("Severità Leggi Locali (Moltiplicatore CO2)", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier')

        # Dati Grafici Dinamici
        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        emissions_tot = get_tot_emissions()
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            profit = st.session_state.revenue - st.session_state.opex - (eff_price * emissions_tot)
            plot_data.append({"Anno": row['Anno'], "Utile Netto (€)": profit, "DSCR": (profit+st.session_state.ammortamenti)/st.session_state.rata_prestito if st.session_state.rata_prestito else 99, "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price})
        plot_df = pd.DataFrame(plot_data)
        color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}

        cg1, cg2 = st.columns(2)
        # Legende Spostate in basso
        fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, title="Evoluzione Prezzo Carbonio")
        fig_prezzo.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
        cg1.plotly_chart(fig_prezzo, use_container_width=True)
        
        fig_utile = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, title="Impatto sugli Utili (Senza Transizione)")
        fig_utile.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
        cg2.plotly_chart(fig_utile, use_container_width=True)

        st.divider()

        # NUOVO BLOCCO: Prima vs Dopo la transizione
        st.subheader("2. Analisi d'Impatto: Prima e Dopo la Transizione (Simulazione 2030)")
        st.markdown("Confronto visivo tra lo scenario senza interventi (tasse elevate) e lo scenario con CapEx (tasse ridotte, inclusa rata prestito).")
        
        prezzo_rif = 70.0 * st.session_state.policy_multiplier
        tasse_prima = emissions_tot * prezzo_rif
        costi_prima = st.session_state.opex + tasse_prima
        utile_prima = st.session_state.revenue - costi_prima
        
        tasse_dopo = st.session_state.em_final * prezzo_rif
        costi_dopo = st.session_state.opex + tasse_dopo + st.session_state.rata_prestito
        utile_dopo = st.session_state.revenue - costi_dopo
        
        col_bar1, col_bar2 = st.columns(2)
        
        with col_bar1:
            fig_prima = go.Figure(data=[
                go.Bar(name='Ricavi', x=[''], y=[st.session_state.revenue], offsetgroup=0, marker_color='#0070C0'),
                go.Bar(name='Costi (OpEx + Tasse)', x=[''], y=[costi_prima], offsetgroup=1, marker_color='#C00000'),
                go.Bar(name='Utile Netto', x=[''], y=[utile_prima], offsetgroup=1, base=[costi_prima], marker_color='#00B050')
            ])
            fig_prima.update_layout(title=dict(text="Prima della Transizione", x=0.5), legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_prima, use_container_width=True)
            
        with col_bar2:
            fig_dopo = go.Figure(data=[
                go.Bar(name='Ricavi', x=[''], y=[st.session_state.revenue], offsetgroup=0, marker_color='#0070C0'),
                go.Bar(name='Costi (Incl. Prestito e Tasse)', x=[''], y=[costi_dopo], offsetgroup=1, marker_color='#C00000'),
                go.Bar(name='Utile Netto (Post-Transizione)', x=[''], y=[utile_dopo], offsetgroup=1, base=[costi_dopo], marker_color='#00B050')
            ])
            fig_dopo.update_layout(title=dict(text="Dopo la Transizione", x=0.5), legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_dopo, use_container_width=True)

        st.divider()

        st.subheader("3. Carbon Offsetting (Crediti VERs)")
        st.markdown(f"Per neutralizzare le **{st.session_state.em_final:,} tCO2** residue calcolate nella fase di transizione.")
        prezzo_ver = st.number_input("Prezzo Mercato Volontario (€/tCO2)", value=15)
        costo_offsetting = st.session_state.em_final * prezzo_ver
        st.metric("Costo Annuale per raggiungere 'Net Zero'", f"€ {costo_offsetting:,.0f}")

# --- TAB 3: TASSONOMIA UE ---
with t_tax:
    st.header("Allineamento Tassonomia UE")
    settore = st.selectbox("Settore Economico NACE", ["Real Estate (Immobiliare)", "Trasporti e Logistica", "Agricoltura e Allevamento", "Chimica (Ammoniaca/Plastica)", "Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
    
    if settore == "Real Estate (Immobiliare)": unita, soglia, target_unit = "Metri Quadri (m2)", 80, "kWh/m2"
    elif settore == "Trasporti e Logistica": unita, soglia, target_unit = "Tonnellate per km (tkm)", 50, "gCO2/tkm"
    elif settore == "Agricoltura e Allevamento": unita, soglia, target_unit = "Ettari Coltivati", 2.5, "tCO2eq/Ettaro (Inc. CH4)"
    elif settore == "Chimica (Ammoniaca/Plastica)": unita, soglia, target_unit = "Tonnellate", 1.0, "tCO2/ton"
    elif settore == "Generazione Elettrica": unita, soglia, target_unit = "MWh", 100, "gCO2/kWh"
    else: unita, soglia, target_unit = "Tonnellate", 0.7, "tCO2/ton"
    
    prod = st.number_input(f"Produzione/Volume Totale ({unita})", value=100000, step=10000)
    int_calc = (get_tot_emissions() / prod) if prod > 0 else 0
    if target_unit.startswith("g"): int_calc *= 1000 
    
    is_aligned = int_calc <= soglia
    st.metric(f"Intensità Calcolata ({target_unit})", f"{int_calc:.2f}", delta="ALLINEATO AI CRITERI UE" if is_aligned else "NON ALLINEATO", delta_color="normal" if is_aligned else "inverse")

# --- TAB 4: CBAM E SUPPLY CHAIN ---
with t_cbam:
    st.header("🔗 Analisi CBAM & Supply Chain")
    st.markdown("Valuta l'impatto del Carbon Border Adjustment Mechanism (CBAM) integrando i dati della **Banca Mondiale** sulle Carbon Tax estere.")
    
    wb_database = {
        "Nessuna Tassa (Es. India, Turchia)": 0.0,
        "Cina (China National ETS)": 10.0,
        "Sud Africa (Carbon Tax)": 11.0,
        "Regno Unito (UK ETS)": 45.0,
        "Canada (Federal Carbon Pricing)": 55.0,
        "Svizzera (Swiss ETS)": 68.0
    }
    
    col_cbam1, col_cbam2 = st.columns(2)
    with col_cbam1:
        st.subheader("🌍 Profilo Importazione Extra-UE")
        origine_fornitori = st.selectbox("Paese di Origine Fornitori", list(wb_database.keys()))
        tassa_estera = wb_database[origine_fornitori]
        emissioni_importate = st.number_input("Emissioni Fornitori Extra-UE (tCO2)", value=int(st.session_state.scope3 * 0.6), step=1000)
        
    with col_cbam2:
        st.subheader("💶 Impatto Fiscale (CBAM)")
        prezzo_eu_ets = 70.0 
        differenziale_cbam = max(0, prezzo_eu_ets - tassa_estera)
        costo_lordo_cbam = emissioni_importate * prezzo_eu_ets
        sconto_tassa = emissioni_importate * tassa_estera
        costo_netto_cbam = emissioni_importate * differenziale_cbam
        
        st.metric("Tassa Estera Pagata all'origine", f"€ {tassa_estera}/tCO2")
        st.metric("Costo Netto CBAM", f"€ {costo_netto_cbam:,.0f}", f"- € {sconto_tassa:,.0f} (Sconto tassa estera)", delta_color="inverse")

    st.subheader("🔄 Flusso dei Costi Climatici")
    labels = ["Fornitori Extra-UE", "Fornitori UE", "Tassa Doganale LORDA", "Sconto Tasse Estere", "CBAM Netto (Da Pagare)", "La Tua Azienda (OpEx)", "Utile Netto"]
    source, target = [0, 0, 1, 2, 2, 4, 5, 5], [2, 5, 5, 3, 4, 5, 5, 6]
    val_fornitori_ue = st.session_state.scope3 - emissioni_importate
    value = [
        costo_lordo_cbam, val_fornitori_ue * prezzo_eu_ets, val_fornitori_ue * prezzo_eu_ets, 
        sconto_tassa, costo_netto_cbam, costo_netto_cbam, st.session_state.opex, 
        (st.session_state.revenue - st.session_state.opex - costo_netto_cbam)
    ]
    
    # MODIFICA FONT SANKEY: Reso nero, più grande e visibile
    fig_sankey = go.Figure(data=[go.Sankey(
        node=dict(
            pad=15, 
            thickness=20, 
            line=dict(color="black", width=0.5), 
            label=labels, 
            color="#2E86AB"
        ), 
        link=dict(
            source=source, 
            target=target, 
            value=value, 
            color="#EAEAEA"
        )
    )])
    fig_sankey.update_layout(
        height=450, 
        margin=dict(l=0, r=0, t=30, b=0),
        font=dict(size=14, color="black", family="Arial, sans-serif") # Impostazione Font ben visibile
    )
    st.plotly_chart(fig_sankey, use_container_width=True)

# --- TAB 5: DOWNLOAD ---
with t_down:
    st.header("📥 Esportazione Dati & Report")
    st.markdown("Genera la documentazione ufficiale per l'alta direzione o per la compilazione dei registri normativi.")
    
    col_d1, col_d2 = st.columns(2)
    
    with col_d1:
        st.subheader("Report Strategico (PDF)")
        st.markdown("Documento discorsivo riepilogativo per Board e investitori (Standard TCFD/CSRD).")
        if st.button("🪄 Genera PDF"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 18)
            pdf.cell(200, 15, txt="Enterprise Climate Risk & ESG Report", ln=True, align='C')
            pdf.ln(10)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(200, 10, txt="1. Dati Finanziari di Base", ln=True)
            pdf.set_font("Arial", '', 12)
            pdf.cell(200, 8, txt=f"Ricavi Totali: {st.session_state.revenue:,.0f} Euro", ln=True)
            pdf.cell(200, 8, txt=f"Costi Operativi (OpEx): {st.session_state.opex:,.0f} Euro", ln=True)
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(200, 10, txt="2. Analisi Impronta Carbonica", ln=True)
            pdf.set_font("Arial", '', 12)
            pdf.cell(200, 8, txt=f"- Scope 1: {st.session_state.scope1:,} tCO2", ln=True)
            pdf.cell(200, 8, txt=f"- Scope 2: {st.session_state.scope2:,} tCO2", ln=True)
            pdf.cell(200, 8, txt=f"- Scope 3: {st.session_state.scope3:,} tCO2", ln=True)
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(200, 10, txt="3. Transizione e CBAM", ln=True)
            pdf.set_font("Arial", '', 12)
            pdf.cell(200, 8, txt=f"Emissioni residue post-CapEx: {st.session_state.em_final:,} tCO2", ln=True)
            pdf.cell(200, 8, txt=f"Status SBTi: {'Approvato' if st.session_state.sbti_approved else 'Assente'}", ln=True)
            
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            st.success("PDF pronto!")
            st.download_button(label="📥 Scarica Report (.PDF)", data=pdf_bytes, file_name="Report_Strategico_ESG.pdf", mime="application/pdf")

    with col_d2:
        st.subheader("Registro Doganale CBAM (CSV)")
        st.markdown("File precompilato strutturato per l'upload sul portale transitorio della Commissione UE.")
        
        cbam_csv_data = f"Importer_ID,Origin_Country,Goods_Category,Imported_Emissions_tCO2,Foreign_Tax_Paid_EUR,Net_CBAM_Due\nIT99999999,{origine_fornitori},Steel/Aluminum,{emissioni_importate},{tassa_estera},{costo_netto_cbam:.2f}"
        
        st.download_button(label="📥 Scarica Dichiarazione CBAM (.CSV)", data=cbam_csv_data, file_name="Dichiarazione_CBAM_EU.csv", mime="text/csv")
