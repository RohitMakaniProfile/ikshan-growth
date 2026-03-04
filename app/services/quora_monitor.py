"""
IKSHAN GROWTH — Quora Monitor Service
Finds relevant unanswered/low-answer Quora questions via Tavily.
Drafts answers with Claude, sends to Telegram for human review.
NO auto-posting — human posts manually (avoids account ban).
Runs every 8 hours via APScheduler.
"""

import logging
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Quora search queries — mapped to Ikshan's 4 growth buckets
QUORA_SEARCH_QUERIES = [
    # Lead Generation
    "site:quora.com small business how to get more leads",
    "site:quora.com SEO tips small business website",
    "site:quora.com B2B lead generation strategy",
    "site:quora.com Google Business Profile optimization",
    "site:quora.com LinkedIn outreach small business",

    # Sales & Retention
    "site:quora.com how to reduce customer churn",
    "site:quora.com best CRM for small business",
    "site:quora.com lead conversion rate improve",
    "site:quora.com WhatsApp marketing small business",
    "site:quora.com customer retention strategy SMB",

    # Business Strategy
    "site:quora.com business analytics dashboard small business",
    "site:quora.com how to track marketing ROI",
    "site:quora.com cash flow management small business",
    "site:quora.com profit margin improvement tips",
    "site:quora.com sales forecasting small business",

    # Automation
    "site:quora.com automate invoice processing small business",
    "site:quora.com email automation tools small business",
    "site:quora.com customer support automation",
    "site:quora.com AI tools for small business owners",
    "site:quora.com how to save time running a business",
]

_seen_urls: set[str] = set()


def _search_quora_questions(query: str) -> list[dict]:
    s = get_settings()
    try:
        from tavily import TavilyClient
        t = TavilyClient(api_key=s.TAVILY_KEY)
        result = t.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_domains=["quora.com"],
        )
        return result.get("results", [])
    except Exception as e:
        logger.warning(f"Tavily Quora search error: {e}")
        return []


def _draft_quora_answer(question_title: str, question_url: str) -> str:
    s = get_settings()
    prompt = f"""You are a growth expert answering on Quora. You help small business owners with practical advice.

Quora question: "{question_title}"

Write a high-quality Quora answer:
- 200–350 words
- Start with a direct, confident answer to the question (no "Great question!" intros)
- Give 3–4 actionable steps or insights, with brief explanations
- Practical and specific — use real examples or numbers where possible
- India-relevant context where appropriate
- At the very end, ONE natural mention of ikshan.in ONLY if it directly solves the problem
- If ikshan.in is not directly relevant, skip it entirely
- Quora readers are smart — no fluff, no corporate speak

Write only the answer text, nothing else."""

    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {s.OPENROUTER_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "anthropic/claude-opus-4",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8,
                "max_tokens": 600,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Claude Quora draft error: {e}")
        return "(Could not generate draft)"


def _send_telegram_alert(title: str, url: str, draft: str):
    s = get_settings()
    short_title = title[:80] if title else "Quora Question"

    msg = (
        f"💡 *Quora Opportunity Found*\n\n"
        f"*Q:* {short_title}\n\n"
        f"─────────────────\n"
        f"*Draft Answer (review before posting):*\n\n"
        f"{draft}\n\n"
        f"─────────────────\n"
        f"🔗 [Open on Quora]({url})"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "📖 Open Quora Question", "url": url},
        ]]
    }

    api = f"https://api.telegram.org/bot{s.TELEGRAM_TOKEN}"
    try:
        httpx.post(f"{api}/sendMessage", json={
            "chat_id": s.TELEGRAM_CHAT,
            "text": msg,
            "parse_mode": "Markdown",
            "reply_markup": keyboard,
            "disable_web_page_preview": False,
        }, timeout=15)
        logger.info(f"Telegram alert sent for Quora: {short_title[:50]}")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def run_quora_monitor():
    """
    Search Quora via Tavily for relevant SMB questions.
    Draft answers with Claude. Send to Telegram for human review.
    Runs every 8 hours via APScheduler.
    """
    logger.info("=== QUORA MONITOR STARTED ===")
    found = 0

    for query in QUORA_SEARCH_QUERIES:
        results = _search_quora_questions(query)
        for result in results:
            url = result.get("url", "")
            title = result.get("title", "").replace(" - Quora", "").strip()

            if not url or "quora.com" not in url:
                continue
            if url in _seen_urls:
                continue
            if not title:
                continue

            _seen_urls.add(url)

            logger.info(f"Found Quora question: {title[:60]}")
            draft = _draft_quora_answer(title, url)
            _send_telegram_alert(title, url, draft)
            found += 1

            # Max 2 alerts per run to avoid Telegram spam
            if found >= 2:
                break
        if found >= 2:
            break

    logger.info(f"=== QUORA MONITOR DONE: {found} opportunities found ===")
    return found
