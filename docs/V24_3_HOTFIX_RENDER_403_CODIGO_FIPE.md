# V24.3 — Hotfix Render 403 + coleta por código FIPE

## Motivo

O diagnóstico V24.2 mostrou que o endpoint histórico usado pelo painel local (`https://veiculos.fipe.org.br/api/veiculos/ConsultarTabelaDeReferencia`) retorna `HTTP 403 Forbidden` no Render. Esse bloqueio acontece antes da matemática de depreciação e impede o fluxo fiel do painel local quando se tenta usar diretamente o endpoint web da FIPE a partir do datacenter.

## Correção aplicada

A V24.3 deixou de depender, por padrão, do endpoint `veiculos.fipe.org.br` no Render. O adapter V19.17 agora usa a API FIPE v2 em modo mensal por referência e por código FIPE:

- lista referências mensais pela API v2;
- percorre mês a mês;
- consulta `codigo_fipe + codigo_ano` dentro de cada referência;
- encontra primeira aparição;
- procura zero km `32000` do mesmo código FIPE na referência da primeira aparição ou anteriores;
- monta histórico amostrado por referências mensais;
- continua sem usar `/history` curto como espinha dorsal;
- continua sem salvar curva definitiva.

## Arquivos alterados

- `services/depreciacao_motor_v1917_adapter.py`
- `services/fipe_historico_painel_adapter.py`
- `static/js/depreciacao.js`
- `templates/depreciacao.html`

## Segurança

O botão definitivo `/api/depreciacao/calcular` continua protegido. A rota V24.3 continua diagnóstica e paralela:

- `POST /api/depreciacao/diagnostico_v1917`
- `POST /api/depreciacao/diagnostico_v1917/continuar`
- `GET /api/depreciacao/diagnostico_v1917/status/<job_id>`

## Observação técnica

O caminho web original do painel local ainda pode ser habilitado manualmente com `FIPE_WEB_V1917_ENABLED=1` para teste local. No Render, o padrão fica desligado para evitar o 403 e o diagnóstico usa `fipe_v2_codigo_fipe_v1917`.
