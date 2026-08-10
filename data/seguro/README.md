# Seguro — referência simples UF + tecnologia

Esta versão remove o percentual universal de seguro e mantém uma estimativa automática simples, editável e auditável.

## 1. Componente geográfico

Para cada UF, a taxa-base é obtida a partir da referência regional AUTOSEG/SUSEP:

`taxa_UF = prêmio médio / importância segurada média`

Na ausência de UF válida, utiliza-se a referência nacional (`BR`).

Base regional desta V1:
- automóvel/CASCO;
- 1º semestre de 2020;
- tabela regionalizada elaborada a partir de informações de mercado da SUSEP.

## 2. Ajuste de tecnologia

A tecnologia não recebe percentual autoral. O ajuste é relativo ao comparativo do IPSA/TEx de abril de 2026 para veículos com até 2 anos:

- Gasolina: 3,4% → fator 1,0000
- Diesel: 2,7% → fator 0,7941
- Híbrido: 2,5% → fator 0,7353
- Elétrico: 3,7% → fator 1,0882

A gasolina é a referência de normalização.

`fator_tecnologia = IPSA_tecnologia / IPSA_gasolina`

## 3. Estimativa final

`taxa_final = taxa_UF × fator_tecnologia`

`seguro_estimado = valor_FIPE × taxa_final`

Mapeamento operacional:
- BEV/EV → elétrico;
- PHEV/HEV/MHEV → híbrido;
- diesel → diesel;
- gasolina/flex/etanol e demais ICEV → gasolina.

O AUTOSEG/SUSEP continua determinando a variação geográfica. O IPSA/TEx é usado apenas como ajuste relativo da tecnologia.

## Limitações

Esta é uma versão rápida, não uma cotação individual. O recorte tecnológico do IPSA considera veículos com até 2 anos e a base regional AUTOSEG é de 2020. Uma versão posterior deve substituir esta combinação por agregações AUTOSEG granulares por código FIPE/modelo, ano, região e exposição mínima.

O valor permanece editável pelo usuário.
