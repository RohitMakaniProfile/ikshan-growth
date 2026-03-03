from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from supabase import create_client

from app.config import get_settings

router = APIRouter()


def _db():
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_KEY)


# ── Schemas ──────────────────────────────────────────────────────
class PostCreate(BaseModel):
    title: str
    slug: str
    content: str
    meta_description: str
    focus_keyword: str
    category: str = "Growth"
    reading_time: int = 5
    cover_image_url: Optional[str] = None
    status: str = "published"


class KeywordCreate(BaseModel):
    keyword: str
    relevance_score: float = 0
    difficulty_score: float = 0
    final_score: float = 0
    source: str = "trends"


# ── Posts ────────────────────────────────────────────────────────
@router.get("/posts")
async def list_posts(
    category: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    db = _db()
    query = (
        db.table("posts")
        .select("id,title,slug,meta_description,focus_keyword,category,reading_time,published_at,cover_image_url")
        .eq("status", "published")
        .order("published_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    if category:
        query = query.eq("category", category)
    result = query.execute()
    return result.data


@router.get("/posts/{slug}")
async def get_post(slug: str):
    db = _db()
    result = (
        db.table("posts")
        .select("*")
        .eq("slug", slug)
        .eq("status", "published")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Post not found")
    return result.data[0]


@router.post("/posts", status_code=201)
async def create_post(post: PostCreate):
    db = _db()
    payload = post.model_dump()
    now = datetime.now(timezone.utc).isoformat()
    payload["published_at"] = now
    payload["updated_at"] = now
    result = db.table("posts").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create post")
    return result.data[0]


# ── Keywords ─────────────────────────────────────────────────────
@router.get("/keywords")
async def list_keywords(status: str = Query("queued")):
    db = _db()
    result = (
        db.table("keywords")
        .select("*")
        .eq("status", status)
        .order("final_score", desc=True)
        .execute()
    )
    return result.data


@router.post("/keywords", status_code=201)
async def add_keywords(keywords: list[KeywordCreate]):
    db = _db()
    payload = [k.model_dump() for k in keywords]
    result = db.table("keywords").upsert(payload, on_conflict="keyword").execute()
    return {"inserted": len(result.data)}


@router.patch("/keywords/{keyword_id}/use")
async def mark_keyword_used(keyword_id: str):
    db = _db()
    db.table("keywords").update({"status": "used"}).eq("id", keyword_id).execute()
    return {"status": "marked used"}


# ── Sitemap ───────────────────────────────────────────────────────
@router.get("/sitemap.xml", response_class=Response)
async def sitemap():
    db = _db()
    result = db.table("posts").select("slug,updated_at").eq("status", "published").execute()
    base = "https://ikshan.in"
    urls = "\n".join([
        f"""  <url>
    <loc>{base}/blog/{p['slug']}</loc>
    <lastmod>{(p.get('updated_at') or '')[:10]}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>"""
        for p in result.data
    ])
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base}/blog</loc>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
{urls}
</urlset>"""
    return Response(content=xml, media_type="application/xml")
