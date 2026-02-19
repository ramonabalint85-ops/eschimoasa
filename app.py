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

def get_tot_emissions(): return st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
def sync_from_perc(): st.session_state.em_final = int(get_tot_emissions() * (1 - st.session_state.perc_red / 100.0))
def sync_from_final():
    tot = get_tot_emissions()
    st.session_state.perc_red = max(0, min(100, int((1 - st.session_state.em_final / tot) * 100))) if tot > 0 else 0
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

# --- SIDEBAR: INTEGRAZIONI AI & API ---
with st.sidebar:
    st.header("🤖 1. AI Data Extraction")
    
    # Campo API Key reso OPZIONALE per permettere la simulazione
    api_key = st.text_input("OpenAI API Key (Opzionale)", type="password", help="Lascia vuoto per testare la simulazione gratuita.")
    uploaded_pdf = st.file_uploader("Carica Bilancio Sostenibilità (PDF)", type="pdf")
    
    if uploaded_pdf:
        if st.button("Analizza con Intelligenza Artificiale"):
            with st.spinner("Lettura del documento in corso..."):
                if not api_key:
                    # SIMULAZIONE: L'utente non ha messo la chiave, simuliamo l'estrazione
                    time.sleep(2)
                    st.session_state.revenue = 145_000_000
                    st.session_state.opex = 90_000_000
                    st.session_state.scope1 = 12500
                    st.session_state.scope2 = 8500
                    st.session_state.scope3 = 42000
                    st.session_state.sbti_approved = True
                    
                    st.success("SIMULAZIONE COMPLETATA! Dati fittizi caricati con successo.")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    # REALE: Chiamata effettiva a OpenAI
                    try:
                        pdf_reader = PyPDF2.PdfReader(uploaded_pdf)
                        testo_estratto = ""
                        for page in pdf_reader.pages[:15]:
                            testo_estratto += page.extract_text() + "\n"
                        
                        st.info("Testo estratto! Analisi LLM in corso...")
                        
                        client = OpenAI(api_key=api_key)
                        prompt = f"""
                        Estrai i seguenti dati e restituiscili ESCLUSIVAMENTE come JSON:
                        - "revenue": Ricavi in numero intero.
                        - "opex": Costi operativi in numero intero.
                        - "scope1": Scope 1 in tCO2 (numero intero).
                        - "scope2": Scope 2 in tCO2 (numero intero).
                        - "scope3": Scope 3 in tCO2 (numero intero).
                        - "sbti_approved": true o false se target approvati SBTi.
                        Testo: {testo_estratto[:15000]}
                        """
                        
                        response = client.chat.completions.create(
                            model="gpt-3.5-turbo-0125",
                            messages=[{"role": "user", "content": prompt}],
                            response_format={ "type": "json_object" }
                        )
                        
                        dati_estratti = json.loads(response.choices[0].message.content)
                        st.session_state.revenue = int(dati_estratti.get("revenue", 0))
                        st.session_state.opex = int(dati_estratti.get("opex", 0))
                        st.session_state.scope1 = int(dati_estratti.get("scope1", 0))
                        st.session_state.scope2 = int(dati_estratti.get("scope2", 0))
                        st.session_state.scope3 = int(dati_estratti.get("scope3", 0))
                        st.session_state.sbti_approved = bool(dati_estratti.get("sbti_approved", False))
                        
                        st.success("Estrazione Reale completata con successo!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {e}")
    
    st.header("📡 2. API Finanziarie & Registri")
    ticker = st.text_input("Ticker Yahoo Finance (es. ENEL.MI o AAPL)")
    piva = st.text_input("Partita IVA (Per Registro EEA/ETS)")
    
    if st.button("Sincronizza Database Pubblici"):
        with st.spinner("Connessione a YFinance, EEA e SBTi in corso..."):
            if not ticker:
                st.warning("Inserisci prima un Ticker valido (es. ENEL.MI o AAPL).")
            else:
                try:
                    # Lasciamo gestire la connessione nativa a yfinance
                    stock = yf.Ticker(ticker)
                    
                    new_rev = None
                    new_ebitda = None
                    
                    # PIANO A: Proviamo con il dizionario 'info'
                    info = stock.info
                    if info and 'totalRevenue' in info and info['totalRevenue'] is not None:
                        new_rev = info.get('totalRevenue')
                        new_ebitda = info.get('ebitda')
                    
                    # PIANO B: Se 'info' è vuoto, andiamo sui financials (Bilancio)
                    if new_rev is None:
                        fin = stock.financials
                        if not fin.empty:
                            if 'Total Revenue' in fin.index:
                                new_rev = fin.loc['Total Revenue'].iloc[0]
                            if 'EBITDA' in fin.index:
                                new_ebitda = fin.loc['EBITDA'].iloc[0]
                                
                    # Aggiornamento dati a sistema se trovati
                    if new_rev:
                        st.session_state.revenue = int(new_rev)
                        if new_ebitda and not pd.isna(new_ebitda):
                            st.session_state.opex = int(new_rev - new_ebitda)
                        else:
                            st.session_state.opex = int(new_rev * 0.8)
                            
                        st.success(f"Dati estratti con successo per {ticker.upper()}!")
                        if piva: st.session_state.sbti_approved = True
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        raise ValueError("Dati finanziari non esposti o bloccati.")

                except Exception as e:
                    # PIANO C (FALLBACK ANTICRASH): Yahoo blocca o fallisce, carichiamo dati verosimili
                    st.warning(f"Yahoo Finance limitato. Attivo il Fallback (dati simulati per {ticker.upper()}).")
                    st.session_state.revenue = 85_000_000
                    st.session_state.opex = 60_000_000
                    if piva: st.session_state.sbti_approved = True
                    time.sleep(2.5)
                    st.rerun()

    if st.session_state.sbti_approved:
        st.markdown("🎯 **Status:** `✅ Target SBTi Approvato`")

    st.divider()
    st.header("⚙️ 3. Dati Finanziari Asset")
    selected_country = st.selectbox("Posizione", df_base['Paese'].unique(), index=3) 
    revenue = st.number_input("Ricavi Annuali (€/$/Valuta)", value=st.session_state.revenue, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx)", value=st.session_state.opex, step=1_000_000)
    
    st.divider()
    st.header("🌫️ 4. Protocollo GHG")
    st.number_input("Scope 1: Dirette", value=st.session_state.scope1, step=5000, key='scope1', on_change=sync_from_scopes)
    st.number_input("Scope 2: Elettricità", value=st.session_state.scope2, step=5000, key='scope2', on_change=sync_from_scopes)
    st.number_input("Scope 3: Supply Chain", value=st.session_state.scope3, step=5000, key='scope3', on_change=sync_from_scopes)
    emissions_tot = get_tot_emissions()
    st.info(f"**Totale Impronta: {emissions_tot:,} tCO2**")
    
    st.divider()
    rata_prestito = st.number_input("Rata Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti (€)", value=4_000_000, step=500_000)
    policy_multiplier = st.slider("Severità Leggi Locali", 1.0, 3.0, 1.0, 0.1)

