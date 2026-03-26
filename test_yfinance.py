"""
Script di test per verificare che l'integrazione yfinance funziona correttamente
Esegui con: python test_yfinance.py
"""

import yfinance as yf
from app import get_company_info, format_number

def test_company_fetch():
    """Test il recupero dati di una società"""
    print("🧪 Test Integrazione yfinance\n")
    print("=" * 60)
    
    test_tickers = ['AAPL', 'TSLA', 'ASML']
    
    for ticker in test_tickers:
        print(f"\n📊 Testing {ticker}...")
        company_data = get_company_info(ticker)
        
        if company_data:
            print(f"✅ {company_data['company_name']}")
            print(f"   Paese: {company_data['country']}")
            print(f"   Settore: {company_data['sector']}")
            print(f"   Industria: {company_data['industry']}")
            print(f"   Attivo: {format_number(company_data['total_assets'])}")
            print(f"   Ricavi: {format_number(company_data['revenue'])}")
            print(f"   OpEx: {format_number(company_data['operating_expense'])}")
            print(f"   CapEx: {format_number(company_data['capex'])}")
            print(f"   Dipendenti: {company_data['employees']:,}")
        else:
            print(f"❌ Errore nel caricamento di {ticker}")
    
    print("\n" + "=" * 60)
    print("✅ Test completato!")

if __name__ == "__main__":
    test_company_fetch()
