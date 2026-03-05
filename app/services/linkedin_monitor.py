"""
IKSHAN GROWTH — LinkedIn Monitor Service
Runs every 12h. Finds trending LinkedIn hashtags + posts in startup/SMB/AI space.
Drafts a comment/post for Rohit to manually publish. Sends to Telegram.
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

LINKEDIN_QUERIES = [
    # AI & startup trending
    "site:linkedin.com/posts AI tools for small business 2026",
    "site:linkedin.com/posts startup growth hacks founders 2026",
    "site:linkedin.com/posts revenue growth SMB strategy 2026",
    "site:linkedin.com/posts best productivity tools startup team",
    "site:linkedin.com/posts AI automation save time business",
    # Funding & startup news
    "site:linkedin.com/posts startup funding India 2026",
    "site:linkedin.com/posts bootstrapped startup lessons founders",
    "site:linkedin.com/posts product market fit lessons startup",
    # Design & team
    "site:linkedin.com/posts AI design tools creative team 2026",
    "site:linkedin.com/posts small team big results startup productivity",
]

TRENDING_HASHTAG_QUERIES = [
    "trending LinkedIn hashtags startups AI tools 2026",
    "trending LinkedIn hashtags small business growth India",
    "trending LinkedIn hashtags founder productivity automation",
    "trending LinkedIn hashtags SaaS startup revenue",
]


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    s = get_settings()
    try:
        from tavily import TavilyClient
        t = TavilyClient(api_key=s.TAVILY_KEY)
        result = t.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
        )
        return result.get("results", [])
    except Exception as e:
        logger.warning(f"Tavily error for '{query[:50]}': {e}")
        return []


def _extract_hashtags_from_text(text: str) -> list[str]:
    import re
    raw = re.findall(r'#([A-Za-z][A-Za-z0-9_]{2,29})', text)
    # Normalize and deduplicate
    seen, result = set(), []
    for tag in raw:
        lower = tag.lower()
        if lower not in seen and lower not in {"the", "and", "for", "with", "this", "that"}:
            seen.add(lower)
            result.append(f"#{tag}")
    return result[:15]


def _draft_linkedin_post(topic: str, context: str) -> str:
    s = get_settings()
    prompt = f"""You are writing a LinkedIn post for Rohit Makani, founder of Ikshan.in — an AI-powered growth analytics platform for small businesses and startups.

**Topic / Trending Discussion:** {topic}

**Context from web:**
{context[:800]}

**LinkedIn Post Rules:**
- 150-200 words max
- Hook in first line (no "I am excited to share" — use a stat, question, or bold statement)
- Practical insight for founders and SMB owners
- 1 mention of Ikshan.in naturally (not salesy)
- 3-5 relevant hashtags at the end
- Conversational, founder-to-founder tone
- India context where natural

Write ONLY the post text. No explanation. No "Here is the post:" prefix."""

    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {s.OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://ikshan.in",
                "X-Title": "Ikshan LinkedIn Agent",
            },
            json={
                "model": "anthropic/claude-opus-4",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.8,
                "max_tokens": 500,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Claude draft error: {e}")
        return ""


def _notify_telegram(hashtags: list[str], post_draft: str, topic: str, source_url: str):
    s = get_settings()
    tag_line = " ".join(hashtags[:8]) if hashtags else "No hashtags found"
    caption = (
        f"LinkedIn Trend Alert\n\n"
        f"Topic: {topic[:100]}\n\n"
        f"Trending Hashtags:\n{tag_line}\n\n"
        f"Draft Post:\n{post_draft[:800]}\n\n"
        f"Source: {source_url[:100] if source_url else 'N/A'}\n\n"
        f"Post manually on LinkedIn"
    )
    api = f"https://api.telegram.org/bot{s.TELEGRAM_TOKEN}"
    try:
        httpx.post(f"{api}/sendMessage", json={
            "chat_id": s.TELEGRAM_CHAT,
            "text": caption,
            "parse_mode": "Markdown",
        }, timeout=15)
        logger.info("LinkedIn Telegram alert sent")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def run_linkedin_monitor():
    """Find LinkedIn trending topics + hashtags, draft a post, send to Telegram. Runs every 12h."""
    logger.info("=== LINKEDIN MONITOR STARTED ===")

    # Step 1: Find trending hashtags
    all_hashtags = []
    for query in TRENDING_HASHTAG_QUERIES[:2]:
        results = _tavily_search(query, max_results=5)
        for r in results:
            combined = f"{r.get('title', '')} {r.get('content', '')}"
            all_hashtags.extend(_extract_hashtags_from_text(combined))

    # Deduplicate hashtags
    seen, unique_hashtags = set(), []
    for tag in all_hashtags:
        if tag.lower() not in seen:
            seen.add(tag.lower())
            unique_hashtags.append(tag)
    top_hashtags = unique_hashtags[:12]
    logger.info(f"Found {len(top_hashtags)} trending hashtags")

    # Step 2: Find a trending LinkedIn post/topic
    alerts_sent = 0
    for query in LINKEDIN_QUERIES[:4]:
        if alerts_sent >= 2:
            break
        results = _tavily_search(query, max_results=3)
        if not results:
            continue

        top = results[0]
        title = top.get("title", "")
        content = top.get("content", "")
        url = top.get("url", "")

        if not title or len(title) < 20:
            continue

        # Step 3: Draft LinkedIn post
        context = f"{title}\n{content[:500]}"
        draft = _draft_linkedin_post(title, context)
        if not draft:
            continue

        # Combine discovered hashtags with ones from this result
        result_tags = _extract_hashtags_from_text(f"{title} {content}")
        combined_tags = list(dict.fromkeys(result_tags + top_hashtags))[:10]

        _notify_telegram(combined_tags, draft, title, url)
        alerts_sent += 1

    logger.info(f"=== LINKEDIN MONITOR DONE: {alerts_sent} alerts sent ===")
    return alerts_sent
