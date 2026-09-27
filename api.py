"""FastAPI backend for the Viral Product Hunter application."""
import html
import json
import logging
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# Decodo Configuration
DECODO_API_URL = os.getenv("DECODO_API_URL") or "https://scraper-api.decodo.com/v2/scrape"
DECODO_AUTH_TOKEN = os.getenv("DECODO_AUTH_TOKEN")
DECODO_REQUEST_TIMEOUT = int(os.getenv("DECODO_REQUEST_TIMEOUT") or "120")
DECODO_MAX_WORKERS = int(os.getenv("DECODO_MAX_WORKERS") or "5")
DECODO_PROXY_POOL = os.getenv("DECODO_PROXY_POOL") or "premium"
DECODO_SUPPLIER_MAX_WORKERS = int(os.getenv("DECODO_SUPPLIER_MAX_WORKERS") or "10")

if not DECODO_AUTH_TOKEN:
    raise ValueError(
        "Missing DECODO_AUTH_TOKEN in .env. "
        "Copy .env.example to .env and set DECODO_AUTH_TOKEN to your Decodo auth token. "
        "Note: the variable must be named DECODO_AUTH_TOKEN "
        "(a common typo is DECODE_AUTH_TOKEN, which is ignored)."
    )

# AI Provider Configuration
DEFAULT_AI_MODEL_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_AI_MODEL_NAME = "gpt-4o-mini"
DEFAULT_KIMI_MODEL_API_URL = "https://api.moonshot.ai/v1/chat/completions"
DEFAULT_KIMI_MODEL_NAME = "kimi-k3"
DEFAULT_KIMI_CODE_API_URL = "https://api.kimi.com/coding/v1/chat/completions"
DEFAULT_KIMI_CODE_MODEL_NAME = "k3-256k"

BACKEND_PORT = 8000

# Currency conversion rates to USD (Step 8)
CURRENCY_TO_USD = {
    "USD": 1.0,
    "EUR": 1.09,
    "GBP": 1.28,
    "CNY": 0.14,
    "RMB": 0.14,
    "AUD": 0.66,
    "CAD": 0.73,
}

logger = logging.getLogger("viral_product_hunter")

