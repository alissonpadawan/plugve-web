# CurVE V50.11 — Snapshots imutáveis e identificadores S/D/F

## Objetivo

A V50.11 cria a fundação de rastreabilidade temporal dos resultados. Cada resultado concluído passa a poder receber um identificador único:

- `S-AAAAMMDD-XXXXXXXXXX` — Simulação/TCO;
- `D-AAAAMMDD-XXXXXXXXXX` — Depreciação;
- `F-AAAAMMDD-XXXXXXXXXX` — Consulta Fipe+.

O identificador aponta para um **snapshot imutável** persistido no disco do Render. A etapa V50.11 não cria ainda a tela pública de recuperação por código; ela congela e testa o resultado original para que uma etapa posterior possa reabri-lo sem recalcular FIPE, inflação, custos ou curvas.

## Persistência

Banco dedicado:

`/var/data/plugve/institucional/result_snapshots.sqlite3`

No desenvolvimento local, o arquivo segue `PLUGVE_PERSISTENT_DIR`/fallback da configuração.

Cada registro guarda:

- código do resultado;
- tipo S/D/F e módulo;
- data/hora UTC e `America/Sao_Paulo`;
- versão do schema e da plataforma;
- SHA-256 do conteúdo canônico;
- tamanho do snapshot;
- JSON canônico do snapshot;
- hashes pseudônimos de visitante/sessão quando disponíveis.

Não há IP bruto no banco de resultados.

## Imutabilidade

A tabela possui triggers SQLite que bloqueiam `UPDATE` e `DELETE`. Uma nova consulta ou um futuro “recalcular com dados atuais” deve gerar **outro código**, nunca alterar o registro histórico.

## Conteúdo por módulo

### S — Simulação/TCO

Preserva entradas do formulário, veículos/códigos FIPE, parâmetros, resultados calculados, componentes, memória anual, cenários e auditoria. HTMLs Plotly são removidos do snapshot para evitar crescimento desnecessário do banco; os dados numéricos que originam as visualizações são preservados para futura renderização sem recálculo econômico.

### D — Depreciação

Preserva o payload da consulta e a resposta completa da curva aplicada. Consultas internas feitas pela Simular ou pela Fipe+ não geram D adicional; somente a consulta direta do usuário na Depreciação recebe D.

### F — Consulta Fipe+

Somente a página Fipe+ solicita `contexto_resultado=fipe_plus` ao endpoint FIPE. Simular e Depreciação continuam consultando o mesmo catálogo/preço sem gerar falsos identificadores F. O snapshot preserva códigos de catálogo, resposta FIPE, preço e referência originais.

## Segurança e integridade

- sufixo aleatório com 10 caracteres de alfabeto sem caracteres ambíguos;
- hash SHA-256 do JSON canônico;
- comparação de integridade disponível na leitura interna;
- banco separado da telemetria de uso;
- limite de 3 MB por snapshot;
- falha de persistência não altera o cálculo original, mas é registrada em log e o resultado fica sem código.

## Fora do escopo desta etapa

Ainda não implementado na V50.11:

- campo “Consultar resultado”;
- rota pública de recuperação por código;
- página histórica de S/D/F;
- botão “Refazer com dados atuais”;
- padronização final dos nomes dos PDFs com o código;
- garantia de inclusão visual do código em todos os PDFs (etapa posterior de PDF/rastreabilidade).
