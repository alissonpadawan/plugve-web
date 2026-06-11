# V23 — Análise geral do fluxo de depreciação

## Diagnóstico do problema

O painel local antigo funcionava melhor porque não tentava usar o código atual do veículo em referências antigas. Ele entrava primeiro no mês de referência da FIPE e, dentro daquele mês, reconstruía a busca: marca, modelo, ano e preço.

No web, os primeiros pacotes tentaram atalhos. Esses atalhos eram rápidos, mas falhavam para modelos antigos/descontinuados e podiam cair em proxy fraco. O log do Render mostrou que a coleta por referências também podia dar timeout quando tentava consultar pontos demais em uma única requisição.

## Princípio adotado agora

Não reinventar o painel antigo. Adaptar a lógica dele ao Flask/Render/API v2.

O novo diagnóstico passa a usar o fluxo:

1. referência mensal;
2. marca dentro daquela referência;
3. ano dentro daquela marca/referência;
4. modelos daquele ano/referência;
5. preço.

Essa ordem reproduz a lógica visual da FIPE web antiga e evita depender de código atual para consultar meses antigos.

## Casos que precisam tratamento separado

### 1. Zero km com curva familiar salva

Usa a curva salva da família desde idade zero. Não precisa recalcular.

### 2. Zero km sem curva familiar salva

Escolhe uma coorte usada representativa. Preferência: ano atual menos 7. Se não existir, usa ano próximo disponível. Monta curva da família e aplica ao valor FIPE zero km atual.

### 3. Usado com curva familiar salva

Não reinicia a curva. Calcula a idade atual do veículo e projeta a partir daquele ponto da curva.

### 4. Usado sem curva familiar salva

Monta a curva da família usando uma coorte representativa. Depois aplica a curva a partir da idade atual do veículo selecionado.

### 5. Modelo recente

Se existir há poucos anos, usa janela curta e coleta mais densa. A confiança deve ser exploratória se houver poucos pontos.

### 6. Modelo descontinuado

Usa o último ano útil disponível ou o ano mais próximo de ano atual - 7. Não força zero km se o modelo não existe mais como zero km.

### 7. Histórico suficiente

Com histórico suficiente, calcula a curva familiar por coorte: IPCA, pandemia, ratio e projeção.

### 8. Histórico insuficiente

Não salva curva definitiva. O sistema mostra diagnóstico e motivo.

### 9. Proxy técnico

Proxy só entra depois de tentar mesma família/modelo/coorte. Quando usado, deve aparecer como proxy no relatório.

### 10. Limite ou erro FIPE

Não bloqueia modelo e não salva curva. Interrompe e mostra erro controlado.

## Regra de segurança

- Não salvar curva com zero pontos históricos.
- Não salvar curva se a coleta falhar.
- Não usar SUV como proxy de hatch sem aviso claro.
- Não consultar pontos demais em uma única chamada.
- Manter diagnóstico separado antes de ligar o motor definitivo.

## O que este pacote altera

- Adiciona `services/fipe_historico_painel_adapter.py`.
- Adiciona métodos FIPE v2 para consulta por referência: marcas, anos da marca, modelos por ano e preço.
- Altera o diagnóstico de coorte para usar a ordem do painel antigo: referência -> marca -> ano -> modelos -> preço.
- Mantém o cálculo principal sem substituição definitiva.
- Não salva curva ainda pelo novo motor.

## Próximo passo depois de validar

Quando o diagnóstico começar a retornar pontos suficientes, ligar o mesmo adaptador ao motor definitivo de depreciação por família/coorte.
