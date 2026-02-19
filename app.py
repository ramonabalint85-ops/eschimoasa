import streamlit as st
import pandas as pd
import plotly.express as px

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar 360°", layout="wide")

# --- SINCRONIZZAZIONE TELEPATICA (Session State & Callbacks) ---
if 'em_init' not in st.session_state: st.session_state.em_init = 150000
if 'perc_red' not in st.session_state: st.session_state.perc_red = 50
if 'em_final' not in st.session_state: st.session_state.em_final = 75000

def sync_from_perc():
    st.session_state.em_final = int(st.session_state.em_init * (1 - st.session_state.perc_red / 100.0))

def sync_from_final():
    if st.session_state.em_init > 0:
        val = (1 - st.session_state.em_final / st.session_state.em_init) * 100
        st.session_state.perc_red = max(0, min(100, int(val)))
    else:
        st.session_state.perc_red = 0

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
    emissions = st.number_input("Emissioni Iniziali (tCO2)", step=10_000, key='em_init', on_change=sync_from_init)
    emissions_final = st.number_input("Emissioni Finali (tCO2)", step=10_000, key='em_final', on_change=sync_from_final, help="Questo valore è sincronizzato con il Piano di Transizione.")
    
    st.divider()
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
        "Scenario": row['Scenario'], "Prezzo Carbonio (€/t)": eff_price
    })
plot_df = pd.DataFrame(plot_data)

# ORDINE LEGENDA AGGIORNATO (BAU -> Ordinaria -> Shock)
color_map = {'Net Zero 2050 (Ordinata)': '#EF553B', 'Transizione Ritardata (Shock)': '#FECB52', 'Politiche Attuali (BAU)': '#00CC96'}
ordine_scenari = {"Scenario": ["Politiche Attuali (BAU)", "Net Zero 2050 (Ordinata)", "Transizione Ritardata (Shock)"]}

# --- 3. MENU DI NAVIGAZIONE PRINCIPALE ---
st.title("🌍 CarbonRisk Radar 360°")
st.markdown("Piattaforma integrata di Stress Test Climatico e Finanziario.")

tab_1, tab_tax, tab_transizione, tab_fisico, tab_credito = st.tabs([
    "💰 Prezzi & Utile", 
    "🇪🇺 Tassonomia UE", 
    "🔄 Piano di Transizione", 
    "🌪️ Rischio Fisico",
    "🏦 Rischio Credito"
])

# ==========================================
# SCHERMATA 1: PREZZI E UTILE NETTO
# ==========================================
with tab_1:
    st.header("Traiettoria Prezzi e Impatto Base")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Traiettoria Prezzo del Carbonio")
        fig_prezzo = px.line(plot_df, x="Anno", y="Prezzo Carbonio (€/t)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_prezzo.update_traces(line_shape='spline', line=dict(width=3))
        fig_prezzo.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_prezzo, use_container_width=True)
        
    with col2:
        st.subheader("Utile Netto Aziendale (Senza Interventi)")
        fig_profit = px.line(plot_df, x="Anno", y="Utile Netto (€)", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
        fig_profit.update_traces(line_shape='spline', line=dict(width=3))
        fig_profit.add_hline(y=0, line_dash="dot", line_color="black", annotation_text="Fallimento (Utile < 0)")
        fig_profit.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None))
        st.plotly_chart(fig_profit, use_container_width=True)

