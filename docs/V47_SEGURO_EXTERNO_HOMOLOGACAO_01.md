# CurVE V47 — Seguro externo anual — homologação 01

## Escopo autorizado

Esta entrega parte de `curve-v46-pacote-teste-04.zip` e altera somente o tratamento de seguro automotivo no Simular/TCO. Não promove a versão para produção e não altera matching FIPE × PBEV, catálogos FIPE, ANEEL, ANP, IPVA, depreciação, financiamento, Painel Local ou snapshot.

## Decisão implementada

A CurVE não calcula mais seguro por percentual geral da FIPE. A premissa automática de 4,7% foi removida do navegador, do backend, da memória de cálculo e dos textos do relatório.

A nova ordem é:

1. série anual recebida de uma fonte externa;
2. cache identificado da mesma estimativa, quando aplicável;
3. série anual informada pelo usuário;
4. exclusão explícita do seguro pelo usuário.

Não existe fallback percentual silencioso. Quando a fonte externa não está configurada ou não responde, a simulação exige que o usuário abra **Ajustar** e informe todos os valores anuais, ou escolha **Não considerar seguro**.

## Interface

O campo existente foi preservado no mesmo ponto de cada veículo e passou a mostrar **Seguro anual estimado**. Ele exibe o valor integral do primeiro ano e possui o botão **Ajustar**.

O modal inclui:

- consulta à fonte externa;
- refinamento opcional por faixa etária, sexo do condutor, tipo de uso, garagem, tempo de habilitação e classe de bônus;
- tabela com um valor integral para cada ano do horizonte;
- edição manual da série;
- exclusão explícita do componente;
- fonte, data, faixa e cobertura de referência quando retornadas.

Não há valor mensal, parcelamento ou conversão mensal.

## Série ano a ano

O TCO deixou de reconstruir o seguro com uma taxa constante sobre a FIPE. O motor agora recebe uma série explícita:

```text
Ano 1 -> seguro_1
Ano 2 -> seguro_2
...
Ano n -> seguro_n
```

O valor de cada ano entra diretamente na memória anual e no total do componente Seguro. O percentual equivalente sobre a FIPE permanece apenas como indicador derivado interno de auditoria; ele não gera os valores.

A integração genérica aceita dois formatos:

- `series`: a fonte devolve a série inteira em uma resposta;
- `per_year`: a CurVE consulta a fonte uma vez por ano do horizonte, enviando idade do veículo e FIPE projetada daquele ano;
- `auto`: tenta série completa e, quando necessário, consulta ano a ano.

Se a fonte devolver apenas parte do horizonte, a série é marcada como incompleta e não pode ser usada até o usuário completar os anos.

## Endpoint interno

```text
GET  /api/seguro/status
POST /api/seguro/estimar
```

### Requisição normalizada

```json
{
  "veiculo": {
    "codigo_fipe": "001234-5",
    "modelo": "Modelo e versão",
    "ano_modelo": 2026,
    "combustivel": "Gasolina",
    "propulsao": "icev",
    "valor_fipe": 100000.0
  },
  "localizacao": {
    "uf": "GO",
    "municipio": "Goiânia"
  },
  "perfil": {
    "faixa_etaria": "36_55",
    "tipo_uso": "particular",
    "garagem": "sim"
  },
  "horizonte_anos": 5,
  "depreciacao_percentual": 8.0,
  "projecoes": [
    {
      "indice": 1,
      "ano_referencia": 2026,
      "idade_veiculo": 0,
      "valor_fipe_projetado": 100000.0
    }
  ]
}
```

Os dados opcionais só são enviados quando o usuário os informa. Nome, CPF, telefone, e-mail, placa, endereço e data de nascimento não fazem parte do contrato interno.

### Respostas reconhecidas

O adaptador genérico reconhece chaves equivalentes em português ou inglês, incluindo:

- `serie_anual`, `annual_series`, `premios`, `premiums`;
- `valor_anual`, `annual_premium`, `premium`;
- `faixa_minima`, `range_min`;
- `faixa_maxima`, `range_max`;
- `cobertura_referencia`, `coverage_reference`;
- `data_referencia`, `reference_date`.

O formato específico do fornecedor real deverá ser mapeado no adaptador após a entrega da documentação oficial.

## Configuração do ambiente

```text
INSURANCE_ENABLED=1
INSURANCE_PROVIDER=nome-do-provedor
INSURANCE_SOURCE_LABEL=Nome exibido da fonte
INSURANCE_API_URL=https://endpoint-oficial
INSURANCE_API_KEY=segredo
INSURANCE_API_KEY_HEADER=Authorization
INSURANCE_API_KEY_PREFIX=Bearer
INSURANCE_API_TIMEOUT=20
INSURANCE_API_MODE=auto
INSURANCE_API_ALLOW_PER_YEAR=1
INSURANCE_CACHE_TTL_SECONDS=86400
INSURANCE_CACHE_STALE_SECONDS=2592000
```

As credenciais ficam apenas no ambiente do Render. Nenhuma chave é enviada ao navegador ou incluída no ZIP.

## Cache e contingência

A chave do cache considera veículo, localização, horizonte, projeção e campos opcionais. Os valores brutos do perfil não são gravados nos metadados do cache; apenas os nomes dos campos utilizados são registrados.

- cache fresco: usado dentro do TTL normal;
- cache de contingência: pode ser usado por prazo configurado se a fonte estiver indisponível;
- o uso de cache aparece na interface e na auditoria;
- após a validade de contingência, o valor externo não é aceito como automático.

## Procedência e integridade

Uma estimativa externa recebe um `estimate_id` derivado da requisição. No envio do TCO, o backend relê a estimativa no cache e não confia apenas nos campos ocultos do navegador.

Se o identificador externo não puder ser validado, uma série postada é reclassificada como manual. A edição manual remove a procedência automática.

## Auditoria e relatório

Foram adicionados:

- origem;
- fonte/provedor;
- data de referência;
- método;
- cobertura de referência;
- valor do primeiro ano;
- série anual completa;
- observação e estado de completude.

A descrição anterior baseada em percentual fixo foi substituída pela explicação de série externa ou manual ano a ano.

## Limitação consciente desta entrega

O código não contém endpoint, credencial ou contrato proprietário de qualquer seguradora ou empresa preditiva. Portanto, a fonte externa real permanece desativada por padrão.

Isso não é um fallback técnico incompleto: é uma proteção contra inventar API, valores ou parâmetros. Após o fornecedor entregar documentação e acesso, será necessário apenas:

1. configurar as variáveis de ambiente;
2. validar o payload exigido;
3. ajustar o mapeamento de resposta, se necessário;
4. homologar veículos, regiões e séries anuais reais.

## Arquivos de produção alterados

- `.env.example`
- `app.py`
- `config.py`
- `routes/tco_routes.py`
- `routes/seguro_routes.py` — novo
- `services/seguro_service.py` — novo
- `templates/simular.html`
- `templates/auditoria_tco.html`

## Testes

- compilação Python dos módulos alterados: aprovada;
- análise sintática dos templates Jinja: aprovada;
- `node --check` nos seis blocos JavaScript do Simular: aprovado;
- suíte direcionada de seguro e regressões da interface/FIPE/PBEV/ANEEL/ANP: **72 testes aprovados**;
- a suíte global original possui regressões PBEV preexistentes no pacote de entrada e também excedeu a janela de execução; o primeiro erro foi reproduzido sem alterações no pacote original.
