# V23 Hotfix — Histórico por código FIPE com âncoras

Correção do diagnóstico de depreciação por família/coorte.

## Problema
O endpoint documentado `/cars/{fipeCode}/years/{yearId}/history` funcionou, mas em alguns casos retornou apenas uma janela curta, por exemplo 3 pontos recentes. Isso não é suficiente para montar curva confiável.

## Ajuste
Antes de cair na reconstrução por referência do painel antigo, o diagnóstico agora tenta ampliar a série usando referências âncora:

1. Busca o código FIPE atual.
2. Seleciona poucas referências espalhadas pela janela histórica.
3. Em cada referência, consulta os anos disponíveis por código FIPE.
4. Escolhe o ano da coorte naquela referência.
5. Chama `/cars/{fipeCode}/years/{yearId}/history?reference=...`.
6. Une os pontos únicos retornados.

## Segurança
- Não salva curva.
- Não altera cálculo principal.
- Limita as âncoras para evitar timeout e consumo excessivo.
- Se a API ignorar `reference`, os pontos duplicados são removidos e o diagnóstico mostra baixa qualidade.
