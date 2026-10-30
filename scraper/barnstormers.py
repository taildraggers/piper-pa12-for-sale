"""Scraper for Piper PA-12 Super Cruiser aircraft listings on barnstormers.com.

Listings come from Barnstormers' "Piper PA-12 Super Cruiser" category. The
category also carries engine and parts ads, so each ad's title must name the
airplane (PA-12 or "Super Cruiser"), and titles that look like parts/
accessories/services/raffles are dropped. Surviving titles are rewritten to
a canonical "YEAR Piper MODEL" form so every listing follows the same format.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .common import (
    MIN_AIRCRAFT_PRICE,
    Listing,
    extract_date,
    extract_location,
    extract_price,
    fetch,
    format_aircraft_title,
    price_value,
)

SITE_NAME = "Barnstormers.com"
BASE = "https://www.barnstormers.com"
MAKE = "Piper"

# Barnstormers' Piper PA-12 Super Cruiser category.
SOURCE_URLS = [
    f"{BASE}/category-21191-Piper--PA-12-Super-Cruiser.html",
]

MAX_PAGES = 15
LISTING_LINK_RE = re.compile(r"^/classified-(\d+)-(.+)\.html$")
GENERIC_SITE_TITLE_SNIPPET = "barnstormers.com find aircraft"

# PA-12 model code, any separator ("PA-12", "PA12", "PA 12"), with the
# seaplane's "S" suffix; the number must not run into another digit.
_PA12_RE = re.compile(r"\bpa\s?-?\s?12(?!\d)(?:\s?-?\s?(s)\b)?", re.IGNORECASE)
_SUPER_CRUISER_RE = re.compile(r"super\s*cruiser", re.IGNORECASE)


def _extract_model(title: str) -> tuple[str, str] | None:
    # A title naming the PA-12 is kept even when it mentions the Super Cub
    # parts many PA-12s carry ("PA-12 Super Cub conversion" is still a PA-12).
    match = _PA12_RE.search(title)
    if match:
        return MAKE, "PA-12" + ("S" if match.group(1) else "") + " Super Cruiser"
    if _SUPER_CRUISER_RE.search(title):
        return MAKE, "PA-12 Super Cruiser"
    return None


def _title_from_url(url: str) -> str:
    """Listing pages share a generic <title>/<h1>, but the URL slug is the ad's own title."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    match = LISTING_LINK_RE.match("/" + slug)
    if not match:
        return unquote(slug)
    return unquote(match.group(2)).replace("-", " ").strip()


def _find_listing_links(html: str) -> set[str]:
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = urlparse(urljoin(BASE, a["href"])).path
        if LISTING_LINK_RE.match(href):
            links.add(urljoin(BASE, href))
    return links


def _page_url(source_url: str, page: int) -> str:
    """Build a results page's URL directly, for either kind of source.

    Barnstormers' pagers render as page-number buttons with no "Next" text or
    rel="next" attribute for a link-following heuristic to find, so each
    page's URL is built from the known pattern instead: an advanced search
    takes a page=<n> query parameter, and a category page takes
    ?seocategory=<url-encoded-path>&page=<n>.
    """
    if page <= 1:
        return source_url
    parts = urlparse(source_url)
    if parts.path.endswith("cat_search.php"):
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        query.append(("page", str(page)))
        return urlunparse(parts._replace(query=urlencode(query)))
    return f"{source_url}?seocategory={quote(parts.path, safe='')}&page={page}"

def _debug_dump_hrefs(html: str, limit: int = 25) -> None:
    soup = BeautifulSoup(html, "lxml")
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    interesting = [h for h in hrefs if "classified" in h.lower() or "pa-12" in h.lower()]
    sample = interesting[:limit] or hrefs[:limit]
    print(f"  [debug] {len(hrefs)} total <a href> on page; sample: {sample}")


def _parse_detail_page(url: str, html: str) -> Listing | None:
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    if title:
        title = re.sub(r"\s*[\|\-]\s*Barnstormers.*$", "", title, flags=re.IGNORECASE).strip()
    if not title or GENERIC_SITE_TITLE_SNIPPET in title.lower():
        title = _title_from_url(url)
    if not title:
        return None

    text = soup.get_text(" ", strip=True)

    formatted_title = format_aircraft_title(title, text, _extract_model)
    if not formatted_title:
        return None
    title = formatted_title

    price = extract_price(text)
    value = price_value(price)
    if value is not None and value < MIN_AIRCRAFT_PRICE:
        return None
    location = extract_location(text)
    date_posted = extract_date(text)

    return Listing(
        title=title,
        price=price,
        location=location,
        date_posted=date_posted,
        site=SITE_NAME,
        url=url,
    )


def scrape() -> list[Listing]:
    print(f"[{SITE_NAME}] starting scrape")
    all_links: set[str] = set()

    for source_url in SOURCE_URLS:
        seen_this_source: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            url = _page_url(source_url, page)
            html = fetch(url)
            if not html:
                break
            links = _find_listing_links(html)
            new_links = links - seen_this_source
            print(f"  [{'search' if 'cat_search' in source_url else 'category'} page {page}]: {len(links)} links ({len(new_links)} new)")
            if page == 1 and not links:
                _debug_dump_hrefs(html)
            seen_this_source |= links
            if not new_links:
                break
        all_links |= seen_this_source

    print(f"[{SITE_NAME}] {len(all_links)} unique listing URLs found")

    listings: list[Listing] = []
    for url in sorted(all_links):
        html = fetch(url)
        if not html:
            continue
        listing = _parse_detail_page(url, html)
        if listing:
            listings.append(listing)

    print(f"[{SITE_NAME}] parsed {len(listings)} listings")
    return listings
