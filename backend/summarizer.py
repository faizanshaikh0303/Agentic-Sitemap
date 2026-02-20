"""
Contextual Summarization via Groq
===================================
Takes scraped product data and generates a structured JSON summary
optimized for AI shopping agents.

The system prompt is the core intellectual work — it defines what "agent-ready"
data looks like. We ask the LLM to produce fields that a downstream agent can
act on directly: intent tags, why-buy, CTA URL, stock status.
"""

import os
import json
import logging
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# This prompt is the heart of the project.
# It tells the LLM exactly what signals matter for a shopping agent.
INDEXING_SYSTEM_PROMPT = """You are an indexing assistant for an AI shopping agent.
Your job: analyze product page content and extract structured, agent-ready intelligence.

Return ONLY a valid JSON object — no markdown fences, no explanation, no extra text.

Required fields:
{
  "title": "Product name, concise, under 60 chars",
  "price": "Price string like '$29.99', or null if unavailable",
  "primary_benefit": "The single most compelling benefit, one sentence",
  "best_for_intent": "The search intent this product satisfies, e.g. 'budget-friendly skincare for dry skin' or 'high-performance trail running shoes'",
  "why_buy": "Unique selling point in 15 words or fewer — this is what an agent cites",
  "stock_status": "in_stock | out_of_stock | unknown",
  "target_audience": "Who benefits most from this product, specific not generic",
  "cta_url": "The primary buy/checkout URL — must be a real URL string",
  "sentiment": "positive | neutral | negative (based on reviews and tone)",
  "confidence": 0.0 to 1.0 — how confident you are given the data quality
}

Rules:
- why_buy must be ≤ 15 words. Be sharp and specific, not generic ('Great quality!' is bad).
- best_for_intent should read like a search query a shopper would type.
- If price is ambiguous (range, subscription), use the lowest entry price.
- confidence < 0.5 means the page had very little product data.
- Never invent data not present in the input."""


def summarize_product(scraped_data: dict) -> dict:
    """
    Call Groq with scraped product data.
    Returns a structured JSON summary dict.
    """
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    # Build a compact but complete context block for the LLM
    cta_text = json.dumps(scraped_data.get("cta_buttons", []), ensure_ascii=False)
    review_text = json.dumps(scraped_data.get("review_snippets", []), ensure_ascii=False)

    source = scraped_data.get("_source", "html")
    stock_hint = scraped_data.get("_stock_hint", "")
    stock_note = f"\nStock Status (verified from API): {stock_hint}" if stock_hint else ""

    user_message = f"""Analyze this product page and return the structured JSON summary.
Data source: {source}{stock_note}

--- PRODUCT PAGE DATA ---
URL: {scraped_data.get("url", "")}
Title: {scraped_data.get("title", "Not found")}
Price: {scraped_data.get("price", "Not found")}
Description: {scraped_data.get("description", "Not found")}
CTA Buttons: {cta_text}
Customer Reviews: {review_text}

Page Content:
{scraped_data.get("raw_text", "")[:3000]}
--- END DATA ---

Return ONLY the JSON object."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": INDEXING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,  # Low temp for consistent structured output
            max_tokens=1024,
        )

        raw = response.choices[0].message.content.strip()

        # Handle accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        summary = json.loads(raw)

        # Ensure cta_url is populated
        if not summary.get("cta_url"):
            buttons = scraped_data.get("cta_buttons", [])
            summary["cta_url"] = buttons[0]["url"] if buttons else scraped_data.get("url", "")

        logger.info(f"Summarized: '{summary.get('title')}' (confidence: {summary.get('confidence')})")
        return summary

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e}\nRaw output: {raw!r}")
        return _fallback_summary(scraped_data)
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        raise


def _fallback_summary(scraped: dict) -> dict:
    """Return a minimal valid summary when LLM output can't be parsed."""
    buttons = scraped.get("cta_buttons", [])
    return {
        "title": scraped.get("title", "Unknown Product"),
        "price": scraped.get("price"),
        "primary_benefit": scraped.get("description", "See product page for details")[:120],
        "best_for_intent": "general shopping",
        "why_buy": "Visit the product page for details",
        "stock_status": "unknown",
        "target_audience": "general consumers",
        "cta_url": buttons[0]["url"] if buttons else scraped.get("url", ""),
        "sentiment": "neutral",
        "confidence": 0.1,
    }