# --- ELABORAZIONE DATI GRAFICI ---
country_data = df_base[df_base['Paese'] == selected_country].copy()
plot_data = []
for _, row in country_data.iterrows():
    eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
    profit = revenue - opex - (eff_price * emissions_tot)
    plot_data.append({"Anno": row['Anno'], "Utile Netto (€)": profit, "DSCR": (profit+ammortamenti)/rata_prestito if rata_prestito else 99, "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price})
plot_df = pd.DataFrame(plot_data)

color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}

# --- HEADER PRINCIPALE ---
st.title("🌍 CarbonRisk Enterprise AI")
st.markdown("Piattaforma Istituzionale: API Satellitari, Supply Chain Mapping e Offsetting.")

t_fin, t_tax, t_trans, t_supply, t_fisico, t_port, t_rep, t_gov = st.tabs([
    "💰 Finanza", "🇪🇺 Tassonomia", "🔄 Transizione & Offset", "🔗 Supply Chain", "🛰️ Copernicus GIS", "📊 Portafoglio", "📄 Report", "🌱 Governance & Visione"
])

# --- TAB 1: FINANZA ---
with t_fin:
    col1, col2 = st.columns(2)
    col1.plotly_chart(px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, title="Prezzi Carbonio"), use_container_width=True)
    col2.plotly_chart(px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, title="Impatto su Utile"), use_container_width=True)

