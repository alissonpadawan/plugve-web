# V46 — Pacote de teste 01

## Base e escopo

Este pacote parte da V44 homologada. A página `templates/simular.html` e seu JavaScript inline não foram alterados. O SHA-256 preservado é:

`4c9b4d37173dd7202a834fa3a52d42bf23342b7258bbcf772c0342d34d4e5834`

A alteração está restrita ao backend PBEV, aos novos módulos de matching, aos testes e à documentação.

## Motor multivisão

O motor compara a entrada FIPE por várias representações simultâneas:

- texto canônico;
- texto segmentado;
- forma compacta;
- tokens e átomos comerciais;
- n-gramas de caracteres;
- evidências técnicas confiáveis;
- campos estruturados existentes na base PBEV.

Busca, bloqueios, ranking, equivalência técnica e decisão de autofill permanecem separados. A normalização preserva tanto a forma colada quanto a separada, evitando destruir identificadores como `xDrive40i`, `XC60`, `E2008`, `Style1.0` e `TB12V`.

## Segurança e rollback

O motor multivisão é o padrão deste pacote. A implementação homologada da V44 foi preservada integralmente como fallback.

Para rollback explícito no Render:

```text
PBEV_MATCHING_ENGINE=v44
```

Para ativar o pacote de teste de forma explícita:

```text
PBEV_MATCHING_ENGINE=multivisao
```

Valores diferentes de `v44`, `legacy` ou `atual` selecionam o motor multivisão.

## Arquivos de produção alterados ou adicionados

- `services/pbev_service.py`: fachada mínima e fallback;
- `services/pbev_matching_v46/`: motor isolado;
- `data/pbev/casos_regressao_matching_v46.json`: suíte consolidada de casos reais.

Nenhuma rota, template ou arquivo JavaScript de produção foi modificado.

## Auditoria reproduzível

Execute:

```bash
python scripts/auditar_matching_v46.py
```

O comando reprocessa os casos reais conhecidos e grava o relatório em `docs/V46_RELATORIO_REGRESSAO_PACOTE_TESTE_01.json`.

## Validações executadas antes do empacotamento

- compilação Python com `compileall`;
- 120 testes aprovados;
- 5 testes institucionais ignorados porque o ambiente de montagem não possui o pacote Flask instalado;
- 54 subtestes aprovados;
- 44 casos reais consolidados aprovados;
- parsing Jinja dos templates;
- verificação de sintaxe dos JavaScripts com Node;
- Chromium headless com execução real de `DOMContentLoaded`;
- inicialização dos três controles PBEV;
- carregamento de municípios após seleção de UF;
- geolocalização permitida;
- geolocalização negada;
- ausência de `ReferenceError` no bootstrap;
- conferência de que `templates/simular.html` permanece idêntico à V44.

O Chromium corporativo bloqueia navegação para `file://` e `localhost`. Para testar a execução, o HTML foi carregado pelo Chrome DevTools Protocol (`Page.setDocumentContent`), com os arquivos JavaScript locais reais incorporados e respostas externas controladas. Isso testa o bootstrap e os listeners no motor JavaScript real, mas não substitui a homologação final no Render.

## Checklist recomendado no Render

1. Abrir a Simular e confirmar console limpo.
2. Selecionar UF e município.
3. Testar “Usar minha localização” permitido e negado.
4. Consultar BEV, PHEV, HEV, flex, gasolina e diesel.
5. Conferir edição manual e remoção do selo Inmetro.
6. Conferir ANEEL, ANP e financiamento.
7. Executar o TCO.
8. Testar na Consulta FIPE+ o selo, a comprovação e o consumo.
9. Repetir os casos de regressão prioritários: Creta, C3 Live Plus, C3 YOU, BMW X7, Yuan Pro, HB20S, Fiesta, Haval H6, Volvo XC60/XC90 e os negativos SF90/XKR/XFR-S.

Este é um candidato de teste. Ele não deve ser chamado de pacote final antes da homologação no ambiente publicado.
