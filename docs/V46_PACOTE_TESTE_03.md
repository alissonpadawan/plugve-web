# V46 — Pacote de teste 03

## Base e escopo

Este pacote é cumulativo e parte do **V46 pacote de teste 02**, construído sobre a V44 homologada.

A rodada 03 corrige o catálogo FIPE usado pela **Simular** e pela **Depreciação**, sem restringir a **Consulta FIPE+**.

Regras implementadas:

- Simular e Depreciação só exibem marcas que tenham ao menos um modelo elegível;
- modelos exclusivamente anteriores a 2012 são ocultados;
- anos anteriores a 2012 são removidos no backend;
- Zero km continua elegível e não é tratado como ano;
- lado VE aceita somente BEV e PHEV;
- lado ICEV aceita combustão, flex, gasolina, diesel, HEV e MHEV;
- PHEV não compete no lado ICEV;
- HEV não plug-in não compete no lado VE;
- FIPE+ continua usando os endpoints públicos integrais e preserva marcas, modelos e anos anteriores a 2012.

## Aproveitamento do robô de varredura

O robô já existente continua sendo a principal fonte do recorte temporal. O pacote lê diretamente, quando presentes no Persistent Disk do Render:

```text
/var/data/plugve/fipe_cache/marcas_varridas.json
/var/data/plugve/fipe_cache/marcas_bloqueadas.json
/var/data/plugve/fipe_cache/modelos_bloqueados.json
/var/data/plugve/fipe_cache/modelos_zero_km.json
/var/data/plugve/fipe_cache/modelos_novos.json
/var/data/plugve/fipe_cache/progresso_varredura.json
```

Esses arquivos **não são sobrescritos no bootstrap**. O pacote apenas cria sementes vazias quando o arquivo ainda não existe.

Não foi possível exportar o conteúdo real do Render durante a montagem, pois o ambiente de validação não possui acesso de rede ao serviço publicado. Portanto, o ZIP não contém uma cópia inventada da varredura: ele consome o estado persistente que já estiver conectado ao serviço.

## Fallback quando o estado do robô não existe

Se o Persistent Disk estiver vazio ou desconectado, o backend usa a base PBEV local como evidência conservadora de existência pós-2012. Isso impede que marcas sem qualquer evidência contemporânea, como o Cadillac do caso testado, sejam liberadas indiscriminadamente.

Esse fallback é propositalmente conservador. Um modelo pós-2012 muito raro, ausente da PBEV e sem estado salvo pelo robô, pode permanecer oculto até que o catálogo seja novamente varrido. Essa limitação é preferível a liberar todo o catálogo antigo na Simular e na Depreciação.

## Classificação de propulsão

Foi criado `services/fipe_catalog_classifier.py`.

Ele combina:

- indicações explícitas no nome e no combustível FIPE;
- evidências da base PBEV local;
- normalização multivisão já usada pelo matching V46;
- ano exato ou adjacente quando disponível;
- regra conservadora para o texto genérico “Híbrido”.

O lado da interface não transforma mais, por si só, um híbrido genérico em PHEV. O backend classifica antes de devolver modelos e anos.

## Índice de elegibilidade e auditoria

O pacote acrescenta:

```text
data/fipe_cache/catalogo_elegibilidade_fipe_v1.json
```

No Render, o arquivo operacional fica em:

```text
/var/data/plugve/fipe_cache/catalogo_elegibilidade_fipe_v1.json
```

Ele registra, de forma aditiva:

- contextos permitidos por modelo e ano;
- tipo de propulsão interpretado;
- origem e confiança da classificação;
- score e margem PBEV usados como evidência;
- data da última atualização.

Esse índice não substitui os arquivos do robô e não altera o catálogo integral da FIPE+.

## Autocorreção durante o uso

Quando o endpoint de anos confirma que um modelo possui somente anos anteriores a 2012:

