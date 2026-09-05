# CurVE V50.30 — Catálogo FIPE pré-compilado para navegação

## Escopo

A V50.30 altera apenas a origem da lista de marcas/modelos usada por **Simular TCO** e **Depreciação**. A **Consulta Fipe+** permanece integral e continua consultando o catálogo FIPE público, inclusive para veículos anteriores a 2012.

A regra temporal permanece: em Simular/Depreciação somente são publicados modelos com **Zero km ou pelo menos um ano-modelo >= 2012**.

## Motivação

Até a V50.29 a lista já era estável, mas o clique da marca ainda podia depender da API FIPE e da classificação PBEV em massa. Em marcas grandes isso produzia latência de dezenas de segundos.

A V50.30 move o trabalho de preparação para fora da navegação pública:

1. catálogo recente de anos/modelos é processado offline;
2. a elegibilidade temporal é resolvida por `modelo_id` FIPE;
3. o lado de navegação VE/ICEV é pré-resolvido com as regras já existentes;
4. o resultado é salvo em `data/fipe_cache/catalogo_navegacao_fipe_v1.json`;
5. no Render, esse arquivo é semeado em `/var/data/plugve/fipe_cache/` somente se ainda não existir;
6. cada worker carrega o arquivo em memória e só recarrega quando tamanho/mtime mudam.

Assim, **o clique da marca não consulta `/anos`, não classifica PBEV em massa e não grava estado persistente**.

## Fontes da compilação inicial

- `analise_familias_pais_curve(2).zip` — mapa de 4.721 modelos FIPE, gerado em 02/09/2026.
- `fipe_cache.tar.gz` — estado real da varredura recuperado do Persistent Disk do Render.
- `catalogo_elegibilidade_fipe_v2.json` da V50.29 — identidade/códigos já consolidados.

SHA-256 dos insumos usados nesta rodada:

- análise de famílias: `1f592f82914531ff6926980c9dce1d88f63bc425497d7a68b4457ff3c390e6e3`
- cache real Render: `35371d85ebb8afd6646b222837ce4b052af21bf5ae204d810704bc2291085ab3`

## Resultado compilado

`catalogo_navegacao_fipe_v1.json`:

- 78 marcas com pelo menos um modelo elegível;
- 4.494 modelos na Depreciação;
- 348 ocorrências no lado VE;
- 4.167 ocorrências no lado ICEV;
- dois registros sem identidade suficiente permaneceram fora da navegação pública.

Alguns modelos podem pertencer aos dois lados quando a classificação homologada do catálogo é mista; isso preserva o comportamento do classificador existente e não representa duplicidade de identidade.

Casos relevantes auditados:

- Ford Fiesta Class 1.0 2p (`modelo_id=773`) — fora de Simular/Depreciação;
- Ford Courier Van (`modelo_id=4134`, ano máximo 2012) — incluído na fronteira;
- BYD — catálogo de navegação no lado VE;
- Haval H6 PHEV19/PHEV34/PHEV35/GT — VE;
- Haval H6 HEV/HEV2 não plug-in — ICEV;
- Fipe+ — sem o recorte temporal.

SHA-256 do catálogo compilado:

`a0701158fb7bb99763cd66dc850b2a46e1b5dc55e8ebf1d76fd44d8be37b422e`

## Desempenho local

Com o catálogo carregado em memória:

- primeira leitura + resposta Ford ICEV: ~19,8 ms no container de teste;
- 1.000 consultas Ford ICEV subsequentes: ~1,10 ms por consulta em média;
- chamadas FIPE durante essas consultas: **0**.

Os números absolutos dependem do ambiente, mas a propriedade importante é arquitetural: a latência da lista deixa de depender do número de endpoints FIPE/PBEV necessários para preparar a marca.

## Anos e preços após selecionar o modelo

A V50.30 **não substitui a FIPE como fonte atual do veículo selecionado**. Depois que o usuário escolhe um modelo, a CurVE continua consultando os anos desse único modelo e, depois, o preço/competência selecionados pelo fluxo existente.

## Curvas salvas, verde, ✓ e similaridade

Não foram alterados. A lista pré-compilada entra no mesmo fluxo frontend já existente, e o serviço atual de marcadores continua aplicando curva própria/similaridade depois que os modelos são inseridos no dropdown.

## Atualização futura

`scripts/atualizar_catalogo_navegacao_fipe.py` é uma rotina de manutenção fora da navegação pública. Ela:

- compara o catálogo atual da FIPE com os IDs conhecidos;
- reaproveita modelos já conhecidos;
- consulta `/anos` somente para códigos realmente novos/desconhecidos;
- classifica esses novos modelos com o classificador atual;
- salva checkpoint `.build`;
- somente substitui o catálogo ativo após a conclusão integral, por operação atômica.

Em erro, timeout ou 429, o catálogo ativo anterior continua sendo servido.

## Arquivos funcionais alterados

- `services/fipe_service.py`
- `services/persistent_storage.py`
- `config.py`
- `data/fipe_cache/catalogo_navegacao_fipe_v1.json` (novo)
- `scripts/gerar_catalogo_navegacao_fipe_v1.py` (novo)
- `scripts/atualizar_catalogo_navegacao_fipe.py` (novo)

Além de testes/documentação.
