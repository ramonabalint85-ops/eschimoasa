"""
Configurazioni per CarbonRisk Radar PRO
Contiene mappature e costanti globali
"""

# Mappatura paesi: yfinance -> Applicazione
COUNTRY_MAPPING = {
    'United States': 'Stati Uniti',
    'China': 'Cina',
    'Germany': 'Germania',
    'Italy': 'Italia',
    'India': 'India',
    'Japan': 'Giappone',
    'Brazil': 'Brasile',
    'United Kingdom': 'Regno Unito',
    'France': 'Francia',
    'Spain': 'Spagna',
    'Netherlands': 'Paesi Bassi',
    'Sweden': 'Svezia',
    'Switzerland': 'Svizzera',
    'Canada': 'Canada',
    'Australia': 'Australia',
}

# Settori GICS comuni
GICS_SECTORS = {
    'Financials': 'Finanziari',
    'Information Technology': 'Tecnologia',
    'Health Care': 'Sanità',
    'Industrials': 'Industriali',
    'Consumer Cyclical': 'Consumer Ciclico',
    'Consumer Defensive': 'Consumer Difensivo',
    'Energy': 'Energia',
    'Utilities': 'Utilities',
    'Real Estate': 'Real Estate',
    'Materials': 'Materiali',
    'Communication Services': 'Comunicazioni',
}

# Fattori di moltiplicazione del prezzo carbonio per paese
CARBON_PRICE_MULTIPLIERS = {
    'Stati Uniti': 1.0,
    'Cina': 0.8,
    'Germania': 1.4,
    'Italia': 1.4,
    'India': 0.5,
    'Giappone': 1.1,
    'Brasile': 0.5,
    'Regno Unito': 1.4,
    'Francia': 1.3,
    'Spagna': 1.3,
    'Paesi Bassi': 1.5,
    'Svezia': 1.5,
    'Svizzera': 1.5,
}

# Scenari climatici
SCENARIOS = {
    'Net Zero 2050 (Ordinata)': {
        'color': '#EF553B',
        'description': 'Transizione climatica ordinata verso Zero Netto',
    },
    'Transizione Ritardata (Shock)': {
        'color': '#FECB52',
        'description': 'Shock politico con implementazione tardiva',
    },
    'Politiche Attuali (BAU)': {
        'color': '#00CC96',
        'description': 'Continuazione delle politiche attuali',
    }
}

# Anni di proiezione
FORECAST_YEARS = [2020, 2025, 2030, 2035, 2040, 2045, 2050]

# Parametri di stress test
STRESS_TEST_CONFIG = {
    'min_multiplier': 1.0,
    'max_multiplier': 3.0,
    'default_multiplier': 1.0,
    'step': 0.1,
    'description': 'Simula l\'impatto di leggi più severe/miti rispetto alle proiezioni IPCC standard'
}

# Ticker di esempio per testing
EXAMPLE_TICKERS = [
    ('AAPL', 'Apple Inc.', 'Stati Uniti'),
    ('TSLA', 'Tesla Inc.', 'Stati Uniti'),
    ('ASML', 'ASML Holding N.V.', 'Paesi Bassi'),
    ('SIE', 'Siemens AG', 'Germania'),
    ('ENEL', 'Enel S.p.A.', 'Italia'),
    ('ALV', 'Allianz SE', 'Germania'),
    ('NSRGY', 'Nestlé S.A.', 'Svizzera'),
]
