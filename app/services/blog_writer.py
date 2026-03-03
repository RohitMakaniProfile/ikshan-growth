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

# ── Seed topics derived from Ikshan's 138 task categories ────────
# Mapped to 4 Growth Buckets: Lead Gen | Sales & Retention | Business Strategy | Save Time

SEED_TOPICS = [
    # ── LEAD GENERATION (Marketing, SEO & Social) ─────────────────
    "how to get more leads from Google website small business",
    "SEO for small business website 2026",
    "Google Business Profile optimization tips for local business",
    "how to write SEO blog posts that rank small business",
    "B2B cold email outreach strategy small business",
    "LinkedIn lead generation for small companies",
    "social media content strategy for small business",
    "how to repurpose content for multiple platforms",
    "high converting ad copy for small business",
    "how to reduce wasted ad spend Google Ads",
    "competitor ad research tools for small business",
    "how to find decision maker emails B2B",
    "how to automate LinkedIn outreach small business",
    "viral content ideas for small business social media",
    "personal brand building on LinkedIn for founders",
    "how to improve Google Business Profile leads",
    "ecommerce product listing SEO tips",

    # ── SALES & RETENTION ─────────────────────────────────────────
    "how to qualify leads automatically CRM",
    "lead conversion rate optimization small business",
    "how to reduce customer churn small business",
    "upsell and cross sell strategy for small business",
    "how to improve online reviews and reputation",
    "WhatsApp sales strategy for small business India",
    "how to speed up deal closure small business",
    "customer retention strategies SMB",
    "how to follow up leads automatically",
    "why customers don't convert website",
    "how to reduce missed leads faster reply",
    "call tracking and conversation intelligence tools",

    # ── BUSINESS STRATEGY (Intelligence, Market & Org) ────────────
    "sales dashboard for small business owners",
    "marketing ROI dashboard small business",
    "how to track marketing performance KPIs",
    "competitor price monitoring tools small business",
    "cash flow management tips small business",
    "how to find profit leaks in small business",
    "business intelligence tools for SMBs",
    "how to hire faster small business",
    "market trend research tools for small business",
    "sales revenue forecasting small business",
    "AI business analytics for founders",
    "how to build SOPs for small business",
    "financial health dashboard for business owners",
    "budget vs actual analysis small business",
    "how to predict demand small business inventory",

    # ── SAVE TIME (Automation, Workflow, Ops, Finance, Admin) ─────
    "how to automate lead capture into CRM",
    "invoice data extraction software small business",
    "how to summarize meetings automatically AI",
    "customer support automation tools small business",
    "email automation sequences small business",
    "how to automate social media posting",
    "expense tracking automation small business",
    "resume screening automation tools",
    "how to automate invoice and payment reminders",
    "contract review automation small business",
    "how to extract data from PDF to spreadsheet",
    "WhatsApp auto reply business automation",
    "support ticket routing automation",
    "how to automate employee onboarding",
    "content calendar automation tools small business",
    "how to automate procurement approvals",
    "AI tools to save time for small business owners",
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
    prompt = f"""You are an expert SEO content writer for ikshan.in — an AI-powered growth platform for small and mid-sized businesses (SMBs).

**What Ikshan does:** Ikshan helps SMB owners instantly identify their biggest growth leaks across 4 areas:
1. Lead Generation (SEO, social media, ads, B2B outreach)
2. Sales & Retention (conversion, churn, upsell, reviews)
3. Business Strategy (analytics dashboards, market research, cash flow, hiring)
4. Save Time (automation of invoices, support, HR, emails, meetings)

Write a complete, SEO-optimized blog post for the following keyword:

**Focus Keyword:** {keyword}

**Competitor Research (write something BETTER than these):**
{context}

**Writing Rules:**
- Word count: 1800–2200 words minimum
- Tone: practical, direct, data-driven — written for busy SMB owners
- No buzzword fluff — every sentence must be actionable
- Focus keyword in: H1, first 100 words, at least 2 H2s, meta description
- 2 natural mentions of Ikshan.in as a tool that solves this problem
- India-relevant examples where applicable (Indian SMBs, rupees, local context)
- End with a clear CTA to try ikshan.in

**Mandatory Structure:**

1. **H1** — includes keyword, max 60 chars
2. **Intro** — 120–150 words: hook with a pain point, state the keyword problem, preview what reader will learn
3. **Key Takeaways box:**
   > **Key Takeaways**
   > - [actionable insight 1]
   > - [actionable insight 2]
   > - [actionable insight 3]
   > - [actionable insight 4]
   > - [actionable insight 5]
4. **## Table of Contents** — bullet list of all H2 section links
5. **Main body** — 5 to 7 H2 sections, each with:
   - H3 sub-sections
   - Numbered or bullet lists
   - Bold key terms
   - At least 1 real stat or data point per H2
6. **## Frequently Asked Questions** — 5 Q&As:
   ### Q: [question]
   [2–3 sentence answer, includes keyword naturally]
7. **## Conclusion** — 100 words: summarize top insight + CTA to ikshan.in

**Pick the most relevant category:**
- "Lead Generation" — if about SEO, ads, social media, B2B outreach, content
- "Sales & Retention" — if about conversion, churn, reviews, upsell, CRM
- "Business Strategy" — if about analytics, dashboards, market research, finance, hiring
- "Automation" — if about saving time, workflow automation, AI tools, ops

**Output (JSON only, no markdown wrapper, no extra text):**
{{
  "title": "SEO title 50–60 chars with keyword",
  "meta_description": "155-char meta with keyword and clear benefit",
  "content": "Full markdown post",
  "category": "Lead Generation | Sales & Retention | Business Strategy | Automation"
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
