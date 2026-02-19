import streamlit as st
import pandas as pd
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar 360°", layout="wide")

# --- SINCRONIZZAZIONE TELEPATICA (Session State & Callbacks) ---
# Inizializziamo i valori la prima volta che si apre l'app
if 'em_init' not in st.session_state: st.session_state.em_init = 150000
if 'perc_red' not in st.session_state: st.session_state.perc_red = 50
if 'em_final' not in st.session_state: st.session_state.em_final = 75000

# Funzione: Se muovo il cursore delle % nel Piano di Transizione -> Aggiorna le Emissioni Finali a sinistra
def sync_from_perc():
    st.session_state.em_final = int(st.session_state.em_init * (1 - st.session_state.perc_red / 100.0))

# Funzione: Se scrivo le Emissioni Finali a sinistra -> Aggiorna il cursore delle % nel Piano di Transizione
def sync_from_final():
    if st.session_state.em_init > 0:
        val = (1 - st.session_state.em_final / st.session_state.em_init) * 100
        st.session_state.perc_red = max(0, min(100, int(val)))
    else:
        st.session_state.perc_red = 0

# Funzione: Se cambio le Emissioni Iniziali -> Ricalcola le Finali mantenendo la % attuale
def sync_from_init():
    st.session_state.em_final = int(st.session_state.em_init * (1 - st.session_state.perc_red / 100.0))

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

# --- 2. SIDEBAR GLOBALE ---
with st.sidebar:
    st.header("⚙️ Dati Generali Asset")
    selected_country = st.selectbox("Posizione", df_base['Paese'].unique(), index=3) 
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    
    st.divider()
    st.markdown("**Dati Emissioni**")
    # I campi numerici ora sono collegati alle funzioni in alto
    st.number_input("Emissioni Iniziali (tCO2)", step=10_000, key='em_init', on_change=sync_from_init)
    st.number_input("Emissioni Finali (tCO2)", step=10_000, key='em_final', on_change=sync_from_final, help="Questo valore è sincronizzato con il Piano di Transizione.")
    
    st.divider()
    rata_prestito = st.number_input("Rata Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti (€)", value=4_000_000, step=500_000)
    policy_multiplier = st.slider("Severità Leggi Locali", 1.0, 3.0, 1.0, 0.1)

# Estraiamo i valori dal Session State per usarli nei calcoli
emissions = st.session_state.em_init
emissions_final = st.session_state.em_final

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
        "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price
    })
plot_df = pd.DataFrame(plot_data)

color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}
ordine_scenari = {"Scenario": ["Politiche Attuali (BAU)", "Transizione Ritardata (Shock)", "Net Zero 2050 (Ordinata)"]}

# --- 3. MENU DI NAVIGAZIONE PRINCIPALE ---
st.title("🌍 CarbonRisk Radar 360°")
st.markdown("Piattaforma integrata di Stress Test Climatico: seleziona un modulo qui sotto per aprire la schermata dedicata.")

# ORDINE DELLE SCHEDE AGGIORNATO
tab_1, tab_fisico, tab_tax, tab_transizione = st.tabs([
    "🏦 Prezzi & Rischio Credito", 
    "🌪️ Rischio Fisico",
    "🇪🇺 Tassonomia UE", 
    "🔄 Piano di Transizione"
])

# ==========================================
# SCHERMATA 1: PREZZI E RISCHIO CREDITO
# ==========================================
with tab_1:
    st.header("Analisi Prezzi del Carbonio e Rischio di Credito")
    
    st.subheader("Traiettoria del Prezzo del Carbonio")
    fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
    fig_prezzo.update_traces(line_shape='spline', line=dict(width=3))
    fig_prezzo.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
    st.plotly_chart(fig_prezzo, use_container_width=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("DSCR (Capacità di Rimborso)")
        fig_dscr = px.line(plot_df, x="Anno", y="DSCR", color="Scenario
