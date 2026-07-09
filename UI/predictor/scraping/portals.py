"""
Per-portal article parsers (RTRS, Klix, Stav).

Selectors are taken directly from the reference scrapers so the retrieved
title / content match what the models were evaluated on.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .base import ScrapeError, clean_text


# ---------------------------------------------------------------------------
# RTRS  (rtrs_scrape_content.py)
# ---------------------------------------------------------------------------
def parse_rtrs(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    article = soup.select_one("article")
    if article is None:
        raise ScrapeError("Could not find the RTRS <article> block.")

    rubrika_tag = soup.select_one(".pod-meni li.sel a")
    rubrika = clean_text(rubrika_tag.get_text(" ")) if rubrika_tag else ""

    vrijeme_izvor_tag = article.select_one(".vrijeme-izvor")
    vrijeme_izvor = (clean_text(vrijeme_izvor_tag.get_text(" "))
                     if vrijeme_izvor_tag else "")
    datum = ""
    if vrijeme_izvor:
        m = re.search(r"\d{1,2}/\d{1,2}/\d{4}", vrijeme_izvor)
        if m:
            datum = m.group(0)

    naslov_tag = article.select_one("h1.naslov_vijesti")
    naslov = clean_text(naslov_tag.get_text(" ")) if naslov_tag else ""

    podnaslov_tag = article.select_one(".lead")
    podnaslov = clean_text(podnaslov_tag.get_text(" ")) if podnaslov_tag else ""

    body_tag = article.select_one(".nwzbody")
    paragraphs = []
    if body_tag:
        for unwanted in body_tag.select(
            "script, style, iframe, img, .caption, .txtcaption, "
            ".twitter-tweet, .nwzphoto, .txtCaptionDiv"
        ):
            unwanted.decompose()
        for p in body_tag.find_all("p"):
            t = clean_text(p.get_text(" "))
            if t:
                paragraphs.append(t)

    content = "\n\n".join(paragraphs)
    return _result("RTRS", naslov, podnaslov, content, url, rubrika, datum)


# ---------------------------------------------------------------------------
# Stav  (stav_content_scrape.py)
# ---------------------------------------------------------------------------
def _meta(soup, selector):
    tag = soup.select_one(selector)
    if tag and tag.get("content"):
        return clean_text(tag["content"])
    return ""


def parse_stav(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    article = soup.select_one("article#article")
    if article is None:
        raise ScrapeError("Could not find the Stav article#article block.")

    meta_title = _meta(soup, 'meta[property="og:title"]')
    meta_description = _meta(soup, 'meta[property="og:description"]')

    rubrika = ""
    datum = ""
    holder = article.select_one("#main p.flex")
    if holder:
        rubrika_tag = holder.select_one('a[href^="/kategorija/"]')
        if rubrika_tag:
            rubrika = clean_text(rubrika_tag.get_text(" "))
        m = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", holder.get_text(" "))
        if m:
            datum = m.group(0)

    naslov_tag = article.select_one("#main h1")
    naslov = clean_text(naslov_tag.get_text(" ")) if naslov_tag else ""
    podnaslov_tag = article.select_one("#main h2")
    podnaslov = clean_text(podnaslov_tag.get_text(" ")) if podnaslov_tag else ""

    if not naslov:
        naslov = meta_title
    if not podnaslov:
        podnaslov = meta_description

    body_tag = article.select_one(".post-content-holder")
    paragraphs = []
    if body_tag:
        for unwanted in body_tag.select(
            "script, style, iframe, img, figure, .reklama, .ads, .twitter-tweet"
        ):
            unwanted.decompose()
        for p in body_tag.find_all("p"):
            t = clean_text(p.get_text(" "))
            if t:
                paragraphs.append(t)

    content = "\n\n".join(paragraphs)
    return _result("STAV", naslov, podnaslov, content, url, rubrika, datum)


# ---------------------------------------------------------------------------
# Klix  (klix_scrape_content.py)
# ---------------------------------------------------------------------------
_KLIX_BAD_PHRASES = [
    "podijeli", "komentari", "komentara", "dijeljenja", "najnovije",
    "najčitanije", "pratite nas", "marketing",
    "preuzimanje sadržaja", "pročitajte još", "vezani članci",
    "kliknite ovdje", "newsletter", "login", "registracija", "forum",
    "naslovnica",
]


def _klix_bad_paragraph(text: str) -> bool:
    text = clean_text(text)
    if not text or len(text) < 20:
        return True
    lower = text.lower()
    return any(p in lower for p in _KLIX_BAD_PHRASES)


def _klix_strip(container):
    selectors = [
        "script", "style", "nav", "aside", "form", "button", "input",
        "textarea", "select", "img", "[id*='ads']", "[class*='ads']",
        "[class*='ad-']", "[class*='advert']", "[class*='share']",
        "[class*='comment']", "[class*='related']", "[class*='breadcrumb']",
        ".twitter-tweet", ".instagram-media",
    ]
    for sel in selectors:
        for tag in container.select(sel):
            tag.decompose()


def _walk_json(value):
    """Yield every dictionary contained in a JSON-LD structure."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _klix_news_json(soup):
    """Return Klix NewsArticle JSON-LD when it is available."""
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for obj in _walk_json(data):
            obj_type = obj.get("@type")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if any(t in {"NewsArticle", "Article"} for t in types):
                return obj
    return {}


