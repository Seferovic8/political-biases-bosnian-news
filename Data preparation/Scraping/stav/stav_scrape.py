import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
import time
import random
import re

BASE_URL = "https://stav.ba"
AJAX_URL = "https://stav.ba/functions/category/new-get-page.php"

CATEGORY_ID = 1
CATEGORY_NAME = "politika"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": "https://stav.ba",
    "referer": f"https://stav.ba/kategorija/{CATEGORY_NAME}/{CATEGORY_ID}",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}


def extract_image_date_info(a):
    """
    Pokušava izvući godinu i mjesec iz src-a slike:
    /cms/uploads/2026/06/...
    
    Ovo nije nužno datum objave članka, nego datum/mjesec uploadovane slike.
    """
    img = a.select_one("img")
    if not img:
        return None, None, None

    src = img.get("src", "")

    match = re.search(r"/cms/uploads/(\d{4})/(\d{2})/", src)

    if not match:
        return None, None, None

    year, month = match.groups()

    image_month = f"{year}-{month}"

    return image_month, year, month


def parse_articles(html):
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    for a in soup.select('a[href^="/vijest/"]'):
        title_tag = a.select_one("h1")
        if not title_tag:
            continue

        title = title_tag.get_text(" ", strip=True)
        link = urljoin(BASE_URL, a["href"])

        image_month, image_year, image_month_number = extract_image_date_info(a)

        articles.append({
            "portal": "stav.ba",
            "category": CATEGORY_NAME,
            "title": title,
            "link": link,
            "image_month": image_month,
            "image_year": image_year,
            "image_month_number": image_month_number
        })

    return articles


def scrape_category(max_pages=1000):
    session = requests.Session()
    session.headers.update(HEADERS)

    all_articles = {}
    empty_pages = 0

    for page in range(1, max_pages + 1):
        print(f"Scraping page {page}...")

        try:
            response = session.post(
                AJAX_URL,
                data={
                    "page": page,
                    "id": CATEGORY_ID
                },
                timeout=30
            )

            if response.status_code != 200:
                print(f"Status code {response.status_code}. Čekam pa nastavljam...")
                time.sleep(180)
                continue

            articles = parse_articles(response.text)

            if not articles:
                empty_pages += 1
                print(f"Nema članaka na page={page}. Empty pages: {empty_pages}")

                if empty_pages >= 3:
                    print("Tri prazne stranice zaredom. Zaustavljam.")
                    break

                continue

            empty_pages = 0

            before = len(all_articles)

            for article in articles:
                all_articles[article["link"]] = article

            after = len(all_articles)

            print(f"Nađeno na ovoj stranici: {len(articles)} | Ukupno unique: {after}")

            # checkpoint svakih 500 stranica
            if page % 500 == 0:
                df_checkpoint = pd.DataFrame(all_articles.values())
                df_checkpoint.to_csv(
                    f"stav_{CATEGORY_NAME}_checkpoint.csv",
                    index=False,
                    encoding="utf-8-sig"
                )
                print("Checkpoint spremljen.")

            time.sleep(random.uniform(1.0, 2.5))

        except requests.exceptions.RequestException as e:
            print(f"Greška: {e}")
            print("Čekam 3 minute pa nastavljam...")
            time.sleep(180)

    return list(all_articles.values())


if __name__ == "__main__":
    articles = scrape_category(max_pages=10000)

    df = pd.DataFrame(articles)
    df.to_csv(f"stav_{CATEGORY_NAME}_links.csv", index=False, encoding="utf-8-sig")

    print(f"Gotovo. Spremljeno {len(df)} članaka.")