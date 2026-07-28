from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from flask import current_app


class SeguroError(RuntimeError):
    """Erro base do serviço de estimativa externa de seguro."""


class SeguroConfiguracaoError(SeguroError):
    """A fonte externa não foi configurada no ambiente."""


class SeguroValidacaoError(SeguroError):
    """Os dados enviados não permitem consultar a estimativa."""


class SeguroFonteError(SeguroError):
    """A fonte externa respondeu com erro ou formato incompatível."""


@dataclass(frozen=True)
class SeguroEstimativa:
    estimate_id: str
    serie_anual: tuple[float, ...]
    fonte: str
    provedor: str
    data_referencia: str
    faixa_minima: float | None = None
    faixa_maxima: float | None = None
    cobertura_referencia: str = ""
    campos_perfil: tuple[str, ...] = ()
    cache: bool = False
    completa: bool = True
    observacao: str = ""

    @property
    def valor_primeiro_ano(self) -> float:
        return float(self.serie_anual[0]) if self.serie_anual else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimate_id": self.estimate_id,
            "valor_anual": self.valor_primeiro_ano,
            "serie_anual": [round(float(v), 2) for v in self.serie_anual],
            "fonte": self.fonte,
            "provedor": self.provedor,
            "data_referencia": self.data_referencia,
            "faixa_minima": self.faixa_minima,
            "faixa_maxima": self.faixa_maxima,
            "cobertura_referencia": self.cobertura_referencia,
            "campos_perfil": list(self.campos_perfil),
            "cache": self.cache,
            "completa": self.completa,
            "observacao": self.observacao,
        }


def _bool_env(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "sim", "s", "yes", "y", "on"}


def _float_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return max(0.0, float(text))
    except ValueError:
        return None


def _find_key(data: Any, keys: Iterable[str]) -> Any:
    wanted = {str(key).lower() for key in keys}
    queue = [data]
    visited = 0
    while queue and visited < 2000:
        current = queue.pop(0)
        visited += 1
        if isinstance(current, dict):
            for key, value in current.items():
                if str(key).lower() in wanted:
                    return value
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return None


def _parse_series_item(item: Any) -> float | None:
    direct = _float_value(item)
    if direct is not None:
        return direct
    if isinstance(item, dict):
        candidate = _find_key(
            item,
            (
                "valor",
                "value",
                "premium",
                "premio",
                "annual_value",
                "annual_premium",
                "valor_anual",
                "preco",
                "price",
            ),
        )
        return _float_value(candidate)
    return None


def _parse_series(response: Any) -> list[float]:
    raw = _find_key(
        response,
        (
            "serie_anual",
            "annual_series",
            "series",
            "premiums",
            "premios",
            "annual_values",
            "valores_anuais",
        ),
    )
    values: list[float] = []
    if isinstance(raw, list):
        for item in raw:
            parsed = _parse_series_item(item)
            if parsed is not None:
                values.append(round(parsed, 2))
    if values:
        return values

    single = _find_key(
        response,
        (
            "valor_anual",
            "annual_value",
            "annual_premium",
            "premium",
            "premio",
            "preco_otimo",
            "optimal_price",
            "price",
            "valor",
        ),
    )
    parsed = _float_value(single)
    return [round(parsed, 2)] if parsed is not None else []


def _sanitize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "faixa_etaria",
        "sexo_condutor",
        "tipo_uso",
        "garagem",
        "tempo_habilitacao",
        "classe_bonus",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        value = profile.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"nao_informado", "não informado", "prefiro_nao_informar"}:
            result[key] = text[:80]
    return result


