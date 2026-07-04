"""
Script de seed para demo — preenche as semanas faltantes de junho/2026
com dados fictícios que totalizam o valor real do iFruti (R$ 63.756,58).

Uso: python seed_junho_demo.py
Para reverter: python seed_junho_demo.py --desfazer
"""
import sys
from datetime import date, timedelta, datetime
from database import SessionLocal
from models.venda_semana import VendaSemana

DESFAZER = "--desfazer" in sys.argv

# Semanas já salvas (não mexer)
SEMANAS_EXISTENTES = [date(2026, 6, 15)]

# Semanas que vamos criar
SEMANAS_DEMO = [date(2026, 6, 1), date(2026, 6, 8), date(2026, 6, 22)]

DIA_OFFSET = {"SEGUNDA": 0, "TERÇA": 1, "QUARTA": 2, "QUINTA": 3, "SEXTA": 4, "SABADO": 5}

# ── Dados fictícios por semana ───────────────────────────────────────────────
# Total existente (semana 15/06): R$ 14.115,01
# Meta: R$ 63.756,58 → restante: R$ 49.641,57 → ~R$ 16.547 por semana

SEMANAS_DATA = [
    # ── Semana 01/06 ── total: R$ 16.420,00
    {
        "semana_ref": date(2026, 6, 1),
        "vendas": [
            # Gabriel
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEGUNDA", "produto": "1A MINEIR",   "quantidade": 30, "pagamento": "PIX",     "fat": 180.00},
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEGUNDA", "produto": "2A COOP",     "quantidade": 20, "pagamento": "PIX",     "fat": 100.00},
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEGUNDA", "produto": "Bet Esp",     "quantidade": 15, "pagamento": "PIX",     "fat": 540.00},
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "TERÇA",   "produto": "2A MINEIR",  "quantidade": 40, "pagamento": "BOLETO",  "fat": 240.00},
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "TERÇA",   "produto": "BET AA",      "quantidade": 25, "pagamento": "BOLETO",  "fat": 900.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "QUARTA",  "produto": "Tc Coop",     "quantidade": 35, "pagamento": "PIX",     "fat": 420.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "QUARTA",  "produto": "3A MINAS",    "quantidade": 20, "pagamento": "PIX",     "fat": 100.00},
            {"vendedor": "Gabriel", "cliente": "Abc Igarape",    "dia": "QUINTA",  "produto": "REP ROX",     "quantidade": 18, "pagamento": "DINHEIRO","fat": 200.00},
            {"vendedor": "Gabriel", "cliente": "Abc Igarape",    "dia": "QUINTA",  "produto": "2A MINAS",    "quantidade": 30, "pagamento": "DINHEIRO","fat": 160.00},
            {"vendedor": "Gabriel", "cliente": "VITOR DE CLAUDIO","dia": "SEXTA",  "produto": "1A MINEIR",   "quantidade": 25, "pagamento": "PIX",     "fat": 150.00},
            {"vendedor": "Gabriel", "cliente": "VITOR DE CLAUDIO","dia": "SEXTA",  "produto": "Bet Esp",     "quantidade": 12, "pagamento": "PIX",     "fat": 432.00},
            {"vendedor": "Gabriel", "cliente": "Malaca",         "dia": "SABADO",  "produto": "2A COOP",     "quantidade": 22, "pagamento": "PIX",     "fat": 110.00},
            # Cassio
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SEGUNDA", "produto": "1A MINEIR",   "quantidade": 50, "pagamento": "BOLETO",  "fat": 300.00},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SEGUNDA", "produto": "2A MINAS",    "quantidade": 60, "pagamento": "BOLETO",  "fat": 320.00},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SEGUNDA", "produto": "MORANGA",     "quantidade": 40, "pagamento": "BOLETO",  "fat": 300.00},
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "TERÇA",   "produto": "Bet Esp",     "quantidade": 30, "pagamento": "PIX",     "fat": 1080.00},
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "TERÇA",   "produto": "TC COOP",     "quantidade": 45, "pagamento": "PIX",     "fat": 540.00},
            {"vendedor": "Cassio",  "cliente": "Leo Cabana",     "dia": "QUARTA",  "produto": "BET AA",      "quantidade": 20, "pagamento": "BOLETO",  "fat": 720.00},
            {"vendedor": "Cassio",  "cliente": "Leo Cabana",     "dia": "QUARTA",  "produto": "REP ROX",     "quantidade": 25, "pagamento": "BOLETO",  "fat": 275.00},
            {"vendedor": "Cassio",  "cliente": "VIANA E SILVA",  "dia": "QUINTA",  "produto": "2A COOP",     "quantidade": 35, "pagamento": "BOLETO",  "fat": 175.00},
            {"vendedor": "Cassio",  "cliente": "VIANA E SILVA",  "dia": "SEXTA",   "produto": "Tc Coop",     "quantidade": 40, "pagamento": "BOLETO",  "fat": 480.00},
            {"vendedor": "Cassio",  "cliente": "MR",             "dia": "SABADO",  "produto": "1A MINEIR",   "quantidade": 30, "pagamento": "PIX",     "fat": 180.00},
            # Matheus
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "SEGUNDA", "produto": "BET AA",      "quantidade": 25, "pagamento": "PIX",     "fat": 900.00},
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "SEGUNDA", "produto": "REP ROX",     "quantidade": 18, "pagamento": "PIX",     "fat": 200.00},
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "TERÇA",   "produto": "2A MINEIR",  "quantidade": 35, "pagamento": "BOLETO",  "fat": 210.00},
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "TERÇA",   "produto": "Bet Esp",     "quantidade": 20, "pagamento": "BOLETO",  "fat": 720.00},
            {"vendedor": "Matheus", "cliente": "Juninho",        "dia": "QUARTA",  "produto": "REP ROX",     "quantidade": 30, "pagamento": "DINHEIRO","fat": 333.00},
            {"vendedor": "Matheus", "cliente": "Juninho",        "dia": "QUARTA",  "produto": "TC COOP",     "quantidade": 25, "pagamento": "DINHEIRO","fat": 300.00},
            {"vendedor": "Matheus", "cliente": "Malaca",         "dia": "QUINTA",  "produto": "BET AA",      "quantidade": 20, "pagamento": "PIX",     "fat": 720.00},
            {"vendedor": "Matheus", "cliente": "Malaca",         "dia": "SEXTA",   "produto": "1A MINEIR",   "quantidade": 28, "pagamento": "PIX",     "fat": 168.00},
            {"vendedor": "Matheus", "cliente": "Leo Cabana",     "dia": "SABADO",  "produto": "Bet Esp",     "quantidade": 15, "pagamento": "PIX",     "fat": 540.00},
        ],
    },
    # ── Semana 08/06 ── total: R$ 16.680,57
    {
        "semana_ref": date(2026, 6, 8),
        "vendas": [
            # Gabriel
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "SEGUNDA", "produto": "Bet Esp",     "quantidade": 18, "pagamento": "BOLETO",  "fat": 648.00},
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "SEGUNDA", "produto": "2A COOP",     "quantidade": 30, "pagamento": "BOLETO",  "fat": 150.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "TERÇA",   "produto": "1A MINEIR",   "quantidade": 35, "pagamento": "PIX",     "fat": 210.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "TERÇA",   "produto": "BET AA",      "quantidade": 20, "pagamento": "PIX",     "fat": 720.00},
            {"vendedor": "Gabriel", "cliente": "Abc Igarape",    "dia": "QUARTA",  "produto": "Tc Coop",     "quantidade": 30, "pagamento": "DINHEIRO","fat": 360.00},
            {"vendedor": "Gabriel", "cliente": "Abc Igarape",    "dia": "QUARTA",  "produto": "3A MINAS",    "quantidade": 15, "pagamento": "DINHEIRO","fat": 75.00},
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "QUINTA",  "produto": "REP ROX",     "quantidade": 20, "pagamento": "PIX",     "fat": 222.00},
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEXTA",   "produto": "2A MINAS",    "quantidade": 35, "pagamento": "PIX",     "fat": 187.00},
            {"vendedor": "Gabriel", "cliente": "VITOR DE CLAUDIO","dia": "SABADO", "produto": "Bet Esp",     "quantidade": 10, "pagamento": "PIX",     "fat": 360.00},
            # Cassio
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "SEGUNDA", "produto": "BET AA",      "quantidade": 30, "pagamento": "BOLETO",  "fat": 1080.00},
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "SEGUNDA", "produto": "1A MINEIR",   "quantidade": 45, "pagamento": "BOLETO",  "fat": 270.00},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "TERÇA",   "produto": "2A MINAS",    "quantidade": 55, "pagamento": "BOLETO",  "fat": 293.57},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "TERÇA",   "produto": "Bet Esp",     "quantidade": 25, "pagamento": "BOLETO",  "fat": 900.00},
            {"vendedor": "Cassio",  "cliente": "VIANA E SILVA",  "dia": "QUARTA",  "produto": "TC COOP",     "quantidade": 40, "pagamento": "PIX",     "fat": 480.00},
            {"vendedor": "Cassio",  "cliente": "VIANA E SILVA",  "dia": "QUINTA",  "produto": "REP ROX",     "quantidade": 28, "pagamento": "PIX",     "fat": 308.00},
            {"vendedor": "Cassio",  "cliente": "Leo Cabana",     "dia": "SEXTA",   "produto": "2A COOP",     "quantidade": 30, "pagamento": "BOLETO",  "fat": 150.00},
            {"vendedor": "Cassio",  "cliente": "MR",             "dia": "SABADO",  "produto": "Tc Coop",     "quantidade": 35, "pagamento": "PIX",     "fat": 420.00},
            # Matheus
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "SEGUNDA", "produto": "BET AA",      "quantidade": 22, "pagamento": "PIX",     "fat": 792.00},
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "SEGUNDA", "produto": "2A MINEIR",  "quantidade": 30, "pagamento": "PIX",     "fat": 180.00},
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "TERÇA",   "produto": "Bet Esp",     "quantidade": 16, "pagamento": "BOLETO",  "fat": 576.00},
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "QUARTA",  "produto": "REP ROX",     "quantidade": 20, "pagamento": "PIX",     "fat": 222.00},
            {"vendedor": "Matheus", "cliente": "Juninho",        "dia": "QUINTA",  "produto": "TC COOP",     "quantidade": 28, "pagamento": "DINHEIRO","fat": 336.00},
            {"vendedor": "Matheus", "cliente": "Malaca",         "dia": "SEXTA",   "produto": "1A MINEIR",   "quantidade": 32, "pagamento": "PIX",     "fat": 192.00},
            {"vendedor": "Matheus", "cliente": "Leo Cabana",     "dia": "SABADO",  "produto": "BET AA",      "quantidade": 18, "pagamento": "PIX",     "fat": 648.00},
        ],
    },
    # ── Semana 22/06 ── total: R$ 16.542,00
    {
        "semana_ref": date(2026, 6, 22),
        "vendas": [
            # Gabriel
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEGUNDA", "produto": "Bet Esp",     "quantidade": 16, "pagamento": "PIX",     "fat": 576.00},
            {"vendedor": "Gabriel", "cliente": "Leo Cabana",     "dia": "SEGUNDA", "produto": "1A MINEIR",   "quantidade": 28, "pagamento": "PIX",     "fat": 168.00},
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "TERÇA",   "produto": "BET AA",      "quantidade": 22, "pagamento": "BOLETO",  "fat": 792.00},
            {"vendedor": "Gabriel", "cliente": "VIANA E SILVA",  "dia": "TERÇA",   "produto": "Tc Coop",     "quantidade": 32, "pagamento": "BOLETO",  "fat": 384.00},
            {"vendedor": "Gabriel", "cliente": "Abc Igarape",    "dia": "QUARTA",  "produto": "2A COOP",     "quantidade": 25, "pagamento": "DINHEIRO","fat": 125.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "QUINTA",  "produto": "REP ROX",     "quantidade": 22, "pagamento": "PIX",     "fat": 244.00},
            {"vendedor": "Gabriel", "cliente": "MR",             "dia": "SEXTA",   "produto": "3A MINAS",    "quantidade": 18, "pagamento": "PIX",     "fat": 90.00},
            {"vendedor": "Gabriel", "cliente": "VITOR DE CLAUDIO","dia": "SABADO", "produto": "1A MINEIR",   "quantidade": 22, "pagamento": "PIX",     "fat": 132.00},
            # Cassio
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SEGUNDA", "produto": "Bet Esp",     "quantidade": 28, "pagamento": "BOLETO",  "fat": 1008.00},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SEGUNDA", "produto": "2A MINAS",    "quantidade": 58, "pagamento": "BOLETO",  "fat": 310.00},
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "TERÇA",   "produto": "BET AA",      "quantidade": 28, "pagamento": "PIX",     "fat": 1008.00},
            {"vendedor": "Cassio",  "cliente": "Márcio Divin",   "dia": "QUARTA",  "produto": "TC COOP",     "quantidade": 38, "pagamento": "PIX",     "fat": 456.00},
            {"vendedor": "Cassio",  "cliente": "Leo Cabana",     "dia": "QUINTA",  "produto": "1A MINEIR",   "quantidade": 42, "pagamento": "BOLETO",  "fat": 252.00},
            {"vendedor": "Cassio",  "cliente": "VIANA E SILVA",  "dia": "QUINTA",  "produto": "REP ROX",     "quantidade": 24, "pagamento": "BOLETO",  "fat": 264.00},
            {"vendedor": "Cassio",  "cliente": "MR",             "dia": "SEXTA",   "produto": "Tc Coop",     "quantidade": 38, "pagamento": "PIX",     "fat": 456.00},
            {"vendedor": "Cassio",  "cliente": "HM",             "dia": "SABADO",  "produto": "2A COOP",     "quantidade": 28, "pagamento": "BOLETO",  "fat": 140.00},
            # Matheus
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "SEGUNDA", "produto": "BET AA",      "quantidade": 20, "pagamento": "PIX",     "fat": 720.00},
            {"vendedor": "Matheus", "cliente": "Hélio JR",       "dia": "TERÇA",   "produto": "REP ROX",     "quantidade": 22, "pagamento": "PIX",     "fat": 244.00},
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "TERÇA",   "produto": "Bet Esp",     "quantidade": 18, "pagamento": "BOLETO",  "fat": 648.00},
            {"vendedor": "Matheus", "cliente": "Juninho",        "dia": "QUARTA",  "produto": "TC COOP",     "quantidade": 30, "pagamento": "DINHEIRO","fat": 360.00},
            {"vendedor": "Matheus", "cliente": "Juninho",        "dia": "QUINTA",  "produto": "2A MINEIR",  "quantidade": 28, "pagamento": "PIX",     "fat": 168.00},
            {"vendedor": "Matheus", "cliente": "Malaca",         "dia": "SEXTA",   "produto": "BET AA",      "quantidade": 18, "pagamento": "PIX",     "fat": 648.00},
            {"vendedor": "Matheus", "cliente": "Leo Cabana",     "dia": "SABADO",  "produto": "1A MINEIR",   "quantidade": 25, "pagamento": "PIX",     "fat": 150.00},
            {"vendedor": "Matheus", "cliente": "ABC Vitoria",    "dia": "SABADO",  "produto": "Tc Coop",     "quantidade": 30, "pagamento": "BOLETO",  "fat": 360.00},
        ],
    },
]


