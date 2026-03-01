"""WordPress REST API 자동 발행 모듈.

WP Application Password + Basic Auth로 포스트를 발행한다.
"""

import base64
import logging
import re

import httpx

from app.core.config import get_settings
from app.core.models import BriefingType

logger = logging.getLogger(__name__)

# BriefingType → WordPress category slug 매핑
CATEGORY_SLUG_MAP: dict[str, str] = {
    BriefingType.NASDAQ: "us-stocks",
    BriefingType.NEWS_DIVE: "daily-news",
    BriefingType.ISSUE_DIVE: "deep-dive",
    BriefingType.KOSPI: "kr-stocks",
    BriefingType.REAL_ESTATE: "real-estate",
}


def _slugify(title: str) -> str:
    """제목에서 ASCII-safe 파일명을 생성한다."""
    from urllib.parse import quote
    slug = re.sub(r"[^\w가-힣]", "-", title)
    slug = re.sub(r"-+", "-", slug).strip("-")
    slug = slug[:80] if slug else "og-image"
    return quote(slug, safe="-_")


async def _upload_media(
    client: httpx.AsyncClient,
    image_bytes: bytes,
    filename: str,
    alt_text: str = "",
) -> tuple[int, str] | None:
    """WordPress에 이미지를 업로드하고 (media_id, source_url)을 반환한다."""
    content_type = "image/jpeg" if filename.endswith((".jpg", ".jpeg")) else "image/png"
    resp = await client.post(
        f"{get_settings().wp_url}/wp-json/wp/v2/media",
        content=image_bytes,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
    if resp.status_code == 201:
        media = resp.json()
        media_id = media["id"]
        source_url = media.get("source_url", "")
        logger.info("WordPress 미디어 업로드 완료: id=%d, file=%s", media_id, filename)

        # alt 텍스트 설정 (SEO 점수에 기여)
        if alt_text:
            await client.post(
                f"{get_settings().wp_url}/wp-json/wp/v2/media/{media_id}",
                json={"alt_text": alt_text},
            )

        return media_id, source_url

    logger.error(
        "WordPress 미디어 업로드 실패: status=%s, body=%s",
        resp.status_code,
        resp.text[:300],
    )
    return None


async def _resolve_category_id(client: httpx.AsyncClient, slug: str) -> int | None:
    """카테고리 slug → ID를 조회한다."""
    resp = await client.get(
        f"{get_settings().wp_url}/wp-json/wp/v2/categories",
        params={"slug": slug},
    )
    if resp.status_code == 200:
        cats = resp.json()
        if cats:
            return cats[0]["id"]
    logger.warning("WordPress 카테고리 조회 실패: slug=%s, status=%s", slug, resp.status_code)
    return None


async def _resolve_tag_ids(client: httpx.AsyncClient, tags: list[str]) -> list[int]:
    """태그 이름 → WordPress 태그 ID 리스트. 없으면 새로 생성한다."""
    tag_ids = []
    for name in tags:
        # GET 검색
        resp = await client.get(
            f"{get_settings().wp_url}/wp-json/wp/v2/tags",
            params={"search": name, "per_page": 5},
        )
        if resp.status_code == 200:
            results = resp.json()
            # 정확히 일치하는 태그 찾기
            matched = [t for t in results if t["name"] == name]
            if matched:
                tag_ids.append(matched[0]["id"])
                continue

        # POST 생성
        resp = await client.post(
            f"{get_settings().wp_url}/wp-json/wp/v2/tags",
            json={"name": name},
        )
        if resp.status_code == 201:
            tag_ids.append(resp.json()["id"])
        else:
            logger.warning("WordPress 태그 생성 실패: name=%s, status=%s", name, resp.status_code)
    return tag_ids


async def _update_rankmath_meta(
    client: httpx.AsyncClient,
    post_id: int,
    *,
    focus_keyword: str = "",
    seo_title: str = "",
    description: str = "",
    og_image_url: str = "",
    category_id: int | None = None,
) -> None:
    """Rank Math SEO 메타데이터를 WordPress REST API로 직접 설정한다.

    functions.php에 register_post_meta()로 rank_math_* 필드를
    show_in_rest=true 등록이 필요하다.
    """
    meta: dict[str, str] = {}

    # 기본 SEO
    if focus_keyword:
        meta["rank_math_focus_keyword"] = focus_keyword
    if seo_title:
        meta["rank_math_title"] = seo_title
    if description:
        meta["rank_math_description"] = description

    # Open Graph (Facebook)
    meta["rank_math_facebook_title"] = seo_title or focus_keyword
    if description:
        meta["rank_math_facebook_description"] = description
    if og_image_url:
        meta["rank_math_facebook_image"] = og_image_url

    # Twitter: Facebook 설정 재활용
    meta["rank_math_twitter_use_facebook"] = "on"
    meta["rank_math_twitter_card_type"] = "summary_large_image"

    # 카테고리
    if category_id:
        meta["rank_math_primary_category"] = str(category_id)

    if not meta:
        return

    try:
        resp = await client.post(
            f"{get_settings().wp_url}/wp-json/wp/v2/posts/{post_id}",
            json={"meta": meta},
        )
        if resp.status_code == 200:
            logger.info("Rank Math SEO 메타 업데이트 완료: post_id=%d, keyword=%s", post_id, focus_keyword)
        else:
            logger.warning("Rank Math 업데이트 실패: status=%s, body=%s", resp.status_code, resp.text[:200])
    except httpx.HTTPError as e:
        logger.warning("Rank Math 요청 실패: %s", e)


async def publish_to_wordpress(
    title: str,
    html: str,
    briefing_type: str,
    status: str = "publish",
    slug: str = "",
    excerpt: str = "",
    tags: list[str] | None = None,
    og_image: bytes | None = None,
    focus_keyword: str = "",
    seo_description: str = "",
    unsplash_image: tuple[bytes, str, str] | None = None,
) -> tuple[int, str] | None:
    """WordPress에 포스트를 발행하고 (post_id, post_link)를 반환한다.

    wp_url이 설정되어 있지 않으면 건너뛴다 (개발 환경 등).
    실패 시 None을 반환하되 파이프라인은 중단하지 않는다.
    """
    if not get_settings().wp_url or not get_settings().wp_user or not get_settings().wp_app_password:
        logger.info("WordPress 설정 미완료 — 발행 건너뜀")
        return None

    # Basic Auth 헤더 구성
    credentials = f"{get_settings().wp_user}:{get_settings().wp_app_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            # 카테고리 매핑
            category_ids = []
            cat_slug = CATEGORY_SLUG_MAP.get(briefing_type)
            if cat_slug:
                cat_id = await _resolve_category_id(client, cat_slug)
                if cat_id:
                    category_ids.append(cat_id)

            # 태그 ID 변환
            tag_ids = []
            if tags:
                tag_ids = await _resolve_tag_ids(client, tags)

            # OG 이미지 업로드 → featured_media
            featured_media_id = None
            og_image_url = ""
            if og_image:
                filename = f"{_slugify(title)}-og.png"
                upload_result = await _upload_media(
                    client, og_image, filename,
                    alt_text=focus_keyword or title,
                )
                if upload_result:
                    featured_media_id, og_image_url = upload_result

            # Unsplash 이미지 업로드 → 본문 상단에 삽입
            content_html = html
            if unsplash_image:
                img_bytes, _img_url, photographer = unsplash_image
                unsplash_filename = f"{_slugify(title)}-unsplash.jpg"
                unsplash_upload = await _upload_media(
                    client, img_bytes, unsplash_filename,
                    alt_text=focus_keyword or title,
                )
                if unsplash_upload:
                    _, unsplash_src = unsplash_upload
                    alt = focus_keyword or title
                    content_html = (
                        f'<figure style="margin:0 0 1.5rem;">'
                        f'<img src="{unsplash_src}" alt="{alt}" '
                        f'style="width:100%;height:auto;border-radius:12px;" />'
                        f'<figcaption style="font-size:0.75rem;color:#8B95A1;text-align:center;margin-top:0.5rem;">'
                        f'Photo by {photographer} / Unsplash</figcaption>'
                        f'</figure>\n'
                        + content_html
                    )

            payload = {
                "title": title,
                "content": content_html,
                "status": status,
                "categories": category_ids,
            }
            if featured_media_id:
                payload["featured_media"] = featured_media_id
            if slug:
                payload["slug"] = slug
            if excerpt:
                payload["excerpt"] = excerpt
            if tag_ids:
                payload["tags"] = tag_ids

            resp = await client.post(
                f"{get_settings().wp_url}/wp-json/wp/v2/posts",
                json=payload,
            )

            if resp.status_code == 201:
                post = resp.json()
                post_id = post["id"]
                post_link = post.get("link", "")
                logger.info("WordPress 발행 완료: id=%d, url=%s", post_id, post_link)

                # Rank Math SEO 메타 업데이트
                await _update_rankmath_meta(
                    client,
                    post_id,
                    focus_keyword=focus_keyword,
                    seo_title=title,
                    description=seo_description or excerpt,
                    og_image_url=og_image_url,
                    category_id=category_ids[0] if category_ids else None,
                )

                # Google Indexing API 자동 요청
                if post_link:
                    from app.publishing.google_indexing import request_indexing
                    await request_indexing(post_link)

                return post_id, post_link

            logger.error(
                "WordPress 발행 실패: status=%s, body=%s",
                resp.status_code,
                resp.text[:300],
            )
            return None

    except httpx.HTTPError as e:
        logger.error("WordPress 요청 실패: %s", e)
        return None
