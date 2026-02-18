import streamlit as st
import pandas as pd
import plotly.express as px
import pyam

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar PRO", layout="wide")

# --- MAPPATURE PER IL DATABASE REALE ---
# I database IPCC usano i codici ISO per i Paesi e nomi specifici per gli scenari
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
        # Si connette al database della fase 4
        conn = pyam.read_iiasa('ngfs_phase_4')
        
        # Estrae i prezzi del carbonio previsti dal modello REMIND-MAgPIE
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
st.title("🌍 CarbonRisk Radar: Live Database")
st.markdown("Connesso in tempo reale al database **NGFS (Network for Greening the Financial System)**.")

with st.sidebar:
    st.header("1. Posizione dell'Asset")
    selected_country_ita = st.selectbox("Seleziona Paese", list(country_map.keys()), index=4) 
    
    st.header("2. Dati Finanziari dell'Asset")
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni (tonnellate CO2)", value=150_000, step=10_000)
    
    st.header("3. Stress Test delle Politiche")
    policy_multiplier = st.slider("Moltiplicatore Severità Leggi", min_value=1.0, max_value=3.0, value=1.0, step=0.1)

# --- 3. ELABORAZIONE DATI ---
raw_df = get_real_climate_data()

if raw_df is not None:
    # Filtra per il Paese selezionato (usando il codice ISO corretto)
    iso_code = country_map[selected_country_ita]
    country_data = raw_df[raw_df['region'] == iso_code].copy()
    
    # Prende solo gli anni dal 2020 al 2050
    country_data = country_data[(country_data['year'] >= 2020) & (country_data['year'] <= 2050)]
    
    plot_data = []
    current_year_profit = revenue - opex

    for _, row in country_data.iterrows():
        # Converte il nome dello scenario in Italiano
        scenario_ita = scenario_map.get(row['scenario'], row['scenario'])
        
        # Calcola i costi (Nota: i dati grezzi NGFS sono in $, li assumiamo 1:1 con l'€ per semplicità)
        effective_carbon_price = row['value'] * policy_multiplier
        carbon_liability = effective_carbon_price * emissions
        profit = revenue - opex - carbon_liability
        
        plot_data.append({
            "Anno": row['year'], 
            "Utile Netto (€)": profit, 
            "Scenario": scenario_ita,
            "Prezzo Carbonio Effettivo (€/t)": effective_carbon_price,
            "Costo Tassa Carbonio (€)": carbon_liability
        })
        
        if row['year'] == 2025 and 'Net Zero' in scenario_ita:
            current_year_profit = profit

    plot_df = pd.DataFrame(plot_data)

    # --- 4. LAYOUT DASHBOARD ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Utile Previsto (2025)", f"€{current_year_profit/1000000:.1f}M")

    shock_data = plot_df[(plot_df['Anno'] == 2030) & (plot_df['Scenario'] == 'Transizione Ritardata (Shock)')]
    liability_2030_shock = shock_data['Costo Tassa Carbonio (€)'].values[0] if not shock_data.empty else 0
    col2.metric("Passività Stimata 2030 (Shock Politico)", f"€{liability_2030_shock/1000000:.1f}M")

    status = "🔴 Alto Rischio" if current_year_profit < (revenue * 0.1) else "🟢 Margine Sicuro"
    col3.metric("Stato a Breve Termine", status)

    st.divider()

    tab1, tab2, tab3 = st.tabs(["📉 Erosione della Redditività", "💰 Traiettoria Prezzo Carbonio", "📥 Esporta Report (Excel)"])

    color_map = {
        'Net Zero 2050 (Ordinata)': '#EF553B',
        'Transizione Ritardata (Shock)': '#FECB52',
        'Politiche Attuali (BAU)': '#00CC96'
    }

    with tab1:
        fig1 = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", markers=True,
                       color_discrete_map=color_map,
                       title=f"Proiezioni Utile Netto per {selected_country_ita}",
                       template="plotly_white")
        
        fig1.update_traces(line_shape='spline', line=dict(width=3), marker=dict(size=8)) 
        fig1.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Linea di Fallimento", annotation_position="top left")
        
        # HOVER DISATTIVATO QUI
        fig1.update_layout(
            hovermode=False, # <-- Questo spegne i valori al passaggio del mouse
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None),
            margin=dict(b=80) 
        )
        st.plotly_chart(fig1, use_container_width=True)
        
    with tab2:
        fig2 = px.line(plot_df, x="Anno", y="Prezzo Carbonio Effettivo (€/t)", color="Scenario", markers=True,
                       color_discrete_map=color_map,
                       title=f"Traiettoria della Tassa sul Carbonio ({selected_country_ita})",
                       template="plotly_white")
        fig2.update_traces(line_shape='spline', line=dict(width=3))
        
        # HOVER DISATTIVATO QUI
        fig2.update_layout(
            hovermode=False, # <-- Questo spegne i valori al passaggio del mouse
            legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None),
            margin=dict(b=80)
        )
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        st.subheader("Scarica i Dati Live dello Stress Test")
        csv = plot_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Scarica Report Finanziario (CSV)",
            data=csv,
            file_name=f"CarbonRisk_Report_Live_{selected_country_ita}.csv",
            mime="text/csv",
        )
