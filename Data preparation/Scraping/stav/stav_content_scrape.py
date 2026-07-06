import re
import time
import random
import os
import json
import hashlib
import pandas as pd
import requests

from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


INPUT_CSV = "stav_politika_links.csv"

# ============================================================
# PODESI OVO NA SVAKOM SERVERU
# ============================================================

NUM_SERVERS = 4       # ukupan broj servera
SERVER_ID = 2          # ovaj server: 0, 1, 2, 3 ...

# Primjer:
# Server 1: SERVER_ID = 0
# Server 2: SERVER_ID = 1
# Server 3: SERVER_ID = 2

# ============================================================

BASE_CHECKPOINT_DIR = "checkpoints/stav"
CHECKPOINT_DIR = os.path.join(BASE_CHECKPOINT_DIR, f"server_{SERVER_ID}")

OUTPUT_JSONL = os.path.join(CHECKPOINT_DIR, f"stav_articles_checkpoint_server_{SERVER_ID}.jsonl")
OUTPUT_CSV = os.path.join(CHECKPOINT_DIR, f"stav_articles_final_server_{SERVER_ID}.csv")
ERROR_LOG_CSV = os.path.join(CHECKPOINT_DIR, f"stav_errors_server_{SERVER_ID}.csv")

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


class SkipArticleError(Exception):
    """Greška za članke koje želimo odmah preskočiti, npr. 502 Bad Gateway."""
    pass


def ensure_dirs():
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_link(link):
    if not link:
        return ""

    link = str(link).strip()

    if link.lower() == "nan":
        return ""

    return link


