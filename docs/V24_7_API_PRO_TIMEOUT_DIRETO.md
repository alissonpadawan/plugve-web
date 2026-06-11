# V24.7 — API PRO com timeout ajustado e consulta direta

Objetivo: continuar o porte do motor local V19.17 no web, mantendo diagnóstico paralelo e sem salvar curva definitiva.

Alterações principais:

- Mantida a API PRO `https://fipe.parallelum.com.br/api/v2`.
- Adicionada base alternativa `https://api.fipe.online/api/v2` para fallback apenas em timeout de histórico antigo.
- Aumentado o timeout histórico configurável (`FIPE_HISTORICO_TIMEOUT`, padrão 12s).
- Reduzido o lote do Render para 1 referência por requisição.
- Busca mensal agora tenta primeiro o detalhe direto por `codigo_fipe + yearCode + reference`.
- Só se necessário usa o caminho de redescobrir anos na referência.
- Terminal mostra endpoint, tentativa, status e base quando disponíveis.
- Botão Calcular e salvamento definitivo continuam protegidos.

Variáveis opcionais no Render:

```
FIPE_BASE_URL=https://fipe.parallelum.com.br/api/v2/cars
FIPE_ALT_BASE_URL=https://api.fipe.online/api/v2/cars
FIPE_REQUEST_TIMEOUT=15
FIPE_HISTORICO_TIMEOUT=12
```

Nenhuma curva definitiva é salva nesta etapa.
