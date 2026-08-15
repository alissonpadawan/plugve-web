# CurVE V50.13 — PDFs rastreáveis e integração administrativa

A V50.13 conclui a apresentação dos identificadores S/D/F nos relatórios e liga a telemetria administrativa aos snapshots imutáveis criados nas V50.11–V50.12.

## PDFs

- Simulação/TCO: inclui código do resultado e data/hora original de geração no relatório; ao imprimir/salvar como PDF, o título do documento é `CurVE_Simulacao_<S-CODIGO>`.
- Depreciação: inclui código do resultado e data/hora original de geração no cabeçalho; o título de impressão é `CurVE_Depreciacao_<D-CODIGO>`.
- Fipe+: a consulta já exibia código e data no bloco impresso; o título de impressão passa a ser `CurVE_FIPE_<F-CODIGO>` e o botão é apresentado como Exportar PDF.

A data original do snapshot é preservada separadamente da data de emissão/impressão.

## Telemetria e admin

Eventos de exportação PDF passam a transportar `resultado_codigo` quando disponível. A API administrativa expõe `result_code` derivado do metadata e a linha do tempo em `/admin/uso` exibe o código como link para `/resultado/<codigo>`.

O link abre o snapshot histórico somente leitura; não recalcula o resultado.