def link_belongs_to_this_server(link):
    """
    Deterministički raspoređuje linkove po serverima.
    Isti link će uvijek otići na isti SERVER_ID.
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
        # 502 je namjerno izbačen jer njega želimo odmah preskočiti
        status_forcelist=[500, 503, 504],
        allowed_methods=["GET"]
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def is_blocked_response(response):
    if response.status_code in [403, 429]:
        return True

    # Ako je STAV članak normalno vraćen, nije block.
    # Ovo sprječava false positive zbog Cloudflare analytics skripti u HTML-u.
    if response.status_code == 200 and "post-content-holder" in response.text:
        return False

    text_lower = response.text.lower()

    block_keywords = [
        "too many requests",
        "access denied",
        "forbidden",
        "captcha",
        "temporarily blocked"
    ]

    return any(keyword in text_lower for keyword in block_keywords)


def get_meta_content(soup, selector):
    tag = soup.select_one(selector)

    if not tag:
        return ""

    return clean_text(tag.get("content", ""))


def extract_date_from_text(text):
    """
    Hvata datume tipa:
    10.06.2026.
    10.06.2026
    """
    if not text:
        return ""

    match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}\.?", text)

    if match:
        return match.group(0).rstrip(".")

    return ""


def scrape_stav_article(url, session):
    response = session.get(url, headers=HEADERS, timeout=30)

    # 502 odmah preskoči, bez retry-a i bez čekanja 3 minute
    if response.status_code == 502:
        raise SkipArticleError("SKIP_502_BAD_GATEWAY")

    if is_blocked_response(response):
        raise RuntimeError(f"BLOCKED_OR_RATE_LIMITED: status={response.status_code}")

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    article = soup.select_one("article#article")

    if article is None:
        raise ValueError("Nije pronađen article#article blok.")

    portal = "STAV"

    # -----------------------------
    # META fallback podaci
    # -----------------------------
    meta_title = get_meta_content(soup, 'meta[property="og:title"]')
    meta_description = get_meta_content(soup, 'meta[property="og:description"]')
    meta_image = get_meta_content(soup, 'meta[property="og:image"]')
    meta_url = get_meta_content(soup, 'meta[property="og:url"]')

    # -----------------------------
    # RUBRIKA I DATUM
    # Primjer:
    # Politika | 10.06.2026.
    # -----------------------------
    rubrika = ""
    datum = ""

    category_date_holder = article.select_one("#main p.flex")

    if category_date_holder:
        rubrika_tag = category_date_holder.select_one('a[href^="/kategorija/"]')

        if rubrika_tag:
            rubrika = clean_text(rubrika_tag.get_text(" "))

        datum = extract_date_from_text(category_date_holder.get_text(" "))

    if not datum:
        datum = extract_date_from_text(article.get_text(" "))

    # -----------------------------
    # NASLOV / NADNASLOV / PODNASLOV
    # -----------------------------
    nadnaslov_tag = article.select_one("h3.preheading")
    nadnaslov = clean_text(nadnaslov_tag.get_text(" ")) if nadnaslov_tag else ""

    naslov_tag = article.select_one("#main h1")
    naslov = clean_text(naslov_tag.get_text(" ")) if naslov_tag else ""

    podnaslov_tag = article.select_one("#main h2")
    podnaslov = clean_text(podnaslov_tag.get_text(" ")) if podnaslov_tag else ""

    if not naslov:
        naslov = meta_title

    if not podnaslov:
        podnaslov = meta_description

    # -----------------------------
    # AUTOR
    # -----------------------------
    autori = ""

    author_holder = article.select_one("#author-holder")

    if author_holder:
        author_text = clean_text(author_holder.get_text(" "))
        author_text = re.sub(r"^Autor:\s*", "", author_text, flags=re.IGNORECASE).strip()
        autori = author_text

    # -----------------------------
    # GLAVNA SLIKA I OPIS
    # -----------------------------
    image_url = ""
    image_caption = ""

    main_image = article.select_one("figure img")

    if main_image:
        src = main_image.get("src", "")

        if src:
            image_url = requests.compat.urljoin(url, src)

    if not image_url:
        image_url = meta_image

    caption_tag = article.select_one("figure figcaption")

    if caption_tag:
        image_caption = clean_text(caption_tag.get_text(" "))

    # -----------------------------
    # TAGOVI
    # -----------------------------
    tags = []

    for tag_a in article.select('a[href^="/tag/"]'):
        tag_text = clean_text(tag_a.get_text(" "))

        if tag_text:
            tags.append(tag_text)

    tags_text = ", ".join(dict.fromkeys(tags))

    # -----------------------------
    # SADRŽAJ
    # -----------------------------
    body_tag = article.select_one(".post-content-holder")

    paragraphs = []

    if body_tag:
        for unwanted in body_tag.select(
            "script, style, iframe, img, figure, "
            ".reklama, .ads, .twitter-tweet"
        ):
            unwanted.decompose()

        for p in body_tag.find_all("p"):
            text = clean_text(p.get_text(" "))

            if text:
                paragraphs.append(text)

    sadrzaj = "\n\n".join(paragraphs)

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
        "IMAGE_URL": image_url,
        "IMAGE_CAPTION": image_caption,
        "TAGS": tags_text,
        "META_URL": meta_url
    }


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
            return scrape_stav_article(link, session)

        except SkipArticleError:
            # 502 ne retry-amo, odmah ga šaljemo u main da ga zapiše i preskoči
            raise

        except Exception as e:
            last_error = e
            error_text = str(e)

            print(f"  Pokušaj {attempt}/{MAX_RETRIES_PER_ARTICLE} nije uspio: {error_text}")

            if (
                "BLOCKED_OR_RATE_LIMITED" in error_text
                or "Read timed out" in error_text
                or "ConnectionError" in error_text
                or "Max retries exceeded" in error_text
                or "timeout" in error_text.lower()
            ):
                print("  Mogući block/timeout. Čekam 3 minute pa nastavljam...")
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
        "IMAGE_URL",
        "IMAGE_CAPTION",
        "TAGS",
        "META_URL",
        "ERROR"
    ]

    existing_columns = [col for col in columns if col in df.columns]
    other_columns = [col for col in df.columns if col not in existing_columns]

    df = df[existing_columns + other_columns]

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def get_link_column(df):
    if "link" in df.columns:
        return "link"

    if "LINK" in df.columns:
        return "LINK"

    raise ValueError("Input CSV mora imati kolonu 'link' ili 'LINK'.")


def safe_get(row, column_name):
    if column_name in row.index:
        value = row[column_name]

        if pd.isna(value):
            return ""

        return str(value)

    return ""


def make_error_row(row, link, error_message):
    return {
        "PORTAL": "STAV",
        "DATUM": safe_get(row, "date") or safe_get(row, "image_month"),
        "RUBRIKA": safe_get(row, "category"),
        "NADNASLOV": "",
        "NASLOV": safe_get(row, "title"),
        "PODNASLOV": "",
        "AUTOR(I)": "",
        "LINK": link,
        "SADRZAJ": "",
        "IMAGE_URL": "",
        "IMAGE_CAPTION": "",
        "TAGS": "",
        "META_URL": "",
        "ERROR": str(error_message)
    }


def main():
    ensure_dirs()

    if SERVER_ID < 0 or SERVER_ID >= NUM_SERVERS:
        raise ValueError("SERVER_ID mora biti između 0 i NUM_SERVERS - 1.")

    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"Ne postoji input CSV: {INPUT_CSV}")

    df_links = pd.read_csv(INPUT_CSV)

    link_col = get_link_column(df_links)

    # ukloni prazne i duplikate prije raspodjele
    df_links[link_col] = df_links[link_col].apply(normalize_link)
    df_links = df_links[df_links[link_col] != ""]
    df_links = df_links.drop_duplicates(subset=[link_col]).reset_index(drop=True)

    # uzmi samo linkove koji pripadaju ovom serveru
    df_server = df_links[df_links[link_col].apply(link_belongs_to_this_server)].reset_index(drop=True)

    already_scraped = load_already_scraped_links()

    total_all_links = len(df_links)
    total_server_links = len(df_server)
    remaining = total_server_links - len(already_scraped)

    if remaining < 0:
        remaining = 0

    print(f"Input CSV: {INPUT_CSV}")
    print(f"Broj servera: {NUM_SERVERS}")
    print(f"Ovaj server ID: {SERVER_ID}")
    print(f"Checkpoint folder: {CHECKPOINT_DIR}")
    print(f"JSONL checkpoint: {OUTPUT_JSONL}")
    print(f"Final CSV: {OUTPUT_CSV}")
    print("-" * 80)
    print(f"Ukupno jedinstvenih linkova u inputu: {total_all_links}")
    print(f"Linkova dodijeljeno ovom serveru: {total_server_links}")
    print(f"Već obrađeno na ovom serveru: {len(already_scraped)}")
    print(f"Preostalo za ovaj server: {remaining}")
    print("-" * 80)

    session = create_session()

    for index, row in df_server.iterrows():
        link = normalize_link(row[link_col])

        if not link:
            continue

        if link in already_scraped:
            continue

        print(f"[{index + 1}/{total_server_links}] Server {SERVER_ID} scraping: {link}")

        try:
            article_data = scrape_with_retries(link, session)

            # fallback iz CSV-a ako parser nije našao
            if not article_data["DATUM"]:
                article_data["DATUM"] = safe_get(row, "date") or safe_get(row, "image_month")

            if not article_data["NASLOV"]:
                article_data["NASLOV"] = safe_get(row, "title")

            if not article_data["RUBRIKA"]:
                article_data["RUBRIKA"] = safe_get(row, "category")

            append_row_to_jsonl(article_data, OUTPUT_JSONL)
            already_scraped.add(link)

            print("  OK")

        except SkipArticleError as e:
            print(f"  PRESKAČEM 502: {link}")

            error_row = make_error_row(row, link, e)

            append_row_to_jsonl(error_row, OUTPUT_JSONL)
            log_error(link, e)

            already_scraped.add(link)

        except Exception as e:
            print(f"  GREŠKA: {e}")

            error_row = make_error_row(row, link, e)

            append_row_to_jsonl(error_row, OUTPUT_JSONL)
            log_error(link, e)

            already_scraped.add(link)

        sleep_time = random.uniform(*SLEEP_BETWEEN_REQUESTS)
        time.sleep(sleep_time)

    export_jsonl_to_csv(OUTPUT_JSONL, OUTPUT_CSV)

    print("-" * 80)
    print("Gotovo za ovaj server.")
    print(f"Server ID: {SERVER_ID}")
    print(f"Checkpoint JSONL: {OUTPUT_JSONL}")
    print(f"Finalni CSV: {OUTPUT_CSV}")
    print(f"Greške: {ERROR_LOG_CSV}")


if __name__ == "__main__":
    main()