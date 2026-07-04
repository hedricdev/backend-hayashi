from datetime import date

from fpdf import FPDF

from models.venda_historico import VendaHistorico


def _brl(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def gerar_pdf_fiado(cliente: str, vendas: list[VendaHistorico]) -> bytes:
    """Gera um relatório em PDF com as vendas em aberto de um cliente,
    pronto pra ser enviado como cobrança."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(23, 23, 23)
    pdf.cell(0, 10, "Hayashi Distribuidora", ln=True)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Relatório de fiado em aberto - emitido em {date.today().strftime('%d/%m/%Y')}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(23, 23, 23)
    pdf.cell(0, 8, cliente, ln=True)
    pdf.ln(2)

    col_widths = [28, 90, 20, 26, 26]
    headers = ["Data", "Produto", "Qtde", "Total", "Em aberto"]

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(232, 101, 26)
    pdf.set_text_color(255, 255, 255)
    for w, h in zip(col_widths, headers):
        pdf.cell(w, 8, h, border=0, align="L" if h == "Produto" else "R", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(23, 23, 23)
    total_aberto = 0.0
    for i, v in enumerate(sorted(vendas, key=lambda x: x.data)):
        aberto = float(v.valor_aberto or 0)
        total_aberto += aberto
        pdf.set_fill_color(250, 250, 250 if i % 2 == 0 else 245)
        pdf.cell(col_widths[0], 7, v.data.strftime("%d/%m/%Y"), border=0, align="R", fill=True)
        pdf.cell(col_widths[1], 7, v.produto[:55], border=0, align="L", fill=True)
        pdf.cell(col_widths[2], 7, str(v.qtde), border=0, align="R", fill=True)
        pdf.cell(col_widths[3], 7, _brl(v.total_item), border=0, align="R", fill=True)
        pdf.cell(col_widths[4], 7, _brl(aberto), border=0, align="R", fill=True)
        pdf.ln()

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(23, 23, 23)
    pdf.cell(sum(col_widths[:-1]), 9, "Total em aberto", border=0, align="R")
    pdf.set_text_color(232, 101, 26)
    pdf.cell(col_widths[-1], 9, _brl(total_aberto), border=0, align="R")

    return bytes(pdf.output())
