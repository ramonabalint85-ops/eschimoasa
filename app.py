import streamlit as st
import pandas as pd
import plotly.express as px
import pyam

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar PRO - Bank Edition", layout="wide")

# --- MAPPATURE PER IL DATABASE REALE ---
country_map = {
    'Mondo': 'World', 'Stati Uniti': 'USA', 'Cina': 'CHN', 
    'Germania': 'DEU', 'Italia': 'ITA', 'India': 'IND', 
    'Giappone': 'JPN', 'Brasile': 'BRA', 'Regno Unito': 'GBR'
}

scenario_map = {
    'Net Zero 2050': 'Net Zero 2050 (Ordinata)',
    'Delayed transition': 'Transizione Ritardata (Shock)',
    'Current Policies': 'Politiche Attuali (BAU)'
}

# --- 1. CONNESSIONE AL DATABASE REALE NGFS/IPCC ---
@st.cache_data(show_spinner="Scaricamento dati climatici dal database NGFS in corso...")
def get_real_climate_data():
    try:
        conn = pyam.read_iiasa('ngfs_phase_4')
        df = conn.query(
            model='REMIND-MAgPIE*',
            variable='Price|Carbon',
            scenario=['Net Zero 2050', 'Delayed transition', 'Current Policies'],
            region=list(country_map.values())
        ).as_pandas()
        return df
    except Exception as e:
        st.error(f"Errore di connessione al database: {e}")
        return None

# --- 2. INTERFACCIA UTENTE (UI) ---
st.title("🏦 CarbonRisk Radar: Modulo Rischio di Credito")
st.markdown("Stress test climatico integrato con analisi **DSCR (Debt Service Coverage Ratio)** per conformità bancaria (EBA/BCE).")

with st.sidebar:
    st.header("1. Posizione dell'Asset")
    selected_country_ita = st.selectbox("Seleziona Paese", list(country_map.keys()), index=4) 
    
    st.header("2. Dati Finanziari Core")
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni (tonnellate CO2)", value=150_000, step=10_000)
    
    st.header("3. Dati Bancari (NOVITÀ)")
    st.info("Dati necessari per calcolare la probabilità di default sul debito.")
    rata_prestito = st.number_input("Rata Annuale Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti Annuali (€)", value=4_000_000, step=500_000)
    
    st.header("4. Stress Test delle Politiche")
    policy_multiplier = st.slider("Moltiplicatore Severità Leggi", min_value=1.0, max_value=3.0, value=1.0, step=0.1)

# --- 3. ELABORAZIONE DATI ---
raw_df = get_real_climate_data()

if raw_df is not None:
    iso_code = country_map[selected_country_ita]
    country_data = raw_df[raw_df['region'] == iso_code].copy()
    country_data = country_data[(country_data['year'] >= 2020) & (country_data['year'] <= 2050)]
    
    plot_data = []
    current_year_dscr = 0

    for _, row in country_data.iterrows():
        scenario_ita = scenario_map.get(row['scenario'], row['scenario'])
        
        # Calcolo Impatto Climatico
        effective_carbon_price = row['value'] * policy_multiplier
        carbon_liability = effective_carbon_price * emissions
        profit = revenue - opex - carbon_liability
        
        # Calcolo Bancario: DSCR
        # Flusso di cassa operativo approssimato = Utile + Ammortamenti (costo non monetario)
        flusso_di_cassa = profit + ammortamenti
        
        # Evita la divisione per zero se non ci sono debiti
        if rata_prestito > 0:
            dscr = flusso_di_cassa / rata_prestito
        else:
            dscr = 99.9 # Valore fittizio alto se l'azienda non ha debiti
            
        plot_data.append({
            "Anno": row['year'], 
            "Utile Netto (€)": profit, 
            "DSCR (Copertura Debito)": dscr,
            "Scenario": scenario_ita,
            "Prezzo Carbonio Effettivo (€/t)": effective_carbon_price,
            "Flusso di Cassa (€)": flusso_di_cassa
        })
        
        if row['year'] == 2025 and 'Net Zero' in scenario_ita:
            current_year_dscr = dscr

    plot_df = pd.DataFrame(plot_data)

    # --- 4. LAYOUT DASHBOARD ---
    col1, col2, col3 = st.columns(3)
    
    # Metriche aggiornate per le Banche
    col1.metric("DSCR Attuale (2025)", f"{current_year_dscr:.2f}x", help="> 1.2x è considerato sicuro.")
    
    # Trova l'anno in cui il DSCR scende sotto 1.1 (Soglia di allarme bancario) nello scenario Shock
    shock_data = plot_df[plot_df['Scenario'] == 'Transizione Ritardata (Shock)'].sort_values('Anno')
    anno_default = "Mai"
    for _, row in shock_data.iterrows():
        if row['DSCR (Copertura Debito)'] < 1.1:
            anno_default = str(int(row['Anno']))
            break
            
    col2.metric("Anno di Default Stimato (Shock)", anno_default, delta="Rischio Insolvenza", delta_color="inverse")

    status = "🔴 Allarme Credito" if current_year_dscr < 1.1 else "🟢 Credito Solido"
    col3.metric("Rating di Credito Climatico", status)

    st.divider()

    # TABS AGGIORNATI
    tab1, tab2, tab3 = st.tabs(["🏦 Rischio Bancario (DSCR)", "📉 Erosione Redditività", "📥 Esporta Dati BCE"])

    color_map = {
        'Net Zero 2050 (Ordinata)': '#EF553B',
        'Transizione Ritardata (Shock)': '#FECB52',
        'Politiche Attuali (BAU)': '#00CC96'
    }

    with tab1:
        st.subheader("Traiettoria della Capacità di Rimborso (DSCR)")
        st.markdown("Mostra l'evoluzione della metrica chiave per le banche. Sotto la linea rossa (1.1x), l'azienda rischia di non poter pagare le rate del mutuo a causa delle tasse climatiche.")
        fig_dscr = px.line(plot_df, x="Anno", y="DSCR (Copertura Debito)", color="Scenario", markers=True,
                       color_discrete_map=color_map, template="plotly_white")
        
        fig_dscr.update_traces(line_shape='spline', line=dict(width=3), marker=dict(size=8)) 
        
        # Aggiunta delle linee di allerta bancaria
        fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Soglia Default (< 1.1x)", annotation_position="bottom left")
        fig_dscr.add_hline(y=1.5, line_dash="dot", line_color="green", annotation_text="Soglia Sicurezza (> 1.5x)", annotation_position="top left")
        
        fig_dscr.update_layout(
            hovermode=False,
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None),
            margin=dict(b=80) 
        )
        st.plotly_chart(fig_dscr, use_container_width=True)

    with tab2:
        fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", markers=True,
                       color_discrete_map=color_map, template="plotly_white")
        fig_profit.update_traces(line_shape='spline', line=dict(width=3))
        fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento Aziendale (Utile < 0)", annotation_position="bottom left")
        fig_profit.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None), margin=dict(b=80))
        st.plotly_chart(fig_profit, use_container_width=True)

    with tab3:
        st.subheader("Esportazione per Modelli di Rischio Credito")
        st.markdown("Scarica il CSV contenente Utile Netto, Flussi di Cassa e DSCR proiettati per tutti gli scenari IPCC.")
        csv = plot_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Scarica Dataset DSCR Climatico (CSV)",
            data=csv,
            file_name=f"Climate_Credit_Risk_{selected_country_ita}.csv",
            mime="text/csv",
        )
