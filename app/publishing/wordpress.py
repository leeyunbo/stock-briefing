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
    BriefingType.STOCK_DEEP_DIVE: "stock-deep-dive",
    BriefingType.SEO_CONTENT: "money-deep-dive",
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
    faq_schema_json: str = "",
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

    # FAQ 스키마 (Rank Math가 프론트엔드에서 렌더링)
    if faq_schema_json:
        meta["rank_math_schema_FAQPage"] = faq_schema_json

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
    faq_schema_json: str = "",
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

            # OG 이미지 업로드 (Rank Math SEO용)
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

            # Unsplash 이미지 업로드 → 대표 이미지 + 본문 상단 삽입
            content_html = html
            if unsplash_image:
                img_bytes, _img_url, photographer = unsplash_image
                unsplash_filename = f"{_slugify(title)}-unsplash.jpg"
                unsplash_upload = await _upload_media(
                    client, img_bytes, unsplash_filename,
                    alt_text=focus_keyword or title,
                )
                if unsplash_upload:
                    unsplash_media_id, unsplash_src = unsplash_upload
                    # Unsplash 이미지를 대표 이미지 + OG 이미지로 설정
                    featured_media_id = unsplash_media_id
                    og_image_url = unsplash_src
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

            # WAF가 <script> 태그를 차단하므로 본문에서 제거
            clean_html = re.sub(
                r'<script[^>]*>.*?</script>', '', content_html, flags=re.DOTALL,
            )

            payload = {
                "title": title,
                "content": clean_html,
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
                    faq_schema_json=faq_schema_json,
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


async def fix_featured_images() -> dict:
    """기존 글의 featured_media를 본문 Unsplash 이미지로 교체한다.

    본문에 unsplash 이미지가 있고, featured_media가 OG 이미지(-og.png)인
    포스트를 찾아 일괄 수정한다.
    """
    if not get_settings().wp_url or not get_settings().wp_user or not get_settings().wp_app_password:
        return {"error": "WordPress 설정 미완료"}

    credentials = f"{get_settings().wp_user}:{get_settings().wp_app_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {"Authorization": f"Basic {token}"}

    fixed = []
    errors = []

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            # 전체 포스트 목록 (최대 100건)
            page = 1
            all_posts = []
            while True:
                resp = await client.get(
                    f"{get_settings().wp_url}/wp-json/wp/v2/posts",
                    params={"per_page": 100, "page": page, "status": "publish"},
                )
                if resp.status_code != 200:
                    break
                posts = resp.json()
                if not posts:
                    break
                all_posts.extend(posts)
                page += 1

            for post in all_posts:
                post_id = post["id"]
                content = post.get("content", {}).get("rendered", "")

                # 본문에서 Unsplash 이미지 URL 추출
                match = re.search(
                    r'<img[^>]+src="([^"]*-unsplash[^"]*)"', content
                )
                if not match:
                    continue

                unsplash_url = match.group(1)

                # 현재 featured_media 확인 — 이미 Unsplash면 스킵
                featured_id = post.get("featured_media", 0)
                if featured_id:
                    media_resp = await client.get(
                        f"{get_settings().wp_url}/wp-json/wp/v2/media/{featured_id}",
                    )
                    if media_resp.status_code == 200:
                        current_url = media_resp.json().get("source_url", "")
                        if "unsplash" in current_url:
                            continue  # 이미 Unsplash 이미지가 대표 이미지

                # Unsplash 이미지의 media ID 찾기
                # 파일명으로 미디어 검색
                filename = unsplash_url.rsplit("/", 1)[-1]
                search_resp = await client.get(
                    f"{get_settings().wp_url}/wp-json/wp/v2/media",
                    params={"search": filename.split(".")[0], "per_page": 5},
                )
                unsplash_media_id = None
                if search_resp.status_code == 200:
                    for media in search_resp.json():
                        if "unsplash" in media.get("source_url", ""):
                            unsplash_media_id = media["id"]
                            break

                if not unsplash_media_id:
                    errors.append({"post_id": post_id, "title": post["title"]["rendered"], "reason": "미디어 못 찾음"})
                    continue

                # featured_media 업데이트
                update_resp = await client.post(
                    f"{get_settings().wp_url}/wp-json/wp/v2/posts/{post_id}",
                    json={"featured_media": unsplash_media_id},
                )
                if update_resp.status_code == 200:
                    fixed.append({"post_id": post_id, "title": post["title"]["rendered"]})
                    logger.info("대표 이미지 교체: post_id=%d", post_id)
                else:
                    errors.append({"post_id": post_id, "title": post["title"]["rendered"], "reason": f"status {update_resp.status_code}"})

    except httpx.HTTPError as e:
        return {"error": str(e)}

    return {"fixed": len(fixed), "errors": len(errors), "details": fixed, "error_details": errors}
