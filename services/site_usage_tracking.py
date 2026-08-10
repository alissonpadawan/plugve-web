from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import unquote, urlparse

from flask import current_app, request, session

from services.site_usage_service import get_site_usage_service

SESSION_TIMEOUT_SECONDS = 30 * 60

PAGE_MODULE_BY_ENDPOINT = {
    "main.index": "home",
    "main.consulta_fipe": "fipe_plus",
    "main.depreciacao": "depreciacao",
    "tco.simular": "tco",
    "tco.sobre": "sobre",
    "tco.contato": "contato",
    "main.financiamento": "financiamento",
}


def ensure_site_usage_identity() -> tuple[str, str]:
    session.permanent = True
    visitor_id = str(session.get("site_usage_visitor_id") or "").strip()
    if not visitor_id:
        visitor_id = secrets.token_urlsafe(24)
        session["site_usage_visitor_id"] = visitor_id

    now = int(time.time())
    try:
        last_seen = int(session.get("site_usage_last_active_ts") or 0)
    except (TypeError, ValueError):
        last_seen = 0
    session_id = str(session.get("site_usage_session_id") or "").strip()
    if not session_id or not last_seen or now - last_seen > SESSION_TIMEOUT_SECONDS:
        session_id = secrets.token_urlsafe(24)
        session["site_usage_session_id"] = session_id
    session["site_usage_last_active_ts"] = now

    csrf_token = str(session.get("site_usage_csrf_token") or "").strip()
    if not csrf_token:
        session["site_usage_csrf_token"] = secrets.token_urlsafe(32)
    return visitor_id, session_id


def _first_header(*names: str) -> str:
    for name in names:
        value = str(request.headers.get(name) or "").strip()
        if value:
            return value
    return ""


def _client_ip() -> str:
    direct = _first_header("CF-Connecting-IP", "True-Client-IP", "X-Real-IP")
    if direct:
        return direct.split(",", 1)[0].strip()
    forwarded = _first_header("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return str(request.remote_addr or "").strip()


def _network_hash(ip: str) -> str:
    if not ip:
        return ""
    secret = str(current_app.config.get("SECRET_KEY") or "plugve-usage").encode("utf-8")
    return hmac.new(secret, ip.encode("utf-8"), hashlib.sha256).hexdigest()


def _coarse_user_agent(user_agent: str) -> tuple[str, str, str]:
    ua = str(user_agent or "").lower()
    if "edg/" in ua or "edge/" in ua:
        browser = "Edge"
    elif "opr/" in ua or "opera" in ua:
        browser = "Opera"
    elif "firefox/" in ua:
        browser = "Firefox"
    elif "chrome/" in ua or "crios/" in ua:
        browser = "Chrome"
    elif "safari/" in ua:
        browser = "Safari"
    else:
        browser = "Outro"

    if "ipad" in ua or "tablet" in ua:
        device = "tablet"
    elif "mobile" in ua or "iphone" in ua or "android" in ua:
        device = "mobile"
    else:
        device = "desktop"

    if "windows" in ua:
        os_family = "Windows"
    elif "android" in ua:
        os_family = "Android"
    elif "iphone" in ua or "ipad" in ua or "ios" in ua:
        os_family = "iOS"
    elif "mac os" in ua or "macintosh" in ua:
        os_family = "macOS"
    elif "linux" in ua:
        os_family = "Linux"
    else:
        os_family = "Outro"
    return browser, device, os_family


def current_request_usage_context() -> dict[str, str]:
    browser, device, os_family = _coarse_user_agent(request.headers.get("User-Agent", ""))
    referrer = str(request.referrer or "").strip()
    try:
        referrer_host = urlparse(referrer).hostname or ""
    except Exception:
        referrer_host = ""
    city = _first_header("CF-IPCity", "X-Vercel-IP-City", "X-Geo-City")
    region = _first_header("CF-Region", "CF-Region-Code", "X-Vercel-IP-Country-Region", "X-Geo-Region")
    country = _first_header("CF-IPCountry", "X-Vercel-IP-Country", "X-Geo-Country")
    return {
        "network_hash": _network_hash(_client_ip()),
        "city": unquote(city)[:100],
        "region": unquote(region)[:100],
        "country": unquote(country)[:60],
        "browser_family": browser,
        "device_type": device,
        "os_family": os_family,
        "referrer_host": referrer_host,
        "path": request.path,
    }


def record_current_usage_event(
    *,
    event_type: str,
    module: str,
    action: str,
    metadata: dict | None = None,
    vehicles: list[dict] | None = None,
    simulation_uf: str = "",
    simulation_city: str = "",
    horizon_years=None,
    km_year=None,
    analysis_type: str = "",
) -> int | None:
    try:
        visitor_id, session_id = ensure_site_usage_identity()
        return get_site_usage_service().record_event(
            visitor_id=visitor_id,
            session_id=session_id,
            event_type=event_type,
            module=module,
            action=action,
            request_context=current_request_usage_context(),
            metadata=metadata or {},
            vehicles=vehicles or [],
            simulation_uf=simulation_uf,
            simulation_city=simulation_city,
            horizon_years=horizon_years,
            km_year=km_year,
            analysis_type=analysis_type,
        )
    except Exception as exc:
        current_app.logger.debug("Telemetria CurVE ignorada: %s", exc)
        return None


def maybe_record_page_view(response) -> None:
    if request.method != "GET" or response.status_code >= 400:
        return
    endpoint = str(request.endpoint or "")
    module = PAGE_MODULE_BY_ENDPOINT.get(endpoint)
    if not module:
        return
    content_type = str(response.content_type or "").lower()
    if "text/html" not in content_type:
        return
    record_current_usage_event(event_type="page_view", module=module, action="page_view")
