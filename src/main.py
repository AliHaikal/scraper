import os
import time
import json
from datetime import datetime, timezone
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

BASE_URL = "https://books.toscrape.com"
CACHE_DIR = "cache"
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/AliHaikal/scraper)"
TIMEOUT_SECONDS = 10
DELAY_SECONDS = 0.5


class BookRecord(BaseModel):
    title: str
    product_url: str
    price_gbp: float
    price_text: str
    availability_text: str
    rating_text: str | None
    description: str | None
    source_page: str
    fetched_at: str


def fetch_page(url: str, cache_filename: str) -> str:
    """Fetch a page, using the cache if it already exists locally."""
    cache_path = os.path.join(CACHE_DIR, cache_filename)

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            html = f.read()
        print(f"CACHE HIT: {cache_filename} ({len(html)} bytes)")
        return html

    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)

    if response.status_code != 200:
        raise Exception(f"Failed to fetch {url}: status {response.status_code}")

    response.encoding = "utf-8"
    html = response.text
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"FETCH: {cache_filename} ({len(html)} bytes)")
    time.sleep(DELAY_SECONDS)  # be polite — only matters on a real fetch, cache hits skip this
    return html


def extract_book_links(html: str, page_url: str) -> list[str]:
    """Get every book's absolute URL from a catalogue page."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for article in soup.select("article.product_pod"):
        href = article.select_one("h3 a")["href"]
        absolute_url = urljoin(page_url, href)
        links.append(absolute_url)
    return links


def get_next_page_url(html: str, page_url: str) -> str | None:
    """Return the absolute URL of the 'next' page, or None if there isn't one."""
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("li.next a")
    if next_link is None:
        return None
    return urljoin(page_url, next_link["href"])


def discover_all_book_urls(max_pages: int = 3) -> list[tuple[str, str]]:
    """Walk the catalogue from page 1, following 'next' links, collecting (book_url, source_page) pairs."""
    all_links = []
    page_num = 1
    page_url = f"{BASE_URL}/catalogue/page-1.html"

    while page_url and page_num <= max_pages:
        cache_filename = f"catalogue-page-{page_num}.html"
        html = fetch_page(page_url, cache_filename)

        page_links = extract_book_links(html, page_url)
        for link in page_links:
            all_links.append((link, page_url))

        page_url = get_next_page_url(html, page_url)
        page_num += 1

    seen = set()
    unique_links = []
    for link, source in all_links:
        if link not in seen:
            seen.add(link)
            unique_links.append((link, source))

    print(f"catalogue_pages={min(page_num - 1, max_pages)}")
    print(f"discovered={len(all_links)}")
    print(f"unique_urls={len(unique_links)}")

    return unique_links


def extract_book_record(html: str, product_url: str, source_page: str) -> dict:
    """Pull the raw fields out of a single book detail page."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.select_one("div.product_main h1").get_text(strip=True)
    price_text = soup.select_one("p.price_color").get_text(strip=True)
    availability_text = soup.select_one("p.availability").get_text(strip=True)

    rating_tag = soup.select_one("p.star-rating")
    rating_classes = rating_tag["class"]  # e.g. ["star-rating", "Three"]
    rating_text = rating_classes[1] if len(rating_classes) > 1 else None

    description_heading = soup.select_one("#product_description")
    if description_heading is not None:
        description = description_heading.find_next_sibling("p").get_text(strip=True)
    else:
        description = None

    return {
        "title": title,
        "product_url": product_url,
        "price_text": price_text,
        "availability_text": availability_text,
        "rating_text": rating_text,
        "description": description,
        "source_page": source_page,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def cache_filename_for_book(product_url: str) -> str:
    """Turn a book URL's slug into a safe cache filename."""
    slug = product_url.rstrip("/").split("/")[-2]  # e.g. "a-light-in-the-attic_1000"
    return f"book-{slug}.html"


def extract_all_books(book_urls_with_source: list[tuple[str, str]]) -> list[dict]:
    """Fetch every book detail page and extract its raw record."""
    records = []
    for product_url, source_page in book_urls_with_source:
        cache_filename = cache_filename_for_book(product_url)
        html = fetch_page(product_url, cache_filename)
        record = extract_book_record(html, product_url, source_page)
        records.append(record)

    print(f"detail_pages={len(records)}")
    return records


def normalize_record(raw: dict) -> dict:
    """Turn a raw record's price_text into a numeric price_gbp, keeping the original text too."""
    price_text = raw["price_text"]
    # strip everything except digits and the decimal point (handles "£51.77", stray whitespace, etc.)
    numeric_part = "".join(ch for ch in price_text if ch.isdigit() or ch == ".")
    price_gbp = float(numeric_part)

    normalized = dict(raw)
    normalized["price_gbp"] = price_gbp
    return normalized


def validate_and_store(raw_records: list[dict]) -> None:
    """Normalize, validate, dedupe by product_url, and write books.json / errors.json."""
    seen_urls = set()
    valid_records = []
    error_records = []

    for raw in raw_records:
        try:
            normalized = normalize_record(raw)
            validated = BookRecord(**normalized)
        except (ValueError, ValidationError) as e:
            error_records.append({"record": raw, "reason": str(e)})
            continue

        if validated.product_url in seen_urls:
            continue  # dedupe by canonical URL — keep first occurrence only
        seen_urls.add(validated.product_url)
        valid_records.append(validated.model_dump())

    os.makedirs("output", exist_ok=True)
    with open("output/books.json", "w", encoding="utf-8") as f:
        json.dump(valid_records, f, indent=2, ensure_ascii=False)

    with open("output/errors.json", "w", encoding="utf-8") as f:
        json.dump(error_records, f, indent=2, ensure_ascii=False)

    print(f"valid_records={len(valid_records)}")
    print(f"invalid_records={len(error_records)}")


if __name__ == "__main__":
    book_urls = discover_all_book_urls()
    records = extract_all_books(book_urls)
    validate_and_store(records)