app = FastAPI(title="Viral Product Hunter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


class HuntRequest(BaseModel):
    niche: str


class SourceRequest(BaseModel):
    niche: str
    initial_products: list[dict]


# =============================================================================
# Decodo Source Building
# =============================================================================

def build_source_urls(niche: str) -> list[dict]:
    google_queries = [
        f"viral {niche} products",
        f"problem solving {niche} products",
        f"TikTok {niche} gadgets",
        f"Amazon best selling {niche} under $50",
        f"lightweight {niche} products easy to ship",
        f"{niche} accessories under $50",
    ]

    sources = []
    for index, query in enumerate(google_queries, start=1):
        sources.append({
            "source": f"Google Search {index}",
            "payload": {
                "target": "google_search",
                "query": query,
                "headless": "html",
                "parse": True,
                "page_count": 1,
                "google_results_language": "en",
            },
        })

    first_google_query = google_queries[0]

    sources.append({
        "source": "Amazon Search",
        "payload": {
            "target": "amazon_search",
            "query": f"{niche} under $50",
            "page_from": "1",
            "parse": True,
        },
    })

    sources.append({
        "source": "Reddit Search",
        "payload": {
            "target": "universal",
            "url": f"https://www.reddit.com/search.json?q={quote_plus(first_google_query)}&sort=relevance&t=year&limit=25",
        },
    })

    sources.append({
        "source": "TikTok Shop Search",
        "payload": {
            "target": "tiktok_shop_search",
            "query": niche,
            "parse": True,
        },
    })

    sources.append({
        "source": "YouTube Search",
        "payload": {
            "target": "youtube_search",
            "query": f"viral {niche} products TikTok",
        },
    })

    return sources


# =============================================================================
# Supplier Payload Building
# =============================================================================

def build_supplier_payloads(product_name):
    """Build supplier search payloads for Alibaba and AliExpress."""
    encoded = quote_plus(product_name)
    return [
        {
            "url": f"https://www.alibaba.com/trade/search?SearchText={encoded}",
            "proxy_pool": DECODO_PROXY_POOL,
            "headless": "html",
        },
        {
            "url": f"https://www.aliexpress.com/wholesale?SearchText={encoded}",
            "proxy_pool": DECODO_PROXY_POOL,
            "headless": "html",
        },
    ]


# =============================================================================
# Decodo Content Handling
# =============================================================================

def stringify_decodo_content(content):
    """Try to parse content as JSON; otherwise return as string."""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return content
    return content


def parse_decodo_content(content):
    """Parse Decodo content, handling both parser envelope layouts."""
    content = stringify_decodo_content(content)
    if not isinstance(content, dict):
        return content

    results = content.get("results", content)
    if not isinstance(results, dict):
        return results

    nested_results = results.get("results")
    if isinstance(nested_results, dict):
        return nested_results
    return results


def get_parsed_results(content):
    """Wrapper for parse_decodo_content."""
    return parse_decodo_content(content)


# =============================================================================
# Decodo Trimming
# =============================================================================

def trim_amazon_content(parsed):
    """Trim Amazon parsed content to useful fields and limits."""
    if not isinstance(parsed, dict):
        return parsed

    result = {}
    amazon_fields = {
        'position', 'title', 'price', 'currency', 'rating',
        'reviews', 'sales', 'badges', 'asin', 'url', 'image'
    }

    # Handle organic products
    if 'organic_products' in parsed:
        products = parsed['organic_products']
        if isinstance(products, list):
            result['organic_products'] = products[:25]
            # Trim each product to useful fields
            trimmed = []
            for p in result['organic_products']:
                if isinstance(p, dict):
                    trimmed_p = {k: v for k, v in p.items() if k.lower() in amazon_fields}
                    trimmed.append(trimmed_p)
                else:
                    trimmed.append(p)
            result['organic_products'] = trimmed

    # Handle other sections
    for key, value in parsed.items():
        if key.lower() not in amazon_fields and key != 'organic_products':
            if isinstance(value, (str, int, float, bool)):
                result[key] = value
            elif isinstance(value, (list, dict)):
                result[key] = value

    return result


def trim_google_content(parsed):
    """Trim Google parsed content to useful fields and limits."""
    if not isinstance(parsed, dict):
        return parsed

    result = {}

    # Keep metadata
    for key in ['query', 'page', 'status']:
        if key in parsed:
            result[key] = parsed[key]

    # AI overviews - max 3
    if 'ai_overviews' in parsed:
        result['ai_overviews'] = parsed['ai_overviews'][:3]

    # Organic results - max 10
    if 'organic_results' in parsed:
        result['organic_results'] = parsed['organic_results'][:10]

    # Related questions - max 10
    if 'related_questions' in parsed:
        result['related_questions'] = parsed['related_questions'][:10]

    # Shopping/product sections - max 25 records
    shopping_keys = ['shopping_results', 'product_results', 'products']
    for key in shopping_keys:
        if key in parsed:
            result[key] = parsed[key][:25]

    # Preserve other object-valued sections without slicing
    for key, value in parsed.items():
        if key not in result:
            if isinstance(value, dict):
                result[key] = value
            elif isinstance(value, list) and key not in shopping_keys:
                # For other lists, keep them as-is or limit
                result[key] = value

    return result


def trim_decodo_result(result, max_content_chars=3500):
    """Trim a Decodo result to reasonable size."""
    if not isinstance(result, dict):
        return result

    result = deepcopy(result)

    source_name = result.get('source', '')

    if 'data' in result:
        parsed = parse_decodo_content(result['data'])

        # Apply source-specific trimming
        if isinstance(parsed, dict):
            if source_name and 'Amazon' in source_name:
                parsed = trim_amazon_content(parsed)
            elif source_name and 'Google' in source_name:
                parsed = trim_google_content(parsed)

        result['data'] = parsed

    # Deep truncate strings that are too long
    def deep_truncate(obj, max_chars=max_content_chars):
        if isinstance(obj, str):
            if len(obj) > max_chars:
                return obj[:max_chars] + "...[truncated]"
            return obj
        elif isinstance(obj, dict):
            return {k: deep_truncate(v, max_chars) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [deep_truncate(item, max_chars) for item in obj]
        return obj

    result['data'] = deep_truncate(result.get('data'), max_content_chars)

    return result


def compact_parsed_content(source_name, content):
    """Compact parsed content for a source."""
    parsed = parse_decodo_content(content)

    if source_name and 'Amazon' in source_name:
        return trim_amazon_content(parsed)
    elif source_name and 'Google' in source_name:
        return trim_google_content(parsed)

    return parsed


# =============================================================================
# Decodo Scraping
# =============================================================================

def scrape_with_decodo_payload(source_name: str, payload: dict) -> dict:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Basic {DECODO_AUTH_TOKEN}",
    }
    try:
        response = requests.post(
            DECODO_API_URL,
            json=payload,
            headers=headers,
            timeout=(10, DECODO_REQUEST_TIMEOUT),
        )
        response.raise_for_status()
        parsed_response = response.json()
        # Trim successful results with 12000 char limit
        trimmed_result = trim_decodo_result(
            {"source": source_name, "request": payload, "data": parsed_response},
            max_content_chars=12000
        )
        return trimmed_result
    except Exception as error:
        error_msg = str(error)
        if hasattr(error, "response") and error.response is not None:
            status = error.response.status_code
            detail = str(error.response.text)[:500]
            error_msg = f"HTTP {status}: {detail}"
        return {"source": source_name, "request": payload, "error": error_msg}


def scrape_with_decodo(niche: str, logger=None) -> str:
    sources = build_source_urls(niche)
    max_workers = min(max(1, DECODO_MAX_WORKERS), len(sources))

    def scrape_source(src: dict) -> dict:
        return scrape_with_decodo_payload(src["source"], src["payload"])

    if logger:
        logger.info(f"Starting discovery for {niche}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(scrape_source, sources))

    if logger:
        for r in results:
            status = "success" if "data" in r else "failure"
            logger.info(f"Discovery {status}: {r['source']}")

    return json.dumps(results)


# =============================================================================
# Marketplace HTML Parsing
# =============================================================================

class MarketplaceHTMLParser(HTMLParser):
    """HTMLParser subclass for parsing marketplace pages."""

    def __init__(self, platform):
        super().__init__()
        self.platform = platform
        self.links = []
        self.current_text = ""
        self.current_attrs = {}
        self.current_data = {}
        self.in_anchor = False
        self.in_image = False

    def handle_starttag(self, tag, attrs):
        self.current_attrs = dict(attrs)
        if tag == 'a':
            self.in_anchor = True
            self.current_text = ""
            self.current_data = {"tag": "a"}
            # Store href
            if 'href' in self.current_attrs:
                self.current_data['href'] = self.current_attrs['href']
            # Store other useful attributes
            for attr in ['title', 'class', 'id']:
                if attr in self.current_attrs:
                    self.current_data[attr] = self.current_attrs[attr]
        elif tag == 'img':
            self.in_image = True
            self.current_text = ""
            self.current_data = {"tag": "img"}
            for attr in ['alt', 'title', 'src']:
                if attr in self.current_attrs:
                    self.current_data[attr] = self.current_attrs[attr]

    def handle_endtag(self, tag):
        if tag == 'a' and self.in_anchor:
            self.in_anchor = False
            if 'href' in self.current_data and self.current_text.strip():
                self.current_data['text'] = self.current_text.strip()
                self.links.append(self.current_data)
            self.current_text = ""
            self.current_data = {}
        elif tag == 'img' and self.in_image:
            self.in_image = False
            self.current_text = ""
            self.current_data = {}

    def handle_data(self, data):
        if self.in_anchor:
            self.current_text += data
        elif self.in_image:
            self.current_data['text'] = (self.current_data.get('text', '') + data).strip()

    def handle_startendtag(self, tag, attrs):
        pass

    def get_listing_links(self):
        """Extract and canonicalize listing links."""
        listing_links = []
        seen_urls = set()

        for link in self.links:
            if 'href' not in link:
                continue

            url = link['href']
            text = link.get('text', '')

            # Skip empty or non-listing links
            if not url or not url.strip():
                continue

            # Filter by platform
            if self.platform == 'alibaba':
                if 'product-detail' in url or '/product/' in url:
                    pass  # Alibaba listing
                else:
                    continue
            elif self.platform == 'aliexpress':
                if '/item/' in url:
                    pass  # AliExpress listing
                else:
                    continue

            # Parse URL and remove query string for deduplication
            parsed = urlparse(url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            if clean_url not in seen_urls:
                seen_urls.add(clean_url)
                listing_links.append({
                    'url': url,
                    'canonical_url': clean_url,
                    'text': text,
                })
                if len(listing_links) >= 5:
                    break

        return listing_links


class PriceHTMLParser(HTMLParser):
    """HTMLParser subclass for extracting price information."""

    def __init__(self):
        super().__init__()
        self.prices = []
        self.current_text = ""
        self.in_price_context = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        # Check if this tag is likely to contain a price
        classes = attrs_dict.get('class', '')
        if 'price' in classes.lower() or tag == 'span':
            self.in_price_context = True
            self.current_text = ""

    def handle_endtag(self, tag):
        if self.in_price_context:
            if self.current_text.strip():
                self.prices.append(self.current_text.strip())
            self.in_price_context = False
            self.current_text = ""

    def handle_data(self, data):
        if self.in_price_context:
            self.current_text += data


def extract_prices_from_html(html_content):
    """Extract potential price strings from HTML."""
    parser = PriceHTMLParser()
    try:
        parser.feed(html_content)
    except Exception:
        pass
    return parser.prices


def repair_price(price_str):
    """Repair price string with split currency/symbols."""
    if not price_str or not isinstance(price_str, str):
        return None

    # Remove extra whitespace
    price_str = ' '.join(price_str.split())

    # Common currency symbols
    currency_symbols = {'$': 'USD', '€': 'EUR', '£': 'GBP'}
    
    # Check if price has currency symbol at the beginning or end
    stripped = price_str.strip()
    
    # Try to extract currency and numeric value
    currency = None
    numeric_value = None
    remaining = stripped

    # Check for currency symbol
    for symbol, code in currency_symbols.items():
        if stripped.startswith(symbol):
            currency = code
            remaining = stripped[1:].strip()
            break
        elif stripped.endswith(symbol):
            currency = code
            remaining = stripped[:-1].strip()
            break

    # Also check for currency codes
    currency_codes = ['USD', 'EUR', 'GBP', 'CNY', 'RMB', 'AUD', 'CAD']
    for code in currency_codes:
        if code in stripped:
            currency = code
            remaining = stripped.replace(code, '').strip()
            break

    # Extract numeric value
    # Match numbers with optional decimal
    match = re.search(r'[\d][\d,.]*[\d]?', remaining)
    if match:
        numeric_str = match.group(0)
        # Replace commas (thousands separator)
        numeric_str = numeric_str.replace(',', '')
        try:
            numeric_value = float(numeric_str)
        except ValueError:
            pass

    if numeric_value is not None:
        normalized_currency = normalize_currency(currency) if currency else 'USD'
        return {'value': numeric_value, 'currency': normalized_currency}
    return None


def parse_price_range(price_str):
    """Parse price range string into min/max values."""
    if not price_str:
        return None

    # Try to find range pattern - look for separator between two numbers
    # Match patterns like: $10 - $20, 10-20, 10 to 20, 10.00 - 20.00, etc.
    match = re.search(r'(?:[$€£]|)([\d,]+(?:\.\d+)?)\s*[-–—to\s]\s*(?:[$€£]|)([\d,]+(?:\.\d+)?)', str(price_str))
    if not match:
        # Try simpler pattern without currency symbols
        match = re.search(r'([\d,]+(?:\.\d+)?)\s*[-–—to\s]\s*([\d,]+(?:\.\d+)?)', str(price_str))
    
    if match:
        min_str = match.group(1).replace(',', '')
        max_str = match.group(2).replace(',', '')
        try:
            min_val = float(min_str)
            max_val = float(max_str)
            return {'min': min_val, 'max': max_val}
        except ValueError:
            pass
    return None


def normalize_currency(currency):
    """Normalize currency to standard code."""
    if not currency:
        return 'USD'
    currency = str(currency).upper().strip()
    currency_map = {
        'RMB': 'CNY',
        'CNY': 'CNY',
        'USD': 'USD',
        'EUR': 'EUR',
        'GBP': 'GBP',
        'AUD': 'AUD',
        'CAD': 'CAD',
    }
    return currency_map.get(currency, 'USD')


# =============================================================================
# Supplier Validation and Normalization
# =============================================================================

def extract_listings_from_parsed_json(data, platform, max_listings=5):
    """Extract listings from parsed Decodo JSON."""
    listings = []

    def walk(obj, depth=0):
        if len(listings) >= max_listings:
            return
        if isinstance(obj, dict):
            # Check if this looks like a product listing
            title = obj.get('title') or obj.get('name') or obj.get('product_title') or obj.get('product_name')
            price = obj.get('price') or obj.get('unit_price') or obj.get('current_price')
            url = obj.get('url') or obj.get('link') or obj.get('href')

            if title and (price or url):
                listings.append(obj)
                return

            for v in obj.values():
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(data)
    return listings[:max_listings]


def normalize_supplier_listing(raw, platform, source_url, candidate_index, offer_index):
    """Normalize a single supplier listing."""
    title = raw.get('title') or raw.get('name') or raw.get('product_title') or raw.get('product_name') or ""
    if not title or not isinstance(title, str) or not title.strip():
        return None

    # Get price
    price_raw = raw.get('price') or raw.get('unit_price') or raw.get('current_price')
    price_range_raw = raw.get('price_range')

    price = None
    price_range = None
    currency = raw.get('currency', 'USD')

    if price_raw is not None:
        if isinstance(price_raw, (int, float)):
            price = float(price_raw)
        elif isinstance(price_raw, str):
            repaired = repair_price(price_raw)
            if repaired:
                price = repaired.get('value')
                currency = repaired.get('currency', currency)

    if price_range_raw:
        if isinstance(price_range_raw, dict):
            price_range = {}
            if 'min' in price_range_raw:
                min_val = price_range_raw['min']
                if isinstance(min_val, str):
                    repaired = repair_price(min_val)
                    if repaired:
                        price_range['min'] = repaired.get('value')
                        currency = repaired.get('currency', currency)
                else:
                    price_range['min'] = float(min_val) if min_val else None
            if 'max' in price_range_raw:
                max_val = price_range_raw['max']
                if isinstance(max_val, str):
                    repaired = repair_price(max_val)
                    if repaired:
                        price_range['max'] = repaired.get('value')
                        currency = repaired.get('currency', currency)
                else:
                    price_range['max'] = float(max_val) if max_val else None

    if not price and not price_range:
        return None

    # Get URL
    url = raw.get('url') or raw.get('link') or raw.get('href') or ""
    if not url or not isinstance(url, str) or not url.strip():
        return None

    # Get MOQ
    moq = raw.get('min_order_quantity') or raw.get('moq') or raw.get('minimum_order') or 1
    if isinstance(moq, str):
        try:
            moq = int(moq)
        except ValueError:
            moq = 1

    # Get shipping
    shipping = raw.get('shipping_info') or raw.get('shipping') or ""
    if isinstance(shipping, dict):
        shipping = f"{shipping.get('cost', '')} {shipping.get('method', '')}".strip()

    # Get rating, orders, reviews
    rating = raw.get('rating') or raw.get('score')
    if isinstance(rating, str):
        try:
            rating = float(rating)
        except ValueError:
            rating = None

    orders = raw.get('orders') or raw.get('order_count') or raw.get('sold')
    if isinstance(orders, str):
        try:
            orders = int(orders)
        except ValueError:
            orders = None

    reviews = raw.get('reviews') or raw.get('review_count') or raw.get('num_reviews')
    if isinstance(reviews, str):
        try:
            reviews = int(reviews)
        except ValueError:
            reviews = None

    # Build supplier evidence
    evidence = []
    if price:
        evidence.append(f"price: {price} {currency}")
    if price_range:
        evidence.append(f"price_range: {price_range.get('min')} - {price_range.get('max')} {currency}")
    if moq:
        evidence.append(f"MOQ: {moq}")
    if shipping:
        evidence.append(f"shipping: {shipping}")
    if rating:
        evidence.append(f"rating: {rating}")
    if orders:
        evidence.append(f"orders: {orders}")
    if reviews:
        evidence.append(f"reviews: {reviews}")

    # Build provenance
    provenance = {
        'source_url': source_url,
        'candidate_index': candidate_index,
        'offer_index': offer_index,
        'platform': platform,
    }

    currency = normalize_currency(currency)

    return {
        'product_reference': title,
        'supplier_platform': platform,
        'supplier_title': title,
        'unit_price': price,
        'price_range': price_range,
        'currency': currency,
        'min_order_quantity': moq,
        'shipping_info': shipping,
        'supplier_url': url,
        'rating': rating,
        'orders': orders,
        'reviews': reviews,
        'supplier_evidence': evidence,
        'provenance': provenance,
    }


def extract_listings_from_html(html_content, platform, source_url, candidate_index):
    """Extract listings from rendered HTML."""
    parser = MarketplaceHTMLParser(platform)
    try:
        parser.feed(html_content)
    except Exception:
        pass

    listing_links = parser.get_listing_links()
    listings = []

    for i, link_info in enumerate(listing_links[:5]):  # Max 5 unique links
        title = link_info.get('text', '') or f"{platform} listing {i}"
        url = link_info.get('url', '')

        if not url or not title.strip():
            continue

        # Try to extract price from nearby text or attributes
        # For now, just create a basic listing
        listing = {
            'title': title,
            'url': url,
        }
        listings.append(listing)

    # Now normalize these listings
    normalized = []
    for i, listing in enumerate(listings):
        normalized_listing = normalize_supplier_listing(
            listing, platform, source_url, candidate_index, i
        )
        if normalized_listing:
            normalized.append(normalized_listing)

    return normalized


def process_supplier_response(response, platform, source_url, candidate_index):
    """Process a Decodo supplier response."""
    if not isinstance(response, dict):
        return [], [], False, False

    has_error = 'error' in response
    has_data = 'data' in response

    if has_error:
        return [], [], True, False

    if not has_data:
        return [], [], False, False

    data = response.get('data')

    # Try to parse as JSON first
    parsed = parse_decodo_content(data)

    if isinstance(parsed, dict):
        # Try to extract listings from parsed JSON
        listings = extract_listings_from_parsed_json(parsed, platform)
        normalized = []
        for i, listing in enumerate(listings):
            normalized_listing = normalize_supplier_listing(
                listing, platform, source_url, candidate_index, i
            )
            if normalized_listing:
                normalized.append(normalized_listing)
        return normalized, [parsed], False, False
    elif isinstance(parsed, str):
        # HTML content
        listings = extract_listings_from_html(parsed, platform, source_url, candidate_index)
        # Return empty parsed data, but with metadata
        return listings, [{"type": "html", "content_length": len(parsed)}], False, False
    else:
        return [], [], False, False


def validate_suppliers_for_products(products):
    """Validate and extract supplier information for products."""
    # Take at most 10 products with nonblank product names
    selected_products = []
    for p in products[:10]:
        product_name = p.get('product', '')
        if product_name and isinstance(product_name, str) and product_name.strip():
            selected_products.append(p)

    if not selected_products:
        return {
            'products': [],
            'products_validated': 0,
            'total_supplier_requests': 0,
            'successful_supplier_requests': 0,
            'failed_supplier_requests': 0,
            'empty_supplier_requests': 0,
            'alibaba_offers': 0,
            'aliexpress_offers': 0,
        }

    # Build all supplier jobs
    all_jobs = []
    for idx, product in enumerate(selected_products):
        product_name = product.get('product', '')
        payloads = build_supplier_payloads(product_name)
        for payload in payloads:
            all_jobs.append({
                'product_name': product_name,
                'product': product,
                'candidate_index': idx,
                'platform': 'alibaba' if 'alibaba' in payload['url'] else 'aliexpress',
                'payload': payload,
            })

    # Execute all jobs concurrently
    max_workers = min(max(1, DECODO_SUPPLIER_MAX_WORKERS), len(all_jobs))
    results = []

    def process_job(job):
        try:
            result = scrape_with_decodo_payload(
                f"{job['platform']}_{job['candidate_index']}",
                job['payload']
            )
            return result
        except Exception as e:
            return {'source': job.get('platform', 'unknown'), 'error': str(e)}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_job, all_jobs))

    # Group results by product
    products_supplier_data = []
    alibaba_count = 0
    aliexpress_count = 0
    empty_count = 0
    failed_count = 0
    successful_count = 0

    # Track jobs per product
    product_groups = {}
    for i, job in enumerate(all_jobs):
        product_name = job['product_name']
        if product_name not in product_groups:
            product_groups[product_name] = []
        product_groups[product_name].append((i, job, results[i]))

    for product_name, jobs in product_groups.items():
        product_data = None
        supplier_results = []

        for job_idx, job, result in jobs:
            platform = job['platform']
            candidate_index = job['candidate_index']
            source_url = job['payload']['url']

            has_error = 'error' in result
            has_data = 'data' in result

            if has_error:
                failed_count += 1
                supplier_results.append({
                    'platform': platform,
                    'error': result.get('error', 'Unknown error'),
                    'provenance': {
                        'source_url': source_url,
                        'candidate_index': candidate_index,
                        'offer_index': job_idx % 2,
                        'platform': platform,
                    },
                })
                continue

            if has_data:
                successful_count += 1
                listings, parsed_data, is_empty, is_error = process_supplier_response(
                    result, platform, source_url, candidate_index
                )

                if not listings:
                    empty_count += 1
                    supplier_results.append({
                        'platform': platform,
                        'warning': 'No listings found',
                        'parsed_data': parsed_data,
                        'provenance': {
                            'source_url': source_url,
                            'candidate_index': candidate_index,
                            'offer_index': job_idx % 2,
                            'platform': platform,
                        },
                    })
                else:
                    if platform == 'alibaba':
                        alibaba_count += len(listings)
                    else:
                        aliexpress_count += len(listings)

                    for offer_idx, listing in enumerate(listings):
                        supplier_results.append({
                            'platform': platform,
                            'offer': listing,
                            'parsed_data': parsed_data if not listings else [],
                            'provenance': {
                                'source_url': source_url,
                                'candidate_index': candidate_index,
                                'offer_index': offer_idx,
                                'platform': platform,
                            },
                        })

        if not product_data:
            product_data = {'product_name': product_name, 'supplier_results': supplier_results}
        else:
            product_data['supplier_results'].extend(supplier_results)

        products_supplier_data.append(product_data)

    total_requests = len(all_jobs)

    return {
        'products': products_supplier_data,
        'products_validated': len(selected_products),
        'total_supplier_requests': total_requests,
        'successful_supplier_requests': successful_count,
        'failed_supplier_requests': failed_count,
        'empty_supplier_requests': empty_count,
        'alibaba_offers': alibaba_count,
        'aliexpress_offers': aliexpress_count,
    }


# =============================================================================
# Product Normalization
# =============================================================================

def normalize_title(title):
    """Normalize title for deduplication."""
    if not isinstance(title, str) or not title.strip():
        return ""
    title = title.lower()
    # Replace non-alphanumeric runs with spaces
    title = re.sub(r'[^\w\s]', ' ', title)
    # Collapse multiple spaces
    title = re.sub(r'\s+', ' ', title)
    return title.strip()


def is_product_signal(value):
    """Check if value is a valid product signal."""
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def has_product_signals(item):
    """Check if item has at least one product signal beyond title."""
    product_signals = ['price', 'current_price', 'sale_price', 'original_price',
                       'price_lower', 'price_min', 'currency', 'url', 'link',
                       'image', 'thumbnail', 'rating', 'reviews', 'sales',
                       'orders', 'badges', 'asin']
    for key in product_signals:
        if key in item and is_product_signal(item[key]):
            return True
    # Also check nested in some cases
    for key, value in item.items():
        if key.lower() in ['price', 'currency', 'url', 'link', 'image', 'thumbnail',
                           'rating', 'reviews', 'sales', 'orders', 'badges', 'asin']:
            if is_product_signal(value):
                return True
    return False


def extract_products_single(item, source_name):
    """Extract a single product candidate from an item."""
    if not isinstance(item, dict):
        return None

    title_keys = ['product_title', 'product_name', 'title', 'name']
    title = None
    for tk in title_keys:
        if tk in item and is_product_signal(item[tk]):
            title = item[tk]
            break

    if not title or not isinstance(title, str) or not title.strip():
        return None

    if not has_product_signals(item):
        return None

    product = {}

    # Extract title
    product['product'] = title
    product['source'] = source_name

    # Extract price
    price_keys = ['price', 'current_price', 'sale_price', 'original_price', 'price_lower', 'price_min']
    price = None
    for pk in price_keys:
        if pk in item and is_product_signal(item[pk]):
            price_val = item[pk]
            if isinstance(price_val, str):
                price_val = price_val.strip()
                # Try to convert
                try:
                    price_val = float(price_val)
                except (ValueError, TypeError):
                    price_val = None
            if isinstance(price_val, (int, float)) and price_val > 0:
                price = float(price_val)
                break

    # Extract currency
    currency = None
    currency_keys = ['currency']
    for ck in currency_keys:
        if ck in item and is_product_signal(item[ck]):
            currency = item[ck]
            break

    # Extract URL
    url = None
    url_keys = ['url', 'link']
    for uk in url_keys:
        if uk in item and is_product_signal(item[uk]):
            url = item[uk]
            break

    # Expand relative Amazon URLs
    if url and not url.startswith('http'):
        if 'amazon.com' in url.lower():
            url = 'https://www.amazon.com' + (url if url.startswith('/') else '/' + url)
        elif 'amazon' in source_name.lower():
            url = 'https://www.amazon.com' + (url if url.startswith('/') else '/' + url)
        elif url.startswith('/'):
            url = 'https://www.amazon.com' + url
        else:
            url = 'https://' + url

    # Extract image
    image = None
    image_keys = ['image', 'thumbnail', 'images']
    for ik in image_keys:
        if ik in item and is_product_signal(item[ik]):
            image_val = item[ik]
            if isinstance(image_val, list) and len(image_val) > 0:
                image = image_val[0]
            else:
                image = image_val
            break

    # Extract rating
    rating = None
    rating_keys = ['rating']
    for rk in rating_keys:
        if rk in item and is_product_signal(item[rk]):
            rating_val = item[rk]
            if isinstance(rating_val, (int, float)):
                rating = float(rating_val)
            elif isinstance(rating_val, str):
                try:
                    rating = float(rating_val)
                except (ValueError, TypeError):
                    pass
            break

    # Extract reviews
    reviews = None
    reviews_keys = ['reviews', 'num_reviews', 'review_count']
    for rvk in reviews_keys:
        if rvk in item and is_product_signal(item[rvk]):
            reviews_val = item[rvk]
            if isinstance(reviews_val, (int, float)):
                reviews = int(reviews_val)
            elif isinstance(reviews_val, str):
                try:
                    reviews = int(reviews_val)
                except (ValueError, TypeError):
                    pass
            break

    # Extract sales
    sales = None
    sales_keys = ['sales', 'orders', 'sold', 'sales_count']
    for sk in sales_keys:
        if sk in item and is_product_signal(item[sk]):
            sales_val = item[sk]
            if isinstance(sales_val, (int, float)):
                sales = int(sales_val)
            elif isinstance(sales_val, str):
                try:
                    sales = int(sales_val)
                except (ValueError, TypeError):
                    pass
            break

    # Extract badges
    badges = []
    badge_keys = ['badges']
    for bk in badge_keys:
        if bk in item and is_product_signal(item[bk]):
            badge_val = item[bk]
            if isinstance(badge_val, list):
                badges = badge_val
            elif isinstance(badge_val, str):
                badges = [badge_val]
            break

    # Extract ASIN
    asin = None
    asin_keys = ['asin']
    for ak in asin_keys:
        if ak in item and is_product_signal(item[ak]):
            asin = item[ak]
            break

    # Build evidence list
    evidence = []
    if price is not None:
        evidence.append(f"price: {price} {currency or ''}")
    if rating is not None:
        evidence.append(f"rating: {rating}")
    if reviews is not None:
        evidence.append(f"reviews: {reviews}")
    if sales is not None:
        evidence.append(f"sales: {sales}")
    if url:
        evidence.append(f"url: {url}")
    if image:
        evidence.append(f"image: available")
    if badges:
        for b in badges:
            evidence.append(f"badge: {b}")
    if asin:
        evidence.append(f"asin: {asin}")

    # Calculate viral score
    score = 35

    if price is not None and 5 <= price <= 50:
        score += 12

    if rating is not None:
        score += round(rating * 3)

    volume = reviews or sales or 0
    if volume > 0:
        score += round(math.log10(max(volume, 1)) * 5)

    if image:
        score += 5

    if url:
        score += 5

    if badges:
        badge_lower = [b.lower() for b in badges if isinstance(b, str)]
        for b in badge_lower:
            if 'best seller' in b or 'amazon choice' in b or 'amazon\'s choice' in b:
                score += 10
                break

    score = min(score, 100)

    return {
        'product': title,
        'source': source_name,
        'price': price,
        'currency': currency,
        'url': url,
        'image': image,
        'evidence': evidence,
        'viral_score': score
    }


def walk_dict_or_list(data, source_name, products, seen_titles):
    """Recursively walk data to find product candidates."""
    if isinstance(data, dict):
        # Check if this dict is a product candidate
        candidate = extract_products_single(data, source_name)
        if candidate:
            norm_title = normalize_title(candidate['product'])
            if norm_title and norm_title not in seen_titles:
                seen_titles.add(norm_title)
                products.append(candidate)
            elif norm_title and norm_title in seen_titles:
                # Merge with existing
                for existing in products:
                    if normalize_title(existing['product']) == norm_title:
                        # Merge sources
                        existing_sources = set(existing['source'].split(',') if isinstance(existing['source'], str) else [existing['source']])
                        existing_sources.add(source_name)
                        existing['source'] = ','.join(existing_sources)
                        # Merge evidence
                        existing_evidence = set(existing.get('evidence', []))
                        existing_evidence.update(candidate.get('evidence', []))
                        existing['evidence'] = list(existing_evidence)
                        # Fill missing fields
                        for field in ['price', 'currency', 'url', 'image']:
                            if candidate.get(field) and not existing.get(field):
                                existing[field] = candidate[field]
                        break

        # Recurse into dict values
        for v in data.values():
            walk_dict_or_list(v, source_name, products, seen_titles)

    elif isinstance(data, list):
        for item in data:
            walk_dict_or_list(item, source_name, products, seen_titles)


def extract_products(discovery_results: list[dict], limit: int = 25) -> list[dict]:
    """Extract and normalize products from discovery results."""
    all_products = []
    seen_titles = set()

    for result in discovery_results:
        source_name = result.get('source', 'unknown')
        if 'data' in result:
            data = result['data']
            walk_dict_or_list(data, source_name, all_products, seen_titles)
        elif 'error' in result:
            # Still try to walk the error result
            walk_dict_or_list(result, source_name, all_products, seen_titles)

    # Sort by viral_score descending
    all_products.sort(key=lambda p: p.get('viral_score', 0), reverse=True)

    # Limit to 25
    return all_products[:limit]


# =============================================================================
# Source Summary
# =============================================================================

def count_product_signals(data):
    """Count price/URL/image evidence in data."""
    price_count = 0
    url_count = 0
    image_count = 0

    def walk_and_count(d):
        nonlocal price_count, url_count, image_count
        if isinstance(d, dict):
            for k, v in d.items():
                k_lower = k.lower()
                if k_lower in ['price', 'current_price', 'sale_price', 'original_price', 'price_lower', 'price_min']:
                    if is_product_signal(v):
                        price_count += 1
                elif k_lower in ['url', 'link', 'href']:
                    if is_product_signal(v):
                        url_count += 1
                elif k_lower in ['image', 'thumbnail', 'images']:
                    if is_product_signal(v):
                        image_count += 1
                walk_and_count(v)
        elif isinstance(d, list):
            for item in d:
                walk_and_count(item)

    walk_and_count(data)
    return price_count, url_count, image_count


def detect_robot_block(data):
    """Detect CAPTCHA or robot blocks in content."""
    if not isinstance(data, (str, dict, list)):
        return False

    content_str = str(data).lower() if isinstance(data, (str, int, float, bool)) else ""

    if isinstance(data, dict):
        for v in data.values():
            if detect_robot_block(v):
                return True
    elif isinstance(data, list):
        for item in data:
            if detect_robot_block(item):
                return True

    robot_indicators = ['captcha', 'verify you are human', 'unusual traffic', 'access denied']
    for indicator in robot_indicators:
        if indicator.lower() in content_str:
            return True

    return False


def summarize_decodo_result(result):
    """Create a summary row for a Decodo result."""
    source = result.get('source', 'unknown')
    has_error = 'error' in result
    error_msg = result.get('error', '')

    # Count products
    product_count = 0
    response_count = 0
    http_status = None
    parser_status = 'success'
    content_chars = 0

    if has_error:
        # Try to extract HTTP status from error
        error_lower = error_msg.lower()
        status_match = re.search(r'http (\d{3})', error_lower)
        if status_match:
            http_status = int(status_match.group(1))
        parser_status = 'error'
    else:
        data = result.get('data', {})
        if isinstance(data, dict):
            content_chars = len(str(data))
            response_count = 1
            # Count products in data
            if 'organic_products' in data:
                product_count = len(data.get('organic_products', []))
            elif 'organic_results' in data:
                product_count = len(data.get('organic_results', []))
            else:
                # Walk to find products
                temp_products = []
                seen = set()
                walk_dict_or_list(data, source, temp_products, seen)
                product_count = len(temp_products)

    # Count signals
    price_count, url_count, image_count = count_product_signals(result.get('data', {}))

    # Detect robot blocks
    robot_blocked = detect_robot_block(result.get('data', {})) or detect_robot_block(error_msg)

    # Get preview
    preview = ""
    data = result.get('data', {})
    if isinstance(data, dict):
        products_in_data = []
        seen_preview = set()
        walk_dict_or_list(data, source, products_in_data, seen_preview)
        if products_in_data:
            preview = ', '.join([p.get('product', '') for p in products_in_data[:5]])
        else:
            content_str = str(data)[:200]
            preview = content_str if content_str else error_msg[:200]
    else:
        preview = str(data)[:200] or error_msg[:200]

    return {
        'source': source,
        'error': error_msg if has_error else '',
        'product_count': product_count,
        'response_count': response_count,
        'http_status': http_status,
        'parser_status': parser_status,
        'content_chars': content_chars,
        'price_count': price_count,
        'url_count': url_count,
        'image_count': image_count,
        'robot_blocked': robot_blocked,
        'preview': preview
    }


# =============================================================================
# AI Provider Configuration
# =============================================================================

def get_ai_providers():
    """Get configured AI providers in priority order."""
    providers = []

    # Kimi providers
    kimi_api_key = os.getenv("KIMI_API_KEY", "").strip()
    moonshot_api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    kimi_api_url = os.getenv("KIMI_API_URL", "").strip()
    kimi_model_name = os.getenv("KIMI_MODEL_NAME", "").strip()

    # If KIMI_API_URL is explicitly set, use it
    if kimi_api_url:
        if kimi_api_key and not kimi_api_key.startswith("your_"):
            providers.append({
                'name': 'kimi_custom',
                'api_key': kimi_api_key,
                'api_url': kimi_api_url,
                'model': kimi_model_name or DEFAULT_KIMI_MODEL_NAME,
                'timeout': 240,
                'extra_params': {'reasoning_effort': 'low', 'max_completion_tokens': 4096}
            })
    else:
        # Register both Kimi Platform and Kimi Code defaults
        if kimi_api_key and not kimi_api_key.startswith("your_"):
            providers.append({
                'name': 'kimi_platform',
                'api_key': kimi_api_key,
                'api_url': DEFAULT_KIMI_MODEL_API_URL,
                'model': kimi_model_name or DEFAULT_KIMI_MODEL_NAME,
                'timeout': 240,
                'extra_params': {'reasoning_effort': 'low', 'max_completion_tokens': 4096}
            })
        if moonshot_api_key and not moonshot_api_key.startswith("your_"):
            providers.append({
                'name': 'kimi_moonshot',
                'api_key': moonshot_api_key,
                'api_url': DEFAULT_KIMI_MODEL_API_URL,
                'model': kimi_model_name or DEFAULT_KIMI_MODEL_NAME,
                'timeout': 240,
                'extra_params': {'reasoning_effort': 'low', 'max_completion_tokens': 4096}
            })

    # OpenAI provider
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    ai_model_api_url = os.getenv("AI_MODEL_API_URL", "").strip()
    ai_model_name = os.getenv("AI_MODEL_NAME", "").strip()

    if openai_api_key and not openai_api_key.startswith("your_"):
        providers.append({
            'name': 'openai',
            'api_key': openai_api_key,
            'api_url': DEFAULT_AI_MODEL_API_URL,
            'model': ai_model_name or DEFAULT_AI_MODEL_NAME,
            'timeout': 60,
            'extra_params': {'temperature': 0.7}
        })

    # Generic/custom provider
    generic_api_key = os.getenv("AI_MODEL_API_KEY", "").strip()
    if generic_api_key and not generic_api_key.startswith("your_"):
        providers.append({
            'name': 'generic',
            'api_key': generic_api_key,
            'api_url': ai_model_api_url or DEFAULT_AI_MODEL_API_URL,
            'model': ai_model_name or DEFAULT_AI_MODEL_NAME,
            'timeout': 60,
            'extra_params': {'temperature': 0.7}
        })

    return providers


def build_initial_ranking_messages(niche: str, products: list[dict]) -> tuple[str, str]:
    """Build the default system/user messages used for initial viral ranking."""
    system_message = """You are a product analyst. Analyze the following niche and product candidates.

CRITERIA:
- problem_solving: How well does this solve a specific pain point?
- video_demo: Can it be effectively demonstrated in short-form video (TikTok, Reels)?
- emotional_appeal: Does it evoke strong emotions (happiness, surprise, relief)?
- shipping_ease: Is it lightweight, non-fragile, and easy to ship?
- competition: Is there low-to-medium competition in the market?
- bundling: Can it be bundled with complementary products?
- supplier_evidence: Is there evidence of reliable suppliers?
- year_round_demand: Is there consistent demand throughout the year?

REJECTION REASONS (return viral_score: 0):
- unsafe, restricted, or illegal
- fragile or easily damaged during shipping
- edible, medicinal, or consumable
- branded items with trademark/copyright risk
- difficult or expensive to ship
- unclear value proposition

RESPONSE FORMAT:
Return ONLY a JSON object with this exact structure:
{
    "ranked": [
        {"candidate_index": 0, "viral_score": 85, "reason": "Short evidence-based reason"}
    ]
}

GUIDELINES:
- viral_score must be an integer between 0 and 100
- reason must be a short string (max 200 characters)
- Include at most 10 ranked candidates
- Candidate indexes are zero-based from the input list
- Only include candidates that pass all rejection criteria"""

    products_json = json.dumps([{
        'index': i,
        'product': p.get('product', ''),
        'price': p.get('price'),
        'currency': p.get('currency', ''),
        'rating': p.get('rating'),
        'reviews': p.get('reviews'),
        'sales': p.get('sales'),
        'source': p.get('source', ''),
        'evidence': p.get('evidence', []),
        'url': p.get('url', ''),
        'image': p.get('image', '')
    } for i, p in enumerate(products)], ensure_ascii=False)

    user_message = f"Niche: {niche}\n\nProduct candidates:\n{products_json}"

    return system_message, user_message


def call_ai_provider(
    provider,
    niche,
    products,
    max_retries=1,
    *,
    system_message=None,
    user_message=None,
):
    """Call a single AI provider and return the response or error.

    ``system_message``/``user_message`` may be supplied to override the default
    initial-ranking prompt (used by the final supplier-aware ranking stage).
    """
    api_key = provider['api_key']
    api_url = provider['api_url']
    model = provider['model']
    timeout = provider['timeout']
    extra_params = provider.get('extra_params', {})

    # Fall back to the initial ranking prompt when no explicit messages are given
    if system_message is None or user_message is None:
        default_system_message, default_user_message = build_initial_ranking_messages(niche, products)
        if system_message is None:
            system_message = default_system_message
        if user_message is None:
            user_message = default_user_message

    # Build payload
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message}
        ],
        "response_format": {"type": "json_object"},
        **extra_params
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=timeout
        )
        response.raise_for_status()
        return response.json(), None
    except Exception as error:
        error_msg = str(error)
        if hasattr(error, "response") and error.response is not None:
            status = error.response.status_code
            detail = str(error.response.text)[:500] if hasattr(error.response, 'text') else ""
            error_msg = f"HTTP {status}: {detail}"
        return None, error_msg


