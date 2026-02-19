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

# --- 2. SIDEBAR GLOBALE ---
with st.sidebar:
    st.header("⚙️ Dati Generali Asset")
    selected_country = st.selectbox("Posizione", df_base['Paese'].unique(), index=3) 
    revenue = st.number_input("Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
    opex = st.number_input("Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    emissions = st.number_input("Emissioni Iniziali (tCO2)", value=150_000, step=10_000)
    
    # NUOVO CAMPO: Emissioni Finali
    emissions_final = st.number_input("Emissioni Finali (tCO2)", value=50_000, step=10_000, help="Volume di emissioni post-transizione energetica.")
    
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

# ORDINE LEGENDA FORZATO (BAU -> Shock -> Net Zero)
color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}
ordine_scenari = {"Scenario": ["Politiche Attuali (BAU)", "Transizione Ritardata (Shock)", "Net Zero 2050 (Ordinata)"]}


# --- 3. MENU DI NAVIGAZIONE PRINCIPALE ---
st.title("🌍 CarbonRisk Radar 360°")
st.markdown("Piattaforma integrata di Stress Test Climatico: seleziona un modulo qui sotto per aprire la schermata dedicata.")

tab_1, tab_tax, tab_transizione, tab_fisico = st.tabs([
    "🏦 Prezzi & Rischio Credito", 
    "🇪🇺 Tassonomia UE", 
    "🔄 Piano di Transizione", 
    "🌪️ Rischio Fisico"
])

# ==========================================
# SCHERMATA 1: PREZZI E RISCHIO CREDITO
# ==========================================
with tab_1:
    st.header("Analisi Prezzi del Carbonio e Rischio di Credito")
    
    # Grafico Prezzo Emissioni (ora nel Tab 1)
    st.subheader("Traiettoria del Prezzo del Carbonio")
    st.markdown("Mostra l'aumento previsto delle tasse sulle emissioni nei tre scenari IPCC.")
    fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
    fig_prezzo.update_traces(line_shape='spline', line=dict(width=3))
    fig_prezzo.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
    st.plotly_chart(fig_prezzo, use_container_width=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("DSCR (Capacità di Rimborso)")
        fig_dscr = px.line(plot_df, x="Anno", y="DSCR", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_dscr.update_traces(line_shape='spline', line=dict(width=3)) 
        fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Default Bancario (< 1.1x)")
        fig_dscr.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_dscr, use_container_width=True)
        
    with col2:
        st.subheader("Utile Netto Aziendale")
        fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_profit.update_traces(line_shape='spline', line=dict(width=3))
        fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento (Utile < 0)")
        fig_profit.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_profit, use_container_width=True)

# ==========================================
# SCHERMATA 2: TASSONOMIA EUROPEA
# ==========================================
with tab_tax:
    st.header("Allineamento Tassonomia UE (DNSH & Screening)")
    col_input, col_grafico = st.columns([1, 2])
    
    with col_input:
        settore = st.selectbox("Settore Economico NACE", ["Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
        unita_prod = "MWh" if settore == "Generazione Elettrica" else "Tonnellate"
        val_prod_default = 500_000 if settore == "Generazione Elettrica" else 300_000
        produzione = st.number_input(f"Produzione Annua ({unita_prod})", value=val_prod_default, step=50_000)
        
        # L'intensità viene calcolata sulle emissioni iniziali per vedere se si è allineati ORA
        intensita_tco2 = emissions / produzione if produzione > 0 else 0
        if settore == "Generazione Elettrica":
            intensita_display = intensita_tco2 * 1000
            soglia = 100
            unita_int = "gCO2/kWh"
        elif settore == "Produzione Cemento":
            intensita_display, soglia, unita_int = intensita_tco2, 0.469, "tCO2/ton"
        else:
            intensita_display, soglia, unita_int = intensita_tco2, 1.3, "tCO2/ton"
            
        is_aligned = intensita_display <= soglia

    with col_grafico:
        if is_aligned: st.success("✅ **ALLINEATO:** L'asset rispetta i limiti attuali e può accedere a Green Bonds.")
        else: st.error("❌ **NON ALLINEATO:** L'asset inquina troppo per gli standard europei.")
        
        fig_tax = px.bar(x=[intensita_display], y=[settore], orientation='h', labels={'x': f'Intensità ({unita_int})', 'y': ''})
        fig_tax.update_traces(marker_color="green" if is_aligned else "red")
        fig_tax.add_vline(x=soglia, line_dash="dash", line_color="black", annotation_text=f"Soglia Legale ({soglia})", annotation_position="top")
        fig_tax.update_layout(template="plotly_white", height=250)
        st.plotly_chart(fig_tax, use_container_width=True)

# ==========================================
# SCHERMATA 3: PIANO DI TRANSIZIONE
# ==========================================
with tab_transizione:
    st.header("Simulatore Piano di Transizione (CapEx vs OpEx)")
    st.markdown("Cosa succede se investi oggi per raggiungere le **Emissioni Finali** dichiarate a sinistra? (Confronto basato sullo Scenario 'Transizione Ritardata')")
    
    col_t1, col_t2 = st.columns(2)
    capex = col_t1.number_input("Investimento (CapEx) in €", value=10_000_000, step=1_000_000)
    anno_inv = col_t2.slider("Anno di completamento investimenti", 2025, 2040, 2026)
    
    sim_data = []
    shock_df = country_data[country_data['Scenario'] == 'Transizione Ritardata (Shock)']
    
    for _, row in shock_df.iterrows():
        y = row['Anno']
        eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
        
        # Scenario 1: Non fare nulla (Usa emissioni iniziali per sempre)
        profit_base = revenue - opex - (eff_price * emissions)
        
        # Scenario 2: Investimento completato (Usa emissioni_finali dopo l'anno di investimento)
        emissions_post = emissions_final if y > anno_inv else emissions
        profit_post = revenue - opex - (eff_price * emissions_post)
        if y == anno_inv: profit_post -= capex # Sottrae il costo dell'investimento una tantum
        
        sim_data.append({"Anno": y, "Utile": profit_base, "Strategia": "Nessun Intervento (Default Certo)"})
        sim_data.append({"Anno": y, "Utile": profit_post, "Strategia": "Piano di Transizione (Retrofit)"})
        
    fig_trans = px.line(pd.DataFrame(sim_data), x="Anno", y="Utile", color="Strategia", template="plotly_white")
    fig_trans.update_traces(line_shape='spline', line=dict(width=3))
    fig_trans.add_hline(y=0, line_dash="dot", line_color="red", annotation_text="Fallimento")
    fig_trans.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
    st.plotly_chart(fig_trans, use_container_width=True)

# ==========================================
# SCHERMATA 4: RISCHIO FISICO
# ==========================================
with tab_fisico:
    st.header("Valutazione Rischio Fisico (Danni Climatici)")
    st.markdown("Oltre alle tasse, valuta i danni operativi dovuti a eventi estremi (Es. alluvioni) secondo lo scenario ad alte emissioni (RCP 8.5).")
    
    livello_rischio = st.radio("Livello di Esposizione Geografica dell'Asset:", ["Basso", "Medio", "Alto"], horizontal=True)
    molt_danno = {"Basso": 0.01, "Medio": 0.03, "Alto": 0.06}[livello_rischio]
    
    fisico_data = []
    for y in range(2020, 2055, 5):
        opex_danneggiato = opex * (1 + ((y - 2020) * molt_danno))
        profitto_fisico = revenue - opex_danneggiato
        fisico_data.append({"Anno": y, "Utile Netto (Post-Danni)": profitto_fisico, "Rischio": livello_rischio})
        
    fig_fisico = px.bar(pd.DataFrame(fisico_data), x="Anno", y="Utile Netto (Post-Danni)", color="Rischio", template="plotly_white", color_discrete_sequence=['#ff9999' if livello_rischio=="Medio" else '#ff4d4d' if livello_rischio=="Alto" else '#99ccff'])
    fig_fisico.update_layout(hovermode=False)
    st.plotly_chart(fig_fisico, use_container_width=True)
