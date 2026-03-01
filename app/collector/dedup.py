"""뉴스 시맨틱 중복 제거 — ChromaDB + Gemini 임베딩.

매일 실행되는 파이프라인에서 같은 사건을 다른 언론사가 보도한 경우,
link/title이 달라도 임베딩 유사도로 중복을 제거한다.

ChromaDB는 로컬 파일 기반(data/chroma/)으로 영속 저장되며,
Gemini gemini-embedding-001 임베딩을 사용한다.
"""

import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, TypeVar

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"


class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
    """Gemini gemini-embedding-001을 ChromaDB 임베딩 함수로 래핑."""

    def __call__(self, input: Documents) -> Embeddings:
        from google import genai

        client = genai.Client(api_key=get_settings().gemini_api_key)
        result = client.models.embed_content(
            model="gemini-embedding-001",
            contents=input,
        )
        return [e.values for e in result.embeddings]


class NewsDedup:
    """ChromaDB + Gemini 임베딩으로 뉴스 시맨틱 중복 제거."""

    def __init__(self, collection_name: str = "seen_news"):
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=GeminiEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )
        self.last_filtered: list[str] = []  # 마지막 filter_unseen에서 제거된 텍스트

    def filter_unseen(
        self,
        items: list[T],
        text_fn: Callable[[T], str],
        threshold: float | None = None,
    ) -> list[T]:
        """중복이 아닌 항목만 반환.

        1. 각 항목에서 text_fn으로 텍스트 추출
        2. ChromaDB query로 유사 기사 검색
        3. 유사도 >= threshold인 항목은 중복으로 판정
        4. 통과한 항목을 ChromaDB에 추가 (다음 실행 대비)

        Args:
            items: 필터링할 뉴스 항목 리스트
            text_fn: 각 항목에서 텍스트를 추출하는 함수
            threshold: 유사도 임계값 (0~1, 기본 get_settings().news_dedup_threshold)

        Returns:
            중복이 아닌 항목만 포함된 리스트
        """
        if not items:
            return items

        if threshold is None:
            threshold = get_settings().news_dedup_threshold

        # cosine distance threshold: similarity 0.92 → distance 0.08
        distance_threshold = 1.0 - threshold

        texts = [text_fn(item) for item in items]
        unseen: list[T] = []
        unseen_texts: list[str] = []
        unseen_ids: list[str] = []
        self.last_filtered = []

        # 빈 텍스트 분리
        non_empty_items: list[tuple[T, str]] = []
        for item, text in zip(items, texts):
            if not text.strip():
                unseen.append(item)
            else:
                non_empty_items.append((item, text))

        if not non_empty_items:
            return unseen

        # 컬렉션이 비어있으면 전체 통과
        if self._collection.count() == 0:
            for item, text in non_empty_items:
                unseen.append(item)
                unseen_texts.append(text)
                unseen_ids.append(uuid.uuid4().hex)
        else:
            # 배치 쿼리 — O(1) 호출로 전체 유사도 검색
            query_texts = [text for _, text in non_empty_items]
            results = self._collection.query(
                query_texts=query_texts,
                n_results=1,
            )
            all_distances = results.get("distances", [])

            for i, (item, text) in enumerate(non_empty_items):
                distances = all_distances[i] if i < len(all_distances) else []
                if distances and distances[0] < distance_threshold:
                    logger.info("중복 뉴스 필터링 (distance=%.4f): %s", distances[0], text[:80])
                    self.last_filtered.append(text[:100])
                    continue
                unseen.append(item)
                unseen_texts.append(text)
                unseen_ids.append(uuid.uuid4().hex)

        # 통과한 항목을 DB에 추가
        if unseen_texts:
            now = datetime.now().isoformat()
            self._collection.add(
                ids=unseen_ids,
                documents=unseen_texts,
                metadatas=[{"added_at": now} for _ in unseen_ids],
            )
            logger.info("ChromaDB에 %d건 추가 (총 %d건)", len(unseen_texts), self._collection.count())

        logger.info("뉴스 중복 제거: %d → %d건", len(items), len(unseen))
        return unseen

    def cleanup(self, days: int | None = None) -> int:
        """N일 이전 항목 삭제 (테이블 비대화 방지).

        Returns:
            삭제된 항목 수
        """
        if days is None:
            days = get_settings().news_dedup_ttl_days

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        total = self._collection.count()
        if total == 0:
            return 0

        # ChromaDB에서 전체 항목을 가져와서 오래된 것 찾기
        all_data = self._collection.get(include=["metadatas"])
        old_ids = []
        for doc_id, meta in zip(all_data["ids"], all_data["metadatas"]):
            added_at = meta.get("added_at", "")
            if added_at and added_at < cutoff:
                old_ids.append(doc_id)

        if old_ids:
            self._collection.delete(ids=old_ids)
            logger.info("ChromaDB cleanup: %d건 삭제 (cutoff=%s)", len(old_ids), cutoff)

        return len(old_ids)


def dedup_news(
    items: list[T],
    text_fn: Callable[[T], str],
    collection_name: str,
    *,
    threshold: float | None = None,
    run_id: str = "",
    pipeline: str = "",
) -> list[T]:
    """뉴스 중복 제거 + 트레이싱 — 조립 가능한 파이프라인 스텝.

    실패 시 원본을 그대로 반환한다 (파이프라인 중단 방지).
    """
    original_count = len(items)
    last_filtered: list[str] = []

    try:
        dedup = NewsDedup(collection_name=collection_name)
        items = dedup.filter_unseen(items, text_fn, threshold=threshold)
        last_filtered = dedup.last_filtered
    except Exception:
        logger.warning("뉴스 중복 제거 실패, 원본 사용", exc_info=True)

    filtered_count = original_count - len(items)
    filtered_detail = ""
    if filtered_count > 0 and last_filtered:
        filtered_detail = "\n제거: " + " | ".join(last_filtered)

    if run_id:
        from app.tracing import _save_trace_sync
        _save_trace_sync(
            run_id=run_id, pipeline=pipeline, stage="dedup",
            provider_name="chromadb", model_name="gemini-embedding-001",
            system_prompt="", user_prompt="",
            response=f"뉴스 {original_count}건 → {len(items)}건 (중복 {filtered_count}건 제거){filtered_detail}",
            latency_ms=0, input_tokens=None, output_tokens=None,
            success=True, error_message=None,
        )

    return items
