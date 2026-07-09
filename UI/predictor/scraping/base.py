"""
Shared scraping helpers.

The per-portal parsers below reuse the exact CSS selectors from the reference
scripts ``rtrs_scrape_content.py``, ``klix_scrape_content.py`` and
``stav_content_scrape.py`` — reduced to a single-URL fetch (no multi-server
checkpointing) suitable for on-demand use inside a web request.
"""
from __future__ import annotations

import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "bs-BA,bs;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# Do not search the entire page for a generic word such as ``captcha``.
# Klix may load reCAPTCHA JavaScript for its forms even when the article page
# itself is fully accessible.  A generic substring check therefore produces a
# false "blocked" result for valid HTTP 200 responses.
_BLOCK_PAGE_TITLES = (
    "just a moment",
    "attention required",
    "access denied",
    "request rejected",
    "security check",
)

_BLOCK_PAGE_MARKERS = (
    "verify you are human",
    "checking your browser",
    "cf-chl-",
    "cloudflare ray id",
    "temporarily blocked",
    "too many requests",
)



class ScrapeError(Exception):
    """Raised when an article cannot be retrieved or parsed."""


def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry_strategy = Retry(
        total=2,
        backoff_factor=1,
        status_forcelist=[500, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def is_blocked_response(response) -> bool:
    """Return True only for an actual anti-bot/block page.

    A normal Klix article may contain reCAPTCHA assets because the page has
    interactive forms.  Seeing the word ``captcha`` in raw HTML is therefore
    not sufficient evidence that the request was blocked.
    """
    if response.status_code in (401, 403, 429):
        return True

    text_lower = response.text.lower()
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text_lower, re.S)
    title = clean_text(title_match.group(1)) if title_match else ""

    if any(marker in title for marker in _BLOCK_PAGE_TITLES):
        return True

    # Challenge pages normally contain several anti-bot markers and no real
    # article element. Requiring both avoids false positives from ordinary JS.
    marker_hits = sum(marker in text_lower for marker in _BLOCK_PAGE_MARKERS)
    has_article_markup = "<article" in text_lower or 'property="og:title"' in text_lower
    return marker_hits >= 2 and not has_article_markup


def fetch(url: str, session, timeout: int):
    """GET a URL, translating common failures into friendly ScrapeErrors."""
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.exceptions.Timeout:
        raise ScrapeError("The portal did not respond in time (timeout).")
    except requests.exceptions.ConnectionError:
        raise ScrapeError("Could not connect to the portal.")
    except requests.exceptions.RequestException as exc:
        raise ScrapeError(f"Network error: {exc}")

    if response.status_code == 502:
        raise ScrapeError("The portal returned 502 Bad Gateway.")
    if is_blocked_response(response):
        raise ScrapeError(
            f"The portal blocked the request (status {response.status_code})."
        )
    if response.status_code != 200:
        raise ScrapeError(f"The portal returned HTTP {response.status_code}.")
    return response
