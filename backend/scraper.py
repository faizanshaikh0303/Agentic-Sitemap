"""
Agent-First Scraper
===================
Fetches product/shoppable pages and strips noise (headers, footers, nav, CSS, JS).
Extracts structured signals: price, title, CTA buttons, review snippets, clean text.

The key insight: don't dump all page text — extract specific, high-signal fields
that an LLM can quickly reason about.
"""

import json
import re
import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Sites known to use aggressive bot protection (Akamai, Cloudflare Enterprise, etc.)
# These return 403/429 regardless of headers — Playwright with stealth is required.
PROTECTED_DOMAINS = {
    "adidas.com", "www.adidas.com",
    "supreme.com", "www.supreme.com",
    "ticketmaster.com", "www.ticketmaster.com",
}

# Full Chrome 120 header set — modern browsers send all of these.
# Sec-Fetch-* headers are the most commonly checked by bot detectors.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Cache-Control": "max-age=0",
}

# Tags to remove — these are noise for an LLM
NOISE_TAGS = [
    "script", "style", "nav", "header", "footer",
    "iframe", "noscript", "aside", "meta", "link",
    "form",  # signup forms etc.
]

PRICE_PATTERNS = [
    # Require at least 2 digits to avoid matching "$9" shoe sizes or ratings
    r"\$[\d,]*\d{2,}\.?\d*",
    r"USD\s*[\d,]*\d{2,}\.?\d*",
    r"[\d,]*\d{2,}\.?\d*\s*USD",
    r"£[\d,]*\d{2,}\.?\d*",
    r"€[\d,]*\d{2,}\.?\d*",
    r"Price[:\s]+\$?[\d,]*\d{2,}\.?\d*",
]

CTA_KEYWORDS = [
    "buy now", "add to cart", "shop now", "get it now",
    "order now", "purchase", "checkout", "add to bag",
    "get yours", "buy today",
]

REVIEW_SELECTORS = [
    ".review-text", ".review-body", ".customer-review",
    "[class*='review-content']", "[class*='testimonial']",
    "[class*='review-text']", "[class*='review-body']",
    "[data-testid*='review']",
]

PRICE_SELECTORS = [
    "[itemprop='price']",
    "[class*='price--sale']", "[class*='sale-price']",
    "[class*='current-price']", "[class*='product-price']",
    "[class*='price']", "[id*='price']",
    ".price", "#price", ".cost",
    "span[class*='Price']",  # Shopify pattern
]

DESCRIPTION_SELECTORS = [
    "[itemprop='description']",
    "[class*='product-description']",
    "[class*='product-detail']",
    "[class*='product-body']",
    "[class*='description']",
    ".description", "#description",
    "[data-testid*='description']",
]

TITLE_SELECTORS = [
    "h1",
    "[itemprop='name']",
    "[class*='product-title']",
    "[class*='product-name']",
    "[class*='product__title']",
    "[class*='ProductTitle']",
]


