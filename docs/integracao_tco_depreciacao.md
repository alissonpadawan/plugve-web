# Integração TCO + Depreciação

Esta versão mantém a pasta `calculadora_depreciacao_v2` como projeto principal.

## Módulos adicionados

- `routes/tco_routes.py`: rotas e lógica original do simulador TCO, isoladas do `app.py`.
- `templates/simular.html`: tela original do simulador TCO.
- `data/mensal-municipios-desde-jan2026.xlsx`: base ANP.
- `data/municipios.xlsx`: base local de municípios, distribuidoras e impostos.

## Módulos preservados

- Depreciação em `/depreciacao`.
- API FIPE da depreciação em `/api/fipe`.
- API da depreciação em `/api/depreciacao`.
- TCO usando endpoints originais `/fipe`, `/preco_energia`, `/preco_combustivel` e `/ipva_estimado`.

## Observação

A integração profunda da taxa de depreciação no TCO pode ser feita em etapa posterior. Nesta versão, os dois módulos já funcionam no mesmo site local.
