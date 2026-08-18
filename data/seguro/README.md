# Seguro automotivo na CurVE

## V50.22 — Seguro V2 validado e regionalizado

A estimativa automática combina:

- **IPSA/TEx de maio de 2026** como referência contemporânea por idade, faixa FIPE e, em veículos de até 2 anos, tecnologia/propulsão;
- **IPSA/TEx de maio de 2026 por região metropolitana** para Salvador, Recife, Belém, Belo Horizonte, Porto Alegre, Rio de Janeiro, Fortaleza, Curitiba e São Paulo quando a cidade selecionada é a capital correspondente;
- **AUTOSEG/SUSEP 2021A** como evidência histórica relativa por código FIPE, região e cidade;
- redução dos fatores históricos por exposição e distância temporal;
- fallbacks progressivos quando o modelo específico não possui amostra suficiente.

Arquivos:

- `ipsa_v2_referencias.csv` — referências atuais parametrizadas;
- `seguro_autoseg_2021A_curve_compact.sqlite` — base AUTOSEG compacta;
- `autoseg_taxas_uf_v1.csv` e `ipsa_tecnologia_v1.csv` — estimador legado mantido apenas para contingência técnica/compatibilidade.

A tabela municipal AUTOSEG não possui importância segurada média. Por isso, município histórico é usado somente como fator relativo sobre o nível regional. Quando há referência metropolitana contemporânea do IPSA, ela substitui os ajustes geográficos históricos para evitar dupla contagem; o fator histórico específico do modelo pode continuar sendo aplicado.

### Continuidade numérica das faixas FIPE

O IPSA publica faixas discretas de valor. Para evitar que uma diferença de R$ 1 no valor FIPE provoque um salto artificial relevante no seguro, a V50.22 interpola linearmente somente em uma janela de ±5% ao redor dos limites R$ 50 mil, R$ 80 mil e R$ 150 mil. Fora dessas janelas, a taxa publicada da faixa é preservada integralmente. Essa interpolação é apenas um tratamento de continuidade numérica; não representa uma nova fonte de mercado.

### Veículos com mais de 10 anos

O relatório detalhado não fornece faixa etária específica acima de 10 anos. A V50.22 não retorna ao preço absoluto regional antigo por causa disso. Usa apenas as dimensões contemporâneas ainda aplicáveis — referência geral de mercado e faixa FIPE — e pode manter fatores históricos AUTOSEG reduzidos por credibilidade. A confiança é limitada a **Referência**.

### Estimativa conceitual

`taxa_atual = mediana(IPSA aplicável)`

`taxa_V2 = taxa_atual × ajuste_geográfico × ajuste_modelo`

Quando não há geografia contemporânea IPSA, o ajuste geográfico pode usar região/cidade AUTOSEG histórica reduzida por credibilidade.

`seguro = valor_FIPE × taxa_V2`

A estimativa não é cotação individual e permanece editável pelo usuário.

### Referência temporal

Em agosto de 2026 a página pública do IPSA já anuncia o relatório de junho/2026. A CurVE V50.22 mantém **maio/2026** como base numérica porque é o relatório detalhado completo efetivamente auditado e parametrizado nesta versão. A atualização para junho deve ocorrer somente após ingestão/auditoria do relatório detalhado, sem misturar meses diferentes na mesma calibração.
