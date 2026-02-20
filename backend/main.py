"""
Agentic Sitemap — FastAPI Backend
===================================
Three core endpoints map directly to the three-step pipeline:

  POST /scrape      → Step 1 (scrape) + Step 2 (summarize)
  POST /generate    → Step 3 (generate llms.txt + agent-map.json)
  POST /compare     → Proof Layer (with vs. without context)
"""

import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from groq import Groq
from groq import RateLimitError as GroqRateLimitError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import Comparison, Product, Summary, get_db, init_db
from generator import generate_agent_map_json, generate_llms_txt
from scraper import scrape_product_page
from summarizer import summarize_product

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s │ %(name)s │ %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic Sitemap API",
    description="Transform product pages into AI-ready intelligence layers",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("Database tables ready.")


# ── Request/Response Models ────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    force_refresh: bool = False


class CompareRequest(BaseModel):
    question: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "agentic-sitemap-api"}


@app.post("/scrape")
async def scrape_url(request: ScrapeRequest, db: Session = Depends(get_db)):
    """
    Step 1 + 2: Scrape a product URL, summarize with Groq, store in DB.
    Returns cached result if URL was already indexed (unless force_refresh=True).
    """
    existing = db.query(Product).filter(Product.url == request.url).first()

    if existing and not request.force_refresh:
        return {
            "status": "cached",
            "product_id": existing.id,
            "message": "Already indexed. Pass force_refresh=true to re-scrape.",
            "product": _product_to_dict(existing),
        }

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    logger.info(f"Scraping: {request.url}")
    try:
        scraped = scrape_product_page(request.url)
    except ValueError as e:
        logger.error(f"Scrape failed: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    # ── Step 2: Summarize ─────────────────────────────────────────────────────
    logger.info("Summarizing with Groq...")
    try:
        summary_data = summarize_product(scraped)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM summarization failed: {e}")

    # ── Persist ───────────────────────────────────────────────────────────────
    if existing and request.force_refresh:
        existing.title = scraped["title"]
        existing.price = scraped["price"]
        existing.description = scraped["description"]
        existing.raw_text = scraped["raw_text"]
        existing.cta_buttons = scraped["cta_buttons"]
        existing.review_snippets = scraped["review_snippets"]
        db.flush()

        if existing.summary:
            existing.summary.summary_data = summary_data
        else:
            db.add(Summary(product_id=existing.id, summary_data=summary_data))

        db.commit()
        db.refresh(existing)
        product = existing
    else:
        product = Product(
            url=scraped["url"],
            title=scraped["title"],
            price=scraped["price"],
            description=scraped["description"],
            raw_text=scraped["raw_text"],
            cta_buttons=scraped["cta_buttons"],
            review_snippets=scraped["review_snippets"],
        )
        db.add(product)
        db.flush()
        db.add(Summary(product_id=product.id, summary_data=summary_data))
        db.commit()
        db.refresh(product)

    return {
        "status": "indexed",
        "product_id": product.id,
        "product": _product_to_dict(product),
    }


@app.get("/products")
def list_products(db: Session = Depends(get_db)):
    """List all indexed products with their Groq summaries."""
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    return {"count": len(products), "products": [_product_to_dict(p) for p in products]}


@app.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return _product_to_dict(product)


@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return {"status": "deleted", "product_id": product_id}


@app.post("/generate")
def generate_sitemap(db: Session = Depends(get_db)):
    """
    Step 3: Generate llms.txt and agent-map.json from all indexed products.
    Saves files to disk and returns content for preview.
    """
    products = db.query(Product).all()
    if not products:
        raise HTTPException(status_code=400, detail="No products indexed yet.")

    summaries = [
        {"product_url": p.url, "summary_data": p.summary.summary_data}
        for p in products
        if p.summary
    ]
    if not summaries:
        raise HTTPException(status_code=400, detail="No summaries available. Try re-indexing.")

    llms_txt = generate_llms_txt(summaries)
    agent_map = generate_agent_map_json(summaries)

    return {
        "status": "generated",
        "product_count": len(summaries),
        "files_written": ["llms.txt", "agent-map.json"],
        "llms_txt_preview": llms_txt[:3000],
        "agent_map": agent_map,
    }


@app.get("/llms.txt", response_class=PlainTextResponse)
def serve_llms_txt():
    """Serve the generated llms.txt — this is the file AI agents would fetch."""
    if not os.path.exists("llms.txt"):
        raise HTTPException(
            status_code=404,
            detail="llms.txt not generated yet. POST to /generate first.",
        )
    with open("llms.txt", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/compare")
async def compare_with_without_context(
    request: CompareRequest,
    db: Session = Depends(get_db),
):
    """
    The Proof Layer.
    Query the LLM with the same question twice:
      1. No context   → baseline vague answer
      2. agent-map.json injected → specific, actionable answer with CTAs
    Saves both answers to DB for history.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    model = "llama-3.3-70b-versatile"

    # ── Query WITHOUT context ─────────────────────────────────────────────────
    logger.info("Running baseline query (no context)...")
    try:
        resp_without = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful shopping assistant. "
                        "Answer the user's question about products. "
                        "You have no specific product catalog — answer from general knowledge."
                    ),
                },
                {"role": "user", "content": request.question},
            ],
            temperature=0.7,
            max_tokens=512,
        )
    except GroqRateLimitError as e:
        raise HTTPException(status_code=429, detail=f"Groq rate limit reached: {e}")
    without_answer = resp_without.choices[0].message.content

    # ── Build compact catalog string for the system prompt ────────────────────
    # Always use live DB data so newly-indexed products are included immediately.
    # Compact tabular format instead of full JSON to save ~60% tokens.
    products = db.query(Product).all()
    summaries = [
        {"product_url": p.url, "summary_data": p.summary.summary_data}
        for p in products
        if p.summary
    ]
    if not summaries:
        raise HTTPException(
            status_code=400,
            detail="No indexed products found. Scrape some URLs first.",
        )

    agent_map = generate_agent_map_json(summaries)
    catalog_lines = []
    for p in agent_map.get("products", []):
        catalog_lines.append(
            f"- {p.get('title')} | {p.get('price','?')} | {p.get('best_for_intent','')} | {p.get('why_buy','')} | {p.get('stock_status','unknown')} | {p.get('cta_url','')}"
        )
    catalog_str = "\n".join(catalog_lines)

    # ── Query WITH context ────────────────────────────────────────────────────
    logger.info("Running agent-first query (with agentic sitemap context)...")
    system_with_context = f"""You are an intelligent shopping assistant. You have been given a pre-indexed product catalog (an Agentic Sitemap) built from real product pages.

=== PRODUCT CATALOG ===
{catalog_str}
=== END CATALOG ===

Instructions:
- Search the catalog first. If one or more products match the user's request, recommend those — cite the exact product name, price, and buy URL so the user can act immediately.
- If the user states a price limit, only recommend catalog products at or below that price. Never suggest a catalog product that exceeds the stated budget.
- When multiple catalog products qualify, list all of them.
- You may use your general knowledge to explain WHY a catalog product fits — but do not recommend products that are not in the catalog.
- If no catalog product matches, say so clearly and describe what IS available."""

    try:
        resp_with = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_with_context},
                {"role": "user", "content": request.question},
            ],
            temperature=0.7,
            max_tokens=512,
        )
    except GroqRateLimitError as e:
        raise HTTPException(status_code=429, detail=f"Groq rate limit reached: {e}")
    with_answer = resp_with.choices[0].message.content

    # ── Persist comparison ────────────────────────────────────────────────────
    comparison = Comparison(
        question=request.question,
        without_context=without_answer,
        with_context=with_answer,
    )
    db.add(comparison)
    db.commit()

    return {
        "question": request.question,
        "without_context": {
            "answer": without_answer,
            "tokens_used": resp_without.usage.total_tokens,
            "label": "Baseline — No Product Context",
        },
        "with_context": {
            "answer": with_answer,
            "tokens_used": resp_with.usage.total_tokens,
            "label": "Agent-First — With Agentic Sitemap",
        },
    }


@app.get("/comparisons")
def list_comparisons(db: Session = Depends(get_db)):
    """History of all proof-layer comparisons."""
    rows = db.query(Comparison).order_by(Comparison.created_at.desc()).limit(20).all()
    return {
        "count": len(rows),
        "comparisons": [
            {
                "id": c.id,
                "question": c.question,
                "without_context": c.without_context,
                "with_context": c.with_context,
                "created_at": c.created_at.isoformat(),
            }
            for c in rows
        ],
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _product_to_dict(product: Product) -> dict:
    return {
        "id": product.id,
        "url": product.url,
        "title": product.title,
        "price": product.price,
        "description": product.description,
        "cta_buttons": product.cta_buttons,
        "review_snippets": product.review_snippets,
        "created_at": product.created_at.isoformat(),
        "summary": product.summary.summary_data if product.summary else None,
    }