def _klix_date_from_url(url: str) -> str:
    """Convert Klix ID YYMMDDxxx at the end of a URL to DD.MM.YYYY."""
    match = re.search(r"/(\d{6})\d{3}(?:[/?#]|$)", url)
    if not match:
        return ""
    raw = match.group(1)
    yy, mm, dd = raw[:2], raw[2:4], raw[4:6]
    try:
        year = 2000 + int(yy)
        month = int(mm)
        day = int(dd)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return ""
        return f"{day:02d}.{month:02d}.{year:04d}."
    except ValueError:
        return ""


def _append_klix_text(parts, text):
    """Split, clean and append usable article text."""
    if not text:
        return
    for chunk in re.split(r"[\r\n]+", str(text)):
        chunk = clean_text(chunk)
        if chunk and not _klix_bad_paragraph(chunk):
            parts.append(chunk)


def parse_klix(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    news_json = _klix_news_json(soup)

    naslov = _meta(soup, "meta[property='og:title']")
    if not naslov:
        naslov = clean_text(news_json.get("headline", ""))
    if not naslov:
        h1 = soup.select_one("article h1") or soup.select_one("main h1") or soup.select_one("h1")
        if h1:
            naslov = clean_text(h1.get_text(" "))
    if not naslov:
        title_tag = soup.select_one("title")
        if title_tag:
            naslov = re.sub(
                r"\s*[-|]\s*Klix\.ba\s*$",
                "",
                clean_text(title_tag.get_text(" ")),
                flags=re.I,
            ).strip()

    lead = (
        soup.select_one("article span.lead")
        or soup.select_one("article .lead")
        or soup.select_one("main span.lead")
        or soup.select_one("span.lead")
    )
    podnaslov = clean_text(lead.get_text(" ")) if lead else ""
    if not podnaslov:
        podnaslov = _meta(soup, "meta[name='description']")
    if not podnaslov:
        podnaslov = _meta(soup, "meta[property='og:description']")
    if not podnaslov:
        podnaslov = clean_text(news_json.get("description", ""))

    parts = []
    if lead:
        _append_klix_text(parts, lead.get_text(" "))

    # JSON-LD is the most stable fallback when Klix changes Tailwind classes.
    json_body = news_json.get("articleBody", "")
    if json_body:
        _append_klix_text(parts, json_body)

    body = None
    body_selectors = (
        "article div.break-words",
        "div.break-words",
        "article [class*='break-words']",
        "article [itemprop='articleBody']",
        "[itemprop='articleBody']",
        "article .article-content",
        "article [class*='article-content']",
        "main article",
    )
    for selector in body_selectors:
        body = soup.select_one(selector)
        if body:
            break

    if body:
        body_copy = BeautifulSoup(str(body), "html.parser")
        _klix_strip(body_copy)
        for tag in body_copy.find_all(["p", "h2", "h3"], recursive=True):
            _append_klix_text(parts, tag.get_text(" "))

    # Last fallback for older pages or another CSS redesign.
    if len(parts) <= 1:
        article = soup.select_one("article") or soup.select_one("main")
        if article:
            article_copy = BeautifulSoup(str(article), "html.parser")
            _klix_strip(article_copy)
            for heading in article_copy.find_all("h1"):
                heading.decompose()
            for tag in article_copy.find_all("p"):
                _append_klix_text(parts, tag.get_text(" "))

    # De-duplicate while preserving article order.
    seen = set()
    final_parts = []
    for part in parts:
        key = re.sub(r"\W+", " ", part.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            final_parts.append(part)

    content = "\n\n".join(final_parts)
    if not content:
        raise ScrapeError(
            "Klix page was downloaded, but article text was not found. "
            "The page structure may have changed or an anti-bot page was returned."
        )

    datum = ""
    published = clean_text(news_json.get("datePublished", ""))
    if published:
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", published)
        if match:
            datum = f"{match.group(3)}.{match.group(2)}.{match.group(1)}."
    if not datum:
        time_tag = soup.select_one("time[datetime]")
        if time_tag:
            match = re.match(r"(\d{4})-(\d{2})-(\d{2})", time_tag.get("datetime", ""))
            if match:
                datum = f"{match.group(3)}.{match.group(2)}.{match.group(1)}."
    if not datum:
        datum = _klix_date_from_url(url)

    path_parts = [part for part in urlparse(url).path.split("/") if part]
    rubrika = path_parts[1].replace("-", " ").title() if len(path_parts) >= 3 else ""

    return _result("Klix.ba", naslov, podnaslov, content, url, rubrika, datum)


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------
_HOST_PARSERS = [
    ("rtrs.tv", parse_rtrs),
    ("lat.rtrs.tv", parse_rtrs),
    ("klix.ba", parse_klix),
    ("stav.ba", parse_stav),
]

SUPPORTED_PORTALS = ["RTRS (rtrs.tv)", "Klix (klix.ba)", "Stav (stav.ba)"]


def parser_for_url(url: str):
    host = (urlparse(url).netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for needle, parser in _HOST_PARSERS:
        if needle in host:
            return parser
    return None


def _result(portal, title, subtitle, content, url, rubrika, datum):
    return {
        "portal": portal,
        "title": title,
        "subtitle": subtitle,
        "content": content,
        "url": url,
        "rubrika": rubrika,
        "datum": datum,
    }
