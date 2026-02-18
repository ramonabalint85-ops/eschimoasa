import streamlit as st
import pandas as pd
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar 360°", layout="wide")

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
                if 'Net Zero' in scenario: 
                    price = (year - 2020) * 12
                elif 'Transizione Ritardata' in scenario: 
                    price = 10 if year < 2030 else (year - 2030) * 20 + 20 
                else: 
                    price = (year - 2020) * 2
                
                if country in ['Germania', 'Italia', 'Regno Unito']:
                    price = price * 1.4 
                elif country in ['India', 'Brasile']:
                    price = price * 0.5 
                    
                data.append({'Scenario': scenario, 'Paese': country, 'Anno': year, 'Prezzo Carbonio Base': price})
    return pd.DataFrame(data)

df_base = generate_offline_data()

# --- 2. SIDEBAR GLOBALE (Solo dati di base) ---
with st.sidebar:
    st.header("⚙️ Dati Generali Asset")
    selected_country = st.selectbox("Posizione", df_base['Paese'].unique(), index=3) 
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni Iniziali (tCO2)", value=150_000, step=10_000)
    rata_prestito = st.number_input("Rata Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti (€)", value=4_000_000, step=500_000)
    policy_multiplier = st.slider("Severità Leggi Locali", 1.0, 3.0, 1.0, 0.1)

# Elaborazione Dati Base
country_data = df_base[df_base['Paese'] == selected_country].copy()
plot_data = []

for _, row in country_data.iterrows():
    eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
    liability = eff_price * emissions
    profit = revenue - opex - liability
    flusso = profit + ammortamenti
    dscr = (flusso / rata_prestito) if rata_prestito > 0 else 99.9
        
    plot_data.append({
        "Anno": row['Anno'], "Utile Netto (€)": profit, "DSCR": dscr,
        "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price,
        "Costo Emissioni (€)": liability
    })
plot_df = pd.DataFrame(plot_data)

color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}


# --- 3. MENU DI NAVIGAZIONE PRINCIPALE (In alto) ---
st.title("🌍 CarbonRisk Radar 360°")
st.markdown("Piattaforma integrata di Stress Test Climatico: seleziona un modulo qui sotto per aprire la schermata dedicata.")

# Creazione delle schermate principali (Tabs)
tab_credito, tab_prezzo, tab_tax, tab_transizione, tab_fisico = st.tabs([
    "🏦 Rischio Credito (DSCR)", 
    "💰 Prezzo Emissioni", 
    "🇪🇺 Tassonomia UE", 
    "🔄 Piano di Transizione", 
    "🌪️ Rischio Fisico"
])

# ==========================================
# SCHERMATA 1: RISCHIO CREDITO E REDDITIVITÀ
# ==========================================
with tab_credito:
    st.header("Analisi Rischio di Credito e Redditività")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("DSCR (Capacità di Rimborso)")
        fig_dscr = px.line(plot_df, x="Anno", y="DSCR", color="Scenario", color_discrete_map=color_map, template="plotly_white")
        fig_dscr.update_traces(line_shape='spline', line=dict(width=3)) 
        fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Default Bancario (< 1.1x)")
        fig_dscr.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_dscr, use_container_width=True)
        
    with col2:
        st.subheader("Utile Netto Aziendale")
        fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, template="plotly_white")
        fig_profit.update_traces(line_shape='spline', line=dict(width=3))
        fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento (Utile < 0)")
        fig_profit.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_profit, use_container_width=True)

# ==========================================
# SCHERMATA 2: PREZZO DELLE EMISSIONI
# ==========================================
with tab_prezzo:
    st.header("Traiettoria del Prezzo del Carbonio")
    st.markdown("Mostra l'aumento previsto delle tasse sulle emissioni nei tre scenari IPCC.")
    fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, template="plotly_white")
    fig_prezzo.update_traces(line_shape='spline', line=dict(width=3))
    fig_prezzo.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
    st.plotly_chart(fig_prezzo, use_container_width=True)

# ==========================================
# SCHERMATA 3: TASSONOMIA EUROPEA
# ==========================================
with tab_tax:
    st.header("Allineamento Tassonomia UE (DNSH & Screening)")
    col_input, col_grafico = st.columns([1, 2])
    
    with col_input:
        settore = st.selectbox("Settore Economico NACE", ["Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
        unita_prod = "MWh" if settore == "Generazione Elettrica" else "Tonnellate"
        val_prod_default = 500_000 if settore == "Generazione Elettrica" else 300_000
        produzione = st.number_input(f"Produzione Annua ({unita_prod})", value=val_prod_default, step=50000)
        
        intensita
