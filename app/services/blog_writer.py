"""
IKSHAN GROWTH — Blog Writer Service
Runs on APScheduler: keywords every Monday 9am IST, post every day 10am IST.
Stores posts in Supabase, sends Telegram notification.
"""

import json
import math
import re
import time
import logging
from datetime import datetime, timezone

import httpx
from supabase import create_client
from slugify import slugify

from app.config import get_settings

logger = logging.getLogger(__name__)

SEED_TOPICS = [
    "small business growth strategy",
    "lead generation for small business",
    "sales automation tools SMB",
    "business analytics dashboard",
    "SEO for small business",
    "CRM for small companies",
    "marketing ROI tracking",
    "B2B lead generation tactics",
    "business growth analytics",
    "how to increase website traffic",
    "conversion rate optimization small business",
    "google analytics for business owners",
]


def _db():
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_KEY)


# ══════════════════════════════════════════════════════════════════
# KEYWORD HUNT
# ══════════════════════════════════════════════════════════════════

def _get_pytrends_queries(seed: str) -> list[str]:
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=330, timeout=(10, 25))
        pt.build_payload([seed], cat=0, timeframe="today 3-m", geo="")
        related = pt.related_queries()
        queries = []
        for typ in ["top", "rising"]:
            df = related.get(seed, {}).get(typ)
            if df is not None and not df.empty:
                queries += df["query"].tolist()[:5]
        return queries
    except Exception as e:
        logger.warning(f"pytrends error for '{seed}': {e}")
        return []


def _get_tavily_keywords(seed: str) -> list[str]:
    s = get_settings()
    try:
        from tavily import TavilyClient
        t = TavilyClient(api_key=s.TAVILY_KEY)
        result = t.search(
            query=f"small business {seed} tips guide 2026",
            search_depth="basic",
            max_results=5,
        )
        return [r.get("title", "") for r in result.get("results", [])][:5]
    except Exception as e:
        logger.warning(f"Tavily keyword error: {e}")
        return []


def _score_keyword(keyword: str) -> dict:
    kw = keyword.lower()
    relevance_signals = [
        "small business", "sme", "smb", "startup", "growth", "lead",
        "sales", "seo", "analytics", "crm", "marketing", "revenue",
        "traffic", "conversion", "roi", "kpi", "dashboard", "automation",
    ]
    relevance = min(10, sum(2 for s in relevance_signals if s in kw))
    word_count = len(kw.split())
    difficulty = 9 if word_count >= 5 else 7 if word_count >= 4 else 5 if word_count >= 3 else 3
    intent_signals = [
        "how to", "best", "tips", "guide", "strategy", "improve",
        "increase", "grow", "fix", "optimize", "for small", "for smb",
    ]
    intent = min(10, sum(2 for s in intent_signals if s in kw))
    final_score = round(((relevance + difficulty + intent) / 30) * 100, 1)
    return {
        "keyword": keyword,
        "relevance_score": relevance,
        "difficulty_score": difficulty,
        "final_score": final_score,
        "source": "local",
        "status": "queued",
    }


def run_keyword_hunt():
    """Fetch + score 30 keywords, upsert to Supabase. Runs every Monday 9am IST."""
    logger.info("=== KEYWORD HUNT STARTED ===")
    db = _db()

    # Get already-queued keywords to avoid dupes
    existing_result = db.table("keywords").select("keyword").execute()
    existing = {r["keyword"] for r in existing_result.data}

    all_keywords = []
    for i, seed in enumerate(SEED_TOPICS):
        logger.info(f"[{i+1}/{len(SEED_TOPICS)}] Seeding: {seed}")
        related = _get_pytrends_queries(seed)
        time.sleep(2)
        tavily_kws = _get_tavily_keywords(seed)
        raw = list(set(related + tavily_kws + [seed]))
        for kw in raw:
            if len(kw.split()) >= 3 and kw not in existing:
                scored = _score_keyword(kw)
                if scored["final_score"] >= 30:
                    all_keywords.append(scored)

    seen, unique = set(), []
    for kw in all_keywords:
        if kw["keyword"] not in seen:
            seen.add(kw["keyword"])
            unique.append(kw)
    unique.sort(key=lambda x: x["final_score"], reverse=True)
    top30 = unique[:30]

    if top30:
        db.table("keywords").upsert(top30, on_conflict="keyword").execute()

    logger.info(f"=== KEYWORD HUNT DONE: {len(top30)} keywords saved ===")
    top5 = [f"[{k['final_score']}] {k['keyword']}" for k in top30[:5]]
    logger.info("Top 5: " + " | ".join(top5))
    return top30


# ══════════════════════════════════════════════════════════════════
# CONTENT WRITER
# ══════════════════════════════════════════════════════════════════

