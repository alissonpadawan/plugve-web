# Seguro AUTOSEG/SUSEP — referência V1

Esta base compacta substitui o percentual universal de seguro usado anteriormente pela CurVE.

## Método

Para cada UF, a taxa de referência é:

`taxa = prêmio médio / importância segurada média`

A estimativa anual é:

`seguro_estimado = valor FIPE atual × taxa da UF`

Na ausência de UF válida, utiliza-se a linha nacional (`BR`). O valor continua editável pelo usuário e não representa cotação individual.

## Origem

- Sistema AUTOSEG/SUSEP: cobertura CASCO; o sistema define e disponibiliza prêmio médio e importância segurada média, classificados por região, modelo e ano.
- Valores numéricos desta V1: Tabela 11 — Indicadores técnicos de risco regionalizados – Automóvel, 1º semestre de 2020, elaborada pela Brasil Atuarial a partir das informações de mercado da SUSEP.

Esta V1 usa somente agregação por UF. Não aplica fatores autorais por idade, faixa de valor ou propulsão. Uma versão posterior poderá incorporar o banco granular AUTOSEG por modelo/ano/exposição.
