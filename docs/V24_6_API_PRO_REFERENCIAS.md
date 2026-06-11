# V24.6 — Motor V19.17 via API PRO por referência mensal

Objetivo: manter o diagnóstico paralelo V19.17, sem salvar curva definitiva, mas trocar a fonte histórica no Render.

## Motivo da mudança

O endpoint público Web da FIPE usado pelo painel local (`veiculos.fipe.org.br/api/veiculos`) funciona no desktop, porém retorna `403 Forbidden` no Render. A V24.6 passa a usar a API PRO oficial:

- Base: `https://fipe.parallelum.com.br/api/v2`
- Vehicle type: `cars`
- Token: variável `FIPE_TOKEN` no Render ou arquivo persistente `fipe_token.txt`
- Headers enviados:
  - `X-Subscription-Token`
  - `Authorization: Bearer ...`

## Estratégia histórica

Não usa `/history` como espinha dorsal. O fluxo principal é:

1. `GET /references`
2. Para cada referência mensal: `GET /cars/{codigo_fipe}/years?reference={ref}`
3. Escolhe o `yearId` da coorte, por exemplo `2017-5`
4. Consulta o preço: `GET /cars/{codigo_fipe}/years/{yearId}?reference={ref}`
5. Procura o zero km por `32000-*` no mesmo fluxo
6. Monta o histórico amostrado e só calcula diagnóstico se houver pontos mínimos

## Proteções mantidas

- Não salva curva definitiva.
- Não liga o botão Calcular definitivo.
- Não mexe no TCO, financiamento, EV ou visual geral.
- Mantém terminal temporário para auditoria passo a passo.
- Continua evitando timeout com lotes pequenos.
