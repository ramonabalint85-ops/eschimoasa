import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
import json
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
import requests

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CarbonRisk Radar PRO", layout="wide")

# --- CACHE PERSISTENTE E THROTTLING ---
CACHE_DIR = ".yfinance_cache"
CACHE_TIMEOUT_HOURS = 24
THROTTLE_DELAY = 2  # secondi tra le richieste

# Crea directory cache se non esiste
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_file(ticker):
    """Restituisce il percorso del file cache per un ticker"""
    return os.path.join(CACHE_DIR, f"{ticker.upper()}_cache.json")

def is_cache_valid(ticker):
    """Controlla se la cache è ancora valida"""
    cache_file = get_cache_file(ticker)
    if not os.path.exists(cache_file):
        return False
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
            timestamp = datetime.fromisoformat(cache_data.get('timestamp', '2020-01-01'))
            age_hours = (datetime.now() - timestamp).total_seconds() / 3600
            return age_hours < CACHE_TIMEOUT_HOURS
    except:
        return False

def load_from_cache(ticker):
    """Carica dati dalla cache locale"""
    cache_file = get_cache_file(ticker)
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)['data']
    except:
        return None

def save_to_cache(ticker, data):
    """Salva dati nella cache locale"""
    cache_file = get_cache_file(ticker)
    cache_data = {
        'ticker': ticker.upper(),
        'timestamp': datetime.now().isoformat(),
        'data': data
    }
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except:
        pass  # Non bloccare se cache fallisce

def retry_with_backoff(func, ticker, max_retries=3):
    """Riprova con exponential backoff"""
    for attempt in range(max_retries):
        try:
            time.sleep(THROTTLE_DELAY)  # Throttle per evitare rate limiting
            result = func(ticker)
            if result:
                return result
        except requests.exceptions.ConnectionError:
            wait_time = (2 ** attempt)
            if attempt < max_retries - 1:
                st.info(f"⏳ Tentativo {attempt + 1}/{max_retries}... (attesa {wait_time}s)")
                time.sleep(wait_time)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

# --- FUNZIONI PER YFINANCE ---
@lru_cache(maxsize=128)
def _fetch_from_yfinance(ticker):
    """Fetch da yfinance (interno, con caching LRU)"""
    try:
        company = yf.Ticker(ticker)
        info = company.info
        
        data = {
            'ticker': ticker.upper(),
            'company_name': info.get('longName', 'N/A'),
            'country': info.get('country', 'N/A'),
            'sector': info.get('sector', 'N/A'),
            'industry': info.get('industry', 'N/A'),
            'website': info.get('website', 'N/A'),
            'total_assets': info.get('totalAssets', 0),
            'revenue': info.get('totalRevenue', 0),
            'operating_expense': info.get('operatingExpense', 0),
            'capex': info.get('capitalExpenditure', 0),
            'employees': info.get('fullTimeEmployees', 0),
            'margin': info.get('operatingMargins', 0),
            'currency': info.get('currency', 'EUR'),
            'source': 'yfinance'
        }
        return data
    except Exception as e:
        return None

def get_company_info(ticker):
    """Recupera i dati dell'azienda con cache e retry"""
    ticker = ticker.upper()
    
    # 1. Prova cache locale
    if is_cache_valid(ticker):
        cached_data = load_from_cache(ticker)
        if cached_data:
            return cached_data
    
    # 2. Prova a scaricare da yfinance con retry
    result = retry_with_backoff(_fetch_from_yfinance, ticker)
    
    if result:
        save_to_cache(ticker, result)  # Salva per usi futuri
        return result
    
    # 3. Fallback a cache anche se scaduta
    cached_data = load_from_cache(ticker)
    if cached_data:
        st.warning(f"⚠️ Usignando dati in cache di {(datetime.now() - datetime.fromisoformat(cached_data.get('_cached_at', datetime.now().isoformat()))).days} giorni fa")
        return cached_data
    
    # 4. Niente funziona
    st.error(f"❌ Impossibile caricare dati per {ticker}. Connessione bloccata.")
    return None

