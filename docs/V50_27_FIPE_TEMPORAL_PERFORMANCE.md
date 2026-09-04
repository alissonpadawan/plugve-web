# CurVE Site V50.27 — Elegibilidade temporal FIPE e desempenho do catálogo

## Base

- Base homologada: V50.26
- SHA-256 da base: `0942f619b5e694134ae6f58a057b64f7333482d3d22c4f3734fe4ef5b04f04c4`

## Problema

Simular TCO e Depreciação podiam listar um modelo FIPE sem qualquer ano-modelo elegível (Zero km ou ano >= 2012). A lista de anos então só revelava o problema depois da seleção do modelo. O caso reproduzido foi um Ford Fiesta Class antigo.

A causa era a mistura de duas responsabilidades: a PBEV podia ser usada como evidência temporal quando o estado da varredura FIPE estava incompleto, e o status positivo da marca varrida podia ser usado para liberar modelos sem uma decisão temporal individual. Havia ainda proteção nominal no JavaScript capaz de impedir o bloqueio de um modelo antigo mesmo quando a FIPE havia retornado apenas anos anteriores a 2012.

Além disso, a seleção de marca repetia trabalho: leituras de JSON por modelo, evidência PBEV para a decisão temporal, nova classificação PBEV para propulsão e regravação do catálogo em consultas normais.

## Regra V50.27

A decisão temporal passou a ter uma única fonte de verdade: a lista de anos do modelo FIPE exato.

- elegível: possui Zero km ou pelo menos um ano-modelo >= 2012;
- inelegível: a FIPE exata retornou anos, mas todos são anteriores a 2012 e não existe Zero km;
- pendente: não há decisão persistida e a consulta exata falhou/não foi conclusiva.

Um modelo pendente não é liberado por similaridade PBEV nem pelo estado da marca. A próxima consulta poderá tentar novamente.

A PBEV permanece responsável por classificação/matching de propulsão (VE/ICEV/HEV/PHEV etc.), mas não decide idade/elegibilidade temporal.

## Persistência e desempenho

A decisão temporal exata é persistida por `codigo_marca + codigo_modelo` em `catalogo_elegibilidade_fipe_v1.json`. O catálogo agora preserva, no mesmo registro, metadados temporais e de classificação PBEV.

Para modelos ainda desconhecidos, as consultas de anos são feitas com concorrência limitada (padrão 4), apenas até formar a decisão individual. As respostas do catálogo FIPE continuam aproveitando o cache HTTP já existente.

A lista final filtrada também possui cache em memória por marca/contexto (padrão 300 s) e é invalidada quando o estado temporal relevante muda.

A classificação PBEV persistida recebe uma assinatura do arquivo-base PBEV; enquanto a base não mudar, ela pode ser reutilizada sem reclassificar o modelo em cada seleção.

## Medição controlada

Em um benchmark sintético com 80 modelos:

### V50.26 — seleção repetida

A cada repetição da mesma marca, observou-se aproximadamente:

- 1 chamada à lista de modelos;
- 329 leituras de JSON de estado;
- 80 buscas `model_evidence` da PBEV para temporalidade;
- 80 classificações PBEV;
- 1 regravação do catálogo.

### V50.27

Com 80 modelos inicialmente não verificados e latência sintética de 20 ms por consulta de anos:

- primeira verificação exata: ~0,407 s com 4 workers;
- repetição no mesmo processo: ~0,00045 s, sem novas consultas/classificações;
- simulação de novo processo com índice temporal/PBEV persistido: ~0,0011 s, sem chamadas de anos e sem classificação PBEV.

Esses tempos são benchmark local controlado, não promessa de latência da API em produção. A primeira ocorrência de modelos sem decisão pode depender da latência externa; as decisões comprovadas ficam persistidas para evitar repetir o custo.

## Curvas salvas e marcadores

A arquitetura de marcadores foi preservada. Permaneceram bit a bit inalterados:

- `services/depreciacao_service.py`;
- `static/js/curve_marcadores_curvas.js`;
- `static/js/depreciacao.js`;
- `templates/simular.html`.

O fluxo continua:

`/api/depreciacao/marcadores_curvas` -> marcador de curva própria/similaridade -> aplicação visual verde/✓ após a lista FIPE.

A alteração em `static/js/fipe.js` mantém as chamadas a `CurVE.marcadores.aplicarNoOption`, `aplicarNoSelect` e `aplicarChecksModelosFipe`.

## Consulta Fipe+

A Consulta Fipe+ usa os endpoints públicos separados e continua integral. A regra >=2012/Zero km pertence somente a Simular TCO e Depreciação.
