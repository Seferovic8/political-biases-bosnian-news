import re
import time
import random
import os
import json
import hashlib
import subprocess
import pandas as pd
import requests

from bs4 import BeautifulSoup
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ============================================================
# INPUT
# ============================================================

INPUT_CSV = "nov.csv"

# Input CSV treba imati barem kolonu:
# link
#
# Poželjno ako ima:
# title, date


# ============================================================
# SERVERI
# ============================================================

NUM_SERVERS = 3

# Od kojeg do kojeg servera da ide automatski
START_SERVER_ID = 0
END_SERVER_ID = 2

# Ova vrijednost se automatski mijenja u petlji
SERVER_ID = START_SERVER_ID


# ============================================================
# OUTPUT
# ============================================================

BASE_CHECKPOINT_DIR = "checkpoints/klix"

CHECKPOINT_DIR = ""
OUTPUT_JSONL = ""
OUTPUT_CSV = ""
ERROR_LOG_CSV = ""


# ============================================================
# GOOGLE DRIVE UPLOAD PREKO RCLONE
# ============================================================

UPLOAD_TO_DRIVE = True

# Moraš jednom ranije uraditi:
# rclone config
#
# i napraviti remote npr. "gdrive"
#
# Ovo znači da upload ide u Google Drive folder:
# klix_scrape/server_0/
# klix_scrape/server_1/
# ...
DRIVE_REMOTE_DIR = "gdrive:klix_scrape_70k"

# Ako je True, skripta staje ako upload ne uspije.
# Ako je False, nastavlja na sljedeći server.
STOP_IF_UPLOAD_FAIL = False


# ============================================================
# SETTINGS
# ============================================================

SLEEP_BETWEEN_REQUESTS = (0.8, 2.0)
BLOCK_SLEEP_SECONDS = 180
MAX_RETRIES_PER_ARTICLE = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "bs-BA,bs;q=0.9,en;q=0.8",
}


# ============================================================
# ERRORS
# ============================================================

class SkipArticleError(Exception):
    pass


# ============================================================
# BASIC HELPERS
# ============================================================

def setup_server_paths(server_id):
    """
    Postavlja globalne putanje za trenutni SERVER_ID.
    Ovo omogućava da jedna skripta radi server 0, pa 1, pa 2...
    """
    global SERVER_ID
    global CHECKPOINT_DIR
    global OUTPUT_JSONL
    global OUTPUT_CSV
    global ERROR_LOG_CSV

    SERVER_ID = server_id

    CHECKPOINT_DIR = os.path.join(BASE_CHECKPOINT_DIR, f"server_{SERVER_ID}")

    OUTPUT_JSONL = os.path.join(
        CHECKPOINT_DIR,
        f"klix_articles_checkpoint_server_{SERVER_ID}.jsonl"
    )

    OUTPUT_CSV = os.path.join(
        CHECKPOINT_DIR,
        f"klix_articles_final_server_{SERVER_ID}.csv"
    )

    ERROR_LOG_CSV = os.path.join(
        CHECKPOINT_DIR,
        f"klix_errors_server_{SERVER_ID}.csv"
    )


def ensure_dirs():
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_link(link):
    if link is None:
        return ""

    link = str(link).strip()

    if link.lower() == "nan":
        return ""

    return link


def link_belongs_to_this_server(link):
    """
    Deterministički raspoređuje linkove po serverima.

    Isti link će uvijek otići na isti SERVER_ID.
    Ovo sprječava da dva servera scrapeaju isti članak.
    """
    link = normalize_link(link)

    if not link:
        return False

    link_hash = hashlib.md5(link.encode("utf-8")).hexdigest()
    link_number = int(link_hash, 16)

    return link_number % NUM_SERVERS == SERVER_ID