def format_number(value):
    """Formatta i numeri in modo leggibile"""
    if value is None or value == 0:
        return "N/A"
    if value >= 1e9:
        return f"€{value/1e9:.2f}B"
    elif value >= 1e6:
        return f"€{value/1e6:.2f}M"
    elif value >= 1e3:
        return f"€{value/1e3:.2f}K"
    return f"€{value:.2f}"
countries = ['Stati Uniti', 'Cina', 'Germania', 'Italia', 'India', 'Giappone', 'Brasile', 'Regno Unito']
scenarios = ['Net Zero 2050 (Ordinata)', 'Transizione Ritardata (Shock)', 'Politiche Attuali (BAU)']
years = [2020, 2025, 2030, 2035, 2040, 2045, 2050]

# --- 2. INTERFACCIA UTENTE (UI) ---
st.title("🌍 CarbonRisk Radar: Analisi Paese e Stress Test")
st.markdown("Valuta la resilienza dei tuoi investimenti in base agli scenari climatici IPCC e alle leggi locali.")

# SIDEBAR (Pannello Laterale)
with st.sidebar:
    st.header("1. Ricerca Società Quotata")
    ticker_input = st.text_input("📊 Inserisci Ticker Azienda", placeholder="Es: AAPL, TSLA, ASML", value="").upper()
    
    company_data = None
    cache_status = None
    
    if ticker_input:
        # Mostra status cache
        if is_cache_valid(ticker_input):
            cache_status = "📦 Usignando cache locale (fresca)"
        elif os.path.exists(get_cache_file(ticker_input)):
            cache_status = "📦 Cache disponibile ma scaduta"
        else:
            cache_status = "🌐 Scaricando da yfinance..."
        
        with st.spinner(f"⏳ Caricamento dati per {ticker_input}..."):
            company_data = get_company_info(ticker_input)
    
    # Se abbiamo dati dalla società, mostriamoli
    if company_data:
        st.success(f"✅ {company_data['company_name']}")
        if cache_status:
            st.caption(cache_status)
        st.divider()
        
        # Mostra informazioni aziendali
        col1, col2 = st.columns(2)
        col1.metric("🌍 Paese", company_data['country'])
        col2.metric("📈 Settore GICS", company_data['sector'][:30] + "..." if len(company_data['sector']) > 30 else company_data['sector'])
        
        col1.metric("🏢 Industria", company_data['industry'][:30] + "..." if len(company_data['industry']) > 30 else company_data['industry'])
        col2.metric("👥 Dipendenti", f"{company_data['employees']:,}" if company_data['employees'] > 0 else "N/A")
        
        st.divider()
    
    st.header("2. Dati Finanziari dell'Asset")
    
    # Se abbiamo dati da yfinance, precompiliamo i campi
    if company_data:
        default_revenue = company_data['revenue'] if company_data['revenue'] > 0 else 50_000_000
        default_opex = company_data['operating_expense'] if company_data['operating_expense'] > 0 else 30_000_000
        default_assets = company_data['total_assets'] if company_data['total_assets'] > 0 else 0
        default_capex = company_data['capex'] if company_data['capex'] > 0 else 0
        
        revenue = st.number_input("💰 Ricavi Annuali (€)", value=int(default_revenue) if default_revenue > 0 else 50_000_000, step=1_000_000)
        opex = st.number_input("⚙️ Costi Operativi (OpEx) (€)", value=int(default_opex) if default_opex > 0 else 30_000_000, step=1_000_000)
        
        col1, col2 = st.columns(2)
        col1.metric("💵 Attivo Totale", format_number(company_data['total_assets']))
        col2.metric("🏗️ CapEx Stimato", format_number(company_data['capex']))
        
        # Estrai il paese dalla società
        country_map = {
            'United States': 'Stati Uniti',
            'China': 'Cina',
            'Germany': 'Germania',
            'Italy': 'Italia',
            'India': 'India',
            'Japan': 'Giappone',
            'Brazil': 'Brasile',
            'United Kingdom': 'Regno Unito',
        }
        selected_country = country_map.get(company_data['country'], 'Stati Uniti')
        country = st.selectbox("🌍 Paese", countries, index=countries.index(selected_country) if selected_country in countries else 3)
    else:
        # Valori di default se nessuna società selezionata
        country = st.selectbox("🌍 Seleziona Paese", countries, index=3)
        revenue = st.number_input("💰 Ricavi Annuali (€)", value=50_000_000, step=1_000_000)
        opex = st.number_input("⚙️ Costi Operativi (OpEx) (€)", value=30_000_000, step=1_000_000)
    
    emissions = st.number_input("🌱 Emissioni (tonnellate CO2)", value=150_000, step=10_000)
    
    st.header("3. Stress Test delle Politiche")
    st.info("Simula l'impatto di leggi più severe rispetto alle proiezioni IPCC standard.")
    policy_multiplier = st.slider("Moltiplicatore Severità Leggi", min_value=1.0, max_value=3.0, value=1.0, step=0.1)

