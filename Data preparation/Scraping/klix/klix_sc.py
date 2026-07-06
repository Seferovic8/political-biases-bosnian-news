import re
import time
import random
import os
import pandas as pd
import requests

from bs4 import BeautifulSoup
from urllib.parse import urlencode, urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://www.klix.ba"
SEARCH_URL = "https://www.klix.ba/pretraga"

QUERY = "a"              # pojam pretrage
START_PAGE = 14900        # nastavlja od stranice poslije 8352
MAX_PAGE = 17400         # zadnja stranica do koje scrape-aš

OUTPUT_CSV = "klix_links_titles.csv"
ERROR_CSV = "klix_errors.csv"

SLEEP_BETWEEN_REQUESTS = (0.5, 2.0)

CHECKPOINT_EVERY = 50    # snimi CSV svaku 50. stranicu

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "bs-BA,bs;q=0.9,en;q=0.8",
}


def make_session():
    session = requests.Session()

    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False
    )

    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update(HEADERS)
    return session


def clean_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def build_search_url(query, page):
    params = {"q": query}

    if page > 1:
        params["str"] = page

    return SEARCH_URL + "?" + urlencode(params)


def extract_date_from_klix_url(url):
    """
    Klix URL često završava ID-em oblika YYMMDDxxx.
    Primjer:
    https://www.klix.ba/.../250620123
    25 = 2025
    06 = juni
    20 = dan

    Vraća:
    2025-06-20
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


def parse_search_page(html):
    soup = BeautifulSoup(html, "html.parser")

    articles = []

    for article in soup.select("article"):
        title_tag = article.select_one("h2")
        link_tag = article.select_one('a[href^="/"]')

        if not title_tag or not link_tag:
            continue

        title = clean_text(title_tag.get_text())
        link = urljoin(BASE_URL, link_tag.get("href"))

        # Preskoči nečlanke ako se slučajno uhvate
        if not link.startswith(BASE_URL):
            continue

        date = extract_date_from_klix_url(link)

        articles.append({
            "title": title,
            "link": link,
            "date": date,
        })

    return articles


def load_existing_data():
    all_articles = []
    seen_links = set()

    if os.path.exists(OUTPUT_CSV):
        try:
            old_df = pd.read_csv(OUTPUT_CSV)

            if "link" not in old_df.columns:
                print("Postojeći CSV nema kolonu 'link'. Krećem kao da nema starog CSV-a.")
                return all_articles, seen_links

            old_df = old_df.dropna(subset=["link"])
            old_df["link"] = old_df["link"].astype(str)

            all_articles = old_df.to_dict("records")
            seen_links = set(old_df["link"].tolist())

            print(f"Učitan postojeći CSV: {len(all_articles)} članaka.")
            print(f"Već poznatih linkova: {len(seen_links)}")

        except Exception as e:
            print(f"Nisam mogao učitati postojeći CSV: {e}")
            print("Krećem bez učitavanja starog CSV-a.")

    else:
        print("Nema postojećeg CSV-a. Krećem od nule.")

    return all_articles, seen_links


def save_checkpoint(all_articles, page):
    pd.DataFrame(all_articles).to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )
    print(f"  checkpoint snimljen na stranici {page}")


def save_error(errors):
    if errors:
        pd.DataFrame(errors).to_csv(
            ERROR_CSV,
            index=False,
            encoding="utf-8-sig"
        )


def scrape_links_and_titles():
    session = make_session()

    all_articles, seen_links = load_existing_data()
    errors = []

    print(f"\nNastavljam od stranice {START_PAGE} do {MAX_PAGE}.")
    print("-" * 60)

    for page in range(START_PAGE, MAX_PAGE + 1):
        url = build_search_url(QUERY, page)
        print(f"Scrape stranica {page}: {url}")

        try:
            response = session.get(url, timeout=20)

            # Ako baš dobiješ 502, preskoči stranicu
            if response.status_code == 502:
                print("  502 error, preskačem ovu stranicu.")
                errors.append({
                    "page": page,
                    "url": url,
                    "status_code": response.status_code,
                    "error": "502 Bad Gateway"
                })
                save_error(errors)
                continue

            if response.status_code != 200:
                print(f"  status {response.status_code}, preskačem.")
                errors.append({
                    "page": page,
                    "url": url,
                    "status_code": response.status_code,
                    "error": f"HTTP {response.status_code}"
                })
                save_error(errors)
                continue

            articles = parse_search_page(response.text)

            new_count = 0

            for article in articles:
                link = article["link"]

                if link not in seen_links:
                    article["page"] = page
                    all_articles.append(article)
                    seen_links.add(link)
                    new_count += 1

            print(f"  pronađeno na stranici: {len(articles)} | novih: {new_count}")

            if page % CHECKPOINT_EVERY == 0:
                save_checkpoint(all_articles, page)

        except Exception as e:
            print(f"  greška na stranici {page}: {e}")

            errors.append({
                "page": page,
                "url": url,
                "status_code": "",
                "error": str(e)
            })

            save_error(errors)

        time.sleep(random.uniform(*SLEEP_BETWEEN_REQUESTS))

    # finalno snimanje
    pd.DataFrame(all_articles).to_csv(
        OUTPUT_CSV,
        index=False,
        encoding="utf-8-sig"
    )

    save_error(errors)

    print("\nGotovo.")
    print(f"Ukupno linkova u CSV-u: {len(all_articles)}")
    print(f"Spašeno u: {OUTPUT_CSV}")

    if errors:
        print(f"Greške spašene u: {ERROR_CSV}")


if __name__ == "__main__":
    scrape_links_and_titles()