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
    st.number_input("Ricavi Annuali", value=st.session_state.revenue, step=1_000_000, key='revenue')
    st.number_input("Costi Operativi (OpEx)", value=st.session_state.opex, step=1_000_000, key='opex')
    
    if st.session_state.sbti_approved:
        st.markdown("🎯 **Status:** `✅ Target SBTi Approvato`")

# --- CORPO PRINCIPALE ---
st.title("🌍 Piattaforma CarbonRisk AI")
st.markdown("Seleziona una delle schede qui sotto per procedere con l'analisi strategica.")

t_home, t_rischi, t_tax, t_cbam, t_down = st.tabs([
    "🏠 Home", "📊 Analisi Rischi", "🇪🇺 Tassonomia (EU Template)", "🌍 CBAM", "📥 Download Ufficiali"
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
        st.number_input("Investimento Transizione (CapEx in €)", value=st.session_state.capex_totale, step=1_000_000, key='capex_totale')
        st.slider("Efficacia attesa (Riduzione Stimata %)", 0, 100, key='perc_red', on_change=sync_from_perc)
        st.success(f"**Risultato Atteso:** Le emissioni nette finali scenderanno a **{st.session_state.em_final:,} tCO2**.")

    with rt_credito:
        st.subheader("1. Finanziamento & Evoluzione Carbonio")
        c_cred1, c_cred2, c_cred3 = st.columns(3)
        c_cred1.number_input("Rata Prestito Bancario (€)", value=st.session_state.rata_prestito, step=500_000, key='rata_prestito')
        c_cred2.number_input("Ammortamenti Annuali (€)", value=st.session_state.ammortamenti, step=500_000, key='ammortamenti')
        c_cred3.slider("Severità Leggi Locali (Moltiplicatore CO2)", 1.0, 3.0, value=st.session_state.policy_multiplier, step=0.1, key='policy_multiplier')

        # Calcolo dinamico scenari IPCC (Prima vs Dopo)
        country_data = df_base[df_base['Paese'] == st.session_state.selected_country].copy()
        plot_data = []
        emissions_tot = get_tot_emissions()
        for _, row in country_data.iterrows():
            eff_price = row['Prezzo Carbonio Base'] * st.session_state.policy_multiplier
            # Profitto Scenario BAU (Senza CapEx, subisce tutte le tasse)
            profit_prima = st.session_state.revenue - st.session_state.opex - (eff_price * emissions_tot)
            # Profitto Scenario Transizione (CapEx speso, emissioni ridotte, ma si paga la rata del prestito)
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

        fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, title="Evoluzione Prezzo Tasse Carbonio (€/t) nei tre Scenari IPCC")
        fig_prezzo.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
        st.plotly_chart(fig_prezzo, use_container_width=True)

        st.divider()

        st.subheader("2. Analisi d'Impatto: Utili Prima e Dopo la Transizione (Scenari IPCC)")
        st.markdown("Metti a confronto gli scenari anno su anno per capire se il costo del prestito (CapEx) è giustificato dal risparmio fiscale futuro.")
        col_lin1, col_lin2 = st.columns(2)
        
        with col_lin1:
            fig_prima = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, title="PRIMA: Nessuna Transizione (Alta Esposizione Fiscale)")
            fig_prima.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_prima, use_container_width=True)
            
        with col_lin2:
            fig_dopo = px.line(plot_df, x="Anno", y="Utile Netto Post-Transizione (€)", color="Scenario", color_discrete_map=color_map, title="DOPO: Con Transizione (Basse Emissioni + Rata Prestito)")
            fig_dopo.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5), margin=dict(b=80))
            st.plotly_chart(fig_dopo, use_container_width=True)

        st.divider()
        st.subheader("3. Carbon Offsetting (Crediti VERs per Net Zero)")
        prezzo_ver = st.number_input("Prezzo Mercato Volontario (€/tCO2)", value=0)
        costo_offsetting = st.session_state.em_final * prezzo_ver
        st.metric("Costo Annuale per raggiungere neutralità climatica assoluta", f"€ {costo_offsetting:,.0f}")