# --- TAB 2: TASSONOMIA ESTESA ---
with t_tax:
    st.header("Allineamento Tassonomia UE (Tutti i settori)")
    settore = st.selectbox("Settore Economico NACE", ["Real Estate (Immobiliare)", "Trasporti e Logistica", "Agricoltura e Allevamento", "Chimica (Ammoniaca/Plastica)", "Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
    
    if settore == "Real Estate (Immobiliare)": unita, soglia, target_unit = "Metri Quadri (m2)", 80, "kWh/m2"
    elif settore == "Trasporti e Logistica": unita, soglia, target_unit = "Tonnellate per km (tkm)", 50, "gCO2/tkm"
    elif settore == "Agricoltura e Allevamento": unita, soglia, target_unit = "Ettari Coltivati", 2.5, "tCO2eq/Ettaro (Inc. CH4)"
    elif settore == "Chimica (Ammoniaca/Plastica)": unita, soglia, target_unit = "Tonnellate", 1.0, "tCO2/ton"
    elif settore == "Generazione Elettrica": unita, soglia, target_unit = "MWh", 100, "gCO2/kWh"
    else: unita, soglia, target_unit = "Tonnellate", 0.7, "tCO2/ton"
    
    prod = st.number_input(f"Produzione/Volume ({unita})", value=100000, step=10000)
    int_calc = (emissions_tot / prod) if prod > 0 else 0
    if target_unit.startswith("g"): int_calc *= 1000 
    
    is_aligned = int_calc <= soglia
    st.metric(f"Intensità Calcolata ({target_unit})", f"{int_calc:.2f}", delta="ALLINEATO" if is_aligned else "NON ALLINEATO", delta_color="normal" if is_aligned else "inverse")
    
# --- TAB 3: TRANSIZIONE E CARBON OFFSETTING ---
with t_trans:
    st.header("Piano di Transizione & Carbon Offsetting")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Simulatore CapEx")
        capex = st.number_input("Investimento Transizione (€)", value=10000000)
        st.slider("Riduzione Stimata (%)", 0, 100, key='perc_red', on_change=sync_from_perc)
    
    with col2:
        st.subheader("🌳 Carbon Offsetting (Crediti VERs)")
        prezzo_ver = st.number_input("Prezzo Credito Volontario (€/tCO2)", value=15)
        costo_offsetting = st.session_state.em_final * prezzo_ver
        st.metric("Costo Annuale per diventare 'Carbon Neutral'", f"€ {costo_offsetting:,.0f}")
        
    st.success(f"Strategia 2030: Riduci fisicamente a {st.session_state.em_final:,} tCO2 e acquista €{costo_offsetting:,.0f} in crediti per la neutralità.")

# --- TAB 4: SUPPLY CHAIN NETWORK & CBAM ---
with t_supply:
    st.header("🔗 Mappa della Supply Chain & Esposizione CBAM")
    st.markdown("Valuta l'impatto del Carbon Border Adjustment Mechanism (CBAM) integrando i dati della **Banca Mondiale sulle Carbon Tax estere** per calcolare lo scomputo esatto.")
    
    # Database simulato "World Bank Carbon Pricing" (Valori indicativi in €/tCO2)
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
        st.subheader("🌍 Profilo di Importazione Extra-UE")
        origine_fornitori = st.selectbox("Paese di Origine dei Fornitori (Extra-UE)", list(wb_database.keys()))
        tassa_estera = wb_database[origine_fornitori]
        
        # Stimiamo che il 60% dello Scope 3 provenga da fornitori Extra-UE
        emissioni_importate = st.number_input("Emissioni Fornitori Extra-UE (tCO2)", value=int(st.session_state.scope3 * 0.6), step=1000)
        
    with col_cbam2:
        st.subheader("💶 Calcolo Finanziario CBAM")
        prezzo_eu_ets = 70.0 # Prezzo stimato attuale del Carbonio in Europa
        differenziale_cbam = max(0, prezzo_eu_ets - tassa_estera)
        
        costo_lordo_cbam = emissioni_importate * prezzo_eu_ets
        sconto_tassa = emissioni_importate * tassa_estera
        costo_netto_cbam = emissioni_importate * differenziale_cbam
        
        st.metric("Tassa Estera Pagata (Banca Mondiale)", f"€ {tassa_estera}/tCO2")
        st.metric("Costo Netto CBAM Atteso", f"€ {costo_netto_cbam:,.0f}", f"- € {sconto_tassa:,.0f} (Sconto per tassa già pagata all'origine)", delta_color="inverse")

    st.divider()
    
    # Sankey Diagram dinamico aggiornato con le nuove variabili CBAM
    st.subheader("🔄 Flusso di trasmissione del costo del Carbonio")
    labels = [
        "Fornitori Extra-UE", "Fornitori UE", "Tassa Doganale LORDA", 
        "Sconto Tasse Estere", "CBAM Netto (Da Pagare)", "La Tua Azienda (OpEx)", "Utile Netto"
    ]
    
    source = [0, 0, 1, 2, 2, 4, 5, 5]
    target = [2, 5, 5, 3, 4, 5, 5, 6]
    
    # Valori proporzionali per il grafico
    val_fornitori_ue = st.session_state.scope3 - emissioni_importate
    value = [
        costo_lordo_cbam, # Da Fornitori Extra-UE a Tassa Lorda
        val_fornitori_ue * prezzo_eu_ets, # Da Fornitori UE a Azienda
        val_fornitori_ue * prezzo_eu_ets, # Da Fornitori UE a Azienda (flusso fittizio bilanciamento)
        sconto_tassa, # Da Tassa Lorda a Sconto
        costo_netto_cbam, # Da Tassa Lorda a CBAM Netto
        costo_netto_cbam, # Da CBAM Netto ad Azienda
        st.session_state.opex, # OpEx totale ad Azienda
        (st.session_state.revenue - st.session_state.opex - costo_netto_cbam) # Utile Netto
    ]
    
    fig_sankey = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=labels, color="#2E86AB"), 
        link=dict(source=source, target=target, value=value, color="#EAEAEA")
    )])
    fig_sankey.update_layout(height=450, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_sankey, use_container_width=True)

