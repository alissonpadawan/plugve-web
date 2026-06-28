from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from flask import current_app


USER_AGENT = "CurVE-RadarNoticias/1.1 (+https://plugve-web.onrender.com)"
DEFAULT_TIMEOUT_SECONDS = 4
DEFAULT_CACHE_HOURS = 6
DEFAULT_LIMIT = 6

DEFAULT_KEYWORDS = [
    "carro eletrico",
    "carros eletricos",
    "veiculo eletrico",
    "veiculos eletricos",
    "eletrico",
    "eletricos",
    "eletrificada",
    "eletrificacao",
    "hibrido",
    "hibridos",
    "plug-in",
    "plugin",
    "phev",
    "bateria",
    "baterias",
    "recarga",
    "carregador",
    "carregadores",
    "eletroposto",
    "autonomia",
    "mobilidade eletrica",
    "byd",
    "gwm",
    "tesla",
    "volvo ex",
]


BAD_NEWS_TERMS = [
    "assine", "assinante", "oferta", "promoção", "promocao", "cupom", "benefício", "beneficio",
    "login", "entrar", "cadastro", "newsletter", "ouviu na rádio", "ouviu na radio",
    "rádio", "radio", "podcast", "publicidade", "anuncie", "voltar", "termos de uso",
    "política de privacidade", "politica de privacidade", "carros", "motos", "ofertas"
]

BAD_URL_PARTS = [
    "/assine", "/assinatura", "/ofertas", "/promocoes", "/promoções", "/login",
    "/cadastro", "/newsletter", "/radio", "/rádio", "/podcast", "/tag/", "/tags/",
    "/categoria/", "/categorias/", "/editoria/", "/carros/$", "/motos/$"
]

GOOD_URL_HINTS = [
    "/noticia", "/noticias", "/materia", "/carros-eletricos", "/eletrificacao",
    "/eletricos", "/hibridos", "/veiculos-eletricos", "/carros/eletricos-e-hibridos",
    "/revista/"
]

MIN_NEWS_TITLE_WORDS = 5


_PT_MONTHS = {
    "jan": 1,
    "janeiro": 1,
    "fev": 2,
    "fevereiro": 2,
    "mar": 3,
    "marco": 3,
    "março": 3,
    "abr": 4,
    "abril": 4,
    "mai": 5,
    "maio": 5,
    "jun": 6,
    "junho": 6,
    "jul": 7,
    "julho": 7,
    "ago": 8,
    "agosto": 8,
    "set": 9,
    "setembro": 9,
    "out": 10,
    "outubro": 10,
    "nov": 11,
    "novembro": 11,
    "dez": 12,
    "dezembro": 12,
}


class _MetaImageParser(HTMLParser):
    """Extrai uma imagem de preview de HTML simples, sem dependência externa."""

    def __init__(self) -> None:
        super().__init__()
        self.image_url: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.image_url:
            return
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "meta":
            prop = attrs_dict.get("property", "").lower() or attrs_dict.get("name", "").lower()
            if prop in {"og:image", "twitter:image", "twitter:image:src"}:
                self.image_url = attrs_dict.get("content", "").strip()
        elif tag == "img":
            candidate = _first_image_candidate(attrs_dict)
            if candidate:
                self.image_url = candidate


