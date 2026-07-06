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


INPUT_CSV = "rtrs_2020_2025.csv"

# ============================================================
# PODESI OVO NA SVAKOM SERVERU
# ============================================================

NUM_SERVERS = 50       # ukupan broj servera
SERVER_ID = 24         # ovaj server: 0, 1, 2, 3 ...

# Primjer:
# Server 1: SERVER_ID = 0
# Server 2: SERVER_ID = 1
# Server 3: SERVER_ID = 2
# Server 4: SERVER_ID = 3
# Server 5: SERVER_ID = 4
# Server 6: SERVER_ID = 5

# ============================================================

BASE_CHECKPOINT_DIR = "checkpoints/rtrs"
CHECKPOINT_DIR = os.path.join(BASE_CHECKPOINT_DIR, f"server_{SERVER_ID}")

OUTPUT_JSONL = os.path.join(CHECKPOINT_DIR, f"rtrs_articles_checkpoint_server_{SERVER_ID}.jsonl")
OUTPUT_CSV = os.path.join(CHECKPOINT_DIR, f"rtrs_articles_final_server_{SERVER_ID}.csv")
ERROR_LOG_CSV = os.path.join(CHECKPOINT_DIR, f"rtrs_errors_server_{SERVER_ID}.csv")

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

    text_lower = response.text.lower()

    block_keywords = [
        "too many requests",
        "access denied",
        "forbidden",
        "captcha",
        "temporarily blocked"
    ]

    return any(keyword in text_lower for keyword in block_keywords)


def scrape_rtrs_article(url, session):
    response = session.get(url, headers=HEADERS, timeout=30)

    # 502 odmah preskoči, bez retry-a i bez čekanja 3 minute
    if response.status_code == 502:
        raise SkipArticleError("SKIP_502_BAD_GATEWAY")

    if is_blocked_response(response):
        raise RuntimeError(f"BLOCKED_OR_RATE_LIMITED: status={response.status_code}")

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    article = soup.select_one("article")
    if article is None:
        raise ValueError("Nije pronađen <article> blok.")

    portal = "RTRS"

    rubrika_tag = soup.select_one(".pod-meni li.sel a")
    rubrika = clean_text(rubrika_tag.get_text(" ")) if rubrika_tag else ""

    vrijeme_izvor_tag = article.select_one(".vrijeme-izvor")
    vrijeme_izvor = clean_text(vrijeme_izvor_tag.get_text(" ")) if vrijeme_izvor_tag else ""

    datum = ""
    autori = ""

    if vrijeme_izvor:
        date_match = re.search(r"\d{1,2}/\d{1,2}/\d{4}", vrijeme_izvor)
        if date_match:
            datum = date_match.group(0)

        autor_match = re.search(r"Autor:\s*(.+)$", vrijeme_izvor)
        if autor_match:
            autori = clean_text(autor_match.group(1))

    naslov_tag = article.select_one("h1.naslov_vijesti")
    naslov = clean_text(naslov_tag.get_text(" ")) if naslov_tag else ""

    podnaslov_tag = article.select_one(".lead")
    podnaslov = clean_text(podnaslov_tag.get_text(" ")) if podnaslov_tag else ""

    nadnaslov = ""

    body_tag = article.select_one(".nwzbody")

    paragraphs = []

    if body_tag:
        for unwanted in body_tag.select(
            "script, style, iframe, img, "
            ".caption, .txtcaption, .twitter-tweet, "
            ".nwzphoto, .txtCaptionDiv"
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
        "SADRZAJ": sadrzaj
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
            return scrape_rtrs_article(link, session)

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
        "SADRZAJ"
    ]

    existing_columns = [col for col in columns if col in df.columns]
    other_columns = [col for col in df.columns if col not in existing_columns]

    df = df[existing_columns + other_columns]

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")


def make_error_row(row, link, error_message, df_server):
    return {
        "PORTAL": "RTRS",
        "DATUM": row["date"] if "date" in df_server.columns else "",
        "RUBRIKA": "",
        "NADNASLOV": "",
        "NASLOV": row["title"] if "title" in df_server.columns else "",
        "PODNASLOV": "",
        "AUTOR(I)": "",
        "LINK": link,
        "SADRZAJ": "",
        "ERROR": str(error_message)
    }


def main():
    ensure_dirs()

    if SERVER_ID < 0 or SERVER_ID >= NUM_SERVERS:
        raise ValueError("SERVER_ID mora biti između 0 i NUM_SERVERS - 1.")

    if not os.path.exists(INPUT_CSV):
        raise FileNotFoundError(f"Ne postoji input CSV: {INPUT_CSV}")

    df_links = pd.read_csv(INPUT_CSV)

    if "link" not in df_links.columns:
        raise ValueError("Input CSV mora imati kolonu 'link'.")

    # ukloni prazne i duplikate prije raspodjele
    df_links["link"] = df_links["link"].apply(normalize_link)
    df_links = df_links[df_links["link"] != ""]
    df_links = df_links.drop_duplicates(subset=["link"]).reset_index(drop=True)

    # uzmi samo linkove koji pripadaju ovom serveru
    df_server = df_links[df_links["link"].apply(link_belongs_to_this_server)].reset_index(drop=True)

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
        link = normalize_link(row["link"])

        if not link:
            continue

        if link in already_scraped:
            continue

        print(f"[{index + 1}/{total_server_links}] Server {SERVER_ID} scraping: {link}")

        try:
            article_data = scrape_with_retries(link, session)

            if not article_data["DATUM"] and "date" in df_server.columns:
                article_data["DATUM"] = row["date"]

            if not article_data["NASLOV"] and "title" in df_server.columns:
                article_data["NASLOV"] = row["title"]

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
    print("Gotovo za ovaj server.")
    print(f"Server ID: {SERVER_ID}")
    print(f"Checkpoint JSONL: {OUTPUT_JSONL}")
    print(f"Finalni CSV: {OUTPUT_CSV}")
    print(f"Greške: {ERROR_LOG_CSV}")


if __name__ == "__main__":
    main()