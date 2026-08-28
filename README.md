# The Polite Scraper — Books to Scrape

A small, polite scraping pipeline that downloads the first three
catalogue pages of Books to Scrape, visits all 60 book pages, and
turns the HTML into clean, validated JSON records.

## Target classification

- **Site:** books.toscrape.com
- **Why this site:** toscrape.com is a sandbox built specifically for
  practicing web scraping. books.toscrape.com is a fake bookstore run
  for that exact purpose — no real business behind it, made to be
  scraped freely.
- **Scope:** the first 3 catalogue pages only (60 books total), not
  the whole site.
- **Data collected:** book title, price, availability, rating,
  description, and product URL — all publicly displayed text, no
  personal or account data.
- **robots.txt result:** requested once, returned 404 Not Found — no
  robots file exists for this site. A missing file is not permission,
  it's just a missing file; scraping stays limited to what this site
  explicitly says it's for.

I will not reuse this code on another site without checking its
rules and terms first.

## Lane

Python 3.10+, using:
- `requests` for HTTP
- `BeautifulSoup` for HTML parsing
- `pydantic` for schema validation

## Install & run

```bash
git clone https://github.com/AliHaikal/scraper.git
cd scraper
pip install requests beautifulsoup4 pydantic
python src/main.py
```

First run fetches and caches everything from the live site. Every
run after that reads from `cache/` and finishes in a couple of
seconds. To force a fresh fetch, delete the `cache/` folder.

## Output

- `output/books.json` — 60 validated, unique book records
- `output/errors.json` — any records that failed schema validation, with a reason
- `output/run-report.json` — honest numbers for the run

## Record schema

```json
{
  "title": "A Light in the Attic",
  "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
  "price_gbp": 51.77,
  "price_text": "£51.77",
  "availability_text": "In stock (22 available)",
  "rating_text": "Three",
  "description": "It's hard to imagine a world without A Light in the Attic...",
  "source_page": "https://books.toscrape.com/catalogue/page-1.html",
  "fetched_at": "2026-08-28T14:34:50.671401+00:00"
}
```

`product_url` is each record's canonical identity — re-running the
scraper updates the cache but never duplicates a record.

## Politeness rules

- Every real request sends an identifying user-agent:
  `FlyRankInternshipA9/1.0 (+https://github.com/AliHaikal/scraper)`
- Every request has a 10-second timeout — nothing waits forever
- At least 500ms delay between real requests to the site; cached
  pages need no delay since they never leave the machine
- Status code is checked before anything else — only 200 is treated
  as a real page
- On timeout or a 5xx server error, one retry after a short pause;
  404 and 403 are never retried (a 404 won't appear later, and a 403
  means the site said no)

## Failure handling

Each book page is fetched independently. If one page fails after
its retry, it's logged and skipped — it does not stop the run. This
was verified by adding one deliberately broken URL to the book list:
the run finished, `books.json` still had all 60 good records, and
`run-report.json` reported `failed_pages: 1`. That test is left in
the code, commented out, in `src/main.py`.

## Sample run-report.json

```json
{
  "start_time": "2026-08-28T14:44:02.210434+00:00",
  "duration_seconds": 1.83,
  "pages_fetched": 0,
  "cache_hits": 63,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 1
}
```

(This run also included the deliberately broken test URL described
above, which is why `failed_pages` is 1 here.)

## Why this assignment needed no browser

The book data — title, price, availability, rating, description — is
already present in the raw HTML the server sends back on first
request. There's no client-side JavaScript building the page content
after load, so a full browser (like Playwright) would only add
startup cost and memory overhead for no extra data.

## Known limitation

Catalogue page fetches (the 3 pages that discover book links) are
not individually wrapped in the same per-page failure handling as
the 60 book detail pages — if one of those 3 catalogue pages fails,
the run currently stops rather than skipping it. Given the assignment
scope focuses failure handling on the 60 detail pages, this was left
as-is rather than gold-plated, per the assignment's own guidance not
to over-build Stage 5.

## Ethics note

This scraper only touches a site built for practice scraping, and
even then only the first 3 catalogue pages and the 60 books listed
there. In general: use an official API when one exists, never bypass
logins, paywalls, or blocks, and only collect what you actually need.