# V23 — Hotfix histórico FIPE por código FIPE

Este pacote corrige a direção do diagnóstico histórico.

## Motivo
A documentação atual da API FIPE informa endpoints diretos por código FIPE:

- `/{vehicleType}/{fipeCode}/years`
- `/{vehicleType}/{fipeCode}/years/{yearId}`
- `/{vehicleType}/{fipeCode}/years/{yearId}/history`

Então o diagnóstico deve tentar primeiro o histórico direto por código FIPE antes de reconstruir mês a mês pelo fluxo de marca/modelo/ano.

## Nova prioridade do diagnóstico

1. Obter `codigo_fipe` do veículo selecionado.
2. Escolher a coorte base conforme regra do painel antigo.
3. Consultar `/{vehicleType}/{fipeCode}/years/{yearId}/history`.
4. Se vier histórico suficiente, usar essa série para diagnóstico.
5. Se não vier, cair no fallback seguro por referência mensal inspirado no painel antigo.
6. Não salvar curva no diagnóstico.

## Por que isso ajuda

- Consome menos requisições.
- Reduz risco de timeout no Render.
- Usa o endpoint documentado para histórico.
- Mantém o fallback do painel antigo quando necessário.