def _pick_top_keyword() -> dict | None:
    db = _db()
    result = (
        db.table("keywords")
        .select("*")
        .eq("status", "queued")
        .order("final_score", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _research_keyword(keyword: str) -> str:
    s = get_settings()
    try:
        from tavily import TavilyClient
        t = TavilyClient(api_key=s.TAVILY_KEY)
        result = t.search(
            query=keyword,
            search_depth="advanced",
            max_results=6,
            include_answer=True,
        )
        parts = []
        if result.get("answer"):
            parts.append(f"Summary: {result['answer']}")
        for r in result.get("results", [])[:5]:
            parts.append(f"- [{r.get('title','')}]({r.get('url','')}): {r.get('content','')[:400]}")
        return "\n".join(parts)
    except Exception as e:
        logger.warning(f"Tavily research error: {e}")
        return ""


def _get_cover_image(query: str) -> str | None:
    s = get_settings()
    try:
        r = httpx.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {s.UNSPLASH_KEY}"},
            timeout=10,
        )
        results = r.json().get("results", [])
        if results:
            return results[0]["urls"]["regular"]
    except Exception as e:
        logger.warning(f"Unsplash error: {e}")
    return None


def _write_post_with_claude(keyword: str, context: str) -> dict:
    s = get_settings()
    prompt = f"""You are an expert SEO content writer for ikshan.in — a growth analytics platform for small and mid-sized companies.

Write a complete, SEO-optimized blog post for the following keyword:

**Focus Keyword:** {keyword}

**Competitor Research Context (study these to write something BETTER):**
{context}

**Strict Requirements:**
- Word count: 1800–2200 words
- Tone: practical, data-driven, conversational — no fluff
- Focus keyword in: H1, first 100 words, at least one H2, meta description
- Include 2 natural mentions of Ikshan.in as a tool that helps with this
- End with a CTA section linking to ikshan.in

**Mandatory Structure (in this exact order):**

1. **H1 title** with keyword
2. **Intro paragraph** (150 words max, hook + keyword + what reader will learn)
3. **Key Takeaways box** — use this exact markdown format:
   > **Key Takeaways**
   > - Takeaway 1 (one line, actionable)
   > - Takeaway 2
   > - Takeaway 3
   > - Takeaway 4
   > - Takeaway 5
4. **## Table of Contents** — list all H2 sections as bullet links
5. **Main body** — 5 to 7 H2 sections, each with H3 sub-sections, bullet lists, bold terms, data points
6. **## Frequently Asked Questions** — exactly 5 Q&As in this format:
   ### Q: [question]
   [2-3 sentence answer with keyword naturally included]
7. **## Conclusion** — 100 word summary + CTA to ikshan.in

**Output (JSON only, no other text):**
{{
  "title": "SEO title (50-60 chars, includes keyword)",
  "meta_description": "155-char meta description with keyword",
  "content": "Full markdown post here",
  "category": "Growth | SEO | Analytics | Automation | Sales | Marketing"
}}"""

    r = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {s.OPENROUTER_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ikshan.in",
            "X-Title": "Ikshan Blog Agent",
        },
        json={
            "model": "anthropic/claude-opus-4",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 5000,
        },
        timeout=150,
    )
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _notify_telegram(post: dict):
    s = get_settings()
    words = len(post.get("content", "").split())
    features = []
    if "Table of Contents" in post.get("content", ""):
        features.append("📋 TOC")
    if "Key Takeaways" in post.get("content", ""):
        features.append("💡 Key Takeaways")
    if "Frequently Asked Questions" in post.get("content", "") or "FAQ" in post.get("content", ""):
        features.append("❓ FAQ")

    caption = (
        f"✅ *New Post Published*\n\n"
        f"*{post['title']}*\n\n"
        f"📂 Category: {post['category']}\n"
        f"📝 Words: ~{words}\n"
        f"⏱ Read time: {post['reading_time']} min\n"
        f"🔑 Keyword: {post['focus_keyword'][:50]}\n"
        f"✨ {' · '.join(features) if features else 'Standard format'}\n\n"
        f"🌐 `/blog/{post['slug']}`"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "🌐 View on ikshan.in", "url": f"https://ikshan.in/blog/{post['slug']}"},
        ]]
    }
    api = f"https://api.telegram.org/bot{s.TELEGRAM_TOKEN}"
    try:
        cover = post.get("cover_image_url")
        if cover:
            httpx.post(f"{api}/sendPhoto", json={
                "chat_id": s.TELEGRAM_CHAT,
                "photo": cover,
                "caption": caption,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            }, timeout=15)
        else:
            httpx.post(f"{api}/sendMessage", json={
                "chat_id": s.TELEGRAM_CHAT,
                "text": caption,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            }, timeout=15)
        logger.info("Telegram notification sent")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def run_write_and_publish():
    """Pick top keyword, write post, save to Supabase, notify Telegram. Runs every day 10am IST."""
    logger.info("=== WRITE AND PUBLISH STARTED ===")
    db = _db()

    kw_record = _pick_top_keyword()
    if not kw_record:
        logger.warning("No queued keywords. Running keyword hunt first.")
        run_keyword_hunt()
        kw_record = _pick_top_keyword()
        if not kw_record:
            logger.error("Still no keywords after hunt. Aborting.")
            return

    keyword = kw_record["keyword"]
    logger.info(f"Keyword: {keyword}")

    context = _research_keyword(keyword)
    cover = _get_cover_image(keyword)
    post_data = _write_post_with_claude(keyword, context)

    words = len(post_data["content"].split())
    post = {
        "title": post_data["title"],
        "slug": slugify(post_data["title"]),
        "content": post_data["content"],
        "meta_description": post_data["meta_description"],
        "category": post_data.get("category", "Growth"),
        "reading_time": max(1, math.ceil(words / 200)),
        "cover_image_url": cover,
        "status": "published",
        "focus_keyword": keyword,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    result = db.table("posts").insert(post).execute()
    if not result.data:
        logger.error("Failed to save post to Supabase")
        return

    db.table("keywords").update({"status": "used"}).eq("id", kw_record["id"]).execute()

    logger.info(f"✓ Published: {post['title']} | /blog/{post['slug']} | ~{words} words")
    _notify_telegram(post)
    return post