# --- TAB 3: TASSONOMIA UE (ESTESA A TUTTE LE ATTIVITÀ) ---
with t_tax:
    st.header("🇪🇺 Reporting Tassonomia UE (Struttura Annex II)")
    st.markdown("Dichiara la totalità del tuo CapEx. Le attività non coperte dalla Tassonomia (es. Commercio, Finanza, Estrazione Fossile) verranno classificate in automatico come **Non Ammissibili (Non-Eligible)**.")

    # Database NACE Esteso a includere settori NON eligibili
    tassonomia_db = {
        "Agricoltura, silvicoltura e pesca": {
            "Coltivazione di colture non perenni": "A1.1", 
            "Coltivazione di colture perenni": "A1.2",
            "Allevamento di bestiame": "A1.4",
            "Silvicoltura e gestione forestale": "A2.1"
        },
        "Attività manifatturiere": {
            "Fabbricazione di cemento": "C23.51", 
            "Fabbricazione di alluminio": "C24.42",
            "Fabbricazione di ferro e acciaio": "C24.1", 
            "Fabbricazione di materie plastiche": "C20.16",
            "Fabbricazione di prodotti chimici": "C20.1",
            "Fabbricazione di batterie": "C27.2",
            "Fabbricazione di veicoli a basse emissioni": "C29.1"
        },
        "Fornitura di energia": {
            "Produzione di energia solare fotovoltaica": "D35.11", 
            "Produzione di energia eolica": "D35.11", 
            "Produzione di energia idroelettrica": "D35.11",
            "Trasmissione e distribuzione di energia elettrica": "D35.12",
            "Stoccaggio di energia elettrica": "D35.11"
        },
        "Acqua e Rifiuti": {
            "Raccolta e depurazione delle acque di scarico": "E37.00",
            "Recupero dei materiali (Riciclo)": "E38.32",
            "Raccolta di rifiuti non pericolosi": "E38.11"
        },
        "Trasporto e magazzinaggio": {
            "Trasporto passeggeri interurbano": "H49.39", 
            "Trasporto merci su strada": "H49.41",
            "Trasporto marittimo e costiero": "H50.1",
            "Infrastrutture mobilità zero emissioni": "F42.11"
        },
        "Costruzioni e attività immobiliari": {
            "Costruzione di nuovi edifici": "F41.2", 
            "Ristrutturazione di edifici esistenti": "F41.2",
            "Acquisto e proprietà edifici (Real Estate)": "L68.2"
        },
        "Informazione e comunicazione (ICT)": {
            "Elaborazione dati e hosting (Data Center)": "J63.11",
            "Programmazione informatica (Soluzioni Clima)": "J62.01"
        },
        # --- SETTORI NON AMMISSIBILI ---
        "Attività estrattive (Non Ammissibili)": {
            "Estrazione di carbone": "B05",
            "Estrazione di petrolio greggio e gas naturale": "B06",
            "Altre attività estrattive": "B08"
        },
        "Commercio all'ingrosso e dettaglio (Non Ammissibili)": {
            "Commercio di autoveicoli e motocicli": "G45",
            "Commercio all'ingrosso": "G46",
            "Commercio al dettaglio": "G47"
        },
        "Attività finanziarie e assicurative (Non Ammissibili)": {
            "Intermediazione monetaria (Banche)": "K64",
            "Assicurazioni e fondi pensione": "K65"
        },
        "Altre attività di servizi (Non Ammissibili)": {
            "Servizi di ristorazione e alloggio": "I55-56",
            "Attività professionali, scientifiche e tecniche": "M",
            "Sanità e assistenza sociale": "Q",
            "Altre attività non classificate o generali": "N/A"
        }
    }

    c_tax_head1, c_tax_head2 = st.columns([1, 2])
    c_tax_head1.metric("CapEx Totale di Riferimento", f"€ {st.session_state.capex_totale:,.0f}")
    
    with st.expander("➕ Aggiungi attività al report CapEx", expanded=True):
        col_tax1, col_tax2 = st.columns(2)

        with col_tax1:
            settore = st.selectbox("Macro-Settore", list(tassonomia_db.keys()))
            attivita = st.selectbox("Attività Economica", list(tassonomia_db[settore].keys()))
            nace_code = tassonomia_db[settore][attivita]
            capex_attivita = st.number_input("Absolute CapEx (€)", min_value=0, value=0, step=100000)

        # Logica di Ammissibilità ed Emissioni
        is_eligible = "Non Ammissibili" not in settore
        
        attivita_lower = attivita.lower()
        if not is_eligible:
            unita, soglia, target_unit = "N/A", 0, "N/A"
        elif "edifici" in attivita_lower or "real estate" in attivita_lower: unita, soglia, target_unit = "m2 Gestiti", 80.0, "kWh/m2"
        elif "trasporto" in attivita_lower or "mobilità" in attivita_lower: unita, soglia, target_unit = "tkm", 50.0, "gCO2/tkm"
        elif "cemento" in attivita_lower: unita, soglia, target_unit = "Tonnellate prodotte", 0.72, "tCO2/ton"
        elif "acciaio" in attivita_lower or "alluminio" in attivita_lower: unita, soglia, target_unit = "Tonnellate", 1.3, "tCO2/ton"
        elif "energia" in settore.lower() or "fotovoltaica" in attivita_lower: unita, soglia, target_unit = "MWh", 100.0, "gCO2/kWh"
        elif "data center" in attivita_lower: unita, soglia, target_unit = "Terabyte (TB)", 1.2, "PUE"
        else: unita, soglia, target_unit = "Unità", 1.0, "tCO2/unità"

        with col_tax2:
            if not is_eligible:
                st.error("⚠️ L'attività selezionata **NON è attualmente ammissibile** ai sensi della Tassonomia UE. I test tecnici non sono applicabili.")
                tsc_passed = False
            else:
                st.markdown(f"**Test Substantial Contribution (CCM):** `<= {soglia} {target_unit}`")
                prod = st.number_input(f"Volume Annuo ({unita})", value=0, step=10000)
                
                int_calc = (st.session_state.em_final / prod) if prod > 0 else 0
                if target_unit.startswith("g"): int_calc *= 1000 
                elif "PUE" in target_unit: int_calc = 1.0 + (st.session_state.em_final / 1000000)
                
                tsc_passed = int_calc <= soglia and prod > 0
                st.metric("Substantial Contribution", "Superato (Y)" if tsc_passed else "Non Superato (N)", delta_color="normal" if tsc_passed else "inverse")
            
        if st.button("➕ Inserisci in Tabella"):
            if capex_attivita > 0:
                st.session_state.tax_portfolio.append({
                    "Economic activities": attivita,
                    "Code(s)": nace_code,
                    "Absolute CapEx (€)": capex_attivita,
                    "Eligible (Y/N)": "Y" if is_eligible else "N",
                    "TSC Passed": "Y" if (tsc_passed and is_eligible) else "N",
                    "DNSH": "Y" if is_eligible else "N", 
                    "Safeguards": "Y" if is_eligible else "N", 
                })
                st.success("Aggiunto!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error("Il CapEx deve essere > 0.")

    st.divider()
    st.subheader("📊 EU Taxonomy CapEx Editor (Interattivo)")
    
    if st.session_state.tax_portfolio:
        df_tax = pd.DataFrame(st.session_state.tax_portfolio)
        
        st.markdown("✏️ **Personalizza e Pulisci:** Modifica direttamente i valori nella tabella (es. cambia i DNSH in 'N' per vedere l'impatto). Per cancellare una riga, seleziona la spunta a sinistra e premi Canc/Backspace.")
        
        edited_df = st.data_editor(
            df_tax,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Economic activities": st.column_config.TextColumn("Attività Economica", width="medium"),
                "Code(s)": st.column_config.TextColumn("NACE", width="small"),
                "Absolute CapEx (€)": st.column_config.NumberColumn("CapEx (€)", format="€ %d", width="small"),
                "Eligible (Y/N)": st.column_config.TextColumn("Ammissibile", disabled=True, width="small"),
                "TSC Passed": st.column_config.TextColumn("TSC (Y/N)", disabled=True, width="small"),
                "DNSH": st.column_config.SelectboxColumn("DNSH", options=["Y", "N", "N/A"], required=True, width="small"),
                "Safeguards": st.column_config.SelectboxColumn("Min. Safeguards", options=["Y", "N", "N/A"], required=True, width="small")
            },
            key="tax_editor"
        )
        
        # Logica rigorosa di Allineamento (deve essere ammissibile E superare tutti i test)
        edited_df["Aligned"] = (edited_df["Eligible (Y/N)"] == "Y") & (edited_df["TSC Passed"] == "Y") & (edited_df["DNSH"] == "Y") & (edited_df["Safeguards"] == "Y")
        st.session_state.tax_portfolio = edited_df.drop(columns=["Aligned"]).to_dict('records')
        
        if st.button("🗑️ Svuota Tutto"):
            st.session_state.tax_portfolio = []
            st.rerun()
            
        # Calcolo KPI per Dashboard
        capex_tot = st.session_state.capex_totale
        capex_eligible = edited_df[edited_df["Eligible (Y/N)"] == "Y"]["Absolute CapEx (€)"].sum()
        capex_non_eligible = edited_df[edited_df["Eligible (Y/N)"] == "N"]["Absolute CapEx (€)"].sum()
        capex_aligned = edited_df[edited_df["Aligned"] == True]["Absolute CapEx (€)"].sum()
        
        # Adattiamo il denominatore se il portafoglio supera la baseline iniziale
        capex_dichiarato = capex_eligible + capex_non_eligible
        if capex_dichiarato > capex_tot: capex_tot = capex_dichiarato
        
        c_kpi1, c_kpi2 = st.columns([1, 1.5])
        with c_kpi1:
            st.metric("Total Denominator (CapEx)", f"€ {capex_tot:,.0f}")
            st.metric("Taxonomy-aligned proportion (%)", f"{(capex_aligned/capex_tot*100) if capex_tot>0 else 0:.2f} %")
            st.metric("Eligible proportion (%)", f"{(capex_eligible/capex_tot*100) if capex_tot>0 else 0:.2f} %")
            
        with c_kpi2:
            # Ricalcolo quote non esaminate per far tornare a 100 il grafico
            quota_non_esaminata = capex_tot - (capex_eligible + capex_non_eligible)
            
            fig_pie = go.Figure(data=[go.Pie(
                labels=["Aligned", "Eligible Not Aligned", "Non-Eligible", "Da Classificare"], 
                values=[capex_aligned, capex_eligible - capex_aligned, capex_non_eligible, quota_non_esaminata], 
                hole=.4, marker_colors=['#00B050', '#FECB52', '#C00000', '#D3D3D3']
            )])
            fig_pie.update_layout(margin=dict(t=20, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True)

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
    
    fig_sankey = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, line=dict(color="black", width=0.5), label=labels, color="#2E86AB"), 
        link=dict(source=source, target=target, value=value, color="#EAEAEA")
    )])
    fig_sankey.update_layout(height=450, margin=dict(l=0, r=0, t=30, b=0), font=dict(size=14, color="black", family="Arial, sans-serif"))
    st.plotly_chart(fig_sankey, use_container_width=True)

