import os
import time
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com"
CACHE_DIR = "cache"
USER_AGENT = "FlyRankInternshipA9/1.0 (+https://github.com/AliHaikal/scraper)"
TIMEOUT_SECONDS = 10
DELAY_SECONDS = 0.5


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


def discover_all_book_urls(max_pages: int = 3) -> list[str]:
    """Walk the catalogue from page 1, following 'next' links, collecting book URLs."""
    all_links = []
    page_num = 1
    page_url = f"{BASE_URL}/catalogue/page-1.html"

    while page_url and page_num <= max_pages:
        cache_filename = f"catalogue-page-{page_num}.html"
        html = fetch_page(page_url, cache_filename)

        page_links = extract_book_links(html, page_url)
        all_links.extend(page_links)

        page_url = get_next_page_url(html, page_url)
        page_num += 1

    unique_links = list(dict.fromkeys(all_links))

    print(f"catalogue_pages={min(page_num - 1, max_pages)}")
    print(f"discovered={len(all_links)}")
    print(f"unique_urls={len(unique_links)}")

    return unique_links


if __name__ == "__main__":
    book_urls = discover_all_book_urls()