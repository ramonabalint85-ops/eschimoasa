import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
from fpdf import FPDF
import base64

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Enterprise", layout="wide")

# --- SINCRONIZZAZIONE (Session State) ---
if 'revenue' not in st.session_state: st.session_state.revenue = 50_000_000
if 'opex' not in st.session_state: st.session_state.opex = 30_000_000
if 'scope1' not in st.session_state: st.session_state.scope1 = 50000
if 'scope2' not in st.session_state: st.session_state.scope2 = 40000
if 'scope3' not in st.session_state: st.session_state.scope3 = 60000
if 'em_final' not in st.session_state: st.session_state.em_final = 75000
if 'perc_red' not in st.session_state: st.session_state.perc_red = 50

# Ricalcola le emissioni finali in base alla percentuale
def sync_from_perc():
    tot = st.session_state.scope1 + st.session_state.scope2 + st.session_state.scope3
    st.session_state.em_final = int(tot * (1 - st.session_state.perc_red / 100.0))

# --- 1. MOTORE DATI (Offline Robusto) ---
@st.cache_data
def generate_offline_data():
    data = []
    scenarios = ['Net Zero 2050 (Ordinata)', 'Transizione Ritardata (Shock)', 'Politiche Attuali (BAU)']
    years = [2020, 2025, 2030, 2035, 2040, 2045, 2050]
    countries = ['Stati Uniti', 'Cina', 'Germania', 'Italia', 'India', 'Giappone', 'Brasile', 'Regno Unito']

    for country in countries:
        for scenario in scenarios:
            for year in years:
                if 'Net Zero' in scenario: price = (year - 2020) * 12
                elif 'Transizione Ritardata' in scenario: price = 10 if year < 2030 else (year - 2030) * 20 + 20 
                else: price = (year - 2020) * 2
                
                if country in ['Germania', 'Italia', 'Regno Unito']: price = price * 1.4 
                elif country in ['India', 'Brasile']: price = price * 0.5 
                    
                data.append({'Scenario': scenario, 'Paese': country, 'Anno': year, 'Prezzo Carbonio Base': price})
    return pd.DataFrame(data)

df_base = generate_offline_data()

# --- 2. SIDEBAR (Dati, API e GHG Protocol) ---
with st.sidebar:
    st.header("📡 1. Auto-Compilazione (API)")
    ticker = st.text_input("Inserisci Ticker Yahoo Finance (es. ENEL.MI, TSLA, AAPL)")
    if st.button("Scarica Dati Finanziari"):
        try:
            with st.spinner("Scaricamento bilancio..."):
                stock = yf.Ticker(ticker)
                fin = stock.financials
                if not fin.empty:
                    # Prende i ricavi totali dell'ultimo anno disponibile
                    st.session_state.revenue = int(fin.loc['Total Revenue'].iloc[0])
                    # Stima OpEx come 70% dei ricavi se non trova la voce esatta
                    try:
                        st.session_state.opex = int(fin.loc['Operating Expense'].iloc[0])
                    except:
                        st.session_state.opex = int(st.session_state.revenue * 0.7)
                    st.success(f"Dati di {ticker} caricati!")
                else:
                    st.warning("Dati non trovati per questo Ticker.")
        except Exception as e:
            st.error("Errore API. Inserisci i dati manualmente.")

    st.header("⚙️ 2. Dati Finanziari Asset")
    selected_country = st.selectbox("Posizione", df_base['Paese'].unique(), index=3) 
    revenue = st.number_input("Ricavi Annuali (€)", value=st.session_state.revenue, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=st.session_state.opex, step=1_000_000)
    
    st.divider()
    st.header("🌫️ 3. Protocollo GHG (Emissioni)")
    st.markdown("Suddividi le emissioni alla fonte:")
    scope1 = st.number_input("Scope 1: Dirette (es. fumi, caldaie)", value=st.session_state.scope1, step=5000)
    scope2 = st.number_input("Scope 2: Indirette (es. energia acquistata)", value=st.session_state.scope2, step=5000)
    scope3 = st.number_input("Scope 3: Catena fornitura (es. trasporti)", value=st.session_state.scope3, step=5000)
    
    emissions_tot = scope1 + scope2 + scope3
    st.info(f"**Totale Emissioni: {emissions_tot:,} tCO2**")
    
    emissions_final = st.number_input("Emissioni Finali (Target tCO2)", value=st.session_state.em_final, step=5000)
    
    st.divider()
    st.header("🏦 4. Dati Debito e Politiche")
    rata_prestito = st.number_input("Rata Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti (€)", value=4_000_000, step=500_000)
    policy_multiplier = st.slider("Severità Leggi Locali", 1.0, 3.0, 1.0, 0.1)

