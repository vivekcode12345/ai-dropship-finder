# Viral Product Hunter

A beginner-friendly FastAPI and Streamlit product research app that discovers trending products, ranks them by viral potential, sources suppliers from Alibaba and AliExpress, and produces a final supplier-aware ranking.

## Workflow

```bash
# Create virtual environment (already present in this project as
# `viral-product-hunter/`; re-run only if the directory is missing)
uv venv viral-product-hunter

# Activate virtual environment
# macOS/Linux:
source viral-product-hunter/bin/activate

# Windows:
viral-product-hunter\Scripts\activate

# Install dependencies
uv pip install -r requirements.txt

# Copy environment example
cp .env.example .env

# Configure your API keys in .env
# Required: DECODO_AUTH_TOKEN for scraping (must be a non-empty value)
# Optional: OPENAI_API_KEY, KIMI_API_KEY, MOONSHOT_API_KEY for AI ranking
#
# IMPORTANT: the variable must be spelled DECODO_AUTH_TOKEN.
# A misspelled DECODE_AUTH_TOKEN is silently ignored and the backend
# will refuse to start with a "Missing DECODO_AUTH_TOKEN" error.

# Start backend (FastAPI)
uv run api.py
# or
python api.py

# Start frontend (Streamlit)
uv run streamlit run streamlit_app.py
```

## URLs

- **Backend API**: `http://127.0.0.1:8000`
- **Health Check**: `http://127.0.0.1:8000/health`
- **API Docs**: `http://127.0.0.1:8000/docs`
- **Streamlit Frontend**: `http://localhost:8501`

## API Endpoints

### GET `/health`
Liveness probe. Returns `{"status": "ok"}`.

### POST `/hunt`
Complete synchronous pipeline. Returns:
- `niche`: The product niche
- `message`: Completion message
- `initial_products`: Products from discovery and initial AI ranking
- `final_products`: Products with final supplier-aware ranking
- `supplier_summary`: Metrics for supplier sourcing (products validated, requests, successes, failures, empty)
- `supplier_data`: Per-product supplier offer details
- `discovery_summary`: Per-source summary of discovery results
- `discovery_data`: Compact discovery data for debugging
- `ranking_warnings`: Combined warnings from all stages

### POST `/discover`
Discovery stage only. Accepts `HuntRequest` with `niche`. Returns the same structure as `run_discovery()`:
- `niche`
- `initial_products`
- `discovery_summary`
- `discovery_data`
- `ranking_warnings`

### POST `/source`
Supplier sourcing and final ranking stage. Accepts `SourceRequest` with `niche` and `initial_products`. Returns:
- `final_products`
- `supplier_summary`
- `supplier_data`
- `ranking_warnings`

## Streamlit UI

The frontend uses staged requests with visible progress:
1. Clicks "Hunt Products" clears old results and starts discovery
2. POST to `/discover` with status "Discovering products..."
3. Reports initial candidate count
4. Updates status to "Sourcing Alibaba and AliExpress offers..."
5. POST to `/source` with niche and initial_products
6. Merges both responses and stores in `st.session_state.hunt_results`
7. Marks the status widget complete ("Viral product hunt complete")

The UI displays four main sections:
1. **Initial Viral Ranking**: Rank, product, viral score, retail price, currency, source, clickable product link
2. **Supplier Sourcing**: Five metrics (products validated, total requests, successful, failed, empty) with per-product offer expanders
3. **Final Supplier-Aware Ranking**: Rank, product, final score, selected supplier, supplier cost in USD, MOQ, reasoning, rejection, clickable supplier link
4. **Discovery source details**: Summary table with option to show raw discovery data

## Features

### Discovery
- 10 discovery sources: 6 Google searches, Amazon, Reddit, TikTok Shop, YouTube
- Concurrent scraping via Decodo with configurable `DECODO_MAX_WORKERS` (default 5)
- Response compaction and trimming (12,000 char limit)
- Product extraction with deduplication
- Local viral scoring (0-100) based on price, rating, reviews, image, URL, badges

### AI Initial Ranking
- Provider fallback: Kimi (KIMI_API_KEY or MOONSHOT_API_KEY) -> OpenAI (OPENAI_API_KEY) -> Generic (AI_MODEL_API_KEY)
- Configurable model names and URLs
- Ranks candidates by viral potential, problem-solving, video demo potential, emotional appeal, shipping ease, competition, bundling, supplier evidence, year-round demand
- Rejects unsafe, restricted, fragile, edible, medicinal, branded-risk, or difficult-to-ship products
- Local scoring fallback when AI is unavailable

### Supplier Sourcing
- Sources Alibaba and AliExpress for top 10 initial products
- 20 concurrent requests (2 per product) with configurable `DECODO_SUPPLIER_MAX_WORKERS` (default 10)
- Uses `DECODO_PROXY_POOL` (default "premium")
- Parses both structured JSON and rendered HTML (standard library HTMLParser, no BeautifulSoup)
- Normalizes supplier offers with: product_reference, supplier_platform, supplier_title, unit_price/price_range, currency, min_order_quantity, shipping_info, supplier_url, rating, orders, reviews, supplier_evidence, provenance
- Currency conversion to USD with fixed rates: USD=1.0, EUR=1.09, GBP=1.28, CNY/RMB=0.14, AUD=0.66, CAD=0.73

