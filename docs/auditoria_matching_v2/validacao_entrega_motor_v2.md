# CurVE V45 — Validação da entrega Motor PBEV V2

Data: 26/07/2026

## Escopo autorizado

- reconstrução da camada de matching FIPE × PBEV/Inmetro;
- normalização automotiva e identidade técnica V2;
- separação prévia de propulsão por lado da Simular;
- decisão automática;
- remoção da confirmação manual;
- testes reais e sintéticos;
- preservação das demais funcionalidades da V44.

A frente futura de ocultar marcas/modelos sem ano válido não foi implementada nesta entrega.

## Resultados funcionais

### Regressões reais novas

- casos: 13;
- aprovados: 13;
- autofills esperados: 10;
- negativos/manuais preservados: 3;
- confirmações manuais: 0.

### Matriz legada/ampliada

- casos: 31;
- aprovados: 31;
- positivos localizados: 29;
- positivos autopreenchidos: 28;
- negativos preservados: 2.

### Suíte automatizada

- testes aprovados: 138;
- testes pulados: 5;
- subtestes aprovados: 27.

Os testes pulados dependem de um ambiente Flask completo não disponível no runtime de validação.

## Benchmark sintético

Amostra balanceada por marca:

- registros PBEV utilizáveis: 10.636;
- registros amostrados: 500;
- variações por registro: 3;
- consultas sintéticas: 1.500.

Resultados de recuperação:

- Recall@1: 99,2%;
- Recall@3: 99,6%;
- Recall@5: 99,6%.

Decisão final avaliada em 200 consultas sintéticas:

- autofills: 181;
- autofills corretos: 181;
- falsos autofills: 0;
- precisão de autofill no benchmark: 100%;
- cobertura automática sintética: 90,5%.

Desempenho:

- latência média do ranking: 5,84 ms;
- percentil 95: 9,63 ms.

O benchmark aceita como correto o registro original ou outro registro tecnicamente equivalente com o mesmo consumo. Ele não substitui uma base completa de pares FIPE reais e não autoriza afirmar 100% literal para qualquer nomenclatura futura.

## Interface e contrato

- confirmação manual removida da Simular;
- confirmação manual removida da Consulta FIPE+;
- backend não aceita mais um ID escolhido pelo usuário como mecanismo de decisão;
- match alto continua aplicando valores editáveis;
- edição manual continua removendo a procedência Inmetro;
- comprovação e auditoria continuam disponíveis;
- campos de compatibilidade antigos retornam confirmação desativada.

## Preservação de áreas protegidas

Comparados com o ZIP V45 anterior, permaneceram com hash SHA-256 idêntico:

- `app.py`;
- `routes/tco_routes.py`;
- `routes/depreciacao_routes.py`;
- `services/combustivel_service.py`;
- `services/energia_service.py`;
- `services/depreciacao_service.py`;
- `services/fipe_service.py`;
- `core/motor_combustao_web.py`;
- `templates/depreciacao.html`;
- `templates/relatorio_pdf.html`.

As alterações de produção ficaram restritas à integração PBEV, ao novo motor, aliases, dependência RapidFuzz e remoção autorizada da confirmação nas páginas que consultam o Inmetro.

## Validações técnicas

- `compileall`: aprovado;
- importação e suíte Python: aprovadas;
- diagnóstico de 13 casos reais: aprovado;
- diagnóstico de 31 casos legados/ampliados: aprovado;
- verificação estática dos blocos JavaScript com Node: aprovada;
- busca por referências órfãs do fluxo de confirmação: nenhuma referência funcional encontrada.

## Limitação do ambiente

Não foi possível iniciar um servidor Flask completo nem executar navegação visual real neste ambiente. Por isso, a validação de interface foi feita por testes estáticos, inspeção de templates e verificação sintática JavaScript. O usuário deverá realizar o teste final após publicar o ZIP.