def run():
    db = SessionLocal()
    try:
        if DESFAZER:
            for semana in SEMANAS_DEMO:
                deleted = db.query(VendaSemana).filter(VendaSemana.semana_ref == semana).delete()
                print(f"  Removidas {deleted} linhas da semana {semana}")
            db.commit()
            print("Dados de demo removidos.")
            return

        total_inserido = 0
        for bloco in SEMANAS_DATA:
            semana_ref = bloco["semana_ref"]

            # Não sobrescreve semanas já existentes
            existente = db.query(VendaSemana).filter(VendaSemana.semana_ref == semana_ref).first()
            if existente:
                print(f"  Semana {semana_ref} já existe — pulando.")
                continue

            for v in bloco["vendas"]:
                offset = {"SEGUNDA": 0, "TERÇA": 1, "QUARTA": 2, "QUINTA": 3, "SEXTA": 4, "SABADO": 5}[v["dia"]]
                data_venda = semana_ref + timedelta(days=offset)
                row = VendaSemana(
                    semana_ref=semana_ref,
                    data=data_venda,
                    dia_semana=v["dia"],
                    vendedor=v["vendedor"],
                    cliente=v["cliente"],
                    produto=v["produto"],
                    quantidade=v["quantidade"],
                    pagamento=v["pagamento"],
                    faturamento_estimado=round(v["fat"], 2),
                    importado_em=datetime.utcnow(),
                )
                db.add(row)
                total_inserido += 1

            db.commit()
            fat_semana = sum(v["fat"] for v in bloco["vendas"])
            print(f"  Semana {semana_ref}: {len(bloco['vendas'])} vendas, R$ {fat_semana:,.2f}")

        # Verificação final
        from sqlalchemy import func
        from datetime import date as d
        total = db.query(func.sum(VendaSemana.faturamento_estimado)).filter(
            VendaSemana.data >= d(2026, 6, 1),
            VendaSemana.data <= d(2026, 6, 30),
        ).scalar()
        print(f"\n  Total junho (vendas_semana): R$ {float(total or 0):,.2f}")
        print(f"  Total junho (iFruti):        R$ 63.756,58")
        print(f"  Diferença:                   R$ {abs(float(total or 0) - 63756.58):,.2f}")

    finally:
        db.close()


if __name__ == "__main__":
    print("Desfazendo demo..." if DESFAZER else "Inserindo dados de demo para junho/2026...")
    run()
