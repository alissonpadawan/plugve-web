# V24.4 — Terminal temporário e coleta híbrida V19.17

Objetivo desta etapa:

- manter o motor V19.17 em módulo paralelo;
- não salvar curva definitiva;
- não acionar o botão Calcular definitivo;
- permitir acompanhar a coleta como um terminal de auditoria;
- corrigir a coleta histórica quando o Render bloqueia o endpoint FIPE Web antigo com HTTP 403.

## Alterações principais

1. Criada aba temporária **Terminal temporário V24.4** na tela de relatório técnico.

O terminal mostra, lote por lote:

- criação do job;
- veículo recebido;
- coorte/base escolhida;
- referências FIPE carregadas;
- fonte histórica usada;
- cada tentativa de primeira aparição;
- tentativa por código FIPE;
- fallback por marca/modelo/ano;
- busca do zero km 32000;
- planejamento do histórico;
- coleta ponto a ponto;
- encerramento do diagnóstico.

2. A resposta JSON do adapter agora retorna:

- `terminal_linhas`;
- `terminal_total_linhas`;
- `terminal_atualizado_em`.

3. A coleta FIPE v2 virou híbrida:

- primeiro tenta código FIPE, mas redescobrindo o ano dentro da referência mensal;
- se não encontrar, tenta o fluxo reconstruído por referência: marca -> modelo -> ano -> preço;
- não usa `/history` curto como espinha dorsal.

4. O lote automático no frontend foi reduzido para evitar timeout, porque cada referência pode consumir várias chamadas internas.

## Arquivos alterados

- `services/depreciacao_motor_v1917_adapter.py`
- `services/fipe_historico_painel_adapter.py`
- `templates/depreciacao.html`
- `static/js/depreciacao.js`
- `static/css/app.css`

## Validação local

- `python -m py_compile` passou nos services principais e rota de depreciação.
- `python -m compileall -q services routes core repositories app.py` passou.
- `node --check static/js/depreciacao.js` passou.

## Observação

Esta versão ainda é diagnóstico. O salvamento de curva e a integração definitiva com o botão Calcular continuam protegidos até validar o caso Etios contra o relatório local V19.17.
