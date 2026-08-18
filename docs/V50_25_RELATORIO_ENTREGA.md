# Relatório de entrega — CurVE V50.25

## Base

- Versão: V50.24 homologada
- ZIP-base: `curve-v50-24-tco-reais-constantes.zip`
- SHA-256: `ab8db2f1d57e27bec9f4520df401dbe712e9b6777b287f4b7b8ee36c57fef05e`

## Escopo autorizado

Reavaliação anual do IPVA no TCO por meio do `IpvaService`, utilizando o estado projetado do veículo e preservando todas as demais metodologias da V50.24.

## Arquivos funcionais alterados

- `config.py` — versão V50.25;
- `routes/tco_routes.py` — integração anual com `IpvaService`, memória/auditoria e metadados do snapshot;
- `templates/simular.html` — envio do tipo de propulsão e apresentação do IPVA reavaliado;
- `templates/auditoria_tco.html` — memória anual do IPVA.

O `services/ipva_service.py` não foi alterado.

## Testes

Testes específicos V50.25 cobrem:

- arquitetura sem duplicação de regras estaduais;
- tributação sem mudança de condição;
- aquisição de isenção por idade;
- fronteira anterior/exata/posterior à idade cadastrada;
- veículo já isento;
- benefícios tecnológicos;
- zero km;
- independência de financiamento e seguro;
- IPVA manual e isenção futura;
- compatibilidade de contexto legado;
- interface/auditoria;
- congelamento em snapshot S;
- regressão da convenção monetária V50.24.

Resultados reproduzidos no ambiente de desenvolvimento:

- `compileall`: aprovado;
- suíte dirigida IPVA/TCO/Seguro/snapshots/PDF: 72 aprovados;
- regressão geral agregada: 349 aprovados, 29 falhas legadas já existentes, 10 ignorados e 63 subtests aprovados;
- 29 falhas: exatamente os mesmos grupos legados da V50.24, sem falha nova;
- Jinja: aprovado;
- `node --check`: aprovado nos blocos relevantes;
- Chromium/Playwright sobre a lógica JS modificada: 0 page errors e 0 console errors;
- 107/107 arquivos monitorados em `data/`: hashes idênticos antes/depois.

O ambiente não dispõe de Flask/gunicorn para iniciar a aplicação completa; a validação integral no site publicado permanece etapa de homologação do usuário.

## Preservação histórica

A recuperação de snapshots S históricos permanece baseada no payload congelado e não recalcula IPVA. D/F não foram alterados.

## Backlog — não alterado

Revisão jurídica/atualização integral das regras estaduais de IPVA cadastradas. Nenhuma regra foi alterada nesta rodada.
