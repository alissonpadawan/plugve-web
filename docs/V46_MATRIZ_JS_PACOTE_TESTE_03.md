# V46.03 — Matriz de rastreabilidade JavaScript

Nenhuma função JavaScript foi removida ou renomeada nesta rodada.

| Função | Arquivo | Definição | Chamadas/listeners principais | Alteração V46.03 | Substituta | Teste associado |
|---|---|---:|---|---|---|---|
| `carregarMarcas` | `templates/simular.html` | linhas ~3796 e override em ~7398 | `DOMContentLoaded`; restauração do formulário | adiciona `contexto` e `catalogo=v46_03`; consome lista filtrada do backend | não se aplica | `test_v46_03_fipe_catalog.py`; Chromium |
| `carregarModelos` | `templates/simular.html` | linhas ~3821 e override em ~7423 | listeners `change` de marca VE/ICEV/atual; restauração | envia contexto e nome da marca; recebe apenas modelos elegíveis | não se aplica | `test_v46_03_fipe_catalog.py`; Chromium |
| `carregarAnos` | `templates/simular.html` | linhas ~3861 e override em ~7491 | listeners `change` de modelo VE/ICEV/atual; restauração | backend passa a decidir recorte e propulsão; JS não reclassifica o ano | não se aplica | `test_v46_03_fipe_catalog.py`; Chromium |
| `carregarMarcasFipe` | `static/js/fipe.js` | linha ~596 | inicialização da Depreciação; varredura; restauração | usa `contexto=depreciacao` e versão de cache V46.03 | não se aplica | `test_v46_03_fipe_catalog.py`; `node --check` |
| `carregarModelosFipe` | `static/js/fipe.js` | linha ~625 | listener de marca da Depreciação | usa catálogo temporal filtrado e preserva o robô | não se aplica | `test_v46_03_fipe_catalog.py`; `node --check` |
| `carregarAnosFipe` | `static/js/fipe.js` | linha ~683 | listener de modelo da Depreciação | recebe apenas 2012+ ou Zero km do backend | não se aplica | `test_v46_03_fipe_catalog.py`; `node --check` |
| `varrerMarcaAtual` | `static/js/fipe.js` | linha ~287 | botão de varredura/continuação | não removida; continua consultando catálogo bruto para auditar todos os modelos | não se aplica | regressão estática e preservação dos JSONs |

## Ordem e dependências

- O primeiro bloco da Simular registra os listeners no `DOMContentLoaded`.
- O segundo bloco mantém os wrappers globais usados pela restauração e pelos comboboxes.
- As duas implementações continuam presentes por compatibilidade; ambas receberam o mesmo parâmetro de versão e o mesmo contrato de backend.
- `fipe_combobox.js` continua sendo carregado ao final e não teve funções removidas.
- As chamadas FIPE da Simular permanecem posteriores à inicialização PBEV, mas não foram introduzidas novas funções obrigatórias no bootstrap.

## Resultado da verificação

- 3 scripts inline aprovados no `node --check`;
- 7 scripts estáticos aprovados no `node --check`;
- Chromium sem `ReferenceError`;
- `DOMContentLoaded` concluído;
- chamadas de marcas, modelos e anos observadas com os contextos corretos.
