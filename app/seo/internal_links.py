"""내부 링크 자동 삽입 — ChromaDB 시맨틱 검색 기반.

새 글 발행 시 양방향 내부 링크를 자동으로 삽입한다.
"""

import base64
import logging

import chromadb
import httpx

from app.collector.dedup import CHROMA_DIR, GeminiEmbeddingFunction
from app.core.config import get_settings
from app.core.database import async_session
from app.core.models import ContentCluster

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "seo_internal_links"
_RELATED_SECTION_MARKER = "<!-- related-posts -->"
_MAX_RELATED = 3


def _get_collection():
    """내부 링크 추적용 ChromaDB 컬렉션."""
    embed_fn = GeminiEmbeddingFunction()
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )


def _get_wp_client() -> tuple[httpx.AsyncClient, str] | None:
    """인증된 WP HTTP 클라이언트를 반환한다."""
    settings = get_settings()
    if not settings.wp_url or not settings.wp_user or not settings.wp_app_password:
        return None
    credentials = f"{settings.wp_user}:{settings.wp_app_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {"Authorization": f"Basic {token}"}
    return httpx.AsyncClient(timeout=30, headers=headers), settings.wp_url


async def find_related_posts(
    focus_keyword: str,
    exclude_post_id: int | None = None,
    max_results: int = _MAX_RELATED,
) -> list[dict]:
    """ChromaDB 시맨틱 검색으로 관련 포스트를 찾는다.

    Returns:
        [{"wp_post_id", "url", "title"}]
    """
    collection = _get_collection()
    if collection.count() == 0:
        return []

    n = max_results + (1 if exclude_post_id else 0)
    try:
        results = collection.query(
            query_texts=[focus_keyword],
            n_results=min(n, collection.count()),
        )
    except chromadb.errors.InternalError:
        logger.warning("내부 링크 ChromaDB 쿼리 실패")
        return []

    related = []
    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc_id, meta, dist in zip(ids, metadatas, distances):
        post_id = int(meta.get("wp_post_id", 0))
        if exclude_post_id and post_id == exclude_post_id:
            continue
        if dist > 0.5:  # 너무 먼 것은 제외
            continue
        related.append({
            "wp_post_id": post_id,
            "url": meta.get("url", ""),
            "title": meta.get("title", ""),
        })
        if len(related) >= max_results:
            break

    return related


def _build_related_html(links: list[dict]) -> str:
    """'함께 읽으면 좋은 글' 섹션 HTML을 생성한다."""
    if not links:
        return ""

    items = "\n".join(
        f'<li><a href="{link["url"]}">{link["title"]}</a></li>'
        for link in links
    )
    return (
        f'\n{_RELATED_SECTION_MARKER}\n'
        f'<h2>함께 읽으면 좋은 글</h2>\n'
        f'<ul>\n{items}\n</ul>\n'
    )


async def insert_internal_links_to_post(post_id: int, links: list[dict]) -> bool:
    """WP REST API로 포스트 본문 끝에 관련 글 섹션을 추가한다."""
    wp_info = _get_wp_client()
    if not wp_info or not links:
        return False

    client, wp_url = wp_info
    try:
        async with client:
            # 현재 포스트 내용 가져오기
            resp = await client.get(f"{wp_url}/wp-json/wp/v2/posts/{post_id}")
            if resp.status_code != 200:
                return False

            content = resp.json().get("content", {}).get("raw", "")
            if not content:
                content = resp.json().get("content", {}).get("rendered", "")

            # 이미 관련 글 섹션이 있으면 교체
            if _RELATED_SECTION_MARKER in content:
                marker_idx = content.index(_RELATED_SECTION_MARKER)
                content = content[:marker_idx].rstrip()

            related_html = _build_related_html(links)
            new_content = content + related_html

            # 포스트 업데이트
            resp = await client.post(
                f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
                json={"content": new_content},
            )
            if resp.status_code == 200:
                logger.info("내부 링크 삽입 완료: post_id=%d, links=%d", post_id, len(links))
                return True

            logger.warning("내부 링크 삽입 실패: post_id=%d, status=%s", post_id, resp.status_code)
            return False

    except httpx.HTTPError as e:
        logger.error("내부 링크 삽입 오류: %s", e)
        return False


async def process_internal_links_for_new_post(
    new_post_id: int, url: str, title: str, keyword: str,
) -> int:
    """양방향 내부 링크 처리.

    1. 새 글을 ChromaDB에 등록
    2. 새 글 → 기존 관련 글 링크 삽입
    3. 기존 관련 글 → 새 글 링크 추가

    Returns:
        삽입된 링크 수.
    """
    # 1. 새 글 등록
    collection = _get_collection()
    collection.add(
        ids=[str(new_post_id)],
        documents=[f"{title} {keyword}"],
        metadatas=[{
            "wp_post_id": str(new_post_id),
            "url": url,
            "title": title[:200],
            "keyword": keyword[:100],
        }],
    )

    # 2. 관련 포스트 찾기
    related = await find_related_posts(keyword, exclude_post_id=new_post_id)
    if not related:
        return 0

    total_links = 0

    # 3. 새 글에 관련 포스트 링크 삽입
    if await insert_internal_links_to_post(new_post_id, related):
        total_links += len(related)

    # 4. 기존 관련 글에 새 글 링크 추가 (역방향)
    new_link = {"wp_post_id": new_post_id, "url": url, "title": title}
    for rel in related:
        if await insert_internal_links_to_post(rel["wp_post_id"], [new_link]):
            total_links += 1

    logger.info("양방향 내부 링크 처리: new_post=%d, total_links=%d", new_post_id, total_links)
    return total_links


async def assign_to_cluster(wp_post_id: int, url: str, title: str, keyword: str) -> None:
    """콘텐츠 클러스터에 자동 배정한다.

    키워드 기반으로 가장 적합한 클러스터를 찾거나, 없으면 새로 생성한다.
    """
    async with async_session() as db:
        from sqlalchemy import select as sa_select

        # 기존 클러스터에서 키워드 매칭
        result = await db.execute(sa_select(ContentCluster))
        clusters = result.scalars().all()

        for cluster in clusters:
            # 키워드가 클러스터명에 포함되면 배정
            if cluster.cluster_name in keyword or keyword in cluster.cluster_name:
                # pillar_post가 없으면 이 글을 pillar로 설정
                if not cluster.pillar_post_id:
                    cluster.pillar_post_id = wp_post_id
                    cluster.pillar_url = url
                    await db.commit()
                logger.info("클러스터 배정: '%s' → '%s'", title[:40], cluster.cluster_name)
                return

        # 새 클러스터 생성 (키워드의 첫 단어 기반)
        cluster_name = keyword.split()[0] if keyword else title.split()[0]
        new_cluster = ContentCluster(
            cluster_name=cluster_name,
            pillar_post_id=wp_post_id,
            pillar_url=url,
        )
        db.add(new_cluster)
        await db.commit()
        logger.info("새 클러스터 생성: '%s' (pillar: %s)", cluster_name, title[:40])
