# CurVE V45 — entrega final do matching FIPE × PBEV/Inmetro

## Resultado executivo

- Matriz geral: **31/31 casos aprovados**.
- Casos positivos localizados: **29/29**.
- Autofill automático seguro: **28** casos.
- Match médio confirmável: **1** caso de regressão controlado.
- Ausências reais preservadas: **2/2**.
- Registros utilizáveis da base auditados: **10.636**.
- Falsos identificadores comerciais compostos apenas por tokens técnicos: **0**.
- Suíte completa: **131 testes aprovados**, **5 pulados** e **10 subtestes aprovados**.

## Fluxo final

1. **Match alto**: o backend autoriza o preenchimento automático editável.
2. **Match médio tecnicamente plausível**: o site informa que o veículo foi localizado e apresenta as configurações PBEV para confirmação.
3. **Confirmação**: o navegador envia `confirmar_id_pbev`; o backend recalcula a consulta e só autoriza o ID se ele continuar entre as opções plausíveis.
4. **Match baixo ou ausência real**: nenhum consumo é aplicado.
5. **Edição manual**: remove a procedência; o selo só retorna após nova aplicação oficial PBEV.

## Integrações concluídas

- Simular TCO: botão compacto e modal de confirmação, sem alterar os cards homologados.
- Consulta FIPE+: opções compatíveis aparecem no card Inmetro/PBEV.
- Endpoint `/api/pbev/sugestao_consumo`: contrato antigo preservado e novos campos adicionados.
- Comprovação PBEV: registra quando a configuração foi confirmada pelo usuário.
- Cache: respostas de confirmação usam `Cache-Control: no-store`.

## Segurança da decisão

A confirmação humana não ignora bloqueios. A opção precisa possuir consumo válido, flags liberadas, combustível/propulsão compatíveis, família defensável, identidade mínima e ausência de bloqueios duros. Um ID inexistente ou fora das opções nunca recebe `autopreencher=true`.

## Casos representativos

- Creta Comfort 1.0 TB 12V 2026: match alto automático.
- Aventador SVJ Roadster 2021: match médio; configurações apresentadas; aplicação somente após confirmação.
- Ferrari SF90 Spider sem registro confiável: sem match e sem opções.

## Preservação

Não foram alterados o Painel Local, TCO, depreciação, ANP, ANEEL, financiamento, seguro, IPVA, snapshot ou armazenamento de curvas. A interface V44 foi mantida, com acréscimo somente do fluxo PBEV necessário para confirmação.

## Validações executadas

- `python -m compileall`;
- suíte `pytest` completa;
- matriz V45 de 31 casos;
- auditoria estrutural dos 10.636 registros utilizáveis;
- renderização Jinja das páginas afetadas;
- `node --check` em 5 scripts inline renderizados;
- inspeção de limpeza e estrutura do pacote.

## Limitação do ambiente

Não houve navegador real nem servidor Flask executável neste ambiente. Os cinco testes pulados já existentes dependem de Flask. A lógica backend, os contratos, os templates renderizados e a sintaxe JavaScript foram validados.
