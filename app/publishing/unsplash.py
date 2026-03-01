"""Unsplash API로 키워드 기반 이미지를 가져온다."""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

UNSPLASH_API = "https://api.unsplash.com"


async def fetch_unsplash_image(
    keyword: str,
    orientation: str = "landscape",
) -> tuple[bytes, str, str] | None:
    """키워드로 Unsplash 사진을 검색하고 (image_bytes, download_url, photographer) 반환.

    실패 시 None을 반환한다.
    """
    access_key = get_settings().unsplash_access_key
    if not access_key:
        logger.info("Unsplash 액세스 키 미설정 — 이미지 검색 건너뜀")
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 사진 검색
            resp = await client.get(
                f"{UNSPLASH_API}/search/photos",
                params={
                    "query": keyword,
                    "per_page": 1,
                    "orientation": orientation,
                },
                headers={"Authorization": f"Client-ID {access_key}"},
            )

            if resp.status_code != 200:
                logger.warning("Unsplash 검색 실패: status=%s", resp.status_code)
                return None

            results = resp.json().get("results", [])
            if not results:
                logger.warning("Unsplash 검색 결과 없음: keyword=%s", keyword)
                return None

            photo = results[0]
            image_url = photo["urls"]["regular"]  # 1080px
            photographer = photo["user"]["name"]
            download_location = photo.get("links", {}).get("download_location", "")

            # Unsplash 가이드라인: download 트리거
            if download_location:
                await client.get(
                    download_location,
                    headers={"Authorization": f"Client-ID {access_key}"},
                )

            # 이미지 다운로드
            img_resp = await client.get(image_url)
            if img_resp.status_code != 200:
                logger.warning("Unsplash 이미지 다운로드 실패: status=%s", img_resp.status_code)
                return None

            logger.info("Unsplash 이미지 가져옴: keyword=%s, photographer=%s", keyword, photographer)
            return img_resp.content, image_url, photographer

    except httpx.HTTPError as e:
        logger.warning("Unsplash 요청 실패: %s", e)
        return None
