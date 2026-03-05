"""
IKSHAN GROWTH — Blog Writer Service
Runs on APScheduler: keywords every Monday 9am IST, post every day 10am IST.
Stores posts in Supabase, sends Telegram notification.
"""

import json
import math
import os
import re
import time
import logging
from datetime import datetime, timezone

import httpx
from supabase import create_client
from slugify import slugify

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Load G2 tool data ─────────────────────────────────────────────
_G2_DATA: dict = {}
try:
    _data_path = os.path.join(os.path.dirname(__file__), "..", "data", "g2_tools.json")
    with open(os.path.normpath(_data_path)) as f:
        _G2_DATA = json.load(f)
    logger.info(f"Loaded G2 data: {len(_G2_DATA)} personas")
except Exception as e:
    logger.warning(f"Could not load G2 data: {e}")


def _get_g2_context(keyword: str) -> str:
    """Find relevant G2 tools for a keyword to inject into blog prompt."""
    kw = keyword.lower()
    persona_map = {
        "sales": ["Sales Execution & Enablement", "Lead Management & Conversion"],
        "lead": ["B2B Lead Generation", "Sales Execution & Enablement"],
        "marketing": ["Marketing & Sales Automation", "Content & Social Media"],
        "seo": ["Marketing & Sales Automation", "Business Intelligence & Analytics"],
        "content": ["Content & Social Media", "Marketing & Sales Automation"],
        "analytics": ["Business Intelligence & Analytics", "Marketing & Sales Automation"],
        "finance": ["Finance Legal & Admin", "Financial Health & Risk"],
        "crm": ["Lead Management & Conversion", "Sales Execution & Enablement"],
        "automation": ["Marketing & Sales Automation", "Org Efficiency & Hiring"],
        "hiring": ["Org Efficiency & Hiring", "Recruiting & HR Ops"],
        "hr": ["Recruiting & HR Ops", "Org Efficiency & Hiring"],
        "productivity": ["Personal & Team Productivity", "Org Efficiency & Hiring"],
        "team": ["Personal & Team Productivity", "Org Efficiency & Hiring"],
        "customer": ["Customer Success & Reputation", "Customer Support Ops"],
        "support": ["Customer Support Ops", "Customer Success & Reputation"],
        "competitor": ["Market Strategy & Innovation", "Business Intelligence & Analytics"],
        "design": ["Content & Social Media"],
        "ai tool": ["Marketing & Sales Automation", "Personal & Team Productivity"],
        "startup": ["Marketing & Sales Automation", "Business Intelligence & Analytics"],
    }
    matched_personas = []
    for signal, personas in persona_map.items():
        if signal in kw:
            matched_personas.extend(personas)
    matched_personas = list(dict.fromkeys(matched_personas))[:2]

    tools_text = []
    for persona in matched_personas:
        tools = _G2_DATA.get(persona, [])[:3]
        if tools:
            tools_text.append(f"\n**Top tools for {persona} (G2 verified):**")
            for t in tools:
                pros = " | ".join(t["pros"][:2]) if t["pros"] else ""
                cons = t["cons"][0] if t["cons"] else ""
                tools_text.append(
                    f"- **{t['name']}** — Rating: {t['rating']}/5 ({t['reviews']} reviews)\n"
                    f"  {t['description'][:150]}\n"
                    f"  Pros: {pros}\n"
                    f"  Con: {cons}"
                )
    return "\n".join(tools_text)


# ── Seed topics ───────────────────────────────────────────────────
# 4 Growth Buckets + AI/Startup/Design/Team verticals

