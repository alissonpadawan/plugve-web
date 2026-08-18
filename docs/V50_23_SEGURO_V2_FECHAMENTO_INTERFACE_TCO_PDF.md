# V50.23 — Seguro V2: fechamento de interface, TCO e PDF

## Base

V50.22 — `curve-v50-22-seguro-v2-validacao-regionalizacao.zip`.

## Escopo autorizado

Fechamento da auditoria do Seguro V2 sem alterar a metodologia IPSA/AUTOSEG, a reestimativa anual, o financiamento, os snapshots S/D/F ou o Painel Local.

## Correções

1. O seguro removido pelo usuário passa a ter estado explícito **não considerado**, em vez de ser indistinguível de um seguro manual de R$ 0,00.
2. O aviso **Valor informado pelo usuário.** permanece visível quando localização ou preço disparam uma tentativa de atualização automática; o valor manual continua soberano.
3. Resultado e PDF exibem **Não considerado** quando o componente foi deliberadamente excluído.
4. A memória/auditoria TCO registra o estado `nao_considerado` e mantém o seguro zerado em todos os anos do horizonte.
5. Snapshots antigos, que não possuem o novo campo, continuam interpretados como seguro considerado para preservar compatibilidade histórica.

## Metodologia preservada

Nenhum cálculo do Seguro V2 foi alterado. Permanecem IPSA, AUTOSEG/SUSEP, Código FIPE/modelo, idade, faixa FIPE, regionalização, tecnologia, classes de confiança, fallback e reestimativa anual.
