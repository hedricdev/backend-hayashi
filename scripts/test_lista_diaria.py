"""
Testa o fluxo completo de criar_lista_diaria com 1 produto de exemplo.
    python scripts/test_lista_diaria.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.scraping import IFrutiScraper

ITENS_TESTE = [
    {"produto": "Beterraba 2A", "quantidade": 5, "valor": "40.00", "fornecedor": "JOAOZINHO"},
]


async def main():
    print("Iniciando teste de criar_lista_diaria...")
    try:
        async with IFrutiScraper() as scraper:
            resultado = await scraper.criar_lista_diaria(ITENS_TESTE)
            print(f"Resultado: {resultado}")
    except Exception as e:
        print(f"FALHA: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