SEED_TOPICS = [
    # ── LEAD GENERATION ───────────────────────────────────────────
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
    "best B2B lead generation tools for small business 2026",
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
    "best CRM tools for small business teams 2026",
    "call tracking and conversation intelligence tools",
    "best sales enablement tools for small teams",

    # ── BUSINESS STRATEGY ─────────────────────────────────────────
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
    "best business analytics tools for founders 2026",
    "how to build SOPs for small business",
    "financial health dashboard for business owners",
    "budget vs actual analysis small business",
    "best competitive intelligence tools for startups",

    # ── SAVE TIME & AUTOMATION ────────────────────────────────────
    "how to automate lead capture into CRM",
    "invoice data extraction software small business",
    "how to summarize meetings automatically AI",
    "customer support automation tools small business",
    "email automation sequences small business",
    "how to automate social media posting",
    "expense tracking automation small business",
    "best resume screening tools for small business",
    "how to automate invoice and payment reminders",
    "contract review automation small business",
    "best workflow automation tools for 5 person team",
    "WhatsApp auto reply business automation",
    "support ticket routing automation",
    "how to automate employee onboarding",
    "content calendar automation tools small business",
    "AI tools to save time for small business owners",

    # ── AI FOR BUSINESS ───────────────────────────────────────────
    "best AI tools for small business revenue growth 2026",
    "how to use AI for sales forecasting small business",
    "AI meeting notes tools for small teams",
    "best AI writing tools for business content 2026",
    "how AI can replace manual data entry small business",
    "ChatGPT use cases for small business owners",
    "AI customer support chatbot for small business",
    "best AI analytics tools for startup founders",
    "how to use AI for competitive research startup",
    "AI tools that save 10 hours per week small business",

    # ── STARTUP & FUNDING ─────────────────────────────────────────
    "how to validate a startup idea before building",
    "best tools for early stage startup growth",
    "how to get first 100 customers startup",
    "startup pitch deck mistakes to avoid",
    "how to find angel investors for startup India",
    "product market fit checklist startup founders",
    "best productivity tools for startup teams 2026",
    "how to grow revenue from 0 to 10 lakh startup",
    "startup financial model basics for founders",
    "best free tools for bootstrapped startups",

    # ── AI FOR DESIGNERS & CREATIVE TEAMS ────────────────────────
    "best AI design tools for small teams 2026",
    "how to use AI for social media graphics small business",
    "AI video creation tools for marketing teams",
    "best tools for content creation team of 5 people",
    "how to create content 10x faster with AI",
    "best screen recording tools for remote teams",
    "design collaboration tools for small teams",

    # ── TEAM COLLABORATION & PRODUCTIVITY ────────────────────────
    "best project management tools for 5 person team",
    "how a 5 member team can work like a 50 person company",
    "best team productivity tools for startups 2026",
    "how to build async workflows small remote team",
    "best tools for team collaboration in India startups",
    "how to run daily standups remote team small business",
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
        "source": "tavily",
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


def _write_post_with_claude(keyword: str, context: str, g2_context: str = "") -> dict:
    s = get_settings()
    is_tool_comparison = any(w in keyword.lower() for w in ["best", "top", "tools", "software", "platforms"])
    tool_section = f"""
**Real Tool Data (G2-verified — use these in your comparison):**
{g2_context}

""" if g2_context and is_tool_comparison else ""

    comparison_instructions = """
- If the post is about "best tools" or "top tools": include a **comparison table** with columns: Tool | Best For | Rating | Free Plan? | Key Feature
- Use real tool names, real ratings, real pros/cons from the data provided
""" if is_tool_comparison else ""

    prompt = f"""You are an expert SEO content writer for ikshan.in — an AI-powered growth analytics platform for small and mid-sized businesses (SMBs) and startups.

**What Ikshan does:** Ikshan diagnoses WHY a business isn't growing. It scrapes your website, analyzes your context, and gives you a Root Cause Analysis of your biggest growth leaks — across:
1. Lead Generation (SEO, social media, ads, B2B outreach)
2. Sales & Retention (conversion, churn, upsell, reviews)
3. Business Strategy (analytics, market research, cash flow, hiring)
4. Automation (invoices, support, HR, emails, meetings — save 10+ hours/week)

Write a complete, SEO-optimized blog post for the following keyword:

**Focus Keyword:** {keyword}

**Competitor Research (write something BETTER and more useful than these):**
{context}
{tool_section}
**Writing Rules:**
- Word count: 1800–2200 words minimum
- Tone: practical, direct, founder-friendly — like a knowledgeable friend who runs a business
- No buzzword fluff — every sentence must save the reader time or money
- Focus keyword in: H1, first 100 words, at least 2 H2s, meta description
- 2 natural mentions of Ikshan.in as a tool that diagnoses growth problems
- India-relevant examples where applicable (Indian SMBs, rupees ₹, local context)
- End with a clear CTA to try ikshan.in for free
{comparison_instructions}
**Mandatory Structure:**

1. **H1** — includes keyword, punchy, max 65 chars
2. **Intro** — 120–150 words: open with a sharp pain point + stat, state the keyword problem, tell reader exactly what they'll learn
3. **Key Takeaways box** (use this exact markdown):
   > **Key Takeaways**
   > - [actionable insight 1]
   > - [actionable insight 2]
   > - [actionable insight 3]
   > - [actionable insight 4]
   > - [actionable insight 5]
4. **## Table of Contents** — bullet list of all H2 links (use anchor format: [Section Name](#section-name))
5. **Main body** — 5 to 7 H2 sections, each with:
   - H3 sub-sections where needed
   - Numbered steps or bullet lists
   - **Bold** key terms and tool names
   - At least 1 real stat or data point per H2
   - For "best tools" topics: include a markdown comparison table (| Tool | Best For | Rating | Free Plan | Standout Feature |)
6. **## Quick Comparison** (only for "best tools" posts) — a summary table of all tools covered
7. **## Frequently Asked Questions** — 5 Q&As:
   ### Q: [question readers actually Google]
   **A:** [2–3 sentence answer, includes keyword naturally]
8. **## Conclusion** — 100 words: top insight + CTA to try ikshan.in free

**Pick the most relevant category:**
- "Lead Generation" — SEO, ads, social media, B2B outreach, content marketing
- "Sales & Retention" — conversion, churn, reviews, upsell, CRM, sales tools
- "Business Strategy" — analytics, dashboards, market research, finance, hiring, startup advice
- "Automation" — saving time, workflow automation, AI tools, ops, team productivity

**Output (JSON only, no markdown wrapper, no extra text):**
{{
  "title": "SEO title 50–65 chars with keyword",
  "meta_description": "155-char meta with keyword and clear reader benefit",
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
    g2_context = _get_g2_context(keyword)
    cover = _get_cover_image(keyword)
    post_data = _write_post_with_claude(keyword, context, g2_context)

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

    # Handle duplicate slug by appending a short suffix
    base_slug = post["slug"]
    for attempt in range(5):
        if attempt > 0:
            post["slug"] = f"{base_slug}-{attempt}"
        try:
            result = db.table("posts").insert(post).execute()
            break
        except Exception as e:
            if "posts_slug_key" in str(e) and attempt < 4:
                logger.warning(f"Slug '{post['slug']}' exists, retrying with suffix")
                continue
            logger.error(f"Failed to save post: {e}")
            db.table("keywords").update({"status": "used"}).eq("id", kw_record["id"]).execute()
            return
    if not result.data:
        logger.error("Failed to save post to Supabase")
        return

    db.table("keywords").update({"status": "used"}).eq("id", kw_record["id"]).execute()

    logger.info(f"✓ Published: {post['title']} | /blog/{post['slug']} | ~{words} words")
    _notify_telegram(post)
    return post
