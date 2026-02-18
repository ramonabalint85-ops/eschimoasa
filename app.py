import streamlit as st
import pandas as pd
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar PRO - Bank Edition", layout="wide")

# --- 1. MOTORE DATI (Simulazione Offline Robusta) ---
# Usiamo il calcolo matematico per evitare i crash di memoria sui server gratuiti
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

# --- 2. INTERFACCIA UTENTE (UI) ---
st.title("🏦 CarbonRisk Radar: Modulo Rischio di Credito")
st.markdown("Stress test climatico integrato con analisi **DSCR (Debt Service Coverage Ratio)** per conformità bancaria (EBA/BCE).")

with st.sidebar:
    st.header("1. Posizione dell'Asset")
    selected_country = st.selectbox("Seleziona Paese", df_base['Paese'].unique(), index=3) 
    
    st.header("2. Dati Finanziari Core")
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni (tonnellate CO2)", value=150_000, step=10_000)
    
    st.header("3. Dati Bancari")
    st.info("Dati necessari per calcolare la probabilità di default sul debito.")
    rata_prestito = st.number_input("Rata Annuale Prestito (€)", value=8_000_000, step=500_000)
    ammortamenti = st.number_input("Ammortamenti Annuali (€)", value=4_000_000, step=500_000)
    
    st.header("4. Stress Test Politiche")
    policy_multiplier = st.slider("Moltiplicatore Severità", min_value=1.0, max_value=3.0, value=1.0, step=0.1)

# --- 3. ELABORAZIONE DATI E CALCOLO DSCR ---
country_data = df_base[df_base['Paese'] == selected_country].copy()
plot_data = []
current_year_dscr = 0

for _, row in country_data.iterrows():
    # Impatto Climatico
    effective_carbon_price = row['Prezzo Carbonio Base'] * policy_multiplier
    carbon_liability = effective_carbon_price * emissions
    profit = revenue - opex - carbon_liability
    
    # Flusso di cassa (Utile + Ammortamenti)
    flusso_di_cassa = profit + ammortamenti
    
    # Calcolo DSCR
    dscr = (flusso_di_cassa / rata_prestito) if rata_prestito > 0 else 99.9
        
    plot_data.append({
        "Anno": row['Anno'], 
        "Utile Netto (€)": profit, 
        "DSCR (Copertura Debito)": dscr,
        "Scenario": row['Scenario'],
        "Prezzo Carbonio Effettivo (€/t)": effective_carbon_price,
        "Flusso di Cassa (€)": flusso_di_cassa
    })
    
    if row['Anno'] == 2025 and 'Net Zero' in row['Scenario']:
        current_year_dscr = dscr

plot_df = pd.DataFrame(plot_data)

# --- 4. LAYOUT DASHBOARD ---
col1, col2, col3 = st.columns(3)

col1.metric("DSCR Attuale (2025)", f"{current_year_dscr:.2f}x", help="> 1.2x è considerato sicuro per le banche.")

shock_data = plot_df[plot_df['Scenario'] == 'Transizione Ritardata (Shock)'].sort_values('Anno')
anno_default = "Mai"
for _, row in shock_data.iterrows():
    if row['DSCR (Copertura Debito)'] < 1.1:
        anno_default = str(int(row['Anno']))
        break
        
col2.metric("Anno di Default Stimato (Shock)", anno_default, delta="Rischio Insolvenza", delta_color="inverse")

status = "🔴 Allarme Credito" if current_year_dscr < 1.1 else "🟢 Credito Solido"
col3.metric("Rating di Credito", status)

st.divider()

# TABS
tab1, tab2, tab3 = st.tabs(["🏦 Rischio Bancario (DSCR)", "📉 Erosione Redditività", "📥 Esporta Dati BCE"])

color_map = {
    'Net Zero 2050 (Ordinata)': '#EF553B',
    'Transizione Ritardata (Shock)': '#FECB52',
    'Politiche Attuali (BAU)': '#00CC96'
}

with tab1:
    st.subheader("Traiettoria della Capacità di Rimborso (DSCR)")
    st.markdown("Sotto la linea rossa (1.1x), l'azienda rischia di non poter pagare le rate del mutuo.")
    fig_dscr = px.line(plot_df, x="Anno", y="DSCR (Copertura Debito)", color="Scenario", markers=True,
                   color_discrete_map=color_map, template="plotly_white")
    
    fig_dscr.update_traces(line_shape='spline', line=dict(width=3), marker=dict(size=8)) 
    fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Soglia Default (< 1.1x)", annotation_position="bottom left")
    fig_dscr.add_hline(y=1.5, line_dash="dot", line_color="green", annotation_text="Soglia Sicurezza (> 1.5x)", annotation_position="top left")
    
    fig_dscr.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None), margin=dict(b=80))
    st.plotly_chart(fig_dscr, use_container_width=True)

with tab2:
    fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", markers=True,
                   color_discrete_map=color_map, template="plotly_white")
    fig_profit.update_traces(line_shape='spline', line=dict(width=3))
    fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento (Utile < 0)", annotation_position="bottom left")
    fig_profit.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None), margin=dict(b=80))
    st.plotly_chart(fig_profit, use_container_width=True)

with tab3:
    st.subheader("Esportazione per Modelli di Rischio Credito")
    st.markdown("Scarica il CSV contenente Utile Netto, Flussi di Cassa e DSCR proiettati.")
    csv = plot_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Scarica Dataset DSCR (CSV)",
        data=csv,
        file_name=f"Climate_Credit_Risk_{selected_country}.csv",
        mime="text/csv",
    )