# ==========================================
# SCHERMATA 2: TASSONOMIA EUROPEA
# ==========================================
with tab_tax:
    st.header("Allineamento Tassonomia UE (Stato Attuale vs Post-Transizione)")
    col_input, col_grafico = st.columns([1, 2])
    
    with col_input:
        settore = st.selectbox("Settore Economico NACE", ["Generazione Elettrica", "Produzione Cemento", "Produzione Acciaio"])
        unita_prod = "MWh" if settore == "Generazione Elettrica" else "Tonnellate"
        val_prod_default = 500_000 if settore == "Generazione Elettrica" else 300_000
        
        produzione_iniziale = st.number_input(f"Produzione Attuale ({unita_prod})", value=val_prod_default, step=50_000)
        produzione_finale = st.number_input(f"Produzione Post-Transizione ({unita_prod})", value=val_prod_default, step=50_000)
        
        # Calcolo Intensità Attuale
        int_tco2_iniziale = emissions / produzione_iniziale if produzione_iniziale > 0 else 0
        # Calcolo Intensità Finale (Usa le emissioni finali della sidebar)
        int_tco2_finale = emissions_final / produzione_finale if produzione_finale > 0 else 0
        
        if settore == "Generazione Elettrica":
            int_disp_iniziale, int_disp_finale = int_tco2_iniziale * 1000, int_tco2_finale * 1000
            soglia, unita_int = 100, "gCO2/kWh"
        elif settore == "Produzione Cemento":
            int_disp_iniziale, int_disp_finale, soglia, unita_int = int_tco2_iniziale, int_tco2_finale, 0.469, "tCO2/ton"
        else:
            int_disp_iniziale, int_disp_finale, soglia, unita_int = int_tco2_iniziale, int_tco2_finale, 1.3, "tCO2/ton"
            
        is_aligned_iniziale = int_disp_iniziale <= soglia
        is_aligned_finale = int_disp_finale <= soglia

    with col_grafico:
        # Messaggi di stato dinamici
        if is_aligned_iniziale: st.success(f"Stato Attuale: ✅ **ALLINEATO** ({int_disp_iniziale:.1f} {unita_int})")
        else: st.error(f"Stato Attuale: ❌ **NON ALLINEATO** ({int_disp_iniziale:.1f} {unita_int})")
        
        if is_aligned_finale: st.success(f"Post-Transizione: ✅ **ALLINEATO** ({int_disp_finale:.1f} {unita_int}) - Idoneo per Green Loans!")
        else: st.warning(f"Post-Transizione: ❌ **NON ALLINEATO** ({int_disp_finale:.1f} {unita_int}) - Il piano di riduzione emissioni non è sufficiente.")
        
        # Grafico a doppia barra (Attuale vs Futuro)
        tax_data = pd.DataFrame({
            "Fase": ["Stato Attuale", "Post-Transizione"],
            "Intensità": [int_disp_iniziale, int_disp_finale]
        })
        
        fig_tax = px.bar(tax_data, x="Intensità", y="Fase", orientation='h', color="Fase",
                         color_discrete_map={"Stato Attuale": "red" if not is_aligned_iniziale else "green", 
                                             "Post-Transizione": "red" if not is_aligned_finale else "green"},
                         labels={'Intensità': f'Intensità ({unita_int})', 'Fase': ''})
        
        fig_tax.add_vline(x=soglia, line_dash="dash", line_color="black", annotation_text=f"Soglia Legale ({soglia})", annotation_position="top")
        fig_tax.update_layout(template="plotly_white", height=300, showlegend=False)
        st.plotly_chart(fig_tax, use_container_width=True)

# ==========================================
# SCHERMATA 3: PIANO DI TRANSIZIONE
# ==========================================
with tab_transizione:
    st.header("Simulatore Piano di Transizione (CapEx vs OpEx)")
    st.markdown("Cosa succede se investi oggi per raggiungere il target? Modifica la percentuale qui sotto: vedrai aggiornarsi automaticamente anche il valore delle **Emissioni Finali** nella barra a sinistra!")
    
    col_t1, col_t2, col_t3 = st.columns(3)
    capex = col_t1.number_input("Investimento (CapEx) in €", value=10_000_000, step=1_000_000)
    anno_inv = col_t2.slider("Anno di completamento lavori", 2025, 2040, 2026)
    col_t3.slider("Riduzione Emissioni Stimata (%)", 0, 100, key='perc_red', on_change=sync_from_perc)
    
    sim_data = []
    shock_df = country_data[country_data['Scenario'] == 'Transizione Ritardata (Shock)']
    
    for _, row in shock_df.iterrows():
        y = row['Anno']
        eff_price = row['Prezzo Carbonio Base'] * policy_multiplier
        
        profit_base = revenue - opex - (eff_price * emissions)
        
        emissions_post = emissions_final if y > anno_inv else emissions
        profit_post = revenue - opex - (eff_price * emissions_post)
        if y == anno_inv: profit_post -= capex
        
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
    st.markdown("Oltre alle tasse (Rischio di Transizione), valuta i danni operativi dovuti a eventi estremi (Es. alluvioni, ondate di calore) secondo lo scenario ad alte emissioni (RCP 8.5).")
    
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

# ==========================================
# SCHERMATA 5: RISCHIO CREDITO
# ==========================================
with tab_credito:
    st.header("Analisi Rischio di Credito Bancario (DSCR)")
    st.markdown("Mostra l'evoluzione della metrica chiave per le banche. Sotto la linea rossa (1.1x), l'azienda rischia di non poter pagare le rate del mutuo a causa delle tasse climatiche.")
    
    fig_dscr = px.line(plot_df, x="Anno", y="DSCR", color="Scenario", color_discrete_map=color_map, category_orders=ordine_scenari, template="plotly_white")
    fig_dscr.update_traces(line_shape='spline', line=dict(width=3)) 
    fig_dscr.add_hline(y=1.1, line_dash="dash", line_color="red", annotation_text="Soglia Default (< 1.1x)", annotation_position="bottom left")
    fig_dscr.add_hline(y=1.5, line_dash="dot", line_color="green", annotation_text="Soglia Sicurezza (> 1.5x)", annotation_position="top left")
    
    fig_dscr.update_layout(hovermode=False, legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title=None), margin=dict(b=80))
    st.plotly_chart(fig_dscr, use_container_width=True)