def scrape_product_page(url: str) -> dict:
    """
    Fetch and parse a product/shoppable page.
    Returns a structured dict with high-signal fields only.
    """
    domain = urlparse(url).netloc
    if domain in PROTECTED_DOMAINS:
        raise ValueError(
            f"{domain} uses enterprise bot protection (Akamai/Cloudflare) that blocks "
            "all HTTP scrapers. Use Playwright with a stealth plugin for this site, "
            "or manually paste the product data."
        )

    # Session persists cookies across redirects (e.g. consent pages)
    session = requests.Session()
    session.headers.update(HEADERS)
    # Add a Referer that looks like a Google search referral
    session.headers["Referer"] = "https://www.google.com/"

    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        response.raise_for_status()
    except requests.Timeout:
        raise ValueError(f"Request timed out for {url}")
    except requests.HTTPError as e:
        status = e.response.status_code
        if status == 403:
            raise ValueError(
                f"403 Forbidden — {domain} is blocking automated requests. "
                "This site likely uses bot protection (Cloudflare, Akamai, etc.). "
                "Try a different product URL, or use Playwright for JS-heavy sites."
            )
        if status == 429:
            raise ValueError(
                f"429 Too Many Requests — {domain} is rate-limiting. Wait a moment and retry."
            )
        raise ValueError(f"HTTP {status} fetching {url}")
    except requests.RequestException as e:
        raise ValueError(f"Could not fetch URL: {e}")

    # ── Layer 1: Shopify JSON API (best quality, no JS needed) ───────────────
    shopify_data = _try_shopify_json(url, session)
    if shopify_data:
        logger.info(f"Extracted via Shopify JSON API: {shopify_data['title']}")
        return shopify_data

    soup = BeautifulSoup(response.text, "lxml")

    # ── Layer 2: JSON-LD structured data (schema.org Product) ────────────────
    jsonld_data = _try_jsonld(soup, url)
    if jsonld_data:
        logger.info(f"Extracted via JSON-LD: {jsonld_data['title']}")
        return jsonld_data

    # ── Layer 3: HTML parsing (fallback for non-standard pages) ──────────────
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    return {
        "url": url,
        "title": _extract_title(soup),
        "price": _extract_price(soup, response.text),
        "description": _extract_description(soup),
        "cta_buttons": _extract_cta_buttons(soup, url),
        "review_snippets": _extract_reviews(soup),
        "raw_text": _get_clean_text(soup)[:5000],
    }