### Final Ranking
- AI final ranking considers: viral potential, supplier cost, evidence quality, MOQ, shipping practicality, margin, cross-platform availability
- Requires every candidate exactly once with candidate_index, final_score (0-100), selected_offer_index or null, supplier_price_reasoning, rejection_reason
- Validates selected_offer_index belongs to candidate and has credible price
- Deterministic fallback when AI unavailable using: cost (35%), evidence (30%), MOQ (20%), shipping (15%) for offer selection; viral (30%), cost (18%), evidence (15%), MOQ (10%), shipping (8%), margin (12%), availability (7%) for final score
- Availability: 100 for 2 platforms, 50 for 1, 0 for none; margin defaults to 40 if cannot estimate

## Configuration

### Environment Variables

```bash
# Decodo Scraping
DECODO_AUTH_TOKEN=                     # Required
DECODO_API_URL=https://scraper-api.decodo.com/v2/scrape
DECODO_REQUEST_TIMEOUT=120
DECODO_MAX_WORKERS=5
DECODO_PROXY_POOL=premium
DECODO_SUPPLIER_MAX_WORKERS=10

# AI Providers
OPENAI_API_KEY=
KIMI_API_KEY=
MOONSHOT_API_KEY=
AI_MODEL_API_KEY=
AI_MODEL_API_URL=https://api.openai.com/v1/chat/completions
AI_MODEL_NAME=gpt-4o-mini
KIMI_API_URL=
KIMI_MODEL_NAME=kimi-k3

# Backend
BACKEND_API_URL=http://127.0.0.1:8000
BACKEND_READ_TIMEOUT=600
```

### Principal Project Files

- `api.py`: FastAPI backend with all discovery, ranking, sourcing, and final ranking logic
- `streamlit_app.py`: Streamlit frontend with staged UI
- `test_api.py`: Comprehensive test suite (171 tests)
- `requirements.txt`: Python dependencies
- `.env.example`: Environment variable template
- `.gitignore`: Excludes `.env`, the `viral-product-hunter/` venv, caches and local backups
- `README.md`: This documentation

## Testing

```bash
# Set test token and run tests
DECODO_AUTH_TOKEN=test-token python -m unittest -v test_api.py
```

`test_api.py` also sets `DECODO_AUTH_TOKEN` itself (via `os.environ.setdefault`), so the tests
run even when `.env` is absent. The endpoint tests use `fastapi.testclient.TestClient`, which
requires the `httpx2` package (already listed in `requirements.txt`).

Tests cover:
- Source URL building (10 sources in correct order)
- Decodo content parsing (old and current parser envelopes)
- Content trimming (Google and Amazon specific)
- Product extraction and deduplication
- Local viral scoring
- AI provider configuration and fallback
- AI model analysis and score clamping
- Supplier payload building
- Supplier validation and concurrent requests
- HTML parsing for Alibaba and AliExpress
- Price repair and currency normalization
- Supplier listing normalization
- Supplier response processing
- Deterministic final ranking
- Final AI ranking
- Sourcing and final ranking pipeline
- AI provider prompting (default initial-ranking prompt and final-ranking prompt override)
- All API endpoints

## Live Run Credentials

For a live run, you need:
- `DECODO_AUTH_TOKEN`: Required for all scraping (from Decodo)
- AI API keys are optional (falls back to deterministic ranking):
  - `OPENAI_API_KEY` for OpenAI
  - `KIMI_API_KEY` or `MOONSHOT_API_KEY` for Kimi/Moonshot
  - `AI_MODEL_API_KEY` for generic provider

Without AI keys, the application uses deterministic fallback ranking for both initial and final ranking stages.

## Troubleshooting

### `ValueError: Missing DECODO_AUTH_TOKEN in .env`
The backend reads `DECODO_AUTH_TOKEN` from `.env` at import time and refuses to start without it.

1. Make sure `.env` exists (`cp .env.example .env`).
2. Make sure the variable is spelled exactly `DECODO_AUTH_TOKEN` — a misspelled
   `DECODE_AUTH_TOKEN` is ignored even though the value is present.
3. Make sure the value is not empty.

### `ModuleNotFoundError: No module named 'httpx2'` while running tests
The endpoint tests use `fastapi.testclient`, which requires `httpx2`. Install the dependencies
from `requirements.txt` inside the project venv:

```bash
uv pip install -r requirements.txt
```

### Streamlit says it cannot connect to the backend
Start the FastAPI backend first (`python api.py`) and confirm `http://127.0.0.1:8000/health`
returns `{"status": "ok"}`. If you changed `BACKEND_API_URL`, restart Streamlit so it re-reads `.env`.

### `Final AI ranking failed ... deterministic fallback` warnings
Warnings are informational: the app always produces a ranking. If AI ranking is expected, verify
the relevant API key (`KIMI_API_KEY` / `MOONSHOT_API_KEY` / `OPENAI_API_KEY` / `AI_MODEL_API_KEY`)
is valid and check the "Last error" text in the warning for HTTP status details (401 = bad key,
429 = rate limit).
