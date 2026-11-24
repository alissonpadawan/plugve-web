"""Atualiza a cópia das tarifas B1 da ANEEL.

Execute da raiz do repositório com python -m scripts.atualizar_tarifas_aneel.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from services import energia_service as energia


def main() -> None:
    hoje = energia._data_referencia_aneel()
    campos = (
        "_id", "SigAgente", "NumCNPJDistribuidora", "DatGeracaoConjuntoDados",
        "DscREH", "DatInicioVigencia", "DatFimVigencia", "DscUnidadeTerciaria",
        "VlrTUSD", "VlrTE", *energia.ANEEL_FILTROS_B1,
    )
    filtros = {**energia.ANEEL_FILTROS_B1, "DatFimVigencia": {"gte": hoje.isoformat()}}
    resposta = requests.get(
        energia.ANEEL_DATASTORE_URL,
        params={
            "resource_id": energia.ANEEL_RESOURCE_ID,
            "filters": json.dumps(filtros),
            "fields": ",".join(campos),
            "sort": "SigAgente asc, DatInicioVigencia asc, _id asc",
            "limit": 500,
        },
        timeout=(5, 20),
    )
    resposta.raise_for_status()
    dados = resposta.json()
    resultado = dados["result"]
    registros = resultado["records"]
    if not dados.get("success") or not registros or len(registros) != resultado["total"]:
        raise ValueError("A ANEEL retornou uma base vazia ou incompleta.")

    tarifas = []
    for registro in registros:
        sigla = registro["SigAgente"]
        inicio = energia._parse_data_aneel(registro["DatInicioVigencia"])
        if not inicio or energia._normalizar(sigla) in {"", "NAO INFORMADO"}:
            continue
        if energia._selecionar_tarifa_vigente([registro], sigla, max(hoje, inicio)):
            tarifas.append(registro)
    if not tarifas:
        raise ValueError("A ANEEL não retornou tarifas B1 utilizáveis.")

    copia = {
        "fonte": (
            "https://dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica/"
            f"resource/{energia.ANEEL_RESOURCE_ID}"
        ),
        "licenca": "https://opendatacommons.org/licenses/odbl/1-0/",
        "consultado_em": hoje.isoformat(),
        "registros": tarifas,
    }
    destino = energia.ANEEL_TARIFAS_PUBLICADAS_FILE
    with TemporaryDirectory(dir=destino.parent) as pasta:
        temporario = Path(pasta) / destino.name
        temporario.write_text(json.dumps(copia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporario.replace(destino)
    print(f"{len(tarifas)} registros ANEEL gravados em {destino}.")


if __name__ == "__main__":
    main()