def _try_shopify_json(url: str, session: requests.Session) -> Optional[dict]:
    """
    Shopify exposes a public JSON API at /products/[handle].json.
    This returns perfectly structured data without any JS rendering.
    Works on: Reebok, Allbirds, Gymshark, Skims, thousands of Shopify stores.
    """
    parsed = urlparse(url)
    # Shopify product URLs contain /products/ in the path
    if "/products/" not in parsed.path:
        return None

    # Build the JSON endpoint URL
    # /collections/foo/products/handle → /products/handle.json
    handle = parsed.path.rstrip("/").split("/products/")[-1].split("?")[0]
    json_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.json"

    try:
        resp = session.get(json_url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json().get("product", {})
    except Exception:
        return None

    if not data:
        return None

    title = data.get("title", "")
    if not title:
        return None

    # Price: use lowest variant price (the "from" price shown on PDP)
    variants = data.get("variants", [])
    price = None
    if variants:
        prices = [float(v["price"]) for v in variants if v.get("price")]
        if prices:
            min_price = min(prices)
            price = f"${min_price:.2f}" if min_price != int(min_price) else f"${int(min_price)}"

    # Strip HTML from body_html description
    body_html = data.get("body_html", "")
    description = BeautifulSoup(body_html, "lxml").get_text(separator=" ", strip=True)[:500]

    # Stock: check if any variant is available
    available = any(v.get("available", False) for v in variants)
    stock_status = "in_stock" if available else "out_of_stock"

    # Build clean text for the LLM from all available fields
    tags = ", ".join(data.get("tags", []))
    product_type = data.get("product_type", "")
    raw_text = f"Product: {title}\nType: {product_type}\nTags: {tags}\nDescription: {description}"

    return {
        "url": url,
        "title": title,
        "price": price,
        "description": description,
        "cta_buttons": [{"text": "Buy Now", "url": url}],
        "review_snippets": [],
        "raw_text": raw_text[:5000],
        "_source": "shopify_json",
        "_stock_hint": stock_status,
    }


def _try_jsonld(soup: BeautifulSoup, url: str) -> Optional[dict]:
    """
    Many sites embed schema.org Product data as JSON-LD in a <script> tag.
    This is more reliable than HTML parsing and works pre-JS-render.
    Common on: Nike, most WordPress/WooCommerce stores, editorial sites.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or ""
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        # Handle both single object and @graph array
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            items = data["@graph"]

        for item in items:
            if item.get("@type") not in ("Product", "IndividualProduct"):
                continue

            title = item.get("name", "")
            if not title:
                continue

            # Price from offers
            price = None
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            raw_price = offers.get("price") or offers.get("lowPrice")
            currency = offers.get("priceCurrency", "USD")
            if raw_price:
                symbol = "$" if currency == "USD" else currency + " "
                price = f"{symbol}{float(raw_price):.2f}".replace(".00", "")

            # Stock
            avail = offers.get("availability", "")
            if "InStock" in avail:
                stock_hint = "in_stock"
            elif "OutOfStock" in avail:
                stock_hint = "out_of_stock"
            else:
                stock_hint = "unknown"

            description = item.get("description", "")[:500]
            brand = ""
            if isinstance(item.get("brand"), dict):
                brand = item["brand"].get("name", "")

            raw_text = f"Product: {title}\nBrand: {brand}\nPrice: {price}\nDescription: {description}"

            return {
                "url": url,
                "title": title,
                "price": price,
                "description": description,
                "cta_buttons": [{"text": "Buy Now", "url": url}],
                "review_snippets": [],
                "raw_text": raw_text[:5000],
                "_source": "jsonld",
                "_stock_hint": stock_hint,
            }

    return None


def _extract_title(soup: BeautifulSoup) -> str:
    for selector in TITLE_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 2:
                return text[:200]

    # Fallback: page <title> minus site name
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Strip common suffixes like "| Brand Name"
        title = re.split(r"\s*[\|—–]\s*", title)[0].strip()
        return title[:200]

    return "Unknown Product"


def _extract_price(soup: BeautifulSoup, raw_html: str) -> Optional[str]:
    for selector in PRICE_SELECTORS:
        el = soup.select_one(selector)
        if el:
            # Check content attribute (schema.org)
            content = el.get("content")
            if content and any(c.isdigit() for c in content):
                return f"${content}" if not content.startswith("$") else content

            text = el.get_text(strip=True)
            if text and any(c.isdigit() for c in text) and len(text) < 30:
                return text

    # Regex fallback on raw HTML
    for pattern in PRICE_PATTERNS:
        match = re.search(pattern, raw_html, re.IGNORECASE)
        if match:
            return match.group(0)[:30]

    return None


def _extract_description(soup: BeautifulSoup) -> str:
    # Check meta description first (often best summary)
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        content = meta_desc.get("content", "").strip()
        if len(content) > 30:
            return content[:500]

    for selector in DESCRIPTION_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator=" ", strip=True)
            if len(text) > 30:
                return text[:500]

    return ""


def _extract_cta_buttons(soup: BeautifulSoup, base_url: str) -> list:
    ctas = []
    seen = set()

    for el in soup.find_all(["a", "button"]):
        text = el.get_text(strip=True).lower()
        if any(kw in text for kw in CTA_KEYWORDS):
            display_text = el.get_text(strip=True)
            href = el.get("href", "")

            if href and not href.startswith("#") and not href.startswith("javascript"):
                if not href.startswith("http"):
                    href = urljoin(base_url, href)
            else:
                href = base_url

            key = (display_text.lower(), href)
            if key not in seen:
                seen.add(key)
                ctas.append({"text": display_text, "url": href})

    return ctas[:5]


def _extract_reviews(soup: BeautifulSoup) -> list:
    reviews = []
    seen = set()

    for selector in REVIEW_SELECTORS:
        for el in soup.select(selector)[:5]:
            text = el.get_text(separator=" ", strip=True)
            # Only keep meaningful snippets
            if 20 < len(text) < 400 and text not in seen:
                seen.add(text)
                reviews.append(text)

    return reviews[:5]


def _get_clean_text(soup: BeautifulSoup) -> str:
    """Extract readable text from main content areas, skipping boilerplate."""
    content_selectors = [
        "main", "article",
        "[class*='product-detail']", "[class*='product-page']",
        "[class*='ProductPage']", "[class*='product__info']",
        "[role='main']", ".content", "#content",
        "body",
    ]
    for selector in content_selectors:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            # Collapse excessive blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            if len(text) > 100:
                return text

    return soup.get_text(separator="\n", strip=True)
