# CurVE V50.16 — Inteligência de mercado no `/admin/uso`

## Objetivo

A V50.16 transforma os dados de telemetria já existentes em um recorte analítico combinado, sem alterar os cálculos da CurVE e sem passar a armazenar IP bruto.

## Filtros combinados

Os filtros de período continuam existentes e passam a trabalhar em conjunto com:

- tipo de atividade/módulo;
- veículo ou Código FIPE;
- tecnologia (BEV, PHEV, HEV/MHEV, ICEV e VE legado não detalhado);
- marca;
- cidade/UF aproximada do acesso;
- cidade/UF escolhida na simulação;
- visitante/dispositivo (ID pseudônimo, hash de rede, navegador, dispositivo ou SO);
- código histórico S/D/F.

A mesma combinação é enviada ao servidor para indicadores, rankings, visitantes e lista de atividades. Cidade do acesso e cidade utilizada na simulação continuam sendo dimensões independentes.

### Semântica dos cruzamentos

Filtros de veículo, marca e tecnologia são aplicados ao **evento**: um evento TCO é selecionado quando contém um veículo que satisfaz cada dimensão. Isso permite cruzamentos como “eventos que contêm Corolla e também algum BEV”. Os rankings do recorte mostram todos os veículos presentes nesses eventos, permitindo descobrir quais alternativas são comparadas entre si.

## Indicadores e rankings

Além dos indicadores anteriores, a V50.16 inclui:

- pesquisas concluídas (TCO + Depreciação + Fipe+);
- resultados históricos S/D/F reabertos;
- veículos mais pesquisados com visitantes únicos e decomposição por módulo;
- pares mais comparados com visitantes únicos;
- tecnologias e marcas;
- cidades/UFs escolhidas nas simulações;
- cidades/UFs aproximadas dos acessos;
- visitantes/dispositivos mais ativos;
- curva própria versus similaridade.

## Tecnologia na telemetria

Novos eventos passam a normalizar a tecnologia em `bev`, `phev`, `hev` e `icev` quando a informação é determinável. No TCO, o lado VE usa o tipo canônico escolhido pela interface e os lados ICEV/carro atual usam o classificador tecnológico já existente da plataforma. Isso é somente uma dimensão analítica; não participa do cálculo TCO.

Registros antigos gravados apenas como `ve` permanecem como **VE legado não detalhado**. A V50.16 não reclassifica dados históricos de forma especulativa.

## Privacidade

Permanece a arquitetura pseudonimizada:

- sem armazenamento de IP bruto;
- visitante pseudônimo;
- hash de rede;
- sessão;
- navegador, SO e classe de dispositivo;
- cidade/UF aproximada somente quando fornecida pela infraestrutura.

## Escopo

A V50.16 não altera TCO, FIPE, depreciação, seguro, matching PBEV, snapshots históricos, PDFs, curvas, vínculos ou dados persistidos em `data/`.
