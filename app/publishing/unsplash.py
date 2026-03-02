"""Unsplash API로 키워드 기반 이미지를 가져온다."""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

UNSPLASH_API = "https://api.unsplash.com"


async def fetch_unsplash_image(
    keyword: str | list[str],
    orientation: str = "landscape",
) -> tuple[bytes, str, str] | None:
    """키워드로 Unsplash 사진을 검색하고 (image_bytes, download_url, photographer) 반환.

    keyword가 리스트이면 순차적으로 검색하여 첫 번째 결과를 반환한다.
    실패 시 None을 반환한다.
    """
    access_key = get_settings().unsplash_access_key
    if not access_key:
        logger.info("Unsplash 액세스 키 미설정 — 이미지 검색 건너뜀")
        return None

    # 리스트가 아니면 리스트로 변환
    keywords = keyword if isinstance(keyword, list) else [keyword]
    keywords = [k for k in keywords if k]  # 빈 문자열 제거
    if not keywords:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            results = []
            tried = []

            for kw in keywords:
                resp = await client.get(
                    f"{UNSPLASH_API}/search/photos",
                    params={"query": kw, "per_page": 1, "orientation": orientation},
                    headers={"Authorization": f"Client-ID {access_key}"},
                )
                tried.append(kw)
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    if results:
                        logger.info("Unsplash 검색 성공: '%s' (시도: %s)", kw, tried)
                        break

            if not results:
                logger.warning("Unsplash 검색 결과 없음: keywords=%s", tried)
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