class _NewsLinkParser(HTMLParser):
    """Coleta links de notícia em páginas de categoria.

    É propositalmente genérico e conservador. A CurVE mostra apenas uma chamada
    curta e encaminha o usuário para a fonte original; se uma página mudar de
    estrutura, o fallback/cache mantém a home no ar.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self._stack: list[dict[str, Any]] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "a":
            href = attrs_dict.get("href", "").strip()
            if href:
                self._stack.append({"href": urljoin(self.base_url, href), "text": [], "image": ""})
        elif self._stack and tag in {"img", "source"}:
            candidate = _first_image_candidate(attrs_dict)
            if candidate and not self._stack[-1].get("image"):
                self._stack[-1]["image"] = urljoin(self.base_url, candidate)

    def handle_data(self, data: str) -> None:
        if self._stack and data:
            self._stack[-1]["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._stack:
            return
        current = self._stack.pop()
        text = re.sub(r"\s+", " ", " ".join(current.get("text") or [])).strip()
        href = str(current.get("href") or "").strip()
        image = str(current.get("image") or "").strip()
        if href and text:
            self.links.append({"url": href, "text": text, "image": image})


def _first_image_candidate(attrs: dict[str, str]) -> str:
    for name in ("src", "data-src", "data-lazy-src", "data-original"):
        candidate = attrs.get(name, "").strip()
        if candidate and not candidate.startswith("data:"):
            return candidate
    srcset = attrs.get("srcset", "").strip()
    if srcset:
        candidate = srcset.split(",", 1)[0].split(" ", 1)[0].strip()
        if candidate and not candidate.startswith("data:"):
            return candidate
    return ""


def _data_dir() -> Path:
    try:
        return Path(current_app.config["DATA_DIR"])
    except RuntimeError:
        return Path(__file__).resolve().parents[1] / "data"


def _persistent_dir() -> Path:
    try:
        return Path(current_app.config["PERSISTENT_DIR"])
    except RuntimeError:
        return _data_dir() / "_runtime"


def _sources_path() -> Path:
    return _data_dir() / "noticias_fontes.json"


def _fallback_path() -> Path:
    return _data_dir() / "noticias_home.json"


def _cache_path() -> Path:
    return _persistent_dir() / "noticias" / "noticias_cache.json"


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_text(value: str) -> str:
    value = _strip_accents(value).lower()
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _strip_html(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _truncate(value: str, max_len: int = 165) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    if len(value) <= max_len:
        return value
    corte = value[: max_len - 1].rsplit(" ", 1)[0].strip()
    return f"{corte}…" if corte else value[:max_len]


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for child in list(element):
        if _tag_name(child) in wanted:
            return _strip_html("".join(child.itertext()))
    return ""


def _child_raw(element: ET.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for child in list(element):
        if _tag_name(child) in wanted:
            return child.text or ""
    return ""


def _link_from_entry(entry: ET.Element) -> str:
    # RSS normalmente usa <link>texto</link>. Atom usa <link href="..." rel="alternate" />.
    rss_link = _child_text(entry, "link")
    if rss_link:
        return rss_link
    for child in list(entry):
        if _tag_name(child) == "link":
            href = child.attrib.get("href", "").strip()
            rel = child.attrib.get("rel", "alternate").lower()
            if href and rel in {"alternate", ""}:
                return href
    return ""


def _image_from_html_fragment(value: str) -> str:
    if not value:
        return ""
    patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+srcset=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I)
        if match:
            candidate = match.group(1).split(",", 1)[0].split(" ", 1)[0].strip()
            if candidate and not candidate.startswith("data:"):
                return candidate
    return ""


def _image_from_entry(entry: ET.Element) -> str:
    # Media RSS: <media:content url="..."> / <media:thumbnail url="...">.
    for child in entry.iter():
        name = _tag_name(child)
        if name in {"content", "thumbnail"}:
            url = child.attrib.get("url", "").strip()
            media_type = child.attrib.get("type", "").lower()
            if url and (not media_type or media_type.startswith("image/")):
                return url
        if name == "enclosure":
            url = child.attrib.get("url", "").strip()
            media_type = child.attrib.get("type", "").lower()
            if url and media_type.startswith("image/"):
                return url
    for field in ["description", "summary", "content", "encoded"]:
        html = _child_raw(entry, field)
        imagem = _image_from_html_fragment(html)
        if imagem:
            return imagem
    return ""


def _parse_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_datetime_from_text(value: str) -> datetime | None:
    value = value or ""
    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", value)
    if match:
        day, month, year = [int(x) for x in match.groups()]
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    match = re.search(
        r"\b(\d{1,2})\s+([A-Za-zçÇáéíóúãõâêô\.]+)\s+(\d{4})\b",
        value,
        flags=re.I,
    )
    if match:
        day = int(match.group(1))
        month_name = _normalize_text(match.group(2).replace(".", ""))
        year = int(match.group(3))
        month = _PT_MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def _format_date(dt: datetime | None, fallback: str = "Fonte externa") -> str:
    if not dt:
        return fallback
    meses = ["jan.", "fev.", "mar.", "abr.", "mai.", "jun.", "jul.", "ago.", "set.", "out.", "nov.", "dez."]
    local = dt.astimezone(timezone.utc)
    return f"{local.day} {meses[local.month - 1]} {local.year}"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_settings() -> dict[str, Any]:
    settings = _read_json(_sources_path(), {})
    if not isinstance(settings, dict):
        settings = {}
    settings.setdefault("atualizacao_horas", DEFAULT_CACHE_HOURS)
    settings.setdefault("limite_total", DEFAULT_LIMIT)
    settings.setdefault("palavras_chave", DEFAULT_KEYWORDS)
    settings.setdefault("fontes", [])
    return settings


def _load_fallback_news() -> list[dict[str, Any]]:
    dados = _read_json(_fallback_path(), [])
    if not isinstance(dados, list):
        return []
    return [_normalize_item(item) for item in dados if isinstance(item, dict)]


def _load_cache() -> dict[str, Any] | None:
    cache = _read_json(_cache_path(), None)
    return cache if isinstance(cache, dict) else None


def _is_cache_valid(cache: dict[str, Any], ttl_hours: int) -> bool:
    items = cache.get("items")
    updated_at = cache.get("updated_at")
    if not isinstance(items, list) or not items or not updated_at:
        return False
    dt = _parse_datetime(str(updated_at))
    if not dt:
        return False
    age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    return age_seconds < max(1, ttl_hours) * 3600


def _active_source_names(settings: dict[str, Any]) -> set[str]:
    sources = settings.get("fontes", [])
    if not isinstance(sources, list):
        return set()
    names: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not source.get("ativo", False):
            continue
        name = str(source.get("nome") or "").strip()
        if name:
            names.add(name)
    return names


def _filter_items_by_sources(items: list[dict[str, Any]], allowed_sources: set[str]) -> list[dict[str, Any]]:
    if not allowed_sources:
        return items
    filtered: list[dict[str, Any]] = []
    for item in items:
        fonte = str(item.get("fonte") or "").strip()
        if fonte in allowed_sources:
            filtered.append(item)
    return filtered


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    titulo = str(item.get("titulo") or item.get("title") or "").strip()
    resumo = str(item.get("resumo") or item.get("summary") or item.get("description") or "").strip()
    url = str(item.get("url") or item.get("link") or "").strip()
    fonte = str(item.get("fonte") or item.get("source") or "Fonte externa").strip()
    tag = str(item.get("tag") or item.get("categoria") or "Mobilidade elétrica").strip()
    imagem = str(item.get("imagem") or item.get("image") or "").strip()
    data = str(item.get("data") or item.get("published") or "Fonte externa").strip()
    data_iso = str(item.get("data_iso") or item.get("published_iso") or "").strip()
    return {
        "tag": tag,
        "fonte": fonte,
        "data": data,
        "titulo": _truncate(titulo, 110),
        "resumo": _truncate(_strip_html(resumo), 170),
        "url": url,
        "imagem": imagem,
        "data_iso": data_iso,
    }


def _is_relevant(item: dict[str, Any], keywords: list[str], aceitar_todos: bool = False) -> bool:
    if aceitar_todos:
        return True
    haystack = _normalize_text(" ".join([item.get("titulo", ""), item.get("resumo", ""), item.get("tag", "")]))
    normalized_keywords = [_normalize_text(k) for k in keywords if str(k).strip()]
    return any(keyword and keyword in haystack for keyword in normalized_keywords)


def _fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html;q=0.8, */*;q=0.5",
        },
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def _fetch_og_image(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    try:
        html = _fetch_url(url, timeout=timeout)
        parser = _MetaImageParser()
        parser.feed(html[:200_000])
        return parser.image_url.strip()
    except Exception:
        return ""


def _entries_from_feed(xml_text: str) -> list[ET.Element]:
    root = ET.fromstring(xml_text)
    root_name = _tag_name(root)
    if root_name == "rss":
        channel = next((child for child in list(root) if _tag_name(child) == "channel"), root)
        return [child for child in list(channel) if _tag_name(child) == "item"]
    if root_name == "feed":
        return [child for child in list(root) if _tag_name(child) == "entry"]
    return [child for child in root.iter() if _tag_name(child) in {"item", "entry"}]


def _rss_urls_from_source(source: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ["rss_url", "feed_url"]:
        value = str(source.get(key) or "").strip()
        if value:
            urls.append(value)
    for key in ["rss_urls", "feed_urls"]:
        value = source.get(key)
        if isinstance(value, list):
            urls.extend(str(u).strip() for u in value if str(u).strip())
    return urls


def _html_urls_from_source(source: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ["page_url", "site_url", "html_url"]:
        value = str(source.get(key) or "").strip()
        if value:
            urls.append(value)
    for key in ["page_urls", "html_urls"]:
        value = source.get(key)
        if isinstance(value, list):
            urls.extend(str(u).strip() for u in value if str(u).strip())
    return urls


def _items_from_rss_url(source: dict[str, Any], rss_url: str, keywords: list[str]) -> list[dict[str, Any]]:
    timeout = int(source.get("timeout_segundos") or DEFAULT_TIMEOUT_SECONDS)
    max_items = int(source.get("limite") or 8)
    source_name = str(source.get("nome") or "Fonte externa").strip()
    default_tag = str(source.get("tag_padrao") or "Mobilidade elétrica").strip()
    aceitar_todos = bool(source.get("aceitar_todos", False))
    usar_og_image = bool(source.get("usar_og_image", False))

    xml_text = _fetch_url(rss_url, timeout=timeout)
    entries = _entries_from_feed(xml_text)
    items: list[dict[str, Any]] = []

    for entry in entries[: max_items * 3]:
        titulo = _child_text(entry, "title")
        url = _link_from_entry(entry)
        raw_summary = _child_raw(entry, "description", "summary", "content", "encoded")
        resumo = _strip_html(raw_summary) or _child_text(entry, "summary", "description", "content")
        published_raw = _child_text(entry, "pubDate", "published", "updated", "dc:date")
        published_dt = _parse_datetime(published_raw)
        imagem = _image_from_entry(entry)
        if not imagem and usar_og_image and url:
            imagem = _fetch_og_image(url, timeout=timeout)

        item = _normalize_item(
            {
                "titulo": titulo,
                "resumo": resumo or "Leia a notícia completa na fonte original.",
                "url": url,
                "fonte": source_name,
                "tag": default_tag,
                "imagem": imagem or str(source.get("imagem_fallback") or ""),
                "data": _format_date(published_dt),
                "data_iso": published_dt.isoformat() if published_dt else "",
            }
        )
        if item["titulo"] and item["url"] and _should_keep_external_news(item, source, keywords):
            items.append(item)
        if len(items) >= max_items:
            break
    return items


def _domain_allowed(url: str, allowed_domains: set[str]) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False
    netloc = parsed.netloc.lower().replace("www.", "")
    return any(netloc == domain or netloc.endswith("." + domain) for domain in allowed_domains)


def _clean_html_link_text(value: str, source_name: str) -> tuple[str, str, datetime | None]:
    text = _strip_html(value)
    text = re.sub(r"\b(LEIA MAIS|Leia mais|Veja mais|Continua após publicidade)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|•\t\n")
    published_dt = _extract_datetime_from_text(text)

    # Remove data no início, comum em páginas de categoria.
    text = re.sub(r"^\d{1,2}/\d{1,2}/\d{4}\s*(às|as)?\s*\d{1,2}h\d{0,2}\s*", "", text, flags=re.I)
    text = re.sub(r"^\d{1,2}/\d{1,2}/\d{4}\s*", "", text, flags=re.I)

    # Remove autor/data no fim, comum em páginas da Abril.
    text = re.sub(
        r"\s+Por\s+.+?\s+\d{1,2}\s+[A-Za-zçÇáéíóúãõâêô\.]+\s+\d{4}.*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+\d{1,2}\s+[A-Za-zçÇáéíóúãõâêô\.]+\s+\d{4},?\s+\d{1,2}h\d{0,2}.*$", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -|•\t\n")

    if not text or _normalize_text(text) in {_normalize_text(source_name), "home", "noticias", "ultimas noticias"}:
        return "", "", published_dt

    # Tenta separar título e chamada curta sem copiar conteúdo longo.
    title = text
    summary = "Leia a notícia completa na fonte original."
    match = re.search(r"([\?\.!])\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9])", text)
    if match and match.start() < 125:
        title = text[: match.start() + 1].strip()
        summary = text[match.end() - 1 :].strip()
    elif len(text) > 118:
        title = text[:118].rsplit(" ", 1)[0].strip()
        summary = text[len(title) :].strip(" -|•") or summary

    return _truncate(title, 110), _truncate(summary, 170), published_dt




def _looks_like_bad_news_link(title: str, url: str) -> bool:
    title_norm = _normalize_text(title or "")
    url_norm = _normalize_text(url or "")
    if not title_norm or not url_norm:
        return True

    # Títulos genéricos de menu não são notícia.
    words = [w for w in re.split(r"\s+", title_norm) if w]
    if len(words) < MIN_NEWS_TITLE_WORDS:
        return True

    for bad in BAD_NEWS_TERMS:
        bad_norm = _normalize_text(bad)
        if title_norm == bad_norm or title_norm.startswith(bad_norm + " "):
            return True
        if bad_norm in {"assine", "assinante", "oferta", "promocao", "promoção"} and bad_norm in title_norm:
            return True

    for bad in BAD_URL_PARTS:
        bad_norm = _normalize_text(bad)
        if bad_norm.endswith("$"):
            if url_norm.rstrip("/").endswith(bad_norm[:-1].rstrip("/")):
                return True
        elif bad_norm in url_norm:
            return True

    return False


def _looks_like_article_url(url: str, source: dict[str, Any]) -> bool:
    url_norm = _normalize_text(url or "")
    if not url_norm:
        return False
    if any(part.rstrip("$") in url_norm for part in [_normalize_text(p) for p in BAD_URL_PARTS if not p.endswith("$")]):
        return False
    # Para páginas HTML, exige pelo menos um indício de matéria/artigo.
    if str(source.get("tipo") or "").lower() in {"html", "pagina", "page"}:
        hints = source.get("url_indicios_noticia") or GOOD_URL_HINTS
        if isinstance(hints, list) and hints:
            normalized_hints = [_normalize_text(str(h)) for h in hints]
            return any(h in url_norm for h in normalized_hints)
    return True


def _should_keep_external_news(item: dict[str, Any], source: dict[str, Any], keywords: list[str]) -> bool:
    title = str(item.get("titulo") or "")
    url = str(item.get("url") or "")
    if _looks_like_bad_news_link(title, url):
        return False
    if not _looks_like_article_url(url, source):
        return False
    if not _is_relevant(item, keywords, aceitar_todos=bool(source.get("aceitar_todos", False))):
        return False
    return True

def _items_from_html_url(source: dict[str, Any], page_url: str, keywords: list[str]) -> list[dict[str, Any]]:
    timeout = int(source.get("timeout_segundos") or DEFAULT_TIMEOUT_SECONDS)
    max_items = int(source.get("limite") or 8)
    source_name = str(source.get("nome") or "Fonte externa").strip()
    default_tag = str(source.get("tag_padrao") or "Mobilidade elétrica").strip()
    aceitar_todos = bool(source.get("aceitar_todos", False))
    usar_og_image = bool(source.get("usar_og_image", True))
    max_og_images = int(source.get("max_og_images") or 2)
    imagem_fallback = str(source.get("imagem_fallback") or "")

    parsed_page = urlparse(page_url)
    allowed_domains = {parsed_page.netloc.lower().replace("www.", "")}
    for domain in source.get("dominios_permitidos", []) if isinstance(source.get("dominios_permitidos"), list) else []:
        domain = str(domain).strip().lower().replace("www.", "")
        if domain:
            allowed_domains.add(domain)

    html = _fetch_url(page_url, timeout=timeout)
    parser = _NewsLinkParser(page_url)
    parser.feed(html[:600_000])

    items: list[dict[str, Any]] = []
    og_fetches = 0
    for link in parser.links:
        url = str(link.get("url") or "").strip()
        raw_text = str(link.get("text") or "").strip()
        if not url or not raw_text or not _domain_allowed(url, allowed_domains):
            continue
        if any(part in url.lower() for part in ["/tag/", "/autor/", "/login", "/assine", "/newsletter", "facebook.com", "instagram.com", "youtube.com"]):
            continue

        title, summary, published_dt = _clean_html_link_text(raw_text, source_name)
        if not title:
            continue

        image = str(link.get("image") or "").strip()
        if image:
            image = urljoin(page_url, image)
        if not image and usar_og_image and og_fetches < max_og_images:
            image = _fetch_og_image(url, timeout=timeout)
            og_fetches += 1

        item = _normalize_item(
            {
                "titulo": title,
                "resumo": summary,
                "url": url,
                "fonte": source_name,
                "tag": default_tag,
                "imagem": image or imagem_fallback,
                "data": _format_date(published_dt),
                "data_iso": published_dt.isoformat() if published_dt else "",
            }
        )
        if item["titulo"] and item["url"] and _should_keep_external_news(item, source, keywords):
            items.append(item)
        if len(items) >= max_items:
            break
    return items


def _items_from_source(source: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    if not source.get("ativo", False):
        return []

    tipo = str(source.get("tipo") or "rss").strip().lower()
    items: list[dict[str, Any]] = []

    if tipo in {"rss", "feed", "auto"}:
        for rss_url in _rss_urls_from_source(source):
            try:
                items.extend(_items_from_rss_url(source, rss_url, keywords=keywords))
            except Exception:
                continue

    if tipo in {"html", "pagina", "page", "auto"}:
        for page_url in _html_urls_from_source(source):
            try:
                items.extend(_items_from_html_url(source, page_url, keywords=keywords))
            except Exception:
                continue

    return _sort_items(_dedupe_items(items))


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = _normalize_text(item.get("url") or item.get("titulo") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str]:
        dt = _parse_datetime(str(item.get("data_iso") or ""))
        if not dt:
            return (0, "")
        return (1, dt.isoformat())

    return sorted(items, key=key, reverse=True)


def _diversify_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mistura as notícias por fonte para evitar domínio de um único portal na home."""
    ordered_items = _sort_items(_dedupe_items(items))
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in ordered_items:
        source_key = _normalize_text(str(item.get("fonte") or "fonte externa")) or "fonte externa"
        if source_key not in buckets:
            buckets[source_key] = []
            order.append(source_key)
        buckets[source_key].append(item)

    result: list[dict[str, Any]] = []
    while True:
        progressed = False
        for source_key in order:
            bucket = buckets.get(source_key) or []
            if not bucket:
                continue
            result.append(bucket.pop(0))
            progressed = True
        if not progressed:
            break
    return result


