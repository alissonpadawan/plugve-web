# CurVE Site V50.27 — Relatório de entrega

## Base
- V50.26 homologada
- SHA-256: `0942f619b5e694134ae6f58a057b64f7333482d3d22c4f3734fe4ef5b04f04c4`

## Escopo autorizado
1. Impedir modelos FIPE exclusivamente pré-2012 em Simular/Depreciação.
2. Remover PBEV da decisão temporal.
3. Impedir liberação por marca varrida/proteção nominal sem evidência FIPE exata.
4. Reduzir trabalho repetido na seleção de marca.
5. Preservar verde/✓, curvas próprias, similaridade, VE×ICEV, Zero km e Fipe+ integral.

## Causa
A V50.26 podia usar evidência PBEV ou estado agregado da marca como substituto de uma prova temporal do modelo FIPE exato. A tela só confirmava os anos depois que o modelo já havia sido mostrado. A consulta também relia estados e repetia classificação por modelo.

## Alteração
- Índice temporal individual por código de modelo, baseado nos anos FIPE exatos.
- PBEV exclusivamente para propulsão/matching.
- Modelo temporal desconhecido é validado pela FIPE antes de aparecer; falha deixa pendente, sem falso positivo.
- Remoção da proteção nominal que podia vencer uma resposta FIPE válida.
- Leitura única dos estados por requisição.
- Persistência em lote somente de decisões novas/alteradas.
- Reuso da classificação PBEV persistida enquanto a base PBEV não mudar.
- Cache backend da lista final filtrada com invalidação do estado relevante.

## Arquivos funcionais alterados
- `services/fipe_service.py`
- `static/js/fipe.js`
- `config.py`

Testes existentes foram ajustados apenas para o contrato temporal novo e versionamento; foi acrescentado `tests/test_v50_27_fipe_temporal_performance.py`.

## Preservações comprovadas
Os arquivos centrais dos marcadores/curvas e o template Simular ficaram bit a bit iguais à V50.26. Os 107 arquivos monitorados em `data/` também permaneceram idênticos.

## Testes
- `compileall`: aprovado.
- `node --check`: `fipe.js`, `depreciacao.js`, `curve_marcadores_curvas.js` aprovados.
- focados V50.27/catálogos + preservação: 32 aprovados.
- regressão completa: 364 aprovados, 29 falhas legadas, 10 ignorados, 63 subtests aprovados.
- as 29 falhas são os mesmos quatro grupos legados já presentes na V50.26; nenhuma falha nova foi criada.
- Chromium real/headless via `page.set_content`: 0 page errors, 0 console errors; o marcador ✓ permaneceu aplicado no option de teste.

## Limitação de browser
O ambiente bloqueia navegação `file://` e `http://127.0.0.1`, portanto o site Flask completo não foi iniciado. O JavaScript efetivamente alterado foi executado em Chromium real por conteúdo injetado, com DOM e funções de marcador.

## Teste recomendado em produção
1. Simular/Depreciação -> Ford: modelo antigo sem Zero km/2012+ não deve aparecer.
2. Modelo Ford com ano 2012+ deve permanecer.
3. Selecionar BYD duas vezes: após o primeiro preenchimento/verificação, repetição deve ser significativamente mais rápida.
4. Confirmar que modelos com curvas próprias continuam verdes/✓.
5. Confirmar que modelos por similaridade continuam marcados conforme o vínculo atual.
6. Na Consulta Fipe+, procurar um modelo antigo e confirmar que ele continua disponível.
