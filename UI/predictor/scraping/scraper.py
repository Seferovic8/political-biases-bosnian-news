"""Single-URL scraping entry point used by the views."""
from __future__ import annotations

from urllib.parse import urlparse, urlunparse
from django.conf import settings

from .base import ScrapeError, create_session, fetch
from .portals import SUPPORTED_PORTALS, parser_for_url


def _valid_url(url: str) -> bool:
    try:
        parts = urlparse(url)
        return parts.scheme in ("http", "https") and bool(parts.netloc)
    except Exception:
        return False

def _normalize_url(url: str) -> str:
    try:
        parts = urlparse(url)

        if parts.netloc.lower() in ("www.rtrs.tv", "rtrs.tv"):
            parts = parts._replace(netloc="lat.rtrs.tv")
            return urlunparse(parts)

        return url
    except Exception:
        return url
def scrape_url(url: str, session=None) -> dict:
    """Retrieve and parse a single article URL.

    Returns a dict with ``ok`` plus either the parsed article fields or an
    ``error`` message. Never raises — errors are reported per-URL so a batch
    can continue.
    """
    url = (url or "").strip()
    url = _normalize_url(url)

    base = {"url": url, "ok": False}

    if not url:
        return {**base, "error": "Empty URL."}
    if not _valid_url(url):
        return {**base, "error": "Not a valid http(s) URL."}

    parser = parser_for_url(url)
    if parser is None:
        return {
            **base,
            "error": "Unsupported portal. Supported: "
                     + ", ".join(SUPPORTED_PORTALS) + ".",
        }

    close_session = False
    if session is None:
        session = create_session()
        close_session = True

    try:
        response = fetch(url, session, settings.SCRAPE_TIMEOUT)
        article = parser(response.text, url)
        if not (article.get("content") or "").strip():
            return {**base, "error": "The article text could not be extracted."}
        article["ok"] = True
        return article
    except ScrapeError as exc:
        return {**base, "error": str(exc)}
    except Exception as exc:  # defensive: never break the batch
        return {**base, "error": f"Unexpected error while scraping: {exc}"}
    finally:
        if close_session:
            session.close()


def scrape_many(urls):
    session = create_session()
    try:
        return [scrape_url(u, session=session) for u in urls]
    finally:
        session.close()
