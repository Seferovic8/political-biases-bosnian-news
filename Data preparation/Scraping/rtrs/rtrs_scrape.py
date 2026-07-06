import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://lat.rtrs.tv"

def scrape_rtrs_archive(day, month, year, category_id=10):
    url = (
        f"{BASE_URL}/vijesti/archive.php"
        f"?id={category_id}&arh_d={day}&arh_m={month}&arh_y={year}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # RTRS archive block
    archive_block = soup.select_one("div.nwzcron")
    if archive_block is None:
        print("Nije pronađen archive blok.")
        return []

    # Datum sa stranice, npr. 11.07.2023.
    date_tag = archive_block.select_one("div.dater")
    archive_date = date_tag.get_text(strip=True) if date_tag else f"{day:02d}.{month:02d}.{year}."

    articles = []

    for item in archive_block.select("div.odd, div.even"):
        time_tag = item.select_one("span.time")
        link_tag = item.select_one("span.cpt a")

        if not link_tag:
            continue

        time_text = time_tag.get_text(" ", strip=True).replace(">", "").strip() if time_tag else ""

        title = link_tag.get_text(" ", strip=True)
        relative_link = link_tag.get("href")
        full_link = urljoin(BASE_URL, relative_link)

        articles.append({
            "date": archive_date,
            "time": time_text,
            "title": title,
            "link": full_link
        })

    return articles


from datetime import date, timedelta

start = date(2020, 1, 1)
end = date(2025, 12, 31)

all_articles = []

current = start
while current <= end:
    print(f"Scraping {current}...")

    articles = scrape_rtrs_archive(
        day=current.day,
        month=current.month,
        year=current.year,
        category_id=10
    )

    all_articles.extend(articles)
    current += timedelta(days=1)

df = pd.DataFrame(all_articles)
df.to_csv("rtrs_2020_2025.csv", index=False, encoding="utf-8-sig")

print(f"Ukupno: {len(df)} članaka")