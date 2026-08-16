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


def _clean_items(mapping: dict[str, Any] | None) -> list[dict[str, str]]:
    source = mapping if isinstance(mapping, dict) else {}
    items: list[dict[str, str]] = []
    for key, value in sorted(source.items(), key=lambda item: str(item[0]).lower()):
        if value in (None, ""):
            continue
        if isinstance(value, (dict, list, tuple)):
            continue
        items.append({"key": str(key), "value": str(value)})
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
