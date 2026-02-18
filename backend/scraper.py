"""
Agent-First Scraper
===================
Fetches product/shoppable pages and strips noise (headers, footers, nav, CSS, JS).
Extracts structured signals: price, title, CTA buttons, review snippets, clean text.

The key insight: don't dump all page text — extract specific, high-signal fields
that an LLM can quickly reason about.
"""

import re
import logging
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Tags to remove — these are noise for an LLM
NOISE_TAGS = [
    "script", "style", "nav", "header", "footer",
    "iframe", "noscript", "aside", "meta", "link",
    "form",  # signup forms etc.
]

PRICE_PATTERNS = [
    r"\$[\d,]+\.?\d*",
    r"USD\s*[\d,]+\.?\d*",
    r"[\d,]+\.?\d*\s*USD",
    r"£[\d,]+\.?\d*",
    r"€[\d,]+\.?\d*",
    r"Price[:\s]+\$?[\d,]+\.?\d*",
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
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except requests.Timeout:
        raise ValueError(f"Request timed out for {url}")
    except requests.HTTPError as e:
        raise ValueError(f"HTTP {e.response.status_code} fetching {url}")
    except requests.RequestException as e:
        raise ValueError(f"Could not fetch URL: {e}")

    soup = BeautifulSoup(response.text, "lxml")

    # Strip all noise tags first
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    return {
        "url": url,
        "title": _extract_title(soup),
        "price": _extract_price(soup, response.text),
        "description": _extract_description(soup),
        "cta_buttons": _extract_cta_buttons(soup, url),
        "review_snippets": _extract_reviews(soup),
        # Cap raw text — we don't want to blow the context window
        "raw_text": _get_clean_text(soup)[:5000],
    }


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
