# Validação da entrega — CurVE V45 Etapa 2

## Escopo executado

Implementação do núcleo geral de matching FIPE × PBEV/Inmetro sobre a base V44.3, sem alteração da interface homologada.

Arquivos de produção alterados:

- `services/pbev_service.py`;
- `data/pbev/aliases_automotivos_v1.json`.

Arquivos adicionados para teste e auditoria:

- `data/pbev/casos_regressao_matching_v45_etapa2.json`;
- `scripts/diagnosticar_matching_pbev_v45_etapa2.py`;
- `scripts/auditar_identidade_catalogo_pbev_v45.py`;
- `tests/test_pbev_matching_v45_diagnostico.py`;
- documentação e matrizes em `docs/auditoria_matching_v45_etapa2/`.

## Resultado funcional

- Matriz ponta a ponta: **31/31 casos aprovados**.
- Casos positivos localizados: **29/29**.
- Casos positivos autopreenchidos: **28/29**.
- Match médio conservador preservado: Lamborghini Aventador com ano distante.
- Casos negativos preservados: **2/2** — RAM 2500 e Ferrari SF90.
- Lacunas gerais corrigidas nesta etapa: Creta `TB 12V`, Hilux `TDI 16V`, abreviação `SPI/Spider` e distinção de MY no Volvo XC60.

## Auditoria estrutural da base

- Registros totais: **11.975**.
- Registros utilizáveis auditados pelo parser: **10.636**.
- Marcas auditadas: **64**.
- Falsos tokens comerciais formados apenas por componentes técnicos: **0**.

Essa auditoria valida o parser sobre a base PBEV. Ela não representa uma promessa de cobertura de toda nomenclatura FIPE futura; novos formatos continuam entrando como testes de regressão.

## Testes técnicos

- `python -m pytest -q`: **123 aprovados, 5 pulados e 10 subtestes aprovados**.
- `python -m compileall -q .`: aprovado.
- importação de `PbevService`: aprovada.
- diagnóstico V45 Etapa 2: **31/31 aprovado**.
- auditoria estrutural do catálogo: aprovada.

## Performance observada no ambiente de validação

- Creta, consulta quente: mediana aproximada de **196 ms**.
- Hilux, consulta quente: mediana aproximada de **391 ms**.
- SF90 ausente com busca de resgate: mediana aproximada de **140 ms**.

Os valores são medições locais e podem variar no Render.

## Preservação da V44

Hashes permanecem iguais aos da entrada para:

- `routes/pbev_routes.py`: `33cc7c06617c6de43d9d162c60328d39b3e4a7690885c370d038dcff3299d617`;
- `templates/simular.html`: `4c9b4d37173dd7202a834fa3a52d42bf23342b7258bbcf772c0342d34d4e5834`;
- `static/js/fipe.js`: `79a9af3efce9f80a59114cb33bd819706de5effb9e4d6360c4366625f5ab5d0b`;
- `app.py`: `bfed8bac9316d89eac49740581324d331e86f3a667d9f47ca629477e61eb6e09`.

Não foram alterados TCO, depreciação, ANP, ANEEL, IPVA, seguro, financiamento, Painel Local, snapshot ou armazenamento persistente.

## Limite da validação visual

Não foi executado navegador real nesta etapa. A regressão visual foi protegida por hashes e pelos testes existentes de templates e procedência; nenhum template, CSS ou JavaScript de produção foi alterado.