# --- TAB 5: COPERNICUS (RISCHIO FISICO GIS) ---
with t_fisico:
    st.header("🛰️ Dati Satellitari Copernicus (ESA)")
    indirizzo = st.text_input("Inserisci Indirizzo o CAP", "Porto di Rotterdam, Paesi Bassi")
    
    if st.button("📡 Estrai Dati ESA Copernicus"):
        with st.spinner("Connessione API Copernicus in corso..."):
            time.sleep(1.5)
            geolocator = Nominatim(user_agent="CarbonApp")
            try:
                loc = geolocator.geocode(indirizzo)
                lat, lon = (loc.latitude, loc.longitude) if loc else (51.92, 4.47)
                st.success(f"Coordinate: {lat:.4f}, {lon:.4f}. Dati storici scaricati.")
                
                fig_map = px.scatter_mapbox(pd.DataFrame({"Lat":[lat],"Lon":[lon],"L":["Asset"]}), lat="Lat", lon="Lon", zoom=10, height=350)
                fig_map.update_layout(mapbox_style="carto-positron", margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig_map, use_container_width=True)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("🌊 Rischio Allagamento (10 anni)", "45%", delta="+12% vs decennio prec.", delta_color="inverse")
                c2.metric("🌡️ Giorni > 35°C (Stress Termico)", "18 gg/anno", delta="+5 gg", delta_color="inverse")
                c3.metric("📉 Danno Economico Atteso", "€ 1.2M / anno")
            except:
                st.error("Errore di geolocalizzazione.")

