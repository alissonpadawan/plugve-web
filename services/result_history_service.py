from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_CODE_RE = re.compile(r"^[SDF]-\d{8}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{10}$")


RESULT_LABELS = {
    "S": "Simulação TCO",
    "D": "Depreciação",
    "F": "Consulta Fipe+",
}


def normalize_result_code(value: str) -> str:
    """Normaliza um identificador público sem tentar adivinhar códigos incompletos."""
    return str(value or "").strip().upper()


def is_valid_result_code(value: str) -> bool:
    return bool(_CODE_RE.fullmatch(normalize_result_code(value)))


def _first(mapping: dict[str, Any] | None, *keys: str, default: Any = "") -> Any:
    source = mapping if isinstance(mapping, dict) else {}
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return default


def _format_local_datetime(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return text


def _format_brl(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return f"{number:.2f}%".replace(".", ",")


_INPUT_LABELS = {
    "anos": "Horizonte (anos)",
    "km_ano": "Quilometragem anual (km)",
    "estado_uf": "UF",
    "municipio": "Município",
    "tipo_comparacao": "Tipo de comparação",
    "modelo_atual": "Veículo atual",
    "modelo_ve": "Veículo VE",
    "modelo_icev": "Veículo ICEV",
    "codigo_fipe_atual": "Código FIPE do veículo atual",
    "codigo_fipe_ve": "Código FIPE do VE",
    "codigo_fipe_icev": "Código FIPE do ICEV",
    "ano_modelo_atual": "Ano/modelo do veículo atual",
    "ano_modelo_ve": "Ano/modelo do VE",
    "ano_modelo_icev": "Ano/modelo do ICEV",
    "preco_atual": "Valor do veículo atual",
    "preco_ve": "Valor do VE",
    "preco_icev": "Valor do ICEV",
    "combustivel": "Preço do combustível",
    "energia": "Preço da energia",
    "aumento_combustivel": "Variação anual do combustível (%)",
    "aumento_energia": "Variação anual da energia (%)",
    "consumo_atual": "Consumo do veículo atual",
    "consumo_ve": "Consumo do VE",
    "consumo_icev": "Consumo do ICEV",
    "combustivel_atual": "Combustível do veículo atual",
    "combustivel_ve": "Combustível do VE",
    "combustivel_icev": "Combustível do ICEV",
    "depreciacao_atual": "Depreciação do veículo atual",
    "depreciacao_ve": "Depreciação do VE",
    "depreciacao_icev": "Depreciação do ICEV",
    "ipva_atual": "IPVA do veículo atual",
    "ipva_ve": "IPVA do VE",
    "ipva_icev": "IPVA do ICEV",
    "isencao_ipva_ve": "Isenção de IPVA do VE",
    "manut_atual": "Manutenção do veículo atual",
    "manut_ve": "Manutenção do VE",
    "manut_icev": "Manutenção do ICEV",
    "seguro_atual": "Seguro do veículo atual",
    "seguro_ve": "Seguro do VE",
    "seguro_icev": "Seguro do ICEV",
    "phev_percent_eletrico": "Uso elétrico do PHEV (%)",
    "phev_consumo_eletrico": "Consumo elétrico do PHEV (kWh/km)",
    "phev_consumo_combustivel": "Consumo com combustível do PHEV (km/L)",
    "phev_preco_combustivel": "Preço do combustível do PHEV (R$/L)",
    "fuel_percent_etanol": "Uso de etanol no flex (%)",
    "fuel_consumo_etanol": "Consumo com etanol (km/L)",
    "fuel_consumo_gasolina": "Consumo com gasolina (km/L)",
    "fuel_preco_etanol": "Preço do etanol (R$/L)",
    "fuel_preco_gasolina": "Preço da gasolina (R$/L)",
    "fuel_preco_diesel_s10": "Preço do diesel S10 (R$/L)",
}

_FINANCE_LABELS = {
    "ativo": "Financiamento ativo",
    "custos": "Custos do financiamento",
    "entrada": "Entrada",
    "entrada_pct": "Entrada (%)",
    "juros_mensal": "Juros mensais",
    "juros_total": "Juros totais",
    "meses": "Prazo (meses)",
    "parcela": "Parcela mensal",
    "principal": "Valor financiado",
    "total_pago": "Total pago",
}

_TECHNICAL_INPUT_PATTERNS = (
    "_marca_codigo", "_modelo_codigo", "_ano_codigo",
    "_editado_usuario", "_vehicle_key", "_prefixo_configurado",
    "_configurado", "_perfil_obrigatorio",
)

def _is_public_input_key(key: str) -> bool:
    if key.startswith("pbev_"):
        return False
    return not any(key.endswith(pattern) for pattern in _TECHNICAL_INPUT_PATTERNS)

def _human_input_label(key: str) -> str:
    if key in _INPUT_LABELS:
        return _INPUT_LABELS[key]

    for prefix, vehicle in (("fin_atual_", "Veículo atual"), ("fin_ve_", "VE"), ("fin_icev_", "ICEV")):
        if key.startswith(prefix):
            field = key[len(prefix):]
            base = _FINANCE_LABELS.get(field, field.replace("_", " ").capitalize())
            return f"{base} — {vehicle}"

    for prefix, vehicle in (("seguro_atual_", "veículo atual"), ("seguro_ve_", "VE"), ("seguro_icev_", "ICEV")):
        if key.startswith(prefix):
            field = key[len(prefix):]
            suffixes = {
                "fonte": "Fonte do seguro",
                "data_base": "Data-base do seguro",
                "metodo": "Método do seguro",
                "nivel": "Nível da estimativa de seguro",
                "taxa": "Taxa do seguro",
                "manual": "Seguro informado manualmente",
            }
            return f"{suffixes.get(field, field.replace('_', ' ').capitalize())} — {vehicle}"

    return key.replace("_", " ").strip().capitalize()

def _display_input_value(key: str, value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "—"

    normalized = text.lower().replace(",", ".")
    boolean_key = (
        key.endswith("_ativo") or key.endswith("_manual") or
        key.startswith("isencao_")
    )
    if boolean_key and normalized in {"0", "0.0", "false", "nao", "não"}:
        return "Não"
    if boolean_key and normalized in {"1", "1.0", "true", "sim"}:
        return "Sim"

    try:
        if float(normalized) == 0:
            return "—"
    except (TypeError, ValueError):
        pass
    return text

def _clean_items(mapping: dict[str, Any] | None) -> list[dict[str, str]]:
    source = mapping if isinstance(mapping, dict) else {}
    items: list[dict[str, str]] = []
    for key, value in sorted(source.items(), key=lambda item: str(item[0]).lower()):
        key_text = str(key)
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list, tuple)):
            continue
        if not _is_public_input_key(key_text):
            continue
        items.append({
            "key": key_text,
            "label": _human_input_label(key_text),
            "value": _display_input_value(key_text, value),
        })
    return items


def _build_tco(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("resultado") if isinstance(payload.get("resultado"), dict) else {}
    comparisons = result.get("comparacoes") if isinstance(result.get("comparacoes"), list) else []
    vehicles = payload.get("veiculos") if isinstance(payload.get("veiculos"), list) else []
    return {
        "vehicles": [item for item in vehicles if isinstance(item, dict)],
        "comparisons": [item for item in comparisons if isinstance(item, dict)],
        "input_items": _clean_items(payload.get("entrada")),
        "audit": payload.get("auditoria") if isinstance(payload.get("auditoria"), dict) else {},
    }


def _build_depreciation(payload: dict[str, Any]) -> dict[str, Any]:
    entrada = payload.get("entrada") if isinstance(payload.get("entrada"), dict) else {}
    result = payload.get("resultado") if isinstance(payload.get("resultado"), dict) else {}
    details = result.get("detalhes") if isinstance(result.get("detalhes"), dict) else {}
    vehicle = details.get("veiculo") if isinstance(details.get("veiculo"), dict) else {}

    current_value = _first(result, "valor_atual", default=_first(entrada, "valor_atual"))
    future_value = _first(result, "valor_futuro", "valor_futuro_base")
    depreciation_pct = _first(result, "depreciacao_percentual")
    annual_rate = _first(result, "taxa_anual_efetiva_percentual", "taxa_anual_percentual")
    horizon = _first(result, "horizonte_anos", "horizonte_relatorio_anos", default=_first(entrada, "horizonte_anos"))

    fields = [
        {"label": "Veículo", "value": str(_first(vehicle, "modelo", default=_first(result, "modelo_selecionado", default=_first(entrada, "modelo"))))},
        {"label": "Código FIPE", "value": str(_first(vehicle, "codigo_fipe", default=_first(entrada, "codigo_fipe")))},
        {"label": "Valor FIPE na consulta", "value": _format_brl(current_value) if current_value not in (None, "") else ""},
        {"label": "Valor estimado ao final", "value": _format_brl(future_value) if future_value not in (None, "") else ""},
        {"label": "Horizonte", "value": f"{horizon} ano(s)" if horizon not in (None, "") else ""},
        {"label": "Depreciação no horizonte", "value": _format_percent(depreciation_pct) if depreciation_pct not in (None, "") else ""},
        {"label": "Taxa anual", "value": f"{_format_percent(annual_rate)} a.a." if annual_rate not in (None, "") else ""},
        {"label": "Confiança", "value": str(_first(result, "confianca", default=_first(details, "confianca")))},
        {"label": "Tipo de curva", "value": str(_first(result, "tipo_curva_aplicada", default=_first(details, "tipo_curva_aplicada")))},
        {"label": "Origem da curva", "value": str(_first(result, "origem_curva", default=_first(details, "origem_curva")))},
        {"label": "Modelo de referência", "value": str(_first(result, "modelo_referencia_similaridade", "modelo_referencia", default=_first(details, "modelo_referencia_similaridade", "modelo_referencia")))},
    ]
    return {
        "fields": [item for item in fields if item["value"] not in ("", "None")],
        "input_items": _clean_items(entrada),
        "result": result,
    }


def _build_fipe(payload: dict[str, Any]) -> dict[str, Any]:
    entrada = payload.get("entrada") if isinstance(payload.get("entrada"), dict) else {}
    result = payload.get("resultado") if isinstance(payload.get("resultado"), dict) else {}
    fields = [
        {"label": "Marca", "value": str(_first(result, "Marca", "marca"))},
        {"label": "Modelo", "value": str(_first(result, "Modelo", "modelo"))},
        {"label": "Código FIPE", "value": str(_first(result, "CodigoFipe", "CodigoFIPE", "codigo_fipe"))},
        {"label": "Valor FIPE", "value": str(_first(result, "Valor", "valor"))},
        {"label": "Ano/modelo", "value": str(_first(result, "AnoModelo", "ano_modelo"))},
        {"label": "Combustível", "value": str(_first(result, "Combustivel", "combustivel"))},
        {"label": "Mês de referência", "value": str(_first(result, "MesReferencia", "mes_referencia"))},
        {"label": "Tipo", "value": str(_first(result, "TipoVeiculo", "tipo_veiculo"))},
    ]
    return {
        "fields": [item for item in fields if item["value"] not in ("", "None")],
        "input_items": _clean_items(entrada),
        "result": result,
    }


def build_result_history_view(record: dict[str, Any]) -> dict[str, Any]:
    """Monta uma representação apenas de leitura a partir do snapshot armazenado.

    Esta função não consulta serviços externos e não recalcula nenhum componente.
    Todo valor exibido vem diretamente do envelope imutável persistido na geração.
    """
    snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
    payload = snapshot.get("payload") if isinstance(snapshot.get("payload"), dict) else {}
    result_type = str(record.get("result_type") or snapshot.get("result_type") or "").upper()

    module_view: dict[str, Any]
    if result_type == "S":
        module_view = _build_tco(payload)
    elif result_type == "D":
        module_view = _build_depreciation(payload)
    elif result_type == "F":
        module_view = _build_fipe(payload)
    else:
        module_view = {}

    return {
        "code": str(record.get("code") or ""),
        "result_type": result_type,
        "result_label": RESULT_LABELS.get(result_type, "Resultado CurVE"),
        "module": str(record.get("module") or ""),
        "created_at_local": str(record.get("created_at_local") or ""),
        "created_at_display": _format_local_datetime(str(record.get("created_at_local") or "")),
        "platform_version": str(record.get("platform_version") or ""),
        "schema_version": str(record.get("schema_version") or ""),
        "payload_sha256": str(record.get("payload_sha256") or ""),
        "payload_sha256_short": str(record.get("payload_sha256") or "")[:16],
        "payload_bytes": int(record.get("payload_bytes") or 0),
        "payload": payload,
        "module_view": module_view,
    }


def build_result_admin_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Resumo compacto do snapshot para o modal administrativo.

    Deriva exclusivamente do snapshot imutável já persistido. Não consulta
    fontes externas e não recalcula qualquer valor.
    """
    view = build_result_history_view(record)
    result_type = view.get("result_type") or ""
    mv = view.get("module_view") if isinstance(view.get("module_view"), dict) else {}
    summary: dict[str, Any] = {
        "code": view.get("code") or "",
        "result_type": result_type,
        "result_label": view.get("result_label") or "Resultado CurVE",
        "created_at_display": view.get("created_at_display") or "",
        "platform_version": view.get("platform_version") or "",
        "payload_sha256_short": view.get("payload_sha256_short") or "",
    }

    if result_type == "S":
        comparisons = []
        for comparison in (mv.get("comparisons") or [])[:3]:
            if not isinstance(comparison, dict):
                continue
            details = []
            for item in (comparison.get("detalhes") or [])[:3]:
                if not isinstance(item, dict):
                    continue
                details.append({
                    "nome": str(item.get("nome") or ""),
                    "codigo_fipe": str(item.get("codigo_fipe") or ""),
                    "tco_final": str(item.get("tco_final") or ""),
                    "custo_km": str(item.get("custo_km") or ""),
                    "preco_inicial": str(item.get("preco_inicial") or ""),
                    "valor_revenda": str(item.get("valor_revenda") or ""),
                })
            comparisons.append({
                "titulo": str(comparison.get("titulo") or "Comparação"),
                "detalhes": details,
            })
        summary["comparisons"] = comparisons
        summary["vehicles"] = [
            {
                "role": str(v.get("role") or ""),
                "modelo": str(v.get("modelo") or ""),
                "marca": str(v.get("marca") or ""),
                "codigo_fipe": str(v.get("codigo_fipe") or ""),
                "ano_modelo": str(v.get("ano_modelo") or ""),
            }
            for v in (mv.get("vehicles") or [])[:5]
            if isinstance(v, dict)
        ]
    elif result_type in {"D", "F"}:
        summary["fields"] = [
            {"label": str(item.get("label") or ""), "value": str(item.get("value") or "")}
            for item in (mv.get("fields") or [])[:16]
            if isinstance(item, dict)
        ]
    return summary