def _request_hash(payload: dict[str, Any], provider: str) -> str:
    canonical = json.dumps(
        {"provider": provider, "payload": payload},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SeguroCache:
    def __init__(self, base_dir: Path, ttl_seconds: int) -> None:
        self.base_dir = Path(base_dir)
        self.ttl_seconds = max(60, int(ttl_seconds))

    def _path(self, estimate_id: str) -> Path:
        safe = "".join(ch for ch in str(estimate_id) if ch.isalnum() or ch in {"-", "_"})
        return self.base_dir / f"{safe}.json"

    def load(
        self,
        estimate_id: str,
        *,
        allow_expired: bool = False,
        max_age_seconds: int | None = None,
    ) -> dict[str, Any] | None:
        path = self._path(estimate_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        created = float(data.get("created_at_epoch") or 0)
        age = time.time() - created if created else 0.0
        if max_age_seconds is not None and created and age > max(60, int(max_age_seconds)):
            return None
        if not allow_expired and created and age > self.ttl_seconds:
            return None
        return data

    def save(self, estimate_id: str, result: dict[str, Any], metadata: dict[str, Any]) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(estimate_id)
        tmp = path.with_suffix(".tmp")
        document = {
            "estimate_id": estimate_id,
            "created_at_epoch": time.time(),
            "result": result,
            "metadata": metadata,
        }
        tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


class SeguroService:
    """Integra a CurVE a uma fonte externa sem criar percentual próprio de seguro."""

    def __init__(self) -> None:
        cfg = current_app.config
        self.enabled = _bool_env(cfg.get("INSURANCE_ENABLED"), False)
        self.provider = str(cfg.get("INSURANCE_PROVIDER") or "external").strip()
        self.source_label = str(cfg.get("INSURANCE_SOURCE_LABEL") or self.provider or "Fonte externa").strip()
        self.api_url = str(cfg.get("INSURANCE_API_URL") or "").strip()
        self.api_key = str(cfg.get("INSURANCE_API_KEY") or "").strip()
        self.api_key_header = str(cfg.get("INSURANCE_API_KEY_HEADER") or "Authorization").strip()
        self.api_key_prefix = str(cfg.get("INSURANCE_API_KEY_PREFIX") or "Bearer").strip()
        self.timeout = max(2, int(cfg.get("INSURANCE_API_TIMEOUT") or 20))
        self.mode = str(cfg.get("INSURANCE_API_MODE") or "auto").strip().lower()
        self.allow_per_year = _bool_env(cfg.get("INSURANCE_API_ALLOW_PER_YEAR"), True)
        self.cache = SeguroCache(
            Path(cfg.get("INSURANCE_CACHE_DIR")),
            int(cfg.get("INSURANCE_CACHE_TTL_SECONDS") or 86400),
        )
        self.cache_stale_seconds = max(
            self.cache.ttl_seconds,
            int(cfg.get("INSURANCE_CACHE_STALE_SECONDS") or 2592000),
        )

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_url)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "provider": self.provider,
            "source_label": self.source_label,
            "mode": self.mode,
        }

    def estimate(self, payload: dict[str, Any]) -> SeguroEstimativa:
        normalized = self._normalize_payload(payload)
        if not self.configured:
            raise SeguroConfiguracaoError(
                "A fonte externa de seguro ainda não está configurada neste ambiente."
            )

        estimate_id = _request_hash(normalized, self.provider)
        cached = self.cache.load(estimate_id)
        if cached:
            return self._estimate_from_cached(cached, cache=True)
        stale_cached = self.cache.load(
            estimate_id,
            allow_expired=True,
            max_age_seconds=self.cache_stale_seconds,
        )

        horizon = int(normalized["horizonte_anos"])
        response: Any = None
        series: list[float] = []
        observation = ""

        try:
            if self.mode in {"auto", "series", "provider_series", "batch"}:
                response = self._call_provider(normalized)
                series = _parse_series(response)

            if len(series) < horizon and self.mode in {"auto", "per_year", "single_per_year"} and self.allow_per_year:
                series = self._estimate_per_year(normalized)
                response = response or {}
        except SeguroFonteError:
            if stale_cached:
                cached_estimate = self._estimate_from_cached(stale_cached, cache=True)
                aviso = "Fonte externa indisponível; utilizada a última estimativa armazenada dentro da validade de contingência."
                observacao = " ".join(filter(None, (cached_estimate.observacao, aviso)))
                return replace(cached_estimate, observacao=observacao)
            raise

        complete = len(series) >= horizon
        series = series[:horizon]
        if not series:
            raise SeguroFonteError("A fonte externa não retornou um valor anual reconhecível.")
        if not complete:
            observation = (
                "A fonte externa retornou apenas parte do horizonte. "
                "Os anos restantes devem ser informados antes de usar uma série completa."
            )

        range_min = _float_value(_find_key(response, ("faixa_minima", "min", "minimum", "range_min", "valor_minimo")))
        range_max = _float_value(_find_key(response, ("faixa_maxima", "max", "maximum", "range_max", "valor_maximo")))
        coverage = str(
            _find_key(response, ("cobertura_referencia", "coverage", "coverage_reference", "cobertura")) or ""
        ).strip()[:300]
        reference_date = str(
            _find_key(response, ("data_referencia", "reference_date", "updated_at", "date"))
            or datetime.now(timezone.utc).date().isoformat()
        )[:40]
        provider_name = str(_find_key(response, ("provedor", "provider", "source")) or self.provider).strip()[:120]
        source_label = str(_find_key(response, ("fonte", "source_label")) or self.source_label).strip()[:160]
        profile_fields = tuple(sorted(normalized.get("perfil", {}).keys()))

        result = SeguroEstimativa(
            estimate_id=estimate_id,
            serie_anual=tuple(series),
            fonte=source_label,
            provedor=provider_name,
            data_referencia=reference_date,
            faixa_minima=range_min,
            faixa_maxima=range_max,
            cobertura_referencia=coverage,
            campos_perfil=profile_fields,
            cache=False,
            completa=complete,
            observacao=observation,
        )
        self.cache.save(
            estimate_id,
            result.to_dict(),
            {
                "veiculo": normalized.get("veiculo", {}),
                "localizacao": normalized.get("localizacao", {}),
                "horizonte_anos": horizon,
                "campos_perfil": list(profile_fields),
            },
        )
        return result

    def get_by_id(self, estimate_id: str) -> SeguroEstimativa | None:
        cached = self.cache.load(
            estimate_id,
            allow_expired=True,
            max_age_seconds=self.cache_stale_seconds,
        )
        if not cached:
            return None
        return self._estimate_from_cached(cached, cache=True)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        vehicle = payload.get("veiculo") or {}
        location = payload.get("localizacao") or {}
        profile = _sanitize_profile(payload.get("perfil") or {})

        model = str(vehicle.get("modelo") or "").strip()
        year_text = str(vehicle.get("ano_modelo") or "").strip()
        uf = str(location.get("uf") or "").strip().upper()
        municipality = str(location.get("municipio") or "").strip()
        price = _float_value(vehicle.get("valor_fipe")) or 0.0
        horizon = int(payload.get("horizonte_anos") or 1)
        depreciation_pct = _float_value(payload.get("depreciacao_percentual")) or 0.0

        if not model:
            raise SeguroValidacaoError("Selecione o veículo antes de estimar o seguro.")
        if not year_text:
            raise SeguroValidacaoError("O ano-modelo do veículo não foi identificado.")
        if not uf or not municipality:
            raise SeguroValidacaoError("Selecione UF e município antes de estimar o seguro.")
        if price <= 0:
            raise SeguroValidacaoError("O valor FIPE do veículo ainda não foi carregado.")
        if horizon < 1 or horizon > 30:
            raise SeguroValidacaoError("O horizonte do seguro deve ficar entre 1 e 30 anos.")

        current_year = date.today().year
        year_digits = "".join(ch for ch in year_text if ch.isdigit())
        zero_km = "zero" in year_text.lower() or year_digits == "32000"
        parsed_year = int(year_digits[:4]) if len(year_digits) >= 4 else current_year
        model_year = current_year if zero_km or parsed_year > current_year + 2 else parsed_year
        depreciation_rate = min(max(depreciation_pct / 100.0, 0.0), 0.95)
        projections = []
        projected_value = price
        for index in range(horizon):
            projections.append(
                {
                    "indice": index + 1,
                    "ano_referencia": current_year + index,
                    "idade_veiculo": max(0, current_year + index - model_year),
                    "valor_fipe_projetado": round(projected_value, 2),
                }
            )
            projected_value *= 1.0 - depreciation_rate

        return {
            "veiculo": {
                "codigo_fipe": str(vehicle.get("codigo_fipe") or "").strip(),
                "modelo": model[:300],
                "ano_modelo": model_year,
                "combustivel": str(vehicle.get("combustivel") or "").strip()[:120],
                "propulsao": str(vehicle.get("propulsao") or "").strip()[:80],
                "valor_fipe": round(price, 2),
            },
            "localizacao": {"uf": uf[:2], "municipio": municipality[:160]},
            "perfil": profile,
            "horizonte_anos": horizon,
            "depreciacao_percentual": round(depreciation_pct, 4),
            "projecoes": projections,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            value = self.api_key
            if self.api_key_prefix:
                value = f"{self.api_key_prefix} {self.api_key}".strip()
            headers[self.api_key_header] = value
        return headers

    def _call_provider(self, payload: dict[str, Any]) -> Any:
        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SeguroFonteError(f"Falha de comunicação com a fonte externa: {exc}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                parsed = response.json()
                detail = str(_find_key(parsed, ("message", "error", "detail")) or "")
            except ValueError:
                detail = response.text[:240]
            raise SeguroFonteError(
                f"A fonte externa respondeu HTTP {response.status_code}. {detail}".strip()
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SeguroFonteError("A fonte externa não retornou JSON válido.") from exc

    def _estimate_per_year(self, payload: dict[str, Any]) -> list[float]:
        values: list[float] = []
        for projection in payload.get("projecoes") or []:
            annual_payload = {
                **payload,
                "horizonte_anos": 1,
                "projecoes": [projection],
                "projecao_atual": projection,
                "veiculo": {
                    **payload["veiculo"],
                    "valor_fipe": projection["valor_fipe_projetado"],
                    "idade_veiculo": projection["idade_veiculo"],
                },
            }
            response = self._call_provider(annual_payload)
            annual = _parse_series(response)
            if not annual:
                break
            values.append(round(annual[0], 2))
        return values

    @staticmethod
    def _estimate_from_cached(document: dict[str, Any], *, cache: bool) -> SeguroEstimativa:
        result = document.get("result") or {}
        return SeguroEstimativa(
            estimate_id=str(result.get("estimate_id") or document.get("estimate_id") or ""),
            serie_anual=tuple(float(v) for v in (result.get("serie_anual") or [])),
            fonte=str(result.get("fonte") or "Fonte externa"),
            provedor=str(result.get("provedor") or "external"),
            data_referencia=str(result.get("data_referencia") or ""),
            faixa_minima=_float_value(result.get("faixa_minima")),
            faixa_maxima=_float_value(result.get("faixa_maxima")),
            cobertura_referencia=str(result.get("cobertura_referencia") or ""),
            campos_perfil=tuple(result.get("campos_perfil") or []),
            cache=cache,
            completa=bool(result.get("completa", True)),
            observacao=str(result.get("observacao") or ""),
        )


def get_seguro_service() -> SeguroService:
    return SeguroService()