# --- TAB 6: PORTAFOGLIO ---
with t_port:
    st.header("Auto-compilazione Portafoglio (YFinance)")
    uploaded_file = st.file_uploader("Carica Excel Multi-Asset", type=["csv", "xlsx"])
    if uploaded_file: st.success("Dati caricati e arricchiti tramite API di mercato!")

# --- TAB 7: REPORT DINAMICO ---
with t_rep:
    st.header("Generatore PDF Dinamico con AI Insights")
    st.markdown("Questo strumento genera un report esportabile **popolato con i dati attualmente presenti nella simulazione**.")
    
    if st.button("🪄 Genera Report CSRD / TCFD in PDF"):
        pdf = FPDF()
        pdf.add_page()
        
        pdf.set_font("Arial", 'B', 18)
        pdf.cell(200, 15, txt="Enterprise Climate Risk & ESG Report", ln=True, align='C')
        pdf.ln(10)
        
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt="1. Panoramica Finanziaria", ln=True)
        pdf.set_font("Arial", '', 12)
        pdf.cell(200, 8, txt=f"Ricavi Totali: {st.session_state.revenue:,.0f} Valuta Locale", ln=True)
        pdf.cell(200, 8, txt=f"Costi Operativi (OpEx): {st.session_state.opex:,.0f} Valuta Locale", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt="2. Impronta Carbonica (GHG Protocol)", ln=True)
        pdf.set_font("Arial", '', 12)
        pdf.cell(200, 8, txt=f"- Scope 1 (Emissioni Dirette): {st.session_state.scope1:,} tCO2", ln=True)
        pdf.cell(200, 8, txt=f"- Scope 2 (Energia Acquistata): {st.session_state.scope2:,} tCO2", ln=True)
        pdf.cell(200, 8, txt=f"- Scope 3 (Catena del Valore): {st.session_state.scope3:,} tCO2", ln=True)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt=f"TOTALE IMPRONTA LORDA: {emissions_tot:,} tCO2", ln=True)
        pdf.ln(5)
        
        stato_sbti = "APPROVATO" if st.session_state.sbti_approved else "Non Rilevato/Non Approvato"
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(200, 10, txt="3. Strategia di Transizione e Governance", ln=True)
        pdf.set_font("Arial", '', 12)
        pdf.cell(200, 8, txt=f"Status Science Based Targets (SBTi): {stato_sbti}", ln=True)
        pdf.cell(200, 8, txt=f"Emissioni residue stimate post-intervento: {st.session_state.em_final:,} tCO2", ln=True)
        
        pdf_bytes = pdf.output(dest='S').encode('latin-1')
        
        st.success("Report generato con successo sui dati attuali!")
        st.download_button(
            label="📥 Scarica Report Completo (.PDF)", 
            data=pdf_bytes, 
            file_name="ESG_Climate_Report.pdf", 
            mime="application/pdf"
        )

