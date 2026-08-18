# Relatório de entrega — CurVE V50.26

## Base
- V50.25 homologada.
- SHA-256 da base: `ab8be968882e72d5163ce821dba64c02aca1948036a1dc7a4efd38aeb521f3f5`.

## Escopo
Rodada exclusivamente visual/textual da Simular/TCO e do PDF. Nenhum cálculo de TCO, IPVA, Seguro V2, depreciação, financiamento, CO₂ ou snapshot foi modificado.

## Ajustes
1. Seguro projetado reduzido a taxa + fonte curta (`IPSA + AUTOSEG/SUSEP`), sem exposição visual de 2021/2021A, confiança, agregação ou data-base histórica.
2. Removida do PDF a nota extensa sobre reais constantes/TMA/VPL.
3. Metadado no canto de todas as páginas do PDF reduzido ao código S.
4. Rótulos do PDF simplificados para `Variação da energia` e `Variação dos combustíveis`.
5. Removidas as legendas explicativas das linhas `CO₂ fóssil operacional` e `CO₂ biogênico operacional` nas tabelas comparativas.
6. Cards passam a mostrar `Valor FIPE inicial` acima de `Código FIPE`; no PDF, ambos ficam em linhas próprias.
7. Município/UF selecionado é exibido no resultado do site e nos parâmetros comuns do PDF.
8. Removida da página principal do resultado a frase extensa sobre TCO em reais constantes/TMA/VPL.
9. Removido o parágrafo extenso de metodologia operacional de CO₂ da interface.
10. `Premissas consideradas na comparação` passa a mostrar seguro de forma curta, coerente com o PDF.

## Preservação metodológica
A metodologia monetária em reais constantes continua registrada no backend/auditoria e nos snapshots aplicáveis. A remoção é somente da apresentação solicitada. A base e o serviço do Seguro V2 não foram alterados.

## Testes
- `compileall`: aprovado.
- Jinja: `simular.html` parseado com sucesso.
- Testes dirigidos da rodada e regressões TCO/IPVA/Seguro/snapshot/PDF: 75/75 aprovados.
- Regressão geral fora dos quatro arquivos legados conhecidos: 350 aprovados, 10 ignorados e 58 subtests aprovados.
- Quatro arquivos legados conhecidos: 29 falhas, 7 aprovados e 5 subtests aprovados, totalizando os mesmos 29 casos já conhecidos.
- Resultado agregado: 350 aprovados, 29 falhas legadas, 10 ignorados e 63 subtests aprovados.
- JavaScript inline da Simular: 3/3 blocos aprovados em `node --check`.
- Chromium/Playwright em harness das áreas alteradas: 0 page errors e 0 console errors.
- Aplicação Flask completa: não iniciada neste ambiente por ausência de Flask/gunicorn.
- Dados: 107/107 arquivos com hashes idênticos antes/depois.
