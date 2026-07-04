"""Classifica um produto da planilha em (categoria, fornecedor).

Os nomes que chegam aqui são os cabeçalhos da planilha (abreviações), ex:
"1A COOP", "2A MINAS", "BET ESP", "REP VDS", "MORANGA".

A classificação é por tokens no nome normalizado. A PRIMEIRA regra que casar
vence — por isso a ordem importa (regras mais específicas primeiro).

Produtos sem token conhecido caem em "Outros" — se aparecerem grupos "Outros"
no dashboard, basta adicionar a regra correspondente aqui.
"""
import unicodedata


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split()).upper()


# (token no nome normalizado, rótulo). Ordem importa.
_CATEGORIA_REGRAS: list[tuple[str, str]] = [
    ("BET", "Beterraba"),
    ("REP", "Repolho"),
    ("MORANG", "Moranga"),
    ("CEN", "Cenoura"),
    ("CXP", "Cenoura"),
    ("PL", "Cenoura"),
    ("TC", "Cenoura"),
    ("1A", "Cenoura"),
    ("2A", "Cenoura"),
    ("3A", "Cenoura"),
]

# Fornecedor / marca / origem. Mineira antes de Minas (MINEIR contém parte de
# MINE; precisamos casar Mineira primeiro para não cair em Minas por engano).
_FORNECEDOR_REGRAS: list[tuple[str, str]] = [
    ("COOP", "Coopadap"),
    ("MINEIR", "Mineira"),
    ("MINE", "Mineira"),
    ("MINAS", "Minas"),
    ("BAC", "BAC"),
    ("SHIMADA", "Shimada"),
    ("GAP", "Gap"),
]


def classificar(nome_produto: str) -> tuple[str, str]:
    """Retorna (categoria, fornecedor) para um produto da planilha."""
    n = _norm(nome_produto)
    categoria = next((rot for tok, rot in _CATEGORIA_REGRAS if tok in n), "Outros")
    fornecedor = next((rot for tok, rot in _FORNECEDOR_REGRAS if tok in n), "Outros")
    return categoria, fornecedor