def analyze_with_ai_model(niche: str, products: list[dict]) -> tuple[list[dict], str | None]:
    """Analyze products with AI model and return ranked products with optional warning."""
    providers = get_ai_providers()

    if not providers:
        # No providers configured - return top 10 by local score
        ranked = sorted(products, key=lambda p: p.get('viral_score', 0), reverse=True)[:10]
        return ranked, "No AI provider configured. Using local viral scores as fallback."

    last_error = None

    for provider in providers:
        try:
            result, error = call_ai_provider(provider, niche, products)

            if error:
                last_error = error
                continue

            if result is None:
                last_error = "No response from AI provider"
                continue

            # Parse and validate AI response
            try:
                ranked_data = result.get('choices', [{}])[0].get('message', {}).get('content', {})
                if isinstance(ranked_data, str):
                    ranked_data = json.loads(ranked_data)

                ranked_list = ranked_data.get('ranked', [])

                # Validate and merge AI scores
                validated_ranked = []
                for entry in ranked_list[:10]:  # Max 10
                    idx = entry.get('candidate_index')
                    score = entry.get('viral_score', 0)
                    reason = entry.get('reason', '')

                    # Clamp score to 0-100
                    score = max(0, min(100, int(score)))
                    reason = reason[:200]  # Truncate to 200 chars

                    if 0 <= idx < len(products):
                        # Merge AI score into original product
                        product = deepcopy(products[idx])
                        product['viral_score'] = score
                        product['ai_reason'] = reason
                        validated_ranked.append(product)

                if validated_ranked:
                    # Sort by AI score descending
                    validated_ranked.sort(key=lambda p: p.get('viral_score', 0), reverse=True)
                    return validated_ranked, None
                else:
                    last_error = "No valid AI-ranked candidates"

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = f"Invalid AI response format: {str(e)[:200]}"
                continue

        except Exception as e:
            last_error = str(e)
            continue

    # All providers failed - return top 10 by local score with warning
    ranked = sorted(products, key=lambda p: p.get('viral_score', 0), reverse=True)[:10]
    warning = f"AI ranking failed. Using local viral scores as fallback. Last error: {last_error[:200] if last_error else 'No providers available'}"

    # Add specific warnings for known error types
    if last_error and "HTTP 401" in last_error:
        warning = "AI ranking failed: Authentication error (401). Check your API keys. Using local viral scores as fallback."
    elif last_error and "HTTP 429" in last_error:
        warning = "AI ranking failed: Rate limit exceeded (429). Using local viral scores as fallback."

    return ranked, warning


