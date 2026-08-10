# V50.07 — Painel administrativo de uso e tendências

## Acesso

Rota administrativa de interface:

`/admin/uso`

A página não foi adicionada ao menu público. Ela não recebe o token pela URL.
O administrador informa `PLUGVE_ADMIN_TOKEN` no próprio painel; o navegador o
mantém somente em `sessionStorage` e o envia no cabeçalho
`X-PlugVE-Admin-Token` das consultas administrativas.

As APIs continuam protegidas pelo mesmo contrato administrativo da V50.06.

## Filtros

- Hoje
- últimos 7 dias
- últimos 30 dias
- mês atual
- todo o histórico
- intervalo personalizado

## Indicadores

- visitantes únicos pseudonimizados;
- sessões;
- visualizações de página;
- simulações TCO concluídas;
- consultas de Depreciação;
- consultas Fipe+;
- exportações PDF.

## Tendências e rankings

- evolução diária de visitantes, TCO, Depreciação e Fipe+;
- veículos mais consultados, com filtro por módulo;
- pares mais comparados no TCO;
- tecnologias/propulsões registradas;
- marcas mais presentes nas consultas;
- municípios/UF escolhidos na simulação;
- cidade/UF aproximada do acesso quando fornecida pela infraestrutura.

## Visitantes e linha do tempo

A tabela de visitantes apresenta identificador pseudônimo, hash de rede
abreviado, localização aproximada quando disponível, sessões, eventos, última
atividade e contexto técnico coarse (navegador/dispositivo/SO).

Clicar em um visitante filtra a linha do tempo administrativa para mostrar as
ações registradas daquele identificador: consultas, simulações, exportações e
solicitações de curva. O filtro pode ser removido sem perder o período escolhido.

## Privacidade

A telemetria não grava nem exibe o IP bruto. `network_hash` e `visitor_hash` são
identificadores pseudônimos. Cidade/UF de acesso dependem dos cabeçalhos
fornecidos pela infraestrutura de hospedagem e são mantidas separadas da
localização escolhida pelo usuário para executar uma simulação.

## Persistência

Permanece em `site_usage.sqlite3`, dentro da estrutura persistente já definida
para produção. Não foi criado banco paralelo para o dashboard.
