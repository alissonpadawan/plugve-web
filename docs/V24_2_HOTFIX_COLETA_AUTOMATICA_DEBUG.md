# V24.2 — Hotfix coleta automática e diagnóstico de fonte histórica

Objetivo: manter o motor V19.17 em módulo paralelo, sem salvar curva definitiva, mas reduzir confusão no Render.

Alterações:

1. O diagnóstico V19.17 agora informa explicitamente a fonte histórica usada:
   - `fipe_web_v1917`, quando o endpoint web da FIPE usado pelo painel local respondeu;
   - `fipe_v2`, quando o Render precisou cair para fallback por referência mensal.

2. A resposta mostra:
   - total de referências disponíveis;
   - tamanho da janela de busca da primeira aparição;
   - progresso `indice_busca_primeira/total_referencias_busca`;
   - falha detectada no caminho FIPE Web V19.17, quando existir.

3. A interface passa a continuar automaticamente o diagnóstico em várias requisições pequenas.
   - Isso substitui a necessidade de clicar várias vezes.
   - Cada requisição continua pequena para não gerar `WORKER TIMEOUT` no Render.
   - Nenhuma curva é salva.

4. Para o caminho FIPE Web fiel ao painel local, o backend limita a 1 referência por requisição.
   - O fluxo fiel pode consumir várias chamadas por referência: marca, modelo, ano e valor.
   - Isso é intencional para proteger o Gunicorn no Render.

Ponto metodológico:

O relatório local do Etios mostra que a busca começa em 2016-01 e a primeira aparição ocorre em 2016-06. Portanto, as primeiras tentativas sem ponto válido antes de 2016-06 são esperadas; o problema da V24.1 era a tela parecer parada e não evidenciar claramente que ainda estava avançando.

Proteções mantidas:

- O botão Calcular definitivo continua sem usar este adapter.
- Nenhuma curva é salva.
- `/history` curto não é usado como espinha dorsal.
- O diagnóstico continua em módulo paralelo.