# =============================================================================
# Discovery Pipeline
# =============================================================================

def run_discovery(niche: str):
    """Run full discovery pipeline: scrape, compact, summarize, extract, rank.
    
    Returns dict with:
    - niche
    - initial_products
    - discovery_summary
    - discovery_data
    - ranking_warnings (list)
    """
    # Step 1: Scrape with Decodo
    discovery_results_json = scrape_with_decodo(niche)
    discovery_results = json.loads(discovery_results_json)

    # Step 2: Compact discovery data
    compacted_discovery = []
    for r in discovery_results:
        if 'data' in r:
            compacted = {
                'source': r['source'],
                'request': r['request'],
                'data': compact_parsed_content(r['source'], r['data'])
            }
            compacted_discovery.append(compacted)
        else:
            compacted_discovery.append(r)

    # Step 3: Extract products
    initial_products = extract_products(discovery_results)

    # Step 4: Create discovery summary
    discovery_summary = [summarize_decodo_result(r) for r in discovery_results]

    # Step 5: Rank products with AI
    ranking_warnings = []

    if initial_products:
        ranked_products, ai_warning = analyze_with_ai_model(niche, initial_products)
        if ai_warning:
            ranking_warnings.append(ai_warning)
        initial_products = ranked_products
    else:
        # No products found
        ranking_warnings.append("No products extracted from discovery sources. Check if sources are blocked or content format changed.")

    return {
        'niche': niche,
        'initial_products': initial_products,
        'discovery_summary': discovery_summary,
        'discovery_data': compacted_discovery,
        'ranking_warnings': ranking_warnings
    }