# Elaborazione Dati Base
country_data = df_base[df_base['Paese'] == selected_country].copy()
plot_data = []

for _, row in country_data.iterrows():
    eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
    liability = eff_price * emissions_tot
    profit = revenue - opex - liability
    flusso = profit + ammortamenti
    dscr = (flusso / rata_prestito) if rata_prestito > 0 else 99.9
        
    plot_data.append({
        "Anno": row['Anno'], "Utile Netto (€)": profit, "DSCR": dscr,
        "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price
    })
plot_df = pd.DataFrame(plot_data)

color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}
ordine_scenari = {"Scenario": ["Politiche Attuali (BAU)", "Net Zero 2050 (Ordinata)", "Transizione Ritardata (Shock)"]}

# --- 3. MENU DI NAVIGAZIONE PRINCIPALE ---
st.title("🌍 CarbonRisk Enterprise")
st.markdown("Piattaforma di Stress Test Climatico: API Finanziarie, GHG Protocol e Analisi Portafoglio.")

tab_1, tab_tax, tab_transizione, tab_fisico, tab_credito, tab_portafoglio, tab_report = st.tabs([
    "💰 Prezzi & Utile", 
    "🇪🇺 Tassonomia UE", 
    "🔄 Transizione", 
    "🌪️ Rischio Fisico",
    "🏦 Rischio Credito",
    "📊 Portafoglio (Excel)",
    "📄 Esporta PDF"
])

# (Le schermate 1, 3, 4, 5 rimangono quasi identiche ma usano emissions_tot)
with tab_1:
    st.header("Traiettoria Prezzi e Impatto Base")
    col1, col2 = st.columns(2)
    with col1:
        fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_prezzo.update_traces(line_shape='spline', line=dict(width=3))
        st.plotly_chart(fig_prezzo, use_container_width=True)
    with col2:
        fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_profit.update_traces(line_shape='spline', line=dict(width=3))
        fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento")
        st.plotly_chart(fig_profit, use_container_width=True)