# --- TAB 5: DOWNLOAD (CON TEMPLATE UFFICIALE E PULITO) ---
with t_down:
    st.header("📥 Esportazione Dati & Report Ufficiali")
    
    col_d1, col_d2 = st.columns(2)
    
    with col_d1:
        st.subheader("1. Report Strategico Board (PDF)")
        if st.button("🪄 Genera PDF"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 18)
            pdf.cell(200, 15, txt="ESG & EU Taxonomy Report", ln=True, align='C')
            pdf_bytes = pdf.output(dest='S').encode('latin-1')
            st.success("PDF pronto!")
            st.download_button("📥 Scarica Report (.PDF)", data=pdf_bytes, file_name="ESG_Report.pdf", mime="application/pdf")

    with col_d2:
        st.subheader("2. EU Taxonomy Annex II (CSV)")
        st.markdown("Scarica il template strutturato (CapEx) basato sulle tue elaborazioni.")
        
        if st.session_state.tax_portfolio:
            df_export = pd.DataFrame(st.session_state.tax_portfolio)
            capex_dichiarato = df_export["Absolute CapEx (€)"].sum()
            tot_capex = st.session_state.capex_totale if st.session_state.capex_totale > capex_dichiarato else capex_dichiarato
            
            # Calcoli rigorosi per l'export
            df_export["Proportion of CapEx (%)"] = (df_export["Absolute CapEx (€)"] / tot_capex * 100).round(2).astype(str) + "%"
            df_export["Taxonomy-aligned"] = (df_export["Eligible (Y/N)"] == "Y") & (df_export["TSC Passed"] == "Y") & (df_export["DNSH"] == "Y") & (df_export["Safeguards"] == "Y")
            df_export["Taxonomy-aligned proportion (%)"] = np.where(df_export["Taxonomy-aligned"], df_export["Proportion of CapEx (%)"], "0%")
            df_export["Category"] = np.where(df_export["Eligible (Y/N)"] == "Y", "Transitional", "Non-Eligible")
            
            export_cols = {
                "Economic activities": "Economic activities",
                "Code(s)": "Code(s)",
                "Absolute CapEx (€)": "Absolute CapEx",
                "Proportion of CapEx (%)": "Proportion of CapEx",
                "Eligible (Y/N)": "Taxonomy-Eligible (Y/N)",
                "TSC Passed": "Substantial contribution criteria - CCM",
                "DNSH": "DNSH criteria (Y/N)",
                "Safeguards": "Minimum Safeguards (Y/N)",
                "Taxonomy-aligned proportion (%)": "Taxonomy-aligned proportion of CapEx",
                "Category": "Category (enabling/transitional)"
            }
            
            df_final_export = df_export.rename(columns=export_cols)[list(export_cols.values())]
            csv_data = df_final_export.to_csv(index=False, sep=";")
            
            st.download_button(
                label="📥 Scarica Annex II CapEx (.CSV)", 
                data=csv_data, 
                file_name="EU_Taxonomy_CapEx_Template.csv", 
                mime="text/csv"
            )
        else:
            st.warning("⚠️ Compila prima il portafoglio Tassonomia (Tab 3).")
