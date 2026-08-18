# V50.21 — Seguro V2: IPSA atual + AUTOSEG histórico por FIPE/região

## Objetivo

Substituir o estimador simples UF × tecnologia por uma estimativa estatística mais granular, preservando o valor editável pelo usuário e sem apresentar o resultado como cotação individual.

## Fontes parametrizadas

### IPSA/TEx — maio de 2026

O IPSA fornece o patamar contemporâneo do seguro como percentual do valor do veículo. A V50.21 utiliza o relatório detalhado de maio de 2026:

- índice geral: 4,6%;
- idade: zero km 3,0%; 0–2 anos 3,8%; 3–5 anos 5,0%; 6–10 anos 6,2%;
- valor FIPE: R$31–50 mil 8,5%; R$51–80 mil 6,1%; R$81–150 mil 3,8%; acima de R$151 mil 2,7%;
- veículos de até 2 anos, por propulsão: gasolina 3,5%; diesel 3,0%; híbrido 2,6%; elétrico 3,7%.

Os recortes por idade, valor e tecnologia não são multiplicados entre si. A referência contemporânea é a mediana das dimensões aplicáveis. Isso reduz contagem dupla de efeitos sobrepostos.

O recorte tecnológico somente é aplicado a veículos com até 2 anos, conforme a metodologia do relatório. Veículos com mais de 10 anos não são extrapolados pelo IPSA detalhado e usam explicitamente o fallback legado.

### AUTOSEG/SUSEP — 2021A

A base histórica foi processada a partir das tabelas oficiais AUTOSEG e compactada em:

`data/seguro/seguro_autoseg_2021A_curve_compact.sqlite`

O AUTOSEG não define o preço atual na V50.21. Ele é usado exclusivamente para fatores relativos históricos:

1. **região**: categoria/região ÷ mesma categoria/Brasil;
2. **modelo**: código FIPE/modelo ÷ categoria comparável;
3. **cidade**: prêmio médio do mesmo modelo/cidade ÷ modelo/região.

A tabela municipal não possui IS média e, por isso, nunca é usada como taxa absoluta.

## Credibilidade e redução dos fatores históricos

As células AUTOSEG são classificadas pela exposição observada:

- ALTA: exposição >= 50;
- MÉDIA: 20 a < 50;
- REFERÊNCIA: 5 a < 20;
- abaixo de 5: não entra na base compacta como fator específico.

Além da exposição, fatores antigos são reduzidos em direção a 1 por dois motivos: diferença entre o ano-modelo histórico e o ano-modelo consultado e envelhecimento da própria fonte AUTOSEG 2021A. Usa-se o componente mais conservador dos dois. Isso evita transportar integralmente um comportamento histórico antigo para um veículo atual ou para anos distantes do horizonte projetado.

Guardrails adicionais impedem que categorias residuais ou fatores extremos dominem o resultado.

## Cascata operacional

A estimativa busca, na ordem:

1. código FIPE + região + ano-modelo histórico mais próximo;
2. código FIPE nacional, quando não houver célula regional útil;
3. grupo histórico + região, quando o código existe no catálogo AUTOSEG mas não possui exposição suficiente no nível exato;
4. IPSA contemporâneo sem fator específico, para veículos novos sem histórico AUTOSEG;
5. estimador legado V1, apenas quando a base V2 não estiver disponível ou o veículo estiver fora do recorte etário do IPSA detalhado.

A categoria com maior exposição é priorizada em caso de múltiplas categorias para o mesmo código/ano, evitando categorias residuais.

## Fórmula conceitual

`taxa_IPSA = mediana(referências contemporâneas aplicáveis)`

`taxa_V2 = taxa_IPSA × fator_região_reduzido × fator_modelo_reduzido × fator_cidade_reduzido`

`seguro_anual = valor_FIPE × taxa_V2`

O resultado final recebe guardrail amplo entre 1% e 12% do valor de mercado somente como proteção contra extrapolações estatísticas extremas.

## Confiança

- **Alta**: reservada para uma futura evidência específica de veículo com fonte contemporânea (o AUTOSEG 2021A não recebe este rótulo final em 2026);
- **Média**: código FIPE específico com boa exposição histórica e granularidade regional/municipal, calibrado pelo IPSA contemporâneo;
- **Referência**: IPSA ou grupo/agregação sem evidência específica suficiente do código FIPE;
- **Fallback**: estimador legado usado explicitamente.

## Projeção no TCO

Quando o seguro é automático V2, o TCO não mantém uma taxa fixa por todo o horizonte. A cada ano ele reaplica o Seguro V2 usando:

- valor de mercado projetado naquele ano;
- idade projetada do veículo;
- mesmo código FIPE;
- mesma tecnologia;
- mesma localização escolhida.

Isso permite que mudanças de faixa de idade e valor FIPE alterem a taxa de referência ao longo do horizonte. O modelo não tenta prever o IPSA futuro: ele reaplica a estrutura de referência de maio/2026 às condições projetadas do veículo.

Quando o usuário informa manualmente o seguro, a decisão do usuário prevalece e a projeção mantém a lógica relativa anterior.

## Transparência na interface

A interface informa:

- fonte: IPSA/TEx + AUTOSEG/SUSEP;
- referência temporal;
- nível de agregação utilizado;
- confiança;
- aviso de que é estimativa estatística, não cotação individual.

O valor continua editável.