with tab_tax:
    st.header("Allineamento Tassonomia UE")
    col_input, col_grafico = st.columns([1, 2])
    with col_input:
        settore = st.selectbox("Settore Economico NACE", ["Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
        unita_prod = "MWh" if settore == "Generazione Elettrica" else "Tonnellate"
        produzione_iniziale = st.number_input(f"Produzione Attuale ({unita_prod})", value=500_000, step=50_000)
        produzione_finale = st.number_input(f"Produzione Post-Transizione ({unita_prod})", value=500_000, step=50_000)
        
        int_tco2_iniziale = emissions_tot / produzione_iniziale if produzione_iniziale > 0 else 0
        int_tco2_finale = emissions_final / produzione_finale if produzione_finale > 0 else 0
        
        if settore == "Generazione Elettrica":
            int_disp_iniziale, int_disp_finale, soglia, unita_int = int_tco2_iniziale * 1000, int_tco2_finale * 1000, 100, "gCO2/kWh"
        elif settore == "Produzione Cemento":
            int_disp_iniziale, int_disp_finale, soglia, unita_int = int_tco2_iniziale, int_tco2_finale, 0.469, "tCO2/ton"
        else:
            int_disp_iniziale, int_disp_finale, soglia, unita_int = int_tco2_iniziale, int_tco2_finale, 1.3, "tCO2/ton"
            
    with col_grafico:
        tax_data = pd.DataFrame({"Fase": ["Stato Attuale", "Post-Transizione"], "Intensità": [int_disp_iniziale, int_disp_finale]})
        fig_tax = px.bar(tax_data, x="Intensità", y="Fase", orientation='h', color="Fase", color_discrete_map={"Stato Attuale": "red" if int_disp_iniziale > soglia else "green", "Post-Transizione": "red" if int_disp_finale > soglia else "green"})
        fig_tax.add_vline(x=soglia, line_dash="dash", line_color="black", annotation_text=f"Soglia Legale ({soglia})", annotation_position="top")
        st.plotly_chart(fig_tax, use_container_width=True)

with tab_transizione:
    st.header("Simulatore Piano di Transizione")
    col_t1, col_t2, col_t3 = st.columns(3)
    capex = col_t1.number_input("Investimento (CapEx) in €", value=10_000_000, step=1_000_000)
    anno_inv = col_t2.slider("Anno di completamento lavori", 2025, 2040, 2026)
    col_t3.slider("Riduzione Emissioni Stimata (%)", 0, 100, key='perc_red', on_change=sync_from_perc)
    
    sim_data = []
    shock_df = country_data[country_data['Scenario'] == 'Transizione Ritardata (Shock)']
    for _, row in shock_df.iterrows():
        y = row['Anno']
        eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
        profit_base = revenue - opex - (eff_price * emissions_tot)
        emissions_post = emissions_final if y > anno_inv else emissions_tot
        profit_post = revenue - opex - (eff_price * emissions_post)
        if y == anno_inv: profit_post -= capex
        sim_data.append({"Anno": y, "Utile": profit_base, "Strategia": "Nessun Intervento"})
        sim_data.append({"Anno": y, "Utile": profit_post, "Strategia": "Piano di Transizione"})
        
    fig_trans = px.line(pd.DataFrame(sim_data), x="Anno", y="Utile", color="Strategia", template="plotly_white")
    fig_trans.add_hline(y=0, line_dash="dot", line_color="red")
    st.plotly_chart(fig_trans, use_container_width=True)

with tab_fisico:
    st.header("Valutazione Rischio Fisico")
    livello_rischio = st.radio("Livello Esposizione:", ["Basso", "Medio", "Alto"], horizontal=True)
    molt_danno = {"Basso": 0.01, "Medio": 0.03, "Alto": 0.06}[livello_rischio]
    fisico_data = [{"Anno": y, "Utile Netto": revenue - (opex * (1 + ((y - 2020) * molt_danno)))} for y in range(2020, 2055, 5)]
    fig_fisico = px.bar(pd.DataFrame(fisico_data), x="Anno", y="Utile Netto", template="plotly_white")
    st.plotly_chart(fig_fisico, use_container_width=True)

with tab_credito:
    st.header("Rischio di Credito (DSCR)")
    fig_dscr = px.line(plot_df, x="Anno", y="DSCR", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
    fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Default Bancario")
    st.plotly_chart(fig_dscr, use_container_width=True)

# ==========================================
# NUOVO TAB 6: ANALISI PORTAFOGLIO (EXCEL)
# ==========================================
with tab_portafoglio:
    st.header("📊 Analisi di Portafoglio Multi-Asset")
    st.markdown("Carica un file CSV o Excel contenente i dati di più aziende per mappare il rischio globale.")
    
    # Crea un file Excel di esempio (Mock) che l'utente può scaricare e riempire
    example_df = pd.DataFrame({
        "Azienda": ["Impianto Alpha", "Fabbrica Beta", "Logistica Gamma"],
        "Ricavi": [50000000, 20000000, 15000000],
        "OpEx": [30000000, 18000000, 10000000],
        "Emissioni_Totali": [150000, 80000, 10000]
    })
    st.download_button("📥 Scarica Template Excel (Esempio)", data=example_df.to_csv(index=False).encode('utf-8'), file_name="Template_Portafoglio.csv", mime="text/csv")
    
    uploaded_file = st.file_uploader("Carica il tuo file CSV o Excel", type=["csv", "xlsx"])
    
    if uploaded_file is not None:
        if uploaded_file.name.endswith('.csv'):
            port_df = pd.read_csv(uploaded_file)
        else:
            port_df = pd.read_excel(uploaded_file)
            
        st.success(f"Caricate {len(port_df)} aziende con successo!")
        st.dataframe(port_df.head())
        
        # Simula il rischio nel 2030 (Scenario Shock)
        prezzo_carbonio_2030 = 20 * policy_multiplier
        port_df['Tassa_Carbonio_2030'] = port_df['Emissioni_Totali'] * prezzo_carbonio_2030
        port_df['Utile_2030'] = port_df['Ricavi'] - port_df['OpEx'] - port_df['Tassa_Carbonio_2030']
        port_df['Margine_%'] = (port_df['Utile_2030'] / port_df['Ricavi']) * 100
        
        st.subheader("Mappa di Calore del Rischio (2030)")
        fig_scatter = px.scatter(port_df, x="Emissioni_Totali", y="Margine_%", size="Ricavi", color="Margine_%", hover_name="Azienda", color_continuous_scale="RdYlGn", title="Sopravvivenza del Portafoglio nel 2030 (Più basso e rosso = Rischio Fallimento)")
        fig_scatter.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Soglia Fallimento")
        st.plotly_chart(fig_scatter, use_container_width=True)

# ==========================================
# NUOVO TAB 7: GENERATORE REPORT PDF
# ==========================================
with tab_report:
    st.header("📄 Genera Report Ufficiale PDF (Board-Ready)")
    st.markdown("Crea un documento PDF riassuntivo stampabile, perfetto da allegare ai documenti di compliance TCFD/CSRD o per il Consiglio di Amministrazione.")
    
    if st.button("🪄 Genera e Scarica PDF"):
        # Creazione dinamica del PDF usando FPDF
        pdf = FPDF()
        pdf.add_page()
        
        # Intestazione
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(200, 10, txt="CarbonRisk Enterprise - Report di Sostenibilità", ln=True, align='C')
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(200, 10, txt=f"Asset analizzato in: {selected_country}", ln=True, align='C')
        pdf.ln(10)
        
        # Dati Finanziari
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt="1. Sommari Finanziari e Rischio di Credito", ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.cell(200, 8, txt=f"- Ricavi Annuali: EUR {revenue:,.0f}", ln=True)
        pdf.cell(200, 8, txt=f"- Costi Operativi (OpEx): EUR {opex:,.0f}", ln=True)
        
        # Calcola un dato al volo (DSCR 2030)
        dscr_2030 = plot_df[(plot_df['Anno']==2030) & (plot_df['Scenario']=='Transizione Ritardata (Shock)')]['DSCR'].values[0]
        pdf.cell(200, 8, txt=f"- DSCR Previsto nel 2030 (Shock Scenario): {dscr_2030:.2f}x", ln=True)
        avviso = "ATTENZIONE: Rischio Default" if dscr_2030 < 1.1 else "OK: Nessun Rischio Default"
        pdf.cell(200, 8, txt=f"- Stato Bancario 2030: {avviso}", ln=True)
        pdf.ln(5)
        
        # Emissioni (GHG Protocol)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt="2. Inventario Emissioni (GHG Protocol)", ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.cell(200, 8, txt=f"- Scope 1 (Dirette): {scope1:,} tCO2", ln=True)
        pdf.cell(200, 8, txt=f"- Scope 2 (Indirette): {scope2:,} tCO2", ln=True)
        pdf.cell(200, 8, txt=f"- Scope 3 (Catena del Valore): {scope3:,} tCO2", ln=True)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(200, 8, txt=f"- TOTALE IMPRONTA CARBONICA: {emissions_tot:,} tCO2", ln=True)
        pdf.ln(5)
        
        # Tassonomia UE
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(200, 10, txt="3. Analisi Tassonomia UE (CSRD)", ln=True)
        pdf.set_font("Arial", '', 11)
        esito_tax = "ALLINEATO (Idoneo Green Bonds)" if int_disp_iniziale <= soglia else "NON ALLINEATO"
        pdf.cell(200, 8, txt=f"- Esito Screening Tecnico: {esito_tax}", ln=True)
        pdf.cell(200, 8, txt=f"- Intensita' di emissione calcolata: {int_disp_iniziale:.1f} {unita_int}", ln=True)
        pdf.cell(200, 8, txt=f"- Limite di legge (Soglia UE): {soglia} {unita_int}", ln=True)
        
        # Genera file
        pdf_output = pdf.output(dest="S").encode("latin-1")
        
        # Bottone Download
        st.success("Il PDF è pronto!")
        st.download_button(
            label="📥 Scarica il Report (PDF)",
            data=pdf_output,
            file_name="Report_Sostenibilita_CarbonRisk.pdf",
            mime="application/pdf"
        )
