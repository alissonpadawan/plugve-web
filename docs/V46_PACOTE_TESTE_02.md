# V46 — Pacote de teste 02

## Base e escopo

Este pacote é cumulativo e parte do **V46 pacote de teste 01**, que por sua vez foi construído sobre a V44 homologada.

O motor multivisão, a rota PBEV, a Consulta FIPE+, o TCO, ANEEL, ANP, IPVA, financiamento e as páginas institucionais não foram alterados nesta rodada.

A mudança de produção está restrita a:

- `templates/simular.html`;
- estados visuais e bloqueios temporários das consultas FIPE e PBEV/Inmetro;
- cancelamento de requisições antigas quando o usuário troca o veículo;
- testes e documentação correspondentes.

## Comportamento implementado

### Consulta FIPE

Ao selecionar ano/combustível:

- aparece um spinner com **“Consultando valor FIPE…”**;
- o campo de preço fica temporariamente somente leitura;
- o botão de financiamento fica bloqueado;
- os campos de consumo e perfis associados também permanecem bloqueados até a consulta oficial avançar;
- uma resposta antiga é descartada quando o usuário troca marca, modelo ou ano;
- após 45 segundos, a consulta é interrompida e o preço pode ser informado manualmente.

### Consulta PBEV/Inmetro

Enquanto o consumo está sendo consultado:

- aparece um spinner com **“Consultando consumo no Inmetro…”**;
- o campo principal de consumo fica somente leitura;
- no perfil flex, os dois consumos, o slider e o botão `Próximo/Salvar` ficam bloqueados;
- no perfil PHEV, os dois consumos, o slider e o botão `Próximo/Salvar` ficam bloqueados;
- o botão `Pular` continua disponível;
- após sucesso ou ausência de match, os campos são liberados;
- após 30 segundos ou erro, os campos são liberados para preenchimento manual.

### Proteção contra respostas atrasadas

As consultas FIPE e PBEV agora usam:

- `AbortController`;
- sequência independente por veículo (`atual`, `ve`, `icev`);
- validação da seleção atual antes de aplicar a resposta;
- cancelamento automático ao trocar o veículo.

Assim, uma resposta lenta do veículo anterior não pode preencher o veículo novo.

## Arquivos de produção alterados nesta rodada

- `templates/simular.html`.

O backend de matching do pacote 01 permaneceu byte a byte inalterado.

## Validações executadas

- `compileall` aprovado;
- 126 testes aprovados;
- 5 testes institucionais ignorados por ausência do pacote Flask no ambiente de montagem;
- 54 subtestes aprovados;
- 44 casos reais de matching aprovados;
- 15 templates aprovados no parser Jinja;
- 3 scripts inline da Simular aprovados no `node --check`;
- 7 scripts estáticos aprovados no `node --check`;
- Chromium headless com JavaScript real da Simular e respostas controladas.

No Chromium foram confirmados:

- `DOMContentLoaded` sem exceção;
- três controles de auditoria PBEV inicializados;
- seleção de UF e carregamento de município;
- geolocalização permitida e negada;
- spinner FIPE visível durante requisição pendente;
- preço, financiamento e consumo bloqueados durante FIPE;
- spinner Inmetro visível durante requisição PBEV;
- campos flex e PHEV bloqueados durante a consulta;
- desbloqueio após conclusão;
- cancelamento de requisição antiga ao trocar o ano;
- ausência de `ReferenceError`.

## Matching preservado

A suíte consolidada continua com:

- 44 casos aprovados;
- 31 decisões do motor multivisão;
- 13 decisões pelo fallback conservador V44;
- 0 regressões conhecidas.

## Rollback

Para voltar apenas o matching ao motor original V44:

```text
PBEV_MATCHING_ENGINE=v44
```

Essa variável não remove os novos indicadores de carregamento. Para rollback completo da interface desta rodada, reutilize o ZIP `curve-v46-pacote-teste-01.zip`.

## Checklist no Render

1. Fazer o deploy e abrir a Simular com `Ctrl + F5` ou janela anônima.
2. Selecionar um veículo e confirmar o spinner FIPE.
3. Tentar digitar preço e consumo durante a consulta; os campos devem permanecer bloqueados.
4. Confirmar a troca automática para o spinner Inmetro após o preço FIPE chegar.
5. Em um flex, verificar os dois consumos, slider e `Próximo` bloqueados durante a consulta.
6. Em um PHEV, repetir o mesmo teste.
7. Trocar rapidamente modelo/ano e confirmar que a resposta anterior não aparece.
8. Conferir UF, município, geolocalização, ANEEL, ANP, financiamento e TCO.

Este ainda é um candidato de teste, não um pacote final.
