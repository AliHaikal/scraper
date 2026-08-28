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


class FetchError(Exception):
    """Raised when a page can't be fetched. status_code is None for network-level failures (e.g. timeout)."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def fetch_page(url: str, cache_filename: str, stats: dict | None = None) -> str:
    """Fetch a page, using the cache if it already exists locally. Retries once on timeout/5xx."""
    cache_path = os.path.join(CACHE_DIR, cache_filename)

    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            html = f.read()
        print(f"CACHE HIT: {cache_filename} ({len(html)} bytes)")
        if stats is not None:
            stats["cache_hits"] += 1
        return html

    headers = {"User-Agent": USER_AGENT}
    last_error = None

    for attempt in range(2):  # one try + one retry
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            last_error = FetchError(f"Network error fetching {url}: {e}")
            if attempt == 0:
                time.sleep(1)
                continue
            raise last_error

        if response.status_code == 200:
            response.encoding = "utf-8"
            html = response.text
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"FETCH: {cache_filename} ({len(html)} bytes)")
            time.sleep(DELAY_SECONDS)
            if stats is not None:
                stats["pages_fetched"] += 1
            return html

        if response.status_code in (404, 403):
            # do not retry: 404 won't appear later, 403 means the site said no
            raise FetchError(f"Failed to fetch {url}: status {response.status_code}", response.status_code)

        if response.status_code >= 500 and attempt == 0:
            time.sleep(1)
            continue

        raise FetchError(f"Failed to fetch {url}: status {response.status_code}", response.status_code)

    raise last_error


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


def discover_all_book_urls(stats: dict, max_pages: int = 3) -> list[tuple[str, str]]:
    """Walk the catalogue from page 1, following 'next' links, collecting (book_url, source_page) pairs."""
    all_links = []
    page_num = 1
    page_url = f"{BASE_URL}/catalogue/page-1.html"

    while page_url and page_num <= max_pages:
        cache_filename = f"catalogue-page-{page_num}.html"
        html = fetch_page(page_url, cache_filename, stats)

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


def extract_all_books(book_urls_with_source: list[tuple[str, str]], stats: dict) -> list[dict]:
    """Fetch every book detail page and extract its raw record. One bad page is logged and skipped."""
    records = []
    for product_url, source_page in book_urls_with_source:
        cache_filename = cache_filename_for_book(product_url)
        try:
            html = fetch_page(product_url, cache_filename, stats)
            record = extract_book_record(html, product_url, source_page)
            records.append(record)
        except FetchError as e:
            print(f"FAILED: {product_url} ({e})")
            stats["failed_pages"] += 1

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


def write_run_report(stats: dict, start_time: datetime, valid_count: int, invalid_count: int) -> None:
    """Write a short honest report of what happened during the run."""
    end_time = datetime.now(timezone.utc)
    duration_seconds = (end_time - start_time).total_seconds()

    report = {
        "start_time": start_time.isoformat(),
        "duration_seconds": round(duration_seconds, 2),
        "pages_fetched": stats["pages_fetched"],
        "cache_hits": stats["cache_hits"],
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "failed_pages": stats["failed_pages"],
    }

    os.makedirs("output", exist_ok=True)
    with open("output/run-report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    start_time = datetime.now(timezone.utc)
    stats = {"pages_fetched": 0, "cache_hits": 0, "failed_pages": 0}

    book_urls = discover_all_book_urls(stats)

    # Stage 5 checkpoint: prove one bad page doesn't kill the run.
    # Leave this commented in after you've confirmed it once — it's your proof.
    # book_urls.append((
    #     f"{BASE_URL}/catalogue/this-book-does-not-exist_9999/index.html",
    #     f"{BASE_URL}/catalogue/page-1.html",
    # ))

    records = extract_all_books(book_urls, stats)
    validate_and_store(records)

    with open("output/books.json", "r", encoding="utf-8") as f:
        valid_count = len(json.load(f))
    with open("output/errors.json", "r", encoding="utf-8") as f:
        invalid_count = len(json.load(f))

    write_run_report(stats, start_time, valid_count, invalid_count)