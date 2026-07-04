"""Substitui a base de teste de vendas_historico pelos arquivos oficiais do iFruti.

Apaga tudo que existe em vendas_historico e reimporta a partir dos .xls em
docs/planilhas_oficiais/. Rodar uma única vez, manualmente:

    cd backend-hayashi
    python scripts/migrar_historico_oficial.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from database import SessionLocal
from models.venda_historico import VendaHistorico
from services.historico_import import upsert_historico_rows
from services.historico_parser import parse_ifruti_xls

PASTA_OFICIAIS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "planilhas_oficiais",
)


def main():
    arquivos = sorted(
        f for f in os.listdir(PASTA_OFICIAIS) if f.lower().endswith(".xls")
    )
    if not arquivos:
        print(f"Nenhum .xls encontrado em {PASTA_OFICIAIS}")
        return

    print(f"{len(arquivos)} arquivo(s) encontrado(s) em {PASTA_OFICIAIS}:")
    for nome in arquivos:
        print(f"  - {nome}")

    resp = input("\nIsso vai APAGAR todos os dados atuais de vendas_historico. Continuar? [s/N] ")
    if resp.strip().lower() != "s":
        print("Cancelado.")
        return

    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE TABLE vendas_historico RESTART IDENTITY"))
        db.commit()
        print("vendas_historico truncada.\n")

        total_importados = total_atualizados = 0
        for nome in arquivos:
            caminho = os.path.join(PASTA_OFICIAIS, nome)
            with open(caminho, "rb") as f:
                raw = f.read()
            try:
                rows = parse_ifruti_xls(raw)
            except Exception as e:
                print(f"✗ {nome}: erro ao parsear — {e}")
                continue

            importados, atualizados = upsert_historico_rows(db, rows)
            total_importados += importados
            total_atualizados += atualizados
            print(f"✓ {nome}: {len(rows)} linha(s) lida(s), {importados} importada(s), {atualizados} atualizada(s)")

        total = db.query(VendaHistorico).count()
        print(f"\nConcluído: {total_importados} importadas, {total_atualizados} atualizadas.")
        print(f"Total em vendas_historico: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