def _source_count(items: list[dict[str, Any]]) -> int:
    fontes = {
        _normalize_text(str(item.get("fonte") or ""))
        for item in items
        if isinstance(item, dict) and item.get("fonte")
    }
    return len({fonte for fonte in fontes if fonte})


def _merge_with_fallback(items: list[dict[str, Any]], min_sources: int, limit: int) -> list[dict[str, Any]]:
    """Completa o radar com fallback editorial quando os feeds retornam poucas fontes.

    Isso evita a home ficar visualmente dominada por um único portal quando RSS,
    cache ou scraping de páginas externas entregam resultado limitado.
    """
    normalized_items = [_normalize_item(item) for item in items if isinstance(item, dict)]
    if _source_count(normalized_items) >= min_sources:
        return _diversify_items(normalized_items)[:limit]

    fallback_items = [_normalize_item(item) for item in _load_fallback_news() if isinstance(item, dict)]
    merged = _diversify_items(normalized_items + fallback_items)
    return merged[:limit]


def _refresh_from_sources(settings: dict[str, Any]) -> list[dict[str, Any]]:
    keywords = [str(k) for k in settings.get("palavras_chave", DEFAULT_KEYWORDS)]
    sources = settings.get("fontes", [])
    if not isinstance(sources, list):
        return []

    items: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        try:
            items.extend(_items_from_source(source, keywords=keywords))
        except Exception:
            # Uma fonte fora do ar não deve quebrar a home.
            continue
    return _diversify_items(items)


