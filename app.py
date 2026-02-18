import streamlit as st
import pandas as pd
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar PRO", layout="wide")

# --- 1. GENERAZIONE DATI (Livello Paese) ---
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

df_dummy = pd.DataFrame(data)

# --- 2. INTERFACCIA UTENTE (UI) ---
st.title("🌍 CarbonRisk Radar: Analisi Paese e Stress Test")
st.markdown("Valuta la resilienza dei tuoi investimenti in base agli scenari climatici IPCC e alle leggi locali.")

# SIDEBAR (Pannello Laterale)
with st.sidebar:
    st.header("1. Posizione dell'Asset")
    country = st.selectbox("Seleziona Paese", countries, index=3) 
    
    st.header("2. Dati Finanziari dell'Asset")
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni (tonnellate CO2)", value=150_000, step=10_000)
    
    st.header("3. Stress Test delle Politiche")
    st.info("Simula l'impatto di leggi più severe rispetto alle proiezioni IPCC standard.")
    policy_multiplier = st.slider("Moltiplicatore Severità Leggi", min_value=1.0, max_value=3.0, value=1.0, step=0.1)

# --- 3. MOTORE DI CALCOLO ---
country_data = df_dummy[df_dummy['Paese'] == country].copy()
plot_data = []
current_year_profit = revenue - opex

for _, row in country_data.iterrows():
    effective_carbon_price = row['Prezzo Carbonio Base'] * policy_multiplier
    carbon_liability = effective_carbon_price * emissions
    profit = revenue - opex - carbon_liability
    
    plot_data.append({
        "Anno": row['Anno'], 
        "Utile Netto (€)": profit, 
        "Scenario": row['Scenario'],
        "Prezzo Carbonio Effettivo (€/t)": effective_carbon_price,
        "Costo Tassa Carbonio (€)": carbon_liability
    })
    
    if row['Anno'] == 2025 and 'Net Zero' in row['Scenario']:
        current_year_profit = profit

plot_df = pd.DataFrame(plot_data)

# --- 4. LAYOUT DASHBOARD ---

# Schede KPI in alto
col1, col2, col3 = st.columns(3)
col1.metric("Utile Previsto (2025)", f"€{current_year_profit/1000000:.1f}M")

shock_data = plot_df[(plot_df['Anno'] == 2030) & (plot_df['Scenario'] == 'Transizione Ritardata (Shock)')]
liability_2030_shock = shock_data['Costo Tassa Carbonio (€)'].values[0] if not shock_data.empty else 0
col2.metric("Passività Stimata 2030 (Shock Politico)", f"€{liability_2030_shock/1000000:.1f}M")

status = "🔴 Alto Rischio" if current_year_profit < (revenue * 0.1) else "🟢 Margine Sicuro"
col3.metric("Stato a Breve Termine", status)

st.divider()

# Tab
tab1, tab2, tab3 = st.tabs(["📉 Erosione della Redditività", "💰 Traiettoria Prezzo Carbonio", "📥 Esporta Report (Excel)"])

# IL BLOCCO CHE CAUSAVA L'ERRORE È ORA CORRETTO E CHIUSO:
color_map = {
    'Net Zero 2050 (Ordinata)': '#EF553B',
    'Transizione Ritardata (Shock)': '#FECB52',
    'Politiche Attuali (BAU)': '#00CC96'
}

with tab1:
    fig1 = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", markers=True,
                   color_discrete_map=color_map,
                   title=f"Proiezioni dell'Utile Netto per l'Asset in {country} (Severità Legale: {policy_multiplier}x)",
                   template="plotly_white")
    
    fig1.update_traces(line_shape='spline', line=dict(width=3), marker=dict(size=8)) 
    fig1.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Linea di Fallimento", annotation_position="top left")
    
    fig1.update_layout(
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            xanchor="center",
            x=0.5,
            title=None
        ),
        margin=dict(b=80) 
    )
    st.plotly_chart(fig1, use_container_width=True)
    
with tab2:
    fig2 = px.line(plot_df, x="Anno", y="Prezzo Carbonio Effettivo (€/t)", color="Scenario", markers=True,
                   color_discrete_map=color_map,
                   title=f"Traiettoria della Tassa sul Carbonio in {country}",
                   template="plotly_white")
    fig2.update_traces(line_shape='spline', line=dict(width=3))
    
    fig2.update_layout(
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.15,
            xanchor="center",
            x=0.5,
            title=None
        ),
        margin=dict(b=80)
    )
    st.plotly_chart(fig2, use_container_width=True)

with tab3:
    st.subheader("Scarica i Dati dello Stress Test")
    st.markdown("Esporta i risultati in formato CSV.")
    csv = plot_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Scarica Report Finanziario (CSV)",
        data=csv,
        file_name=f"CarbonRisk_Report_{country}.csv",
        mime="text/csv",
    )
