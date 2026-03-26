"""
Test del sistema di cache e retry per yfinance
Esegui con: python test_cache_system.py
"""

import os
import json
import time
from datetime import datetime
from app import (
    get_company_info, is_cache_valid, load_from_cache, 
    save_to_cache, get_cache_file, CACHE_DIR
)

def test_cache_system():
    print("🧪 Test Sistema di Cache e Retry\n")
    print("=" * 70)
    
    test_ticker = "AAPL"
    print(f"\n1️⃣  Primo caricamento di {test_ticker} (disk cache vuota)")
    print("-" * 70)
    
    start = time.time()
    data1 = get_company_info(test_ticker)
    elapsed = time.time() - start
    
    if data1:
        print(f"   ✅ Caricato in {elapsed:.2f}s")
        print(f"   📊 {data1['company_name']}")
        print(f"   💾 Salvato in cache: {get_cache_file(test_ticker)}")
    else:
        print(f"   ❌ Errore nel caricamento (probabile rate limiting)")
    
    print(f"\n2️⃣  Controllare validità cache")
    print("-" * 70)
    
    is_valid = is_cache_valid(test_ticker)
    cache_exists = os.path.exists(get_cache_file(test_ticker))
    
    print(f"   Cache esiste: {'✅' if cache_exists else '❌'}")
    print(f"   Cache valida: {'✅' if is_valid else '❌'}")
    
    if cache_exists and is_valid:
        cached = load_from_cache(test_ticker)
        if cached:
            print(f"   📦 Dati in cache: {cached['company_name']}")
    
    print(f"\n3️⃣  Secondo caricamento (dovrebbe usare cache)")
    print("-" * 70)
    
    start = time.time()
    data2 = get_company_info(test_ticker)
    elapsed = time.time() - start
    
    if data2:
        print(f"   ✅ Caricato in {elapsed:.2f}s (da cache o yfinance)")
        print(f"   📊 {data2['company_name']}")
        
        # Verifica che sia lo stesso dato
        if data1 and data1['company_name'] == data2['company_name']:
            print("   ✅ Dati consistenti tra i due caricamenti")
    
    print(f"\n4️⃣  Test multiple ticker")
    print("-" * 70)
    
    test_tickers = ['TSLA', 'ASML', 'MSFT']
    
    for ticker in test_tickers:
        print(f"   📍 {ticker}...", end=" ", flush=True)
        data = get_company_info(ticker)
        if data:
            print(f"✅ {data['company_name'][:40]}")
        else:
            print("❌ Errore (potrebbe essere rate limiting)")
        time.sleep(1)  # Throttle tra ticker
    
    print(f"\n5️⃣  Statistiche cache")
    print("-" * 70)
    
    if os.path.exists(CACHE_DIR):
        cache_files = [f for f in os.listdir(CACHE_DIR) if f.endswith('_cache.json')]
        print(f"   📊 File cache: {len(cache_files)}")
        
        total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) 
                        for f in cache_files)
        print(f"   💾 Dimensione totale: {total_size / 1024:.1f} KB")
        
        print(f"\n   File salvati:")
        for f in sorted(cache_files):
            filepath = os.path.join(CACHE_DIR, f)
            size = os.path.getsize(filepath)
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            print(f"      • {f} ({size/1024:.1f}KB) - {mtime.strftime('%H:%M:%S')}")
    
    print("\n" + "=" * 70)
    print("✅ Test completato!\n")
    print("💡 Consigli:")
    print("   • La cache persiste tra i riavvii dell'app")
    print("   • I dati rimangono validi per 24 ore")
    print("   • Sistema di retry automatico con backoff esponenziale")
    print("   • Se bloccato: usa il bottone 'Svuota cache' nell'app")

if __name__ == "__main__":
    test_cache_system()
