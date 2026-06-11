# V24.5 — Combustão em modo público/público

Objetivo: alinhar o diagnóstico V19.17 do PlugVE Web com o modo que funcionava no painel local para veículos a combustão.

## Regra aplicada

- API consulta: 1 - Pública.
- API histórico: 1 - Pública.
- Token FIPE: não utilizado.
- API paga/v2: desativada por padrão.
- `/history` curto: não usado como espinha dorsal.
- Botão Calcular definitivo: continua protegido.
- Salvamento de curva: continua desativado nesta etapa.

## Consulta básica

A consulta de marcas, modelos, anos e preço atual volta a usar a base pública:

`https://parallelum.com.br/fipe/api/v1/carros`

## Histórico V19.17

A coleta histórica tenta reproduzir o painel local:

1. `ConsultarTabelaDeReferencia`
2. `ConsultarMarcas`
3. `ConsultarModelos`
4. `ConsultarAnoModelo`
5. `ConsultarValorComTodosParametros`

Base:

`https://veiculos.fipe.org.br/api/veiculos`

## Render

Se o endpoint público web da FIPE retornar 403 no Render, a V24.5 não cai mais para API paga/token. O terminal mostrará o bloqueio real como erro público da FIPE Web.

## Arquivos alterados

- `config.py`
- `.env.example`
- `services/fipe_service.py`
- `services/fipe_historico_painel_adapter.py`
- `services/depreciacao_motor_v1917_adapter.py`
- `static/js/depreciacao.js`
- `templates/depreciacao.html`