- o modelo é salvo em `modelos_bloqueados.json`;
- ele deixa de aparecer nas próximas consultas;
- se todos os modelos da marca forem confirmados como antigos, a marca também é bloqueada.

Quando existe Zero km, o modelo é salvo em `modelos_zero_km.json`.

## Proteção contra cache antigo do navegador

As chamadas da Simular e da Depreciação usam a versão:

```text
catalogo=v46_03
```

Isso evita que o navegador reutilize por horas as listas não filtradas do pacote anterior. A API ignora esse parâmetro na regra de negócio; ele funciona apenas como versionamento de cache.

## Arquivos de produção alterados

- `services/fipe_catalog_classifier.py` — novo classificador local de propulsão;
- `services/fipe_service.py` — recorte temporal, contexto, persistência e autocorreção;
- `services/tipo_veiculo_service.py` — reconhecimento do contexto Depreciação;
- `services/persistent_storage.py` — bootstrap não destrutivo do novo índice;
- `static/js/fipe.js` — Depreciação passa a solicitar o catálogo filtrado;
- `templates/simular.html` — passa a confiar no backend para anos e força a nova versão do catálogo;
- `data/fipe_cache/catalogo_elegibilidade_fipe_v1.json` — semente versionada.

## Áreas preservadas

Permaneceram byte a byte iguais ao pacote 02:

- `app.py`;
- `routes/pbev_routes.py`;
- `services/pbev_service.py`;
- `routes/tco_routes.py`;
- `services/depreciacao_service.py`;
- `templates/consulta_fipe.html`.

Assim, o matching PBEV, o TCO, a fórmula de depreciação e a FIPE+ não foram reescritos nesta rodada.

## Validações executadas

- `compileall` aprovado;
- 134 testes aprovados;
- 5 testes ignorados por ausência do Flask no ambiente de montagem;
- 54 subtestes aprovados;
- 44 de 44 casos reais de matching aprovados;
- 15 templates aprovados no parser Jinja;
- 3 scripts inline da Simular e 7 scripts estáticos aprovados no `node --check`;
- Chromium headless com o JavaScript real da Simular e respostas de catálogo controladas.

No Chromium foram confirmados:

- `DOMContentLoaded` concluído;
- ausência de `ReferenceError`;
- chamada de marcas com `contexto=ve` e `contexto=icev`;
- BYD exibida no lado VE e não no ICEV no cenário controlado;
- GWM exibida no lado ICEV e não no VE no cenário controlado;
- Yuan Pro e Zero km carregados no lado VE;
- Haval H6 HEV e ano 2025 carregados no lado ICEV;
- modelos e anos solicitados com o contexto correto no backend.

## Checklist no Render

1. Fazer o deploy usando o mesmo Persistent Disk e o mesmo caminho `/var/data/plugve`.
2. Abrir a Simular em janela anônima ou usar `Ctrl + F5`.
3. Confirmar que Cadillac/Deville não aparece na Simular e na Depreciação.
4. Confirmar que o mesmo Cadillac continua disponível na FIPE+.
5. Verificar uma marca que só possua modelos antigos: a marca inteira não deve aparecer.
6. Testar BYD/Tesla no lado ICEV: não devem aparecer ali.
7. Testar um BEV e um PHEV no lado VE.
8. Testar um HEV/MHEV no lado ICEV.
9. Testar uma família com HEV e PHEV, conferindo cada lado.
10. Confirmar que Zero km permanece disponível.
11. Conferir localização, carregamentos FIPE/Inmetro, ANEEL, ANP e TCO.

## Diagnóstico do estado persistente

A rota protegida continua disponível:

```text
/api/fipe/catalogo/status
```

Ela informa contagens de marcas varridas, marcas bloqueadas, modelos bloqueados, Zero km e decisões do novo índice. Exige o token administrativo/sincronização já configurado no serviço.

Este é um **candidato de teste**, não o pacote final.