# --- 1. GENERAZIONE DATI (Livello Paese) ---
data = []

for country_name in countries:
    for scenario in scenarios:
        for year in years:
            if 'Net Zero' in scenario: 
                price = (year - 2020) * 12
            elif 'Transizione Ritardata' in scenario: 
                price = 10 if year < 2030 else (year - 2030) * 20 + 20 
            else: 
                price = (year - 2020) * 2
            
            if country_name in ['Germania', 'Italia', 'Regno Unito']:
                price = price * 1.4 
            elif country_name in ['India', 'Brasile']:
                price = price * 0.5 
                
            data.append({'Scenario': scenario, 'Paese': country_name, 'Anno': year, 'Prezzo Carbonio Base': price})

df_dummy = pd.DataFrame(data)

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

# Mostra informazioni dettagliate della società se disponibili
if company_data and ticker_input:
    st.subheader(f"📊 Dettagli Società: {company_data['company_name']}")
    
    info_col1, info_col2, info_col3, info_col4 = st.columns(4)
    with info_col1:
        st.metric("🌐 Paese", company_data['country'])
    with info_col2:
        st.metric("📈 Settore", company_data['sector'][:25])
    with info_col3:
        st.metric("🏢 Industria", company_data['industry'][:25])
    with info_col4:
        st.metric("🔗 Sito Web", "[Visita](https://" + company_data['website'].replace("https://", "").replace("http://", "") + ")" if company_data['website'] != 'N/A' else "N/A")
    
    fin_col1, fin_col2, fin_col3, fin_col4 = st.columns(4)
    with fin_col1:
        st.metric("💵 Attivo Totale", format_number(company_data['total_assets']))
    with fin_col2:
        st.metric("📊 Ricavi", format_number(company_data['revenue']))
    with fin_col3:
        st.metric("🏗️ CapEx", format_number(company_data['capex']))
    with fin_col4:
        st.metric("👥 Dipendenti", f"{company_data['employees']:,}" if company_data['employees'] > 0 else "N/A", help="Numero di dipendenti a tempo pieno")
    
    st.divider()

# Schede KPI in alto
col1, col2, col3 = st.columns(3)
col1.metric("💰 Utile Previsto (2025)", f"€{current_year_profit/1000000:.1f}M")

shock_data = plot_df[(plot_df['Anno'] == 2030) & (plot_df['Scenario'] == 'Transizione Ritardata (Shock)')]
liability_2030_shock = shock_data['Costo Tassa Carbonio (€)'].values[0] if not shock_data.empty else 0
col2.metric("⚠️ Passività Stimata 2030 (Shock)", f"€{liability_2030_shock/1000000:.1f}M")

