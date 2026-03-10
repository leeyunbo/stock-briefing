"""WP 기존 글 중복 검사 — ChromaDB + Gemini 임베딩 재사용.

기존 dedup.py의 NewsDedup 패턴을 SEO 콘텐츠용 별도 컬렉션으로 활용한다.
"""

import logging
import uuid

import chromadb
import httpx

from app.collector.dedup import CHROMA_DIR, GeminiEmbeddingFunction
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "seo_content_dedup"


def _get_collection():
    """SEO 중복 검사용 ChromaDB 컬렉션을 반환한다."""
    embed_fn = GeminiEmbeddingFunction()
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )


def check_content_duplicate(title: str, keyword: str) -> bool:
    """제목+키워드로 기존 콘텐츠와 중복 여부를 검사한다.

    코사인 유사도가 임계값(seo_dedup_threshold) 이상이면 중복으로 판정.

    Returns:
        True면 중복.
    """
    query_text = f"{title} {keyword}"
    threshold = get_settings().seo_dedup_threshold
    distance_threshold = 1.0 - threshold

    collection = _get_collection()
    if collection.count() == 0:
        return False

    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=1,
        )
    except chromadb.errors.InternalError as e:
        if "Nothing found on disk" in str(e):
            logger.warning("SEO dedup HNSW 인덱스 깨짐 — 중복 아님으로 처리")
            return False
        raise

    distances = results.get("distances", [[]])[0]
    if distances and distances[0] < distance_threshold:
        matched_doc = (results.get("documents", [[]])[0] or [""])[0]
        logger.info(
            "SEO 중복 감지 (distance=%.4f): query='%s', matched='%s'",
            distances[0], query_text[:60], matched_doc[:60],
        )
        return True

    return False


def register_published_content(title: str, keyword: str) -> None:
    """발행된 콘텐츠를 dedup DB에 등록한다."""
    doc_text = f"{title} {keyword}"
    collection = _get_collection()
    collection.add(
        ids=[uuid.uuid4().hex],
        documents=[doc_text],
        metadatas=[{"title": title[:200], "keyword": keyword[:100]}],
    )
    logger.info("SEO dedup 등록: %s", doc_text[:80])


async def fetch_all_wp_posts() -> list[dict]:
    """WordPress REST API로 전체 발행 글을 조회한다.

    Returns:
        [{"id", "title", "link"}]
    """
    settings = get_settings()
    if not settings.wp_url:
        return []

    import base64
    credentials = f"{settings.wp_user}:{settings.wp_app_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    all_posts: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        while True:
            resp = await client.get(
                f"{settings.wp_url}/wp-json/wp/v2/posts",
                params={"per_page": 100, "page": page, "status": "publish"},
            )
            if resp.status_code != 200:
                break
            posts = resp.json()
            if not posts:
                break
            for p in posts:
                all_posts.append({
                    "id": p["id"],
                    "title": p.get("title", {}).get("rendered", ""),
                    "link": p.get("link", ""),
                })
            page += 1

    logger.info("WP 전체 글 조회: %d건", len(all_posts))
    return all_posts


async def seed_wp_content_to_dedup() -> int:
    """기존 WP 글을 dedup DB에 일괄 등록한다 (최초 1회).

    Returns:
        등록된 건수.
    """
    posts = await fetch_all_wp_posts()
    if not posts:
        return 0

    collection = _get_collection()
    existing_count = collection.count()

    registered = 0
    for post in posts:
        title = post["title"]
        if not title.strip():
            continue
        collection.add(
            ids=[uuid.uuid4().hex],
            documents=[title],
            metadatas=[{"wp_post_id": str(post["id"]), "title": title[:200]}],
        )
        registered += 1

    logger.info("WP 기존 글 dedup 등록: %d건 (기존 %d건)", registered, existing_count)
    return registered