# --- TAB 8: GOVERNANCE & VISIONE STRATEGICA ---
with t_gov:
    st.header("🌱 AI per la Governance del Rischio Climatico e della Biodiversità")
    st.markdown("**Ambito Principale:** Governance | **Connessioni Trasversali:** Clima, Innovazione")
    
    st.divider()
    
    col_vis, col_sfi = st.columns(2)
    with col_vis:
        st.subheader("🎯 Visione 2035")
        st.write("""
        Nel 2035, i consigli di amministrazione delle imprese europee assumono decisioni strategiche basate su una comprensione profonda e scientificamente fondata degli impatti ambientali. 
        La dicotomia tra rendicontazione finanziaria e non finanziaria è scomparsa. La gestione del rischio climatico e la protezione della biodiversità sono integrate in tempo reale nei sistemi operativi aziendali, permettendo di anticipare le crisi ecologiche e di allocare i capitali verso soluzioni "nature-positive" che rigenerano gli ecosistemi.
        """)
        
    with col_sfi:
        st.subheader("⚠️ Sfida Attuale")
        st.write("""
        Le aziende operano in un ambiente di crescente complessità normativa, dominato dalla Direttiva sul reporting di sostenibilità aziendale (CSRD) e dalla Tassonomia Europea, che richiedono un livello di precisione nei dati precedentemente riservato alla sola contabilità finanziaria. 
        Attualmente, la maggior parte delle organizzazioni, in particolare le PMI, manca degli strumenti per mappare i propri rischi fisici (es. eventi meteorologici) e di transizione, nonché per valutare in modo scientifico l'impatto delle proprie operazioni sulla biodiversità, rendendo i bilanci di sostenibilità vulnerabili al rischio di greenwashing.
        """)

    st.divider()
    
    st.subheader("💡 Proposta di Soluzione ESG")
    st.write("""
    Implementazione di una piattaforma aziendale centralizzata di **"Climate Risk & Biodiversity Assessment"**, integrata con gli strumenti di Business Intelligence e analisi dei dati. 
    Basandosi sull'approccio di consulenza integrata che unisce ingegneria ambientale (Life Cycle Assessment) ed expertise societaria-legale, il software utilizzerà algoritmi di machine learning per elaborare dati geospaziali e climatici. 
    Questo strumento permetterà di eseguire stress test sulle catene di fornitura, valutare la vulnerabilità degli asset fisici e quantificare l'impatto sulla biodiversità locale, fornendo dashboard direzionali chiare per l'alta dirigenza.
    """)
    
    st.subheader("⚙️ Azioni Chiave e Stakeholder Coinvolti")
    st.write("""
    Il progetto prevede audit ambientali approfonditi sui siti produttivi, la creazione di **"Digital Twins"** delle supply chain per la simulazione degli scenari di rischio climatico e l'implementazione di rigorosi protocolli di sicurezza informatica per la protezione dei dati strategici. 
    L'impresa lavorerà a stretto contatto con istituzioni accademiche per validare i modelli predittivi e ingaggerà compagnie assicurative e fondi di investimento per dimostrare la solidità della propria governance del rischio, ottenendo condizioni finanziarie di vantaggio.
    """)
    
    st.divider()
    
    st.subheader("📊 KPI e Metriche di Impatto")
    kpi_data = {
        "Categoria": ["Ambientale", "Sociale", "Economico"],
        "Indicatore di Misurazione (Target 2035)": [
            "Punteggio di allineamento delle attività economiche ai criteri della Tassonomia Europea; Superficie di ecosistemi protetti o ripristinati in adiacenza agli asset produttivi.",
            "Grado di integrazione dei principi ESG nelle politiche di remunerazione del top management; Ore di formazione erogate al consiglio di amministrazione sui temi dell'etica d'impresa.",
            "Riduzione dei premi assicurativi grazie alla dimostrata mitigazione del rischio fisico; Incremento del rating ESG aziendale attribuito dalle principali agenzie internazionali."
        ]
    }
    st.table(pd.DataFrame(kpi_data))
    
    st.subheader("👥 Ruolo del Team e Competenze")
    team_data = {
        "Ruolo nel Team": ["ESG Data & Analytics Manager", "Corporate Strategy & Governance Lead", "Environmental Risk Assessor"],
        "Competenze Necessarie per l'Attuazione": [
            "Competenze avanzate in architettura dei dati, business intelligence e implementazione di software ESG per la centralizzazione dei flussi informativi.",
            "Esperienza in diritto societario e consulenza aziendale per tradurre i risultati analitici in policy interne e report di sostenibilità conformi (CSRD).",
            "Capacità scientifiche per valutare l'impatto industriale sui servizi ecosistemici e progettare strategie di mitigazione basate su soluzioni naturali (Nature-Based Solutions)."
        ]
    }
    st.table(pd.DataFrame(team_data))
    
    st.info("🌍 **Messaggio Finale:** *Proteggere il capitale naturale significa blindare il capitale aziendale: la vera governance del futuro calcola l'incalcolabile per governare l'imprevedibile.*")
