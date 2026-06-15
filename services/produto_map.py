# Mapeamento de abreviações da planilha para nomes completos no iFruti.
# Chave: como aparece na planilha  |  Valor: nome exato no iFruti

PRODUTO_MAP: dict[str, str] = {
    # Cenoura — Coopadap
    "1A COOP":      "Cenoura 1A Coopadap",
    "2A COOP":      "Cenoura 2A Coopadap",
    "TC COOP":      "Cenoura Toco",
    # Cenoura — Minas
    "1A MINAS":     "Cenoura 1A Minas",
    "2A MINAS":     "Cenoura 2A Minas",
    "3A MINAS":     "Cenoura 3A Minas",
    # Cenoura — Mineira (mapeados para equivalente Minas enquanto não cadastrados no iFruti)
    "1A MINEIR":    "Cenoura 1A Minas",
    "2A MINE":      "Cenoura 2A Minas",
    "2A MINEIR":    "Cenoura 2A Minas",
    "3A MINE":      "Cenoura 3A Minas",
    "3A MINEIR":    "Cenoura 3A Minas",
    # Cenoura — Shimada (aguardando cadastro no iFruti — sem mapeamento)
    # Beterraba
    "BET ESP":      "Beterraba Esp",
    "BET AA":       "Beterraba 2A",
    "BET G":        "Beterraba Graúda",
    # Repolho
    "REP VDS":      "Repolho Verde",
    "REP VD":       "Repolho Verde",
    "REP ROX":      "Repolho Roxo",
    "REP RX":       "Repolho Roxo",
    # Cenoura — Graúda / CXP
    "CEN G":        "Cenoura Graúda",
    "PL COOP":      "Cenoura CXP Coopadap",
    "PL MINAS":     "Cenoura CXP Minas",
    "CXP BAC":      "Cenoura CXP BAC",
    # Outros
    "MORANGA":      "Moranga",
    "MORANGAS":     "Moranga",
    "ESP GAP":      "Beterraba Esp",
    # Aguardando confirmação do nome exato no iFruti:
    # "CEN GERALDO":  "???",
}
