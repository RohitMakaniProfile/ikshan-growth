"""
IKSHAN GROWTH — Reddit Monitor Service
Finds relevant questions on Reddit every 6 hours.
Drafts answers with Claude, sends to Telegram for human review.
NO auto-posting — human posts manually (avoids ban).
"""

import json
import logging
import re
from datetime import datetime, timezone

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Subreddits to monitor
SUBREDDITS = [
    "smallbusiness",
    "entrepreneur",
    "startups",
    "IndianStartups",
    "india",
    "digitalnomad",
    "marketing",
    "SEO",
]

# Keywords that indicate a relevant question
TRIGGER_KEYWORDS = [
    "how to get more leads", "lead generation", "get more customers",
    "seo help", "seo tips", "rank on google", "website traffic",
    "crm recommendation", "best crm", "crm for small",
    "analytics dashboard", "track marketing", "marketing roi",
    "sales automation", "automate leads", "follow up automation",
    "whatsapp business", "whatsapp marketing",
    "email marketing", "email automation",
    "customer churn", "retain customers", "reduce churn",
    "invoice automation", "automate invoice", "expense tracking",
    "hire faster", "recruitment automation",
    "cash flow", "profit margin", "business analytics",
    "competitor research", "track competitors",
    "how to grow my business", "grow sales", "increase revenue",
    "small business tools", "smb software",
]

# Posts already answered (in-memory, resets on restart — fine for now)
_seen_post_ids: set[str] = set()


def _is_relevant(title: str, selftext: str) -> bool:
    text = (title + " " + selftext).lower()
    return any(kw in text for kw in TRIGGER_KEYWORDS)


def _fetch_subreddit_posts(subreddit: str) -> list[dict]:
    try:
        r = httpx.get(
            f"https://www.reddit.com/r/{subreddit}/new.json",
            params={"limit": 25},
            headers={"User-Agent": "ikshan-growth-monitor/1.0"},
            timeout=15,
            follow_redirects=True,
        )
        if not r.is_success:
            return []
        data = r.json()
        posts = data.get("data", {}).get("children", [])
        return [p["data"] for p in posts]
    except Exception as e:
        logger.warning(f"Reddit fetch error ({subreddit}): {e}")
        return []


def _draft_answer(post_title: str, post_body: str, subreddit: str) -> str:
    s = get_settings()
    prompt = f"""You are a helpful growth expert commenting on Reddit. You help small business owners with practical, actionable advice.

A Reddit user in r/{subreddit} asked:

**Title:** {post_title}

**Details:** {post_body[:800] if post_body else "(no details provided)"}

Write a helpful Reddit comment (NOT promotional, NOT spammy):
- 150–250 words
- Genuine, practical advice first — answer their actual question
- Natural, conversational Reddit tone (no corporate language)
- At the end, you MAY mention ikshan.in ONLY IF it directly solves their problem, in 1 sentence max
- If ikshan.in is not relevant, don't mention it at all
- No bullet point lists — write in paragraphs like a real Redditor

Output just the comment text, nothing else."""

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
                "max_tokens": 500,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Claude draft error: {e}")
        return "(Could not generate draft)"


def _send_telegram_alert(post: dict, draft: str):
    s = get_settings()
    title = post.get("title", "")[:80]
    url = f"https://reddit.com{post.get('permalink', '')}"
    subreddit = post.get("subreddit", "")
    score = post.get("score", 0)
    comments = post.get("num_comments", 0)

    msg = (
        f"🔔 *Reddit Opportunity Found*\n\n"
        f"*r/{subreddit}* · ⬆️ {score} · 💬 {comments} comments\n\n"
        f"*Q:* {title}\n\n"
        f"─────────────────\n"
        f"*Draft Answer (review before posting):*\n\n"
        f"{draft}\n\n"
        f"─────────────────\n"
        f"🔗 [Open on Reddit]({url})"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "📖 Open Reddit Post", "url": url},
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
        logger.info(f"Telegram alert sent for: {title[:50]}")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def run_reddit_monitor():
    """
    Scan Reddit for relevant SMB questions.
    Draft answers with Claude. Send to Telegram for human review.
    Runs every 6 hours via APScheduler.
    """
    logger.info("=== REDDIT MONITOR STARTED ===")
    found = 0

    for subreddit in SUBREDDITS:
        posts = _fetch_subreddit_posts(subreddit)
        for post in posts:
            post_id = post.get("id", "")
            if post_id in _seen_post_ids:
                continue
            if post.get("is_self") is False:  # skip link posts
                continue

            title = post.get("title", "")
            body = post.get("selftext", "")

            if not _is_relevant(title, body):
                continue

            # Skip posts older than 24 hours
            created = post.get("created_utc", 0)
            age_hours = (datetime.now(timezone.utc).timestamp() - created) / 3600
            if age_hours > 24:
                continue

            _seen_post_ids.add(post_id)

            logger.info(f"Found relevant post: r/{subreddit} — {title[:60]}")
            draft = _draft_answer(title, body, subreddit)
            _send_telegram_alert(post, draft)
            found += 1

            # Max 3 alerts per run to avoid Telegram spam
            if found >= 3:
                break
        if found >= 3:
            break

    logger.info(f"=== REDDIT MONITOR DONE: {found} opportunities found ===")
    return found
