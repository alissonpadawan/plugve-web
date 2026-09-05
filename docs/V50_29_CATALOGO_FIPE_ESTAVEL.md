# CurVE V50.29 — Catálogo FIPE temporal estável

## Escopo

A V50.29 corrige exclusivamente a elegibilidade temporal e o desempenho da lista de modelos na Simular TCO e na Depreciação.

- Simular TCO e Depreciação: somente Zero km ou modelo FIPE com algum ano-modelo >= 2012.
- Consulta Fipe+: catálogo integral da API FIPE, sem esse recorte temporal.
- PBEV continua responsável pela classificação de propulsão; não decide elegibilidade temporal.
- Marcadores de curvas próprias/similaridade (verde/✓) permanecem no fluxo existente.

## Baseline recuperado

O seed `data/fipe_cache/catalogo_elegibilidade_fipe_v2.json` foi compilado a partir do estado real da varredura recuperado do Persistent Disk do Render.

Estado recuperado:

- 80 marcas varridas;
- 27 marcas bloqueadas;
- decisões explícitas compiladas no seed v2: 3.902 modelos;
- decisões positivas explícitas: 1.217;
- decisões negativas explícitas: 2.685.

Para as 80 marcas varridas, o seed preserva temporariamente a semântica do sweep antigo: a denylist comprovada é aplicada de uma vez, sem consultar `/anos` durante a navegação. Decisões FIPE exatas posteriores sempre prevalecem.

## Navegação

A interação do usuário não executa varredura temporal.

`Marca -> lista FIPE/cache -> catálogo temporal local -> classificação VE/ICEV -> lista completa -> marcadores de curva`

Não há polling incremental nem inserção progressiva de modelos após o dropdown ser exibido.

## Consolidação exata

A rotina `scripts/consolidar_catalogo_fipe_v2.py` converte o baseline antigo em allowlist exata por código de modelo, fora da navegação do usuário.

Execução no Shell do serviço Render, a partir da raiz do projeto:

```bash
python scripts/consolidar_catalogo_fipe_v2.py --reference 334
```

A referência 334 corresponde ao ciclo mensal utilizado para reconstruir a varredura de junho/2026.

A rotina:

1. confronta as marcas varridas com a referência histórica;
2. reaproveita a denylist/Zero km da varredura;
3. verifica por `/anos` apenas os códigos que não pertencem ao baseline histórico, quando o histórico é reconciliável;
4. em caso de histórico não reconciliável, cai para verificação exata da marca;
5. grava progresso em `catalogo_elegibilidade_fipe_v2.json.build` após cada marca;
6. retoma o checkpoint se houver 429, timeout ou interrupção;
7. publica por substituição atômica somente ao concluir o catálogo inteiro.

Enquanto o `.build` está incompleto, o site continua lendo o catálogo ativo anterior. Uma allowlist parcial nunca é publicada.

Após a consolidação, cada marca fica com `status=completo`. Nesse modo, o catálogo funciona como allowlist: um novo código FIPE não aparece em Simular/Depreciação até ser verificado por uma nova manutenção. Isso impede a reentrada silenciosa de versões antigas adicionadas posteriormente pela FIPE.

## Atualizações futuras

Ao rodar novamente o consolidador sobre uma allowlist completa, decisões já comprovadas são reutilizadas. Se os códigos de uma marca não mudaram, a marca é mantida sem consultar anos novamente. Códigos novos são verificados exatamente.

A Consulta Fipe+ não usa essa allowlist e permanece integral.