status = "🔴 Alto Rischio" if current_year_profit < (revenue * 0.1) else "🟢 Margine Sicuro"
col3.metric("📊 Stato a Breve Termine", status)

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
    st.subheader("📥 Esporta Analisi")
    
    # Crea DataFrame con i dati della società
    report_data = []
    if company_data and ticker_input:
        report_data.append({
            'Tipo Dato': 'META INFORMAZIONI',
            'Campo': 'Ticker',
            'Valore': company_data['ticker'],
            'Unità': '-'
        })
        report_data.append({
            'Tipo Dato': 'META INFORMAZIONI',
            'Campo': 'Società',
            'Valore': company_data['company_name'],
            'Unità': '-'
        })
        report_data.append({
            'Tipo Dato': 'META INFORMAZIONI',
            'Campo': 'Paese',
            'Valore': company_data['country'],
            'Unità': '-'
        })
        report_data.append({
            'Tipo Dato': 'META INFORMAZIONI',
            'Campo': 'Settore GICS',
            'Valore': company_data['sector'],
            'Unità': '-'
        })
        report_data.append({
            'Tipo Dato': 'META INFORMAZIONI',
            'Campo': 'Industria',
            'Valore': company_data['industry'],
            'Unità': '-'
        })
        report_data.append({
            'Tipo Dato': 'DATI FINANZIARI',
            'Campo': 'Attivo Totale',
            'Valore': company_data['total_assets'],
            'Unità': '€'
        })
        report_data.append({
            'Tipo Dato': 'DATI FINANZIARI',
            'Campo': 'Ricavi Totali',
            'Valore': company_data['revenue'],
            'Unità': '€'
        })
        report_data.append({
            'Tipo Dato': 'DATI FINANZIARI',
            'Campo': 'Costi Operativi',
            'Valore': company_data['operating_expense'],
            'Unità': '€'
        })
        report_data.append({
            'Tipo Dato': 'DATI FINANZIARI',
            'Campo': 'CapEx',
            'Valore': company_data['capex'],
            'Unità': '€'
        })
        report_data.append({
            'Tipo Dato': 'DATI FINANZIARI',
            'Campo': 'Dipendenti',
            'Valore': company_data['employees'],
            'Unità': 'N. Persone'
        })
    
    # Crea il report Excel
    col_export1, col_export2 = st.columns(2)
    
    with col_export1:
        st.markdown("**Download dati Stress Test (CSV)**")
        csv = plot_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📊 Scarica Stress Test (CSV)",
            data=csv,
            file_name=f"CarbonRisk_StressTest_{country.replace(' ', '_')}.csv",
            mime="text/csv",
            key="csv_download"
        )
    
    with col_export2:
        if company_data and ticker_input:
            st.markdown("**Download Profilo Società + Analisi (Excel)**")
            
            # Crea DataFrame da esportare
            report_df = pd.DataFrame(report_data)
            
            # Usa un buffer per creare il file Excel in memoria
            from io import BytesIO
            buffer = BytesIO()
            
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # Foglio 1: Informazioni Società
                report_df.to_excel(writer, sheet_name='Profilo Società', index=False)
                
                # Foglio 2: Stress Test
                plot_df.to_excel(writer, sheet_name='Analisi Carbonio', index=False)
            
            buffer.seek(0)
            st.download_button(
                label="📁 Scarica Report Completo (Excel)",
                data=buffer.getvalue(),
                file_name=f"CarbonRisk_Report_{ticker_input}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="excel_download"
            )

# --- FOOTER CON INFO CACHE ---
st.divider()
col_footer1, col_footer2, col_footer3 = st.columns(3)

with col_footer1:
    # Conta file cache
    if os.path.exists(CACHE_DIR):
        cache_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('_cache.json')]
        st.caption(f"💾 Cache locale: {len(cache_files)} aziende")
    else:
        st.caption("💾 Cache locale: 0 aziende")

with col_footer2:
    st.caption(f"🕐 Timeout cache: {CACHE_TIMEOUT_HOURS} ore")

with col_footer3:
    if st.button("🗑️ Svuota cache", help="Rimuove tutti i dati in cache per forzare il download da yfinance"):
        import shutil
        try:
            shutil.rmtree(CACHE_DIR)
            os.makedirs(CACHE_DIR, exist_ok=True)
            st.success("✅ Cache svuotata!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Errore: {e}")

# Info sistema
st.caption(
    f"CarbonRisk Radar v2.0 | "
    f"yfinance con cache intelligente | "
    f"📍 Ultimo aggiornamento: {datetime.now().strftime('%H:%M:%S')}"
)
