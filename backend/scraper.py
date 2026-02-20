"""
Agent-First Scraper
===================
Fetches product/shoppable pages and strips noise (headers, footers, nav, CSS, JS).
Extracts structured signals: price, title, CTA buttons, review snippets, clean text.

The key insight: don't dump all page text — extract specific, high-signal fields
that an LLM can quickly reason about.
"""

import asyncio
import concurrent.futures
import json
import re
import logging
import sys
import traceback
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Sites known to use aggressive bot protection (Akamai, Cloudflare Enterprise, etc.)
# These return 403/429 regardless of headers — Playwright with stealth is required.
PROTECTED_DOMAINS = {
    "adidas.com", "www.adidas.com",
    "supreme.com", "www.supreme.com",
    "ticketmaster.com", "www.ticketmaster.com",
    "reebok.com", "www.reebok.com",
}

# Strings that indicate a bot-protection interstitial page (Cloudflare or Akamai).
# These pages return HTTP 200 but contain no product data at all — detecting
# them early prevents silently saving a useless "Unknown" card to the DB.
_CHALLENGE_MARKERS = [
    # Cloudflare JS challenge markers
    "cf-browser-verification",
    "cf_chl_opt",
    "cf_chl_prog",
    "__cf_chl_tk__",
    "DDoS protection by Cloudflare",
    "Checking if the site connection is secure",
    # Akamai Bot Manager markers
    "_abck",          # Akamai bot cookie — present in block pages
    "ak_bmsc",        # Akamai cookie injected into block page HTML
    "akamai-ghost",
    "Pardon Our Interruption",
]
_CHALLENGE_TITLES = {
    # Cloudflare titles
    "just a moment",
    "attention required",
    "checking your browser",
    "please wait",
    "security check",
    "one moment, please",
    # Akamai / generic block titles
    "access denied",
    "pardon our interruption",
    "service unavailable",
    "forbidden",
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


def _is_challenge_page(html: str) -> bool:
    """Return True if the response looks like a Cloudflare/bot-protection interstitial."""
    for marker in _CHALLENGE_MARKERS:
        if marker in html:
            return True
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    if title_match:
        page_title = title_match.group(1).strip().lower()
        if any(ct in page_title for ct in _CHALLENGE_TITLES):
            return True
    return False


def scrape_product_page(url: str) -> dict:
    """
    Fetch and parse a product/shoppable page.
    Returns a structured dict with high-signal fields only.

    Extraction order:
      Protected domains  → Shopify JSON API → Playwright (stealth browser)
      Normal domains     → Shopify JSON API → JSON-LD → HTML → Playwright on 403/challenge
    """
    domain = urlparse(url).netloc

    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["Referer"] = "https://www.google.com/"

    # ── Protected domains: Shopify JSON first (no browser), then Playwright ──
    # These sites block all plain HTTP scrapers; Playwright bypasses that.
    if domain in PROTECTED_DOMAINS:
        shopify_data = _try_shopify_json(url, session)
        if shopify_data:
            logger.info(f"Shopify JSON bypassed protection for {domain}: {shopify_data['title']}")
            return shopify_data
        logger.info(f"{domain} is in PROTECTED_DOMAINS — launching Playwright")
        return _scrape_with_playwright(url)

    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        response.raise_for_status()
    except requests.Timeout:
        raise ValueError(f"Request timed out for {url}")
    except requests.HTTPError as e:
        status = e.response.status_code
        if status == 403:
            # Hard block — try Playwright before giving up
            logger.info(f"403 for {domain}, retrying with Playwright")
            return _scrape_with_playwright(url)
        if status == 429:
            raise ValueError(
                f"429 Too Many Requests — {domain} is rate-limiting. Wait a moment and retry."
            )
        raise ValueError(f"HTTP {status} fetching {url}")
    except requests.RequestException as e:
        raise ValueError(f"Could not fetch URL: {e}")

    # ── Challenge page detection (HTTP 200 but JS interstitial) ──────────────
    if _is_challenge_page(response.text):
        logger.info(f"Challenge page detected for {domain} — retrying with Playwright")
        return _scrape_with_playwright(url)

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

    title = _extract_title(soup)

    # ── Layer 4: Playwright fallback for JS-rendered product pages ────────────
    # If we couldn't find a title on a /products/ URL the page is almost
    # certainly a React/SPA store where the product name is injected by JS
    # (common on Shopify stores whose JSON API is CDN-blocked).
    # Re-render with Playwright rather than save a useless "Unknown" card.
    if title == "Unknown Product" and "/products/" in urlparse(url).path:
        logger.info(f"Title unknown on {domain} product URL — retrying with Playwright")
        try:
            return _scrape_with_playwright(url)
        except ValueError as e:
            logger.warning(f"Playwright fallback also failed: {e}")
            # Fall through to whatever HTML gave us

    return {
        "url": url,
        "title": title,
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
    # Try three handle forms in order:
    #   1. Raw (as-is from URL path, may be percent-encoded)
    #   2. URL-decoded  (e.g. "platinum%C2%AE-..." → "platinum®-...")
    #   3. ASCII-only   (e.g. "platinum®-..." → "platinum-...") ← Shopify's actual slug
    raw_handle = parsed.path.rstrip("/").split("/products/")[-1].split("?")[0]
    decoded_handle = unquote(raw_handle)
    ascii_handle = re.sub(r"[^a-z0-9]+", "-", decoded_handle.lower()).strip("-")

    handle_candidates: list[str] = [raw_handle]
    if decoded_handle != raw_handle:
        handle_candidates.append(decoded_handle)
    if ascii_handle not in handle_candidates:
        handle_candidates.append(ascii_handle)

    resp = None
    for h in handle_candidates:
        json_url = f"{parsed.scheme}://{parsed.netloc}/products/{h}.json"
        try:
            r = session.get(json_url, timeout=10)
            if r.status_code == 200:
                resp = r
                break
        except Exception:
            continue

    if resp is None:
        return None

    try:
        data = resp.json().get("product", {})
    except Exception:
        return None

    if not data:
        return None

    title = data.get("title", "")
    if not title:
        return None

    variants = data.get("variants", [])

    # Price: use the most common/regular price, not just the minimum
    # (min price can be a sale outlier; modal price is more representative)
    price = None
    if variants:
        all_prices = [float(v["price"]) for v in variants if v.get("price")]
        compare_prices = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
        if all_prices:
            # Prefer compare_at_price (original price) when on sale, else modal price
            if compare_prices:
                ref = max(set(compare_prices), key=compare_prices.count)
            else:
                ref = max(set(all_prices), key=all_prices.count)  # most common = regular price
            price = f"${ref:.2f}".replace(".00", "") if ref != int(ref) else f"${int(ref)}"

    # Strip HTML from body_html description
    body_html = data.get("body_html", "")
    description = BeautifulSoup(body_html, "lxml").get_text(separator=" ", strip=True)[:500]

    # Stock: check if any variant is available
    available = any(v.get("available", False) for v in variants)
    stock_status = "in_stock" if available else "out_of_stock"

    # Extract option names + values (Color, Size, Style, etc.)
    options = data.get("options", [])
    option_lines = []
    for opt in options:
        name = opt.get("name", "")
        values = opt.get("values", [])
        if name and values:
            option_lines.append(f"{name}: {', '.join(str(v) for v in values[:8])}")

    # Build a rich context block — every field helps the LLM generate a better summary
    vendor = data.get("vendor", "")
    product_type = data.get("product_type", "")
    tags = ", ".join(data.get("tags", []))

    raw_text = "\n".join(filter(None, [
        f"Product: {title}",
        f"Brand: {vendor}" if vendor else "",
        f"Type: {product_type}" if product_type else "",
        f"Price: {price}" if price else "",
        f"Stock: {stock_status}",
        "\n".join(option_lines) if option_lines else "",
        f"Tags: {tags}" if tags else "",
        f"Description: {description}" if description else "",
    ]))

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


def _playwright_fetch_html(url: str) -> str:
    """
    Fetch fully-rendered HTML using a stealth Chromium browser.

    This MUST run in a worker thread — Playwright's sync API raises an error
    when called from inside a running asyncio event loop (e.g. FastAPI).
    ThreadPoolExecutor gives it a clean thread with no event loop.

    On Windows, worker threads default to SelectorEventLoop which can't launch
    subprocesses. We explicitly set ProactorEventLoop before Playwright starts.
    """
    if sys.platform == "win32":
        # Uvicorn on Windows sets WindowsSelectorEventLoopPolicy globally for compatibility.
        # Playwright calls asyncio.new_event_loop() internally, which creates a loop using
        # the active POLICY — still SelectorEventLoop, which can't spawn subprocesses.
        # We override the policy so new_event_loop() returns ProactorEventLoop instead.
        # This is safe: the main uvicorn loop is already running and won't be recreated.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",           # required in Docker/rootless containers
                "--disable-dev-shm-usage",  # use /tmp instead of /dev/shm (64MB in containers → OOM)
                "--disable-gpu",          # no GPU in headless servers
                "--single-process",       # saves ~100 MB vs multi-process mode
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=HEADERS["User-Agent"],
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = context.new_page()
        # Patch ~30 fingerprint signals before navigation
        Stealth().apply_stealth_sync(page)
        try:
            # "load" fires after main resources are fetched.
            # Cloudflare challenges redirect to the real page within ~2s after load,
            # so we add an extra wait to let that redirect + page render complete.
            # We avoid "networkidle" because e-commerce sites have continuous
            # background telemetry that prevents it from ever firing.
            logger.info(f"Playwright: navigating to {url}")
            page.goto(url, wait_until="load", timeout=30000)
            logger.info("Playwright: page loaded, waiting 3s for JS/challenge redirect")
            page.wait_for_timeout(3000)
            html = page.content()
            logger.info(f"Playwright: got {len(html)} chars")
        except Exception:
            logger.error(f"Playwright page error:\n{traceback.format_exc()}")
            raise
        finally:
            browser.close()

    return html


def _scrape_with_playwright(url: str) -> dict:
    """
    Launch a stealth Chromium browser to render JS-heavy or bot-protected pages.

    Runs the browser in a ThreadPoolExecutor to avoid the asyncio event loop
    conflict that Playwright's sync API raises inside FastAPI routes.
    """
    try:
        import playwright  # noqa: F401 — verify installed before spinning up thread
        from playwright_stealth import Stealth  # noqa: F401
    except ImportError:
        raise ValueError(
            "Playwright is not installed. Run: "
            "pip install playwright playwright-stealth && playwright install chromium"
        )

    domain = urlparse(url).netloc
    logger.info(f"Playwright launching for {domain}")

    # Run in a worker thread — threads have no asyncio loop, so sync_playwright works
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_playwright_fetch_html, url)
        try:
            html = future.result(timeout=60)
        except concurrent.futures.TimeoutError:
            raise ValueError(f"Playwright timed out after 60s for {url}")
        except Exception as e:
            logger.error(f"Playwright thread exception:\n{traceback.format_exc()}")
            raise ValueError(f"Playwright failed for {url}: {type(e).__name__}: {e}")

    logger.info(f"Playwright fetched {len(html)} chars from {domain}")

    # ── Post-render challenge check ───────────────────────────────────────────
    # If the rendered page is still a bot-protection screen (Akamai, Cloudflare
    # Enterprise), raise now rather than sending a useless block page to Groq.
    if _is_challenge_page(html):
        raise ValueError(
            f"{domain} returned a bot-protection block page even after Playwright stealth. "
            "This site likely uses Akamai Bot Manager. A commercial scraping proxy "
            "(ScraperAPI, Bright Data, Zyte API) is required to bypass it."
        )
    # Size sanity-check: a real product page is 50 KB+; block pages are <5 KB.
    if len(html) < 5000:
        raise ValueError(
            f"{domain} returned only {len(html):,} chars after rendering — "
            "looks like a bot-protection block page. "
            "A commercial scraping proxy may be required."
        )

    soup = BeautifulSoup(html, "lxml")

    # ── Layer 1: Shopify JSON still works via requests even on protected sites ─
    session = requests.Session()
    session.headers.update(HEADERS)
    shopify_data = _try_shopify_json(url, session)
    if shopify_data:
        logger.info(f"Playwright fallback → Shopify JSON: {shopify_data['title']}")
        return {**shopify_data, "_source": "playwright+shopify_json"}

    # ── Layer 2: JSON-LD from the now-rendered page ───────────────────────────
    jsonld_data = _try_jsonld(soup, url)
    if jsonld_data:
        logger.info(f"Playwright + JSON-LD: {jsonld_data['title']}")
        return {**jsonld_data, "_source": "playwright_jsonld"}

    # ── Layer 3: HTML parsing of rendered page ────────────────────────────────
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    return {
        "url": url,
        "title": _extract_title(soup),
        "price": _extract_price(soup, html),
        "description": _extract_description(soup),
        "cta_buttons": _extract_cta_buttons(soup, url),
        "review_snippets": _extract_reviews(soup),
        "raw_text": _get_clean_text(soup)[:5000],
        "_source": "playwright_html",
    }
