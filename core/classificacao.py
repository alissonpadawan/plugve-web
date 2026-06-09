from __future__ import annotations


def classificar_confianca_combustao(pontos: int, janela_meses: int) -> str:
    pontos = int(pontos or 0)
    janela_meses = int(janela_meses or 0)

    if pontos >= 24 and janela_meses >= 24:
        return "ALTA"
    if pontos >= 18 and janela_meses >= 18:
        return "MÉDIA"
    if pontos >= 8:
        return "BAIXA"
    return "INSUFICIENTE"


def classificar_confianca_eletrico(valor: str, pontos: int, janela_meses: int) -> str:
    valor = str(valor or "").strip().upper()
    if valor:
        return valor
    if pontos >= 24 and janela_meses >= 24:
        return "ALTA"
    if pontos >= 18 and janela_meses >= 18:
        return "MÉDIA"
    if pontos >= 8:
        return "BAIXA"
    return "INSUFICIENTE"
