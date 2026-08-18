# V50.22 — Seguro V2: validação, continuidade e regionalização

## Escopo

Rodada de validação do Seguro V2 criado na V50.21, sem alterar a arquitetura do TCO ou a editabilidade manual do seguro.

## Problemas encontrados

1. Cortes discretos do IPSA por valor FIPE podiam provocar saltos relevantes ao atravessar R$ 50 mil, R$ 80 mil e R$ 150 mil por diferença mínima de preço.
2. Veículos com mais de 10 anos retornavam ao estimador legado, podendo reduzir abruptamente a taxa exatamente quando passavam do limite etário do IPSA detalhado.
3. Veículos recentes sem AUTOSEG específico não recebiam diferenciação geográfica contemporânea, embora o IPSA publique taxas metropolitanas.

## Correções

- interpolação linear em ±5% de cada limite de faixa FIPE, usando apenas as taxas adjacentes publicadas;
- acima de 10 anos, uso de mercado geral + faixa FIPE atual, sem inventar faixa de idade, com confiança limitada a Referência;
- inclusão das taxas metropolitanas IPSA mai/2026 para Salvador, Recife, Belém, Belo Horizonte, Porto Alegre, Rio de Janeiro, Fortaleza, Curitiba e São Paulo;
- se existir região IPSA atual, ela substitui os fatores geográficos AUTOSEG históricos; o fator relativo histórico do código FIPE/modelo pode continuar;
- status visual reduzido para `Seguro estimado · mai/2026 · <confiança>`; detalhes de fonte/agregação ficam em tooltip/metadados.

## Exemplos de sanidade

Para um BEV zero km de R$ 117.012 sem histórico AUTOSEG específico, a regionalização atual produz diferenciação entre Goiânia (referência nacional), São Paulo, Rio de Janeiro, Curitiba, Salvador, Recife, Belo Horizonte e Porto Alegre.

A passagem R$ 80.000 → R$ 80.001 deixa de produzir salto de faixa; a taxa varia de forma contínua dentro da janela de transição.

A passagem de 10 para 11 anos deixa de retornar ao estimador V1; veículos >10 anos permanecem no Seguro V2, sem faixa etária inventada e com confiança Referência.

## Limite conhecido

A página do IPSA já anuncia junho/2026, porém os recortes detalhados auditados nesta versão permanecem os de maio/2026. Não foi feita mistura parcial de junho com maio.
