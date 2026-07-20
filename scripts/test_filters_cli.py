#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gmail_server.main import list_filters

def test_account(account_name: str):
    print(f"\n--- Analisi filtri per l'account: {account_name.upper()} ---")
    os.environ["GMAIL_ACCOUNT"] = account_name
    try:
        filters = list_filters()
        if not filters:
            print("Nessun filtro trovato per questo account.")
        else:
            print(f"Trovati {len(filters)} filtri:")
            for idx, f in enumerate(filters, 1):
                criteria = f.get("criteria", {})
                action = f.get("action", {})
                print(f"\nFiltro #{idx} (ID: {f.get('id')})")
                print(f"  [Criteri]: {criteria}")
                print(f"  [Azioni] : {action}")
    except Exception as e:
        print(f"Errore durante la lettura dei filtri per l'account '{account_name}': {e}")

def main():
    # Testiamo entrambi gli account configurati
    test_account("info")
    test_account("personal")

if __name__ == "__main__":
    main()
