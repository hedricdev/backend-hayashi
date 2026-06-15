"""
Script de teste do login no iFruti.
Executa na raiz do backend:
    python scripts/test_login.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.scraping import IFrutiScraper


async def main():
    print("Iniciando teste de login no iFruti...")
    try:
        async with IFrutiScraper() as scraper:
            print(f"Login OK — URL atual: {scraper._page.url}")
    except Exception as e:
        print(f"FALHA: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