def create_session():
    session = requests.Session()

    retry_strategy = Retry(
        total=2,
        backoff_factor=2,
        # 502 namjerno nije ovdje jer njega odmah preskačemo
        status_forcelist=[500, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update(HEADERS)

    return session


def is_blocked_response(response):
    if response.status_code in [403, 429]:
        return True

    text_lower = response.text.lower()

    # Važno: NE stavljati samo "captcha".
    # Klix normalno ima recaptcha JS u HTML-u i kad stranica nije blokirana.
    block_keywords = [
        "too many requests",
        "access denied",
        "temporarily blocked",
        "rate limit",
        "your access has been blocked",
        "request blocked",
        "unusual traffic"
    ]

    return any(keyword in text_lower for keyword in block_keywords)


# ============================================================
# JSON / META HELPERS
# ============================================================

def extract_json_ld_objects(soup):
    objects = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()

        if not raw:
            continue

        raw = raw.strip()

        try:
            data = json.loads(raw)

            if isinstance(data, list):
                objects.extend(data)
            elif isinstance(data, dict):
                objects.append(data)

        except Exception:
            continue

    return objects


def find_newsarticle_jsonld(soup):
    objects = extract_json_ld_objects(soup)

    for obj in objects:
        obj_type = obj.get("@type", "")

        if isinstance(obj_type, list):
            if "NewsArticle" in obj_type:
                return obj
        elif obj_type == "NewsArticle":
            return obj

    return {}


def extract_ad_config_json(text):
    """
    Izvlači window.AD_CONFIG = {...};
    Korisno za: Autor, Kategorija, Podkategorija, Segment, ClanakID.
    """
    marker = "window.AD_CONFIG"
    pos = text.find(marker)

    if pos == -1:
        return {}

    eq_pos = text.find("=", pos)

    if eq_pos == -1:
        return {}

    brace_start = text.find("{", eq_pos)

    if brace_start == -1:
        return {}

    depth = 0
    in_string = False
    escape = False

    for i in range(brace_start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1

                if depth == 0:
                    json_text = text[brace_start:i + 1]

                    try:
                        return json.loads(json_text)
                    except Exception:
                        return {}

    return {}


def get_ad_server_value(ad_config, key):
    try:
        return clean_text(ad_config.get("targeting", {}).get("server", {}).get(key, ""))
    except Exception:
        return ""


def extract_meta_content(soup, selector):
    tag = soup.select_one(selector)

    if tag and tag.get("content"):
        return clean_text(tag.get("content"))

    return ""


# ============================================================
# KLIX HELPERS
# ============================================================

def extract_article_id_from_url(url):
    return url.rstrip("/").split("/")[-1]


def extract_date_from_klix_url(url):
    """
    Klix URL često završava ID-em oblika YYMMDDxxx.
    Primjer:
    260611166 -> 2026-06-11 po URL-u

    Napomena:
    Kod novijih Klix članaka bolji datum je iz meta publish-date / JSON-LD.
    Ova funkcija je fallback.
    """
    last_part = url.rstrip("/").split("/")[-1]

    match = re.match(r"^(\d{2})(\d{2})(\d{2})\d*$", last_part)

    if not match:
        return ""

    yy, mm, dd = match.groups()

    try:
        year = int("20" + yy)
        month = int(mm)
        day = int(dd)

        if not (1 <= month <= 12 and 1 <= day <= 31):
            return ""

        return f"{year:04d}-{month:02d}-{day:02d}"

    except ValueError:
        return ""


def normalize_datetime_to_date(value):
    """
    2026-06-20T19:53:00Z -> 2026-06-20
    Ako je već datum, ostaje datum.
    """
    value = clean_text(value)

    if not value:
        return ""

    match = re.search(r"(\d{4}-\d{2}-\d{2})", value)

    if match:
        return match.group(1)

    return value


def extract_article_class_from_url(url):
    try:
        path_parts = urlparse(url).path.strip("/").split("/")

        if len(path_parts) >= 1:
            return clean_text(path_parts[0]).lower()

    except Exception:
        pass

    return ""


def extract_subcategory_from_url(url):
    try:
        path_parts = urlparse(url).path.strip("/").split("/")

        if len(path_parts) >= 2:
            return clean_text(path_parts[1]).lower()

    except Exception:
        pass

    return ""


def extract_title(soup, news_json):
    if news_json.get("headline"):
        return clean_text(news_json.get("headline"))

    value = extract_meta_content(soup, "meta[property='og:title']")
    if value:
        return re.sub(r"\s*-\s*Klix\.ba\s*$", "", value).strip()

    h1 = soup.select_one("article h1") or soup.select_one("h1")
    if h1:
        return clean_text(h1.get_text(" "))

    value = extract_meta_content(soup, "meta[name='twitter:title']")
    if value:
        return re.sub(r"\s*-\s*Klix\.ba\s*$", "", value).strip()

    title_tag = soup.select_one("title")
    if title_tag:
        return re.sub(r"\s*-\s*Klix\.ba\s*$", "", clean_text(title_tag.get_text(" "))).strip()

    return ""


def extract_podnaslov(soup, news_json):
    """
    Podnaslov/lead.
    U HTML-u Klixa lead je najčešće u:
    span.lead
    """
    lead = soup.select_one("article span.lead") or soup.select_one("span.lead")

    if lead:
        value = clean_text(lead.get_text(" "))
        if value:
            return value

    value = extract_meta_content(soup, "meta[name='description']")
    if value:
        return value

    value = extract_meta_content(soup, "meta[property='og:description']")
    if value:
        return value

    if news_json.get("description"):
        return clean_text(news_json.get("description"))

    return ""


def extract_nadnaslov(soup):
    """
    Na Klixu je nadnaslov često mali uppercase tekst iznad h1.
    """
    h1 = soup.select_one("article h1") or soup.select_one("h1")

    if h1:
        previous = h1.find_previous(
            lambda tag:
            tag.name in ["div", "span"]
            and tag.get_text(strip=True)
            and "uppercase" in " ".join(tag.get("class", [])).lower()
        )

        if previous:
            value = clean_text(previous.get_text(" "))
            if 0 < len(value) <= 150:
                return value

    selectors = [
        "article .uppercase",
        "article [class*='uppercase']",
        "main .uppercase",
        "main [class*='uppercase']"
    ]

    for selector in selectors:
        tag = soup.select_one(selector)

        if tag:
            value = clean_text(tag.get_text(" "))

            if value and len(value) <= 150:
                return value

    return ""


def extract_author(soup, news_json, ad_config):
    author_from_ad = get_ad_server_value(ad_config, "Autor")
    if author_from_ad:
        return author_from_ad

    author = news_json.get("author", "")

    if isinstance(author, dict):
        name = clean_text(author.get("name", ""))
        if name:
            return name

    if isinstance(author, list):
        names = []

        for item in author:
            if isinstance(item, dict) and item.get("name"):
                names.append(clean_text(item.get("name")))

        if names:
            return ", ".join(names)

    meta_author = extract_meta_content(soup, "meta[name='author']")
    if meta_author:
        return meta_author

    text = clean_text(soup.get_text(" "))

    match = re.search(r"Piše:\s*([^0-9|]+?)(?:\s+\d+h|\s+\d+min|\s+\d{1,2}\.\d{1,2}\.|$)", text)
    if match:
        return clean_text(match.group(1))

    return ""


def extract_datum(soup, news_json, url):
    meta_publish = extract_meta_content(soup, "meta[name='publish-date']")
    if meta_publish:
        return normalize_datetime_to_date(meta_publish)

    if news_json.get("datePublished"):
        return normalize_datetime_to_date(news_json.get("datePublished"))

    if news_json.get("dateModified"):
        return normalize_datetime_to_date(news_json.get("dateModified"))

    time_tag = soup.select_one("time")
    if time_tag:
        if time_tag.get("datetime"):
            return normalize_datetime_to_date(time_tag.get("datetime"))

        value = clean_text(time_tag.get_text(" "))
        if value:
            return value

    return extract_date_from_klix_url(url)


def extract_picture_path(soup, news_json, url):
    if news_json.get("image"):
        image = news_json.get("image")

        if isinstance(image, list) and image:
            return clean_text(image[0])

        if isinstance(image, str):
            return clean_text(image)

    og_image = extract_meta_content(soup, "meta[property='og:image']")
    if og_image and "klix_og" not in og_image:
        return og_image

    preload_img = soup.select_one('link[rel="preload"][as="image"]')
    if preload_img and preload_img.get("href"):
        return clean_text(preload_img.get("href"))

    article_id = extract_article_id_from_url(url)
    article_class = extract_article_class_from_url(url)

    if article_id and re.match(r"^\d+$", article_id) and article_class:
        return f"https://static.klix.ba/media/images/{article_class}/b_{article_id}.jpg?v=1"

    return ""


def extract_num_of_comments(soup, news_json):
    if news_json.get("commentCount") is not None:
        try:
            return int(news_json.get("commentCount"))
        except Exception:
            pass

    html = str(soup)

    patterns = [
        r'"commentCount"\s*:\s*(\d+)',
        r'"comments_count"\s*:\s*(\d+)',
        r'"comment_count"\s*:\s*(\d+)',
        r'(\d+)\s+komentara'
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    return 0


def extract_num_of_shares(soup):
    text = clean_text(soup.get_text(" "))
    html = str(soup)

    patterns = [
        r"(\d+)\s+dijeljenja",
        r"(\d+)\s+share",
        r'"shares_count"\s*:\s*(\d+)',
        r'"share_count"\s*:\s*(\d+)',
        r'sharesCount\s*[:=]\s*(\d+)',
        r'shareCount\s*[:=]\s*(\d+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))

    return 0


def extract_article_class_and_rubrika(url, ad_config):
    """
    article_class:
      iz URL-a: magazin, vijesti, sport...
    article_class_name:
      ime kategorije iz AD_CONFIG: Magazin, Vijesti...
    RUBRIKA:
      podrubrika: muzika, bih, svijet...
    """
    article_class = extract_article_class_from_url(url)
    rubrika = extract_subcategory_from_url(url)

    article_class_name = get_ad_server_value(ad_config, "Kategorija")
    podkategorija = get_ad_server_value(ad_config, "Podkategorija")

    if podkategorija:
        rubrika = podkategorija

    return article_class, article_class_name, rubrika


def remove_unwanted_from_container(container):
    unwanted_selectors = [
        "script",
        "style",
        "iframe",
        "noscript",
        "figure",
        "video",
        "svg",
        "button",
        "nav",
        "aside",
        "form",
        "input",
        "textarea",
        "select",
        "img",
        "[id*='ads']",
        "[class*='ads']",
        "[class*='ad-']",
        "[class*='advert']",
        "[class*='share']",
        "[class*='comment']",
        "[class*='related']",
        "[class*='breadcrumb']",
        ".twitter-tweet",
        ".instagram-media"
    ]

    for selector in unwanted_selectors:
        for tag in container.select(selector):
            tag.decompose()


def is_bad_paragraph(text):
    text = clean_text(text)

    if not text:
        return True

    if len(text) < 20:
        return True

    lower = text.lower()

    bad_phrases = [
        "podijeli",
        "komentari",
        "komentara",
        "dijeljenja",
        "najnovije",
        "najčitanije",
        "pratite nas",
        "marketing",
        "oglas",
        "preuzimanje sadržaja",
        "pročitajte još",
        "vezani članci",
        "kliknite ovdje",
        "newsletter",
        "login",
        "registracija",
        "forum",
        "naslovnica"
    ]

    if any(phrase in lower for phrase in bad_phrases):
        return True

    return False


def extract_article_text(soup):
    """
    Popravljena ekstrakcija sadržaja.

    Za Klix novi layout:
    - lead: span.lead
    - body: div.break-words ... koji sadrži p tagove

    SADRZAJ uključuje lead + glavni tekst.
    PODNASLOV ostaje posebno u koloni PODNASLOV.
    Nema duple kolone text.
    """
    parts = []

    lead = soup.select_one("article span.lead") or soup.select_one("span.lead")
    if lead:
        lead_text = clean_text(lead.get_text(" "))
        if lead_text and not is_bad_paragraph(lead_text):
            parts.append(lead_text)

    body_candidates = [
        "article div.break-words",
        "div.break-words",
        "article [class*='break-words']",
    ]

    body = None

    for selector in body_candidates:
        body = soup.select_one(selector)

        if body:
            break

    if body:
        body_copy = BeautifulSoup(str(body), "html.parser")
        remove_unwanted_from_container(body_copy)

        for tag in body_copy.find_all(["p", "h2", "h3"]):
            text = clean_text(tag.get_text(" "))

            if is_bad_paragraph(text):
                continue

            parts.append(text)

    # Fallback ako novi layout nije uhvaćen
    if len(parts) <= 1:
        article = soup.select_one("article")

        if article:
            article_copy = BeautifulSoup(str(article), "html.parser")
            remove_unwanted_from_container(article_copy)

            for h1 in article_copy.find_all("h1"):
                h1.decompose()

            for tag in article_copy.find_all(["p"]):
                text = clean_text(tag.get_text(" "))

                if is_bad_paragraph(text):
                    continue

                parts.append(text)

    final_parts = []
    seen = set()

    for part in parts:
        key = part.lower()

        if key not in seen:
            final_parts.append(part)
            seen.add(key)

    return "\n\n".join(final_parts)


def scrape_klix_article(url, session):
    response = session.get(url, timeout=30)

    if response.status_code == 502:
        raise SkipArticleError("SKIP_502_BAD_GATEWAY")

    if is_blocked_response(response):
        raise RuntimeError(f"BLOCKED_OR_RATE_LIMITED: status={response.status_code}")

    if response.status_code != 200:
        raise RuntimeError(f"HTTP_ERROR: status={response.status_code}")

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    news_json = find_newsarticle_jsonld(soup)
    ad_config = extract_ad_config_json(html)

    portal = "Klix.ba"

    datum = extract_datum(soup, news_json, url)

    article_class, article_class_name, rubrika = extract_article_class_and_rubrika(url, ad_config)

    nadnaslov = extract_nadnaslov(soup)
    naslov = extract_title(soup, news_json)
    podnaslov = extract_podnaslov(soup, news_json)
    autori = extract_author(soup, news_json, ad_config)

    num_of_comments = extract_num_of_comments(soup, news_json)
    num_of_shares = extract_num_of_shares(soup)
    picture_path = extract_picture_path(soup, news_json, url)

    sadrzaj = extract_article_text(soup)

    return {
        "PORTAL": portal,
        "DATUM": datum,
        "RUBRIKA": rubrika,
        "NADNASLOV": nadnaslov,
        "NASLOV": naslov,
        "PODNASLOV": podnaslov,
        "AUTOR(I)": autori,
        "LINK": url,
        "SADRZAJ": sadrzaj,
        "ERROR": "",

        "article_class": article_class,
        "article_class_name": article_class_name,
        "num_of_comments": num_of_comments,
        "num_of_shares": num_of_shares,
        "picture_path": picture_path
    }


# ============================================================
# CHECKPOINT HELPERS
# ============================================================

def append_row_to_jsonl(row, path):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def append_row_to_csv(row, path):
    df_row = pd.DataFrame([row])
    file_exists = os.path.exists(path)

    df_row.to_csv(
        path,
        mode="a",
        header=not file_exists,
        index=False,
        encoding="utf-8-sig"
    )


def load_jsonl_rows(path):
    rows = []

    if not os.path.exists(path):
        return rows

    with open(path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"Upozorenje: neispravan JSONL red {line_number}, preskačem ga.")

    return rows


def load_already_scraped_links():
    rows = load_jsonl_rows(OUTPUT_JSONL)

    links = set()

    for row in rows:
        link = row.get("LINK", "")
        link = normalize_link(link)

        if link:
            links.add(link)

    return links


def log_error(link, error_message):
    row = {
        "LINK": link,
        "ERROR": str(error_message),
        "TIME": pd.Timestamp.now().isoformat()
    }

    append_row_to_csv(row, ERROR_LOG_CSV)


def scrape_with_retries(link, session):
    last_error = None

    for attempt in range(1, MAX_RETRIES_PER_ARTICLE + 1):
        try:
            return scrape_klix_article(link, session)

        except SkipArticleError:
            raise

        except Exception as e:
            last_error = e
            error_text = str(e)

            print(f"  Pokušaj {attempt}/{MAX_RETRIES_PER_ARTICLE} nije uspio: {error_text}")

            if "BLOCKED_OR_RATE_LIMITED" in error_text:
                if "status=200" in error_text:
                    print("  Status je 200, vjerovatno false block. Ne čekam 3 minute.")
                    time.sleep(5)
                else:
                    print("  Mogući pravi block/rate limit. Čekam 3 minute pa nastavljam...")
                    time.sleep(BLOCK_SLEEP_SECONDS)

            elif (
                "Read timed out" in error_text
                or "ConnectionError" in error_text
                or "Max retries exceeded" in error_text
                or "timeout" in error_text.lower()
            ):
                print("  Mogući timeout/network problem. Čekam 3 minute pa nastavljam...")
                time.sleep(BLOCK_SLEEP_SECONDS)

            else:
                time.sleep(5)

    raise last_error


def export_jsonl_to_csv(jsonl_path, csv_path):
    rows = load_jsonl_rows(jsonl_path)

    if not rows:
        print("Nema podataka za eksport u CSV.")
        return

    df = pd.DataFrame(rows)

    columns = [
        "PORTAL",
        "DATUM",
        "RUBRIKA",
        "NADNASLOV",
        "NASLOV",
        "PODNASLOV",
        "AUTOR(I)",
        "LINK",
        "SADRZAJ",
        "ERROR",
        "article_class",
        "article_class_name",
        "num_of_comments",
        "num_of_shares",
        "picture_path"
    ]

    for col in columns:
        if col not in df.columns:
            if col in ["num_of_comments", "num_of_shares"]:
                df[col] = 0
            else:
                df[col] = ""

    df = df[columns]

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def make_error_row(row, link, error_message, df_server):
    title = ""
    date = ""

    if "title" in df_server.columns:
        title = clean_text(row.get("title", ""))

    if "date" in df_server.columns:
        date = clean_text(row.get("date", ""))

    if not date:
        date = extract_date_from_klix_url(link)

    article_class = extract_article_class_from_url(link)
    rubrika = extract_subcategory_from_url(link)

    return {
        "PORTAL": "Klix.ba",
        "DATUM": date,
        "RUBRIKA": rubrika,
        "NADNASLOV": "",
        "NASLOV": title,
        "PODNASLOV": "",
        "AUTOR(I)": "",
        "LINK": link,
        "SADRZAJ": "",
        "ERROR": str(error_message),

        "article_class": article_class,
        "article_class_name": "",
        "num_of_comments": 0,
        "num_of_shares": 0,
        "picture_path": ""
    }


# ============================================================
# GOOGLE DRIVE UPLOAD
# ============================================================

def upload_csv_to_drive():
    """
    Uploaduje finalni CSV trenutnog servera na Google Drive preko rclone.

    Primjer destinacije:
    gdrive:klix_scrape_70k/server_0/
    """
    if not UPLOAD_TO_DRIVE:
        print("Upload na Drive je isključen.")
        return True

    if not os.path.exists(OUTPUT_CSV):
        print(f"CSV ne postoji, ne mogu uploadovati: {OUTPUT_CSV}")
        return False

    remote_folder = f"{DRIVE_REMOTE_DIR}/server_{SERVER_ID}"

    print("-" * 80)
    print("Uploadujem CSV na Drive...")
    print(f"Lokalni fajl: {OUTPUT_CSV}")
    print(f"Drive folder: {remote_folder}")
    print("-" * 80)

    cmd = [
        "rclone",
        "copy",
        OUTPUT_CSV,
        remote_folder,
        "--progress"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode == 0:
            print("Upload na Drive uspješan.")
            return True

        print("Upload na Drive nije uspio.")
        print("STDOUT:")
        print(result.stdout)
        print("STDERR:")
        print(result.stderr)

        return False

    except FileNotFoundError:
        print("Greška: rclone nije instaliran ili nije dostupan u PATH-u.")
        print("Instaliraj rclone ili postavi UPLOAD_TO_DRIVE = False.")
        return False

    except Exception as e:
        print(f"Greška pri uploadu na Drive: {e}")
        return False


# ============================================================
# SINGLE SERVER RUN
# ============================================================

def run_single_server():
    ensure_dirs()

    if SERVER_ID < 0 or SERVER_ID >= NUM_SERVERS:
        raise ValueError("SERVER_ID mora biti između 0 i NUM_SERVERS - 1.")

    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"Ne postoji input CSV: {INPUT_CSV}")

    df_links = pd.read_csv(INPUT_CSV)

    if "link" not in df_links.columns:
        raise ValueError("Input CSV mora imati kolonu 'link'.")

    df_links["link"] = df_links["link"].apply(normalize_link)
    df_links = df_links[df_links["link"] != ""]
    df_links = df_links.drop_duplicates(subset=["link"]).reset_index(drop=True)

    df_server = df_links[df_links["link"].apply(link_belongs_to_this_server)].reset_index(drop=True)

    already_scraped = load_already_scraped_links()

    total_all_links = len(df_links)
    total_server_links = len(df_server)

    already_for_this_server = len(already_scraped)
    remaining = total_server_links - already_for_this_server

    if remaining < 0:
        remaining = 0

    print("\n" + "=" * 100)
    print(f"POKREĆEM SERVER {SERVER_ID}")
    print("=" * 100)
    print(f"Input CSV: {INPUT_CSV}")
    print(f"Broj servera: {NUM_SERVERS}")
    print(f"Ovaj server ID: {SERVER_ID}")
    print(f"Checkpoint folder: {CHECKPOINT_DIR}")
    print(f"JSONL checkpoint: {OUTPUT_JSONL}")
    print(f"Final CSV: {OUTPUT_CSV}")
    print("-" * 80)
    print(f"Ukupno jedinstvenih linkova u inputu: {total_all_links}")
    print(f"Linkova dodijeljeno ovom serveru: {total_server_links}")
    print(f"Već obrađeno na ovom serveru: {already_for_this_server}")
    print(f"Preostalo za ovaj server: {remaining}")
    print("-" * 80)

    session = create_session()

    for index, row in df_server.iterrows():
        link = normalize_link(row["link"])

        if not link:
            continue

        if link in already_scraped:
            continue

        print(f"[{index + 1}/{total_server_links}] Server {SERVER_ID} scraping: {link}")

        try:
            article_data = scrape_with_retries(link, session)

            # fallback iz input CSV-a
            if not article_data["DATUM"] and "date" in df_server.columns:
                article_data["DATUM"] = clean_text(row.get("date", ""))

            if not article_data["NASLOV"] and "title" in df_server.columns:
                article_data["NASLOV"] = clean_text(row.get("title", ""))

            append_row_to_jsonl(article_data, OUTPUT_JSONL)
            already_scraped.add(link)

            print("  OK")

        except SkipArticleError as e:
            print(f"  PRESKAČEM 502: {link}")

            error_row = make_error_row(row, link, e, df_server)

            append_row_to_jsonl(error_row, OUTPUT_JSONL)
            log_error(link, e)

            already_scraped.add(link)

        except Exception as e:
            print(f"  GREŠKA: {e}")

            error_row = make_error_row(row, link, e, df_server)

            append_row_to_jsonl(error_row, OUTPUT_JSONL)
            log_error(link, e)

            already_scraped.add(link)

        sleep_time = random.uniform(*SLEEP_BETWEEN_REQUESTS)
        time.sleep(sleep_time)

    export_jsonl_to_csv(OUTPUT_JSONL, OUTPUT_CSV)

    print("-" * 80)
    print(f"Gotovo za server {SERVER_ID}.")
    print(f"Checkpoint JSONL: {OUTPUT_JSONL}")
    print(f"Finalni CSV: {OUTPUT_CSV}")
    print(f"Greške: {ERROR_LOG_CSV}")

    upload_ok = upload_csv_to_drive()

    if not upload_ok and STOP_IF_UPLOAD_FAIL:
        raise RuntimeError(f"Upload na Drive nije uspio za server {SERVER_ID}.")

    print("=" * 100)
    print(f"SERVER {SERVER_ID} ZAVRŠEN")
    print("=" * 100)


# ============================================================
# MAIN AUTO MODE
# ============================================================

def main():
    if START_SERVER_ID < 0:
        raise ValueError("START_SERVER_ID ne može biti manji od 0.")

    if END_SERVER_ID >= NUM_SERVERS:
        raise ValueError("END_SERVER_ID mora biti manji od NUM_SERVERS.")

    if START_SERVER_ID > END_SERVER_ID:
        raise ValueError("START_SERVER_ID ne može biti veći od END_SERVER_ID.")

    print("=" * 100)
    print("AUTO MODE: obrada servera jedan za drugim")
    print(f"Od servera {START_SERVER_ID} do servera {END_SERVER_ID}")
    print("=" * 100)

    for server_id in range(START_SERVER_ID, END_SERVER_ID + 1):
        setup_server_paths(server_id)

        try:
            run_single_server()

        except Exception as e:
            print("=" * 100)
            print(f"GREŠKA NA SERVERU {server_id}: {e}")
            print("=" * 100)

            # Ako želiš da skripta stane čim jedan server pukne, odkomentariši:
            # raise

            # Ovako nastavlja na sljedeći server
            continue

    print("\nSvi zadani serveri su završeni.")


if __name__ == "__main__":
    main()