# =============================================================================
# Supplier Sourcing Pipeline
# =============================================================================

def run_supplier_sourcing(products):
    """Run supplier sourcing for products.
    
    Returns dict with:
    - supplier_data
    - supplier_summary
    """
    supplier_result = validate_suppliers_for_products(products)

    # Build supplier data in the format expected by the API
    supplier_data = supplier_result.get('products', [])

    supplier_summary = {
        'products_validated': supplier_result.get('products_validated', 0),
        'total_supplier_requests': supplier_result.get('total_supplier_requests', 0),
        'successful_supplier_requests': supplier_result.get('successful_supplier_requests', 0),
        'failed_supplier_requests': supplier_result.get('failed_supplier_requests', 0),
        'empty_supplier_requests': supplier_result.get('empty_supplier_requests', 0),
        'alibaba_offers': supplier_result.get('alibaba_offers', 0),
        'aliexpress_offers': supplier_result.get('aliexpress_offers', 0),
    }

    return {
        'supplier_data': supplier_data,
        'supplier_summary': supplier_summary,
    }


# =============================================================================
# Final Ranking (Step 8)
# =============================================================================

def convert_to_usd(amount: float | None, currency: str | None) -> float | None:
    """Convert amount to USD using fixed rates. Returns None for non-credible."""
    if amount is None or currency is None:
        return None
    if not isinstance(amount, (int, float)) or not math.isfinite(amount):
        return None
    if amount <= 0:
        return None
    
    currency_upper = str(currency).upper().strip()
    rate = CURRENCY_TO_USD.get(currency_upper)
    if rate is None:
        return None
    
    return amount * rate


def get_credible_price(offer: dict) -> float | None:
    """Get credible supplier price in USD. Returns None if not credible."""
    if not isinstance(offer, dict):
        return None
    
    unit_price = offer.get('unit_price')
    price_range = offer.get('price_range')
    currency = offer.get('currency')
    
    if unit_price is not None:
        return convert_to_usd(float(unit_price), currency)
    
    if price_range and isinstance(price_range, dict):
        min_price = price_range.get('min')
        if min_price is not None:
            return convert_to_usd(float(min_price), currency)
    
    return None


def build_final_ranking_input(products: list[dict], supplier_data: list[dict]) -> tuple[list[dict], list[dict]]:
    """Build normalized candidates and offers for final ranking.
    
    Returns (candidates, offers) with stable zero-based indexes.
    """
    candidates = []
    offers = []
    
    for candidate_idx, product in enumerate(products):
        candidate = {
            'candidate_index': candidate_idx,
            'product': product.get('product', ''),
            'price': product.get('price'),
            'currency': product.get('currency', 'USD'),
            'viral_score': product.get('viral_score', 0),
            'url': product.get('url', ''),
            'source': product.get('source', ''),
            'evidence': product.get('evidence', []),
        }
        candidates.append(candidate)
        
        # Find supplier offers for this candidate
        candidate_offers = []
        for supplier_result in supplier_data:
            product_name = supplier_result.get('product_name', '')
            if product_name and normalize_title(product_name) == normalize_title(product.get('product', '')):
                for sr in supplier_result.get('supplier_results', []):
                    offer = sr.get('offer', {})
                    if offer and isinstance(offer, dict):
                        candidate_offers.append(offer)
        
        for offer_idx, offer in enumerate(candidate_offers):
            offer_entry = {
                'offer_index': offer_idx,
                'candidate_index': candidate_idx,
                'supplier_platform': offer.get('supplier_platform', ''),
                'supplier_title': offer.get('supplier_title', ''),
                'supplier_url': offer.get('supplier_url', ''),
                'unit_price': offer.get('unit_price'),
                'price_range': offer.get('price_range'),
                'currency': offer.get('currency', 'USD'),
                'min_order_quantity': offer.get('min_order_quantity'),
                'shipping_info': offer.get('shipping_info', ''),
                'rating': offer.get('rating'),
                'orders': offer.get('orders'),
                'reviews': offer.get('reviews'),
                'supplier_evidence': offer.get('supplier_evidence', []),
                'price_usd': get_credible_price(offer),
            }
            offers.append(offer_entry)
    
    return candidates, offers


def compute_cost_desirability(offer: dict) -> float:
    """Compute cost desirability score (0-100). Lower cost = higher score."""
    price_usd = offer.get('price_usd')
    if price_usd is None or not isinstance(price_usd, (int, float)) or price_usd <= 0:
        return 0
    # Inverse: lower price = higher desirability
    # Assuming typical range is 0-100 USD, map to 0-100 score
    if price_usd <= 1:
        return 100
    elif price_usd >= 100:
        return 0
    else:
        return max(0, 100 - (price_usd * 2))


def compute_supplier_evidence_score(offer: dict) -> float:
    """Compute supplier evidence score (0-100) from evidence list."""
    evidence = offer.get('supplier_evidence', [])
    if not evidence:
        return 0
    # Count evidence items, each adds 20 points up to 100
    return min(100, len(evidence) * 20)


def compute_moq_score(offer: dict) -> float:
    """Compute MOQ score (0-100). Lower MOQ = higher score."""
    moq = offer.get('min_order_quantity')
    if moq is None or not isinstance(moq, (int, float)) or moq <= 0:
        return 0
    # Lower MOQ is better
    if moq <= 1:
        return 100
    elif moq >= 100:
        return 0
    else:
        return max(0, 100 - (moq * 2))


def compute_shipping_score(offer: dict) -> float:
    """Compute shipping score (0-100). Better shipping = higher score."""
    shipping = offer.get('shipping_info', '')
    if not shipping or not isinstance(shipping, str):
        return 50  # Neutral score
    shipping_lower = shipping.lower()
    # Check for positive indicators
    if 'free' in shipping_lower:
        return 100
    elif 'fast' in shipping_lower or 'express' in shipping_lower:
        return 80
    elif 'standard' in shipping_lower:
        return 60
    else:
        return 50


def compute_offer_score(offer: dict) -> float:
    """Compute overall offer score (0-100) using deterministic weights."""
    cost_score = compute_cost_desirability(offer)
    evidence_score = compute_supplier_evidence_score(offer)
    moq_score = compute_moq_score(offer)
    shipping_score = compute_shipping_score(offer)
    
    # Weights: cost 35%, evidence 30%, MOQ 20%, shipping 15%
    total = (cost_score * 0.35) + (evidence_score * 0.30) + (moq_score * 0.20) + (shipping_score * 0.15)
    return round(total, 2)


def compute_availability_score(offers: list[dict]) -> float:
    """Compute availability score based on number of platforms."""
    platforms = set()
    for offer in offers:
        platform = offer.get('supplier_platform', '')
        if platform:
            platforms.add(platform)
    
    if len(platforms) >= 2:
        return 100
    elif len(platforms) == 1:
        return 50
    else:
        return 0


def compute_margin_score(product: dict, best_offer: dict | None) -> float:
    """Compute estimated margin score. Returns 40 if cannot estimate."""
    if best_offer is None:
        return 40
    
    retail_price = product.get('price')
    supplier_price_usd = best_offer.get('price_usd')
    
    if retail_price is None or supplier_price_usd is None:
        return 40
    
    if not isinstance(retail_price, (int, float)) or not isinstance(supplier_price_usd, (int, float)):
        return 40
    
    if supplier_price_usd <= 0:
        return 40
    
    # Estimate margin percentage
    margin_percent = ((retail_price - supplier_price_usd) / supplier_price_usd) * 100
    # Clamp to reasonable range and map to 0-100
    if margin_percent >= 100:
        return 100
    elif margin_percent <= 0:
        return 0
    else:
        return min(100, margin_percent * 2)


def deterministic_final_ranking(products: list[dict], supplier_data: list[dict]) -> tuple[list[dict], str]:
    """Deterministic fallback final ranking.
    
    Returns (final_products, warning).
    """
    candidates, all_offers = build_final_ranking_input(products, supplier_data)
    
    # Group offers by candidate
    offers_by_candidate = {}
    for offer in all_offers:
        candidate_idx = offer.get('candidate_index')
        if candidate_idx not in offers_by_candidate:
            offers_by_candidate[candidate_idx] = []
        offers_by_candidate[candidate_idx].append(offer)
    
    final_products = []
    
    for candidate in candidates:
        candidate_idx = candidate.get('candidate_index')
        product = products[candidate_idx] if candidate_idx < len(products) else {}
        
        candidate_offers = offers_by_candidate.get(candidate_idx, [])
        
        # Find best credible offer for this candidate
        best_offer = None
        best_offer_score = -1
        
        for offer in candidate_offers:
            price_usd = offer.get('price_usd')
            if price_usd is not None:
                offer_score = compute_offer_score(offer)
                if offer_score > best_offer_score:
                    best_offer_score = offer_score
                    best_offer = offer
        
        # Compute final score
        viral_score = candidate.get('viral_score', 0) or 0
        
        if best_offer is not None:
            # Has credible offer
            cost_score = compute_cost_desirability(best_offer)
            evidence_score = compute_supplier_evidence_score(best_offer)
            moq_score = compute_moq_score(best_offer)
            shipping_score = compute_shipping_score(best_offer)
            margin_score = compute_margin_score(candidate, best_offer)
            availability_score = compute_availability_score(candidate_offers)
            
            # Weights: viral 30%, cost 18%, evidence 15%, MOQ 10%, shipping 8%, margin 12%, availability 7%
            final_score = (
                (viral_score * 0.30) +
                (cost_score * 0.18) +
                (evidence_score * 0.15) +
                (moq_score * 0.10) +
                (shipping_score * 0.08) +
                (margin_score * 0.12) +
                (availability_score * 0.07)
            )
            
            final_product = {
                **product,
                'final_score': round(final_score, 2),
                'selected_supplier_offer': best_offer,
                'supplier_price_reasoning': f"Cost: {cost_score}, Evidence: {evidence_score}, MOQ: {moq_score}, Shipping: {shipping_score}, Margin: {margin_score}, Availability: {availability_score}",
                'rejection_reason': '',
                'ranking_method': 'deterministic_fallback',
            }
        else:
            # No credible offer
            availability_score = compute_availability_score(candidate_offers)
            
            # Weights without supplier components
            final_score = viral_score * 0.30  # Only viral score component
            
            final_product = {
                **product,
                'final_score': round(final_score, 2),
                'selected_supplier_offer': None,
                'supplier_price_reasoning': '',
                'rejection_reason': 'No credible supplier offer with valid USD price',
                'ranking_method': 'deterministic_fallback',
            }
        
        final_products.append(final_product)
    
    # Sort by final_score descending, then by original candidate index
    final_products.sort(key=lambda p: (-p.get('final_score', 0), p.get('candidate_index', 0)))
    
    warning = "Final ranking used deterministic fallback (no AI available)."
    
    return final_products, warning


def final_rank_products(niche: str, products: list[dict], supplier_data: list[dict]) -> tuple[list[dict], str | None]:
    """Final AI ranking of products with supplier data.
    
    Returns (final_products, warning).
    """
    candidates, all_offers = build_final_ranking_input(products, supplier_data)
    
    if not candidates:
        return [], "No candidates for final ranking"
    
    # Build prompt with candidates and offers
    candidates_json = json.dumps([{
        'candidate_index': c['candidate_index'],
        'product': c['product'],
        'price': c['price'],
        'currency': c['currency'],
        'viral_score': c['viral_score'],
        'evidence': c['evidence'][:5],  # Limit evidence
    } for c in candidates], ensure_ascii=False)
    
    # Group offers by candidate
    offers_by_candidate = {}
    for offer in all_offers:
        candidate_idx = offer.get('candidate_index')
        if candidate_idx not in offers_by_candidate:
            offers_by_candidate[candidate_idx] = []
        offers_by_candidate[candidate_idx].append(offer)
    
    # Build offers JSON
    offers_json = json.dumps([{
        'offer_index': o['offer_index'],
        'candidate_index': o['candidate_index'],
        'supplier_platform': o['supplier_platform'],
        'supplier_title': o['supplier_title'],
        'supplier_url': o['supplier_url'],
        'price_usd': o['price_usd'],
        'currency': o['currency'],
        'min_order_quantity': o['min_order_quantity'],
        'shipping_info': o['shipping_info'],
        'supplier_evidence': o['supplier_evidence'][:3],  # Limit evidence
    } for o in all_offers], ensure_ascii=False)
    
    system_message = """You are a product sourcing analyst. Analyze candidates with their supplier offers.

CRITERIA for final ranking:
- viral_potential: From initial viral score and evidence
- supplier_cost: Lower credible USD cost is better (use price_usd field)
- evidence_quality: Quality and quantity of supplier evidence
- moq: Minimum Order Quantity (lower is better)
- shipping_practicality: Shipping cost, method, and time
- potential_margin: Retail price minus supplier cost
- availability: Present on both Alibaba and AliExpress (better)

REQUIRED OUTPUT FORMAT:
Return ONLY a JSON object with this exact structure:
{
    "ranked": [
        {
            "candidate_index": 0,
            "final_score": 85,
            "selected_offer_index": 0,
            "supplier_price_reasoning": "Low cost with good evidence",
            "rejection_reason": null
        }
    ]
}

RULES:
- Include EVERY candidate exactly once in ranked array
- candidate_index must match input candidate indexes
- final_score must be integer 0-100
- selected_offer_index must be integer index of selected offer for that candidate, or null if none
- If selected_offer_index is not null, it MUST belong to that candidate_index
- supplier_price_reasoning must be a string explaining the selection (max 200 chars)
- rejection_reason must be a string if no offer selected, or null
- selected_offer_index can only be non-null if rejection_reason is null
- Valid selected_offer_index requires: belongs to candidate, numeric, credible price_usd > 0
- If AI generates invalid selected_offer_index, treat as no selection
- Do NOT include model-generated offer objects, only indexes"""

    user_message = f"""Niche: {niche}

Candidates:
{candidates_json}

Supplier Offers:
{offers_json}

Analyze and rank. Return ONLY the JSON response."""

    providers = get_ai_providers()
    
    if not providers:
        # Fall back to deterministic
        return deterministic_final_ranking(products, supplier_data)
    
    last_error = None
    
    for provider in providers:
        try:
            # Use call_ai_provider for consistency, overriding the default
            # initial-ranking prompt with the final ranking prompt.
            result, error = call_ai_provider(
                provider,
                niche,
                candidates,
                system_message=system_message,
                user_message=user_message,
            )
            
            if error:
                last_error = error
                continue
            
            if result is None:
                last_error = "No response from AI provider"
                continue
            
            # Parse AI response
            try:
                ranked_data = result.get('choices', [{}])[0].get('message', {}).get('content', {})
                if isinstance(ranked_data, str):
                    ranked_data = json.loads(ranked_data)
                
                ranked_list = ranked_data.get('ranked', [])
                
                # Validate and process AI response
                validated_ranked = []
                for entry in ranked_list:
                    candidate_idx = entry.get('candidate_index')
                    final_score = entry.get('final_score', 0)
                    selected_offer_idx = entry.get('selected_offer_index')
                    reasoning = entry.get('supplier_price_reasoning', '')
                    rejection = entry.get('rejection_reason')
                    
                    # Validate candidate_index
                    if candidate_idx is None or not isinstance(candidate_idx, int) or candidate_idx < 0 or candidate_idx >= len(candidates):
                        last_error = f"Invalid candidate_index: {candidate_idx}"
                        continue
                    
                    # Validate uniqueness
                    if any(v['candidate_index'] == candidate_idx for v in validated_ranked):
                        last_error = f"Duplicate candidate_index: {candidate_idx}"
                        continue
                    
                    # Clamp score to 0-100
                    final_score = max(0, min(100, int(final_score)))
                    
                    # Validate selected_offer_index
                    selected_offer = None
                    if selected_offer_idx is not None:
                        # Must be numeric
                        if not isinstance(selected_offer_idx, (int, float)):
                            selected_offer_idx = None
                        else:
                            selected_offer_idx = int(selected_offer_idx)
                            # Must belong to this candidate
                            candidate_offers = offers_by_candidate.get(candidate_idx, [])
                            if selected_offer_idx < 0 or selected_offer_idx >= len(candidate_offers):
                                selected_offer_idx = None
                            else:
                                selected_offer = candidate_offers[selected_offer_idx]
                                # Must have credible price
                                if selected_offer.get('price_usd') is None:
                                    selected_offer_idx = None
                                    selected_offer = None
                    
                    # If no offer selected, must have rejection reason
                    if selected_offer_idx is None and not rejection:
                        last_error = f"No offer selected and no rejection reason for candidate {candidate_idx}"
                        continue
                    
                    reasoning = reasoning[:200] if reasoning else ''
                    rejection = rejection[:200] if rejection else ''
                    
                    validated_ranked.append({
                        'candidate_index': candidate_idx,
                        'final_score': final_score,
                        'selected_offer_index': selected_offer_idx,
                        'supplier_price_reasoning': reasoning,
                        'rejection_reason': rejection,
                        'selected_offer': selected_offer,
                    })
                
                # Check if all candidates are covered
                if len(validated_ranked) == len(candidates):
                    # Build final products
                    final_products = []
                    for vr in validated_ranked:
                        candidate_idx = vr['candidate_index']
                        product = products[candidate_idx] if candidate_idx < len(products) else {}
                        
                        final_product = {
                            **product,
                            'final_score': vr['final_score'],
                            'selected_supplier_offer': vr['selected_offer'],
                            'supplier_price_reasoning': vr['supplier_price_reasoning'],
                            'rejection_reason': vr['rejection_reason'],
                            'ranking_method': 'ai',
                        }
                        final_products.append(final_product)
                    
                    # Sort by final_score descending, then by candidate_index
                    final_products.sort(key=lambda p: (-p.get('final_score', 0), p.get('candidate_index', 0)))
                    
                    return final_products, None
                else:
                    last_error = f"AI returned {len(validated_ranked)} candidates but expected {len(candidates)}"
                    continue
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = f"Invalid AI response format: {str(e)[:200]}"
                continue
                
        except Exception as e:
            last_error = str(e)
            continue
    
    # All providers failed - use deterministic fallback
    final_products, fallback_warning = deterministic_final_ranking(products, supplier_data)
    warning = f"Final AI ranking failed. {fallback_warning} Last error: {last_error[:200] if last_error else 'No providers available'}"
    
    return final_products, warning


def run_sourcing_and_final_ranking(niche: str, initial_products: list[dict]) -> dict:
    """Run supplier sourcing and final ranking pipeline.
    
    Returns dict with:
    - final_products
    - supplier_summary
    - supplier_data
    - ranking_warnings (list)
    """
    # Step 1: Run supplier sourcing
    supplier_result = run_supplier_sourcing(initial_products)
    supplier_data = supplier_result.get('supplier_data', [])
    supplier_summary = supplier_result.get('supplier_summary', {})
    
    # Step 2: Run final ranking
    ranking_warnings = []
    
    if initial_products:
        final_products, warning = final_rank_products(niche, initial_products, supplier_data)
        if warning:
            ranking_warnings.append(warning)
    else:
        final_products = []
        ranking_warnings.append("No initial products to rank.")
    
    return {
        'final_products': final_products,
        'supplier_summary': supplier_summary,
        'supplier_data': supplier_data,
        'ranking_warnings': ranking_warnings,
    }


# =============================================================================
# FastAPI Endpoints
# =============================================================================

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/discover")
def discover(request: HuntRequest):
    """Discovery stage: scrape, compact, summarize, extract, rank."""
    return run_discovery(request.niche)


@app.post("/source")
def source(request: SourceRequest):
    """Source stage: source suppliers and run final ranking."""
    return run_sourcing_and_final_ranking(request.niche, request.initial_products)


@app.post("/hunt")
def hunt(request: HuntRequest):
    """Complete synchronous pipeline: discover, source, and final rank."""
    niche = request.niche

    # Step 1: Run discovery
    discovery_result = run_discovery(niche)

    # Step 2: Run sourcing and final ranking on initial products
    initial_products = discovery_result['initial_products']
    
    if initial_products:
        sourcing_result = run_sourcing_and_final_ranking(niche, initial_products)
        final_products = sourcing_result['final_products']
        supplier_summary = sourcing_result['supplier_summary']
        supplier_data = sourcing_result['supplier_data']
        additional_warnings = sourcing_result['ranking_warnings']
        
        # Combine warnings
        combined_warnings = discovery_result['ranking_warnings'] + additional_warnings
    else:
        # No initial products
        final_products = []
        supplier_summary = {
            'products_validated': 0,
            'total_supplier_requests': 0,
            'successful_supplier_requests': 0,
            'failed_supplier_requests': 0,
            'empty_supplier_requests': 0,
            'alibaba_offers': 0,
            'aliexpress_offers': 0,
        }
        supplier_data = []
        additional_warnings = ["No initial products to source or rank."]
        combined_warnings = discovery_result['ranking_warnings'] + additional_warnings

    return {
        "niche": niche,
        "message": "Viral product hunt complete - discovery, AI ranking, supplier sourcing, and final ranking done",
        "initial_products": discovery_result['initial_products'],
        "final_products": final_products,
        "supplier_summary": supplier_summary,
        "supplier_data": supplier_data,
        "discovery_summary": discovery_result['discovery_summary'],
        "discovery_data": discovery_result['discovery_data'],
        "ranking_warnings": combined_warnings
    }


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=BACKEND_PORT, reload=True)