def carregar_noticias_home(limite: int | None = None, forcar_atualizacao: bool = False) -> list[dict[str, Any]]:
    """Carrega o radar da home com cache e fallback seguro.

    Nesta versão do radar, a home usa apenas fontes RSS que já entregaram
    matérias boas com imagem: InsideEVs Brasil e Motor1 Brasil. O filtro por
    fontes ativas impede que um cache antigo do Render reapareça com links de
    assinatura, categorias ou páginas genéricas.
    """
    settings = _load_settings()
    ttl_hours = int(settings.get("atualizacao_horas") or DEFAULT_CACHE_HOURS)
    limit = int(limite or settings.get("limite_total") or DEFAULT_LIMIT)
    allowed_sources = _active_source_names(settings)

    cache = _load_cache()
    if not forcar_atualizacao and cache and _is_cache_valid(cache, ttl_hours):
        cached_items = [
            _normalize_item(item)
            for item in cache.get("items", [])
            if isinstance(item, dict)
        ]
        cached_items = _filter_items_by_sources(cached_items, allowed_sources)
        if cached_items:
            return _diversify_items(cached_items)[:limit]

    fresh_items = _filter_items_by_sources(_refresh_from_sources(settings), allowed_sources)
    if fresh_items:
        final_items = _diversify_items(fresh_items)[:limit]
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": "insideevs_motor1_rss",
            "items": final_items,
            "source_count": _source_count(final_items),
        }
        try:
            _write_json(_cache_path(), payload)
        except Exception:
            pass
        return final_items

    if cache and isinstance(cache.get("items"), list) and cache.get("items"):
        cached_items = [_normalize_item(item) for item in cache["items"] if isinstance(item, dict)]
        cached_items = _filter_items_by_sources(cached_items, allowed_sources)
        if cached_items:
            return _diversify_items(cached_items)[:limit]

    fallback_items = _filter_items_by_sources(_load_fallback_news(), allowed_sources)
    return _diversify_items(fallback_items)[:limit]
