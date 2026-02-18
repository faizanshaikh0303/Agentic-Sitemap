# Agentic Sitemap (ASG) — MVP

> Transform product pages into AI-ready intelligence layers.
> Traditional sitemaps give URLs. An Agentic Sitemap gives pre-digested context — optimized for AI shopping agents.

---

## What it does

| Step | What happens |
|------|-------------|
| **① Scrape** | Fetch any product/shoppable URL → strip noise → extract title, price, CTAs, reviews |
| **② Summarize** | Pass clean signals to Groq (LLaMA 3.3 70B) → receive structured JSON: `why_buy`, `best_for_intent`, `stock_status`, etc. |
| **③ Generate** | Convert summaries → `llms.txt` + `agent-map.json` — serve at your domain root |
| **④ Prove** | Ask the same question with and without the sitemap context — watch the difference |

---

## Stack

- **Backend**: Python · FastAPI · BeautifulSoup4 · SQLAlchemy
- **LLM**: [Groq](https://groq.com) (llama-3.3-70b-versatile)
- **Frontend**: Next.js 14 · React · TypeScript · Tailwind CSS
- **Database**: PostgreSQL

---

## Quick Start (Local)

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL running locally
- Groq API key → [console.groq.com](https://console.groq.com)

### 1. Backend

```bash
cd backend

# Copy and fill in your credentials
cp .env.example .env
# Edit .env: add GROQ_API_KEY and DATABASE_URL

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

### 2. Database

Create the PostgreSQL database:

```bash
psql -U postgres -c "CREATE DATABASE agentic_sitemap;"
```

Tables are created automatically on first startup.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

---

## Quick Start (Docker)

```bash
# Set your Groq API key
export GROQ_API_KEY=your_key_here

docker-compose up --build
```

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

---

## How to Test

1. **Index products**: Paste any public product URL into the Scrape form. Try a few different ones.
2. **Generate**: Click "Generate llms.txt →" in the header. Two files are written: `backend/llms.txt` and `backend/agent-map.json`.
3. **View the sitemap**: Switch to the "② Sitemap" tab. Copy `llms.txt` to serve at your domain.
4. **Run the proof**: Switch to "③ Proof Layer". Ask something like _"What's the best budget option?"_. Watch how the response changes with vs. without your sitemap injected.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/scrape` | Scrape + summarize a URL |
| `GET` | `/products` | List all indexed products |
| `DELETE` | `/products/{id}` | Remove a product |
| `POST` | `/generate` | Generate `llms.txt` + `agent-map.json` |
| `GET` | `/llms.txt` | Serve the generated sitemap |
| `POST` | `/compare` | Proof layer: compare with/without context |
| `GET` | `/comparisons` | History of comparisons |

### Example: Scrape a URL

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/product/sneakers"}'
```

### Example: Run the comparison

```bash
curl -X POST http://localhost:8000/compare \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the best budget option for running shoes?"}'
```

---

## The llms.txt Format

The generated `llms.txt` follows the [llmstxt.org](https://llmstxt.org) emerging standard:

```markdown
# Agentic Sitemap — Product Intelligence Layer

> Generated: 2025-01-01 12:00 UTC
> Products Indexed: 5

## Indexed Products

### [Product Name](https://buy-url.com)
- **Price**: $29.99
- **Why Buy**: _Lightweight, breathable, ships same day_
- **Best For**: `budget running shoes for beginners`
...
```

---

## Project Structure

```
Agentic Sitemap/
├── backend/
│   ├── main.py          # FastAPI app — all routes
│   ├── scraper.py       # Agent-first web scraper
│   ├── summarizer.py    # Groq LLM summarization
│   ├── generator.py     # llms.txt + agent-map.json generator
│   ├── db.py            # SQLAlchemy models
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Main dashboard
│   │   │   └── layout.tsx
│   │   └── components/
│   │       ├── ScrapeForm.tsx   # URL input + indexing
│   │       ├── ProductCard.tsx  # Product summary card
│   │       ├── SitemapViewer.tsx # llms.txt / JSON viewer
│   │       └── ComparePanel.tsx # Proof layer comparison
│   ├── package.json
│   └── next.config.js
├── docker-compose.yml
└── README.md
```

---

## Customizing the LLM Prompt

The core of the project lives in `backend/summarizer.py` → `INDEXING_SYSTEM_PROMPT`.

Edit the prompt to change what fields the LLM extracts. For example, you could add:
- `shipping_time` — "3-5 business days"
- `return_policy` — "30-day free returns"
- `bundle_deals` — whether bundles are available
- `affiliate_id` — append your affiliate tag to `cta_url`

---

## Next Steps / Extensions

- [ ] Playwright scraper for JS-heavy pages (SPAs)
- [ ] Batch scraping: accept a CSV of URLs
- [ ] Auto-refresh: re-scrape on a schedule (price changes, stock changes)
- [ ] Embed summaries into a vector DB for semantic product search
- [ ] Webhook: notify when a product goes out of stock
- [ ] Export to Shopify/Fermat format
