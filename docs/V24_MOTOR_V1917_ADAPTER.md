# V24 — Motor V19.17 em módulo paralelo

Esta entrega cria um caminho paralelo de diagnóstico para portar o motor local V19.17 do Painel de Depreciação para o PlugVE Web, sem alterar o botão definitivo de cálculo/salvamento.

## Arquivos alterados

- `services/depreciacao_motor_v1917_adapter.py`  
  Novo adapter paralelo. Reconstrói a série FIPE por referência mensal, busca primeira aparição, busca zero km base 32000, monta histórico amostrado, corrige por IPCA, trata pandemia e aplica offset de idade para veículo usado.

- `routes/depreciacao_routes.py`  
  Novas rotas isoladas:
  - `POST /api/depreciacao/diagnostico_v1917`
  - `POST /api/depreciacao/diagnostico_v1917/continuar`
  - `GET /api/depreciacao/diagnostico_v1917/status/<job_id>`

- `static/js/depreciacao.js`  
  O botão “Diagnóstico técnico” passa a chamar o diagnóstico V19.17. Quando a coleta não termina em uma chamada, o próprio botão continua o mesmo `job_id` no próximo clique.

- `templates/depreciacao.html`  
  Atualizado apenas o cache-buster do JS para carregar a nova versão no navegador.

## Regras preservadas

- O fluxo atual do site e a rota antiga `/api/depreciacao/diagnostico_coorte` foram preservados.
- O botão `/api/depreciacao/calcular` não foi ligado ao novo motor nesta etapa.
- Nenhuma curva é salva pelo diagnóstico V19.17.
- O modo padrão de pandemia no diagnóstico é `Excluir`, como usado no painel local.
- A coleta é persistida no disco configurado em `PERSISTENT_DIR/depreciacao_v1917`, que no Render deve ficar em `/var/data/plugve/depreciacao_v1917`.

## Como evita timeout

O adapter trabalha por fases e por lotes pequenos:

1. busca primeira aparição da coorte/base;
2. busca zero km base 32000;
3. planeja histórico mensal amostrado;
4. coleta poucas referências por chamada;
5. salva progresso em JSON no disco persistente;
6. o frontend reaproveita o `job_id` e continua a coleta no próximo clique.

O parâmetro padrão é `max_referencias_por_chamada = 4`, com teto interno de 12. Quando a fonte histórica ativa é o fluxo web V19.17 da FIPE, o lote é reduzido internamente para no máximo 2 referências por requisição, porque cada referência exige várias consultas encadeadas.

## Critério de qualidade

- 0 a 3 pontos usados: insuficiente, não calcular;
- 4 a 7 pontos usados: diagnóstico apenas;
- 8 a 15 pontos usados: exploratório;
- 16 a 23 pontos usados: média;
- 24+ pontos usados: alta;
- 50+ pontos usados: alta/robusta.

Mesmo quando a qualidade for alta, esta etapa continua sem salvar curva definitiva.

## Teste de validação recomendado

Usar o caso-padrão do painel local:

- Toyota Etios XLS 1.5 Flex 16V 5p Mec. 2013
- Código FIPE: `002124-5`
- Selecionar o veículo no painel web e clicar em “Diagnóstico técnico” repetidas vezes até aparecer `coleta_concluida = true`.

Para reproduzir exatamente a coorte local quando necessário, enviar no payload de diagnóstico:

```json
{
  "ano_base_preferencial": 2017,
  "modo_pandemia": "Excluir",
  "max_referencias_por_chamada": 4
}
```

A comparação esperada é metodológica: coorte/base, primeira aparição, zero km base, quantidade de pontos, janela histórica, taxa para plataforma e relatório técnico.


## Hotfix V24.1 — destravamento da coleta FIPE histórica

Após o primeiro teste online do Etios, o diagnóstico parou em `erro_api_fipe` antes de achar primeira aparição e zero km. A correção desta versão é:

- usar como caminho preferencial o mesmo fluxo histórico do painel local V19.17 pela FIPE Web: `ConsultarTabelaDeReferencia`, `ConsultarMarcas`, `ConsultarModelos`, `ConsultarAnoModelo` e `ConsultarValorComTodosParametros`;
- manter a API v2 apenas como fallback para carregar referências se a FIPE Web não responder;
- transformar falhas mensais antigas, 404 e referência sem modelo/ano em tentativa controlada, não em erro fatal;
- preservar erro fatal apenas para autenticação/limite quando aplicável;
- incluir `codigo_tipo_combustivel` e `ano_modelo_referencia` no ponto da primeira aparição para permitir consultar zero km 32000 e histórico sem recalcular códigos atuais;
- manter a etapa como diagnóstico: não altera `/api/depreciacao/calcular` e não salva curva definitiva.

## Atualização V24.3

No Render, o endpoint web `veiculos.fipe.org.br/api/veiculos` retornou HTTP 403. A partir da V24.3, o adapter não depende mais desse endpoint por padrão. Ele usa API FIPE v2 por código FIPE e referência mensal (`fipe_v2_codigo_fipe_v1917`), preservando o fluxo metodológico do painel local: primeira aparição, zero km 32000, histórico amostrado e cálculo diagnóstico. O endpoint `/history` curto continua não sendo usado como espinha dorsal.


## V24.5

Modo Pública/Pública aplicado ao diagnóstico paralelo: token/API paga ignorados e histórico por FIPE Web pública, seguindo o fluxo do painel local.


## V24.6

Como o Render bloqueou o endpoint público Web da FIPE com 403, o diagnóstico paralelo passou a usar a API PRO oficial `https://fipe.parallelum.com.br/api/v2`, com token em `FIPE_TOKEN`, montando histórico por referências mensais, código FIPE e `yearId`. O endpoint `/history` não é usado como espinha dorsal; a coleta continua em lotes pequenos e sem salvar curva definitiva.
