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


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도 계산."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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
        self._embed_fn = GeminiEmbeddingFunction()
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self.last_filtered: list[str] = []  # 마지막 filter_unseen에서 제거된 텍스트

    def _safe_query(self, query_texts: list[str], n_results: int = 1) -> dict | None:
        """ChromaDB 쿼리. HNSW 인덱스 깨진 경우 컬렉션 재생성."""
        try:
            return self._collection.query(
                query_texts=query_texts,
                n_results=n_results,
            )
        except chromadb.errors.InternalError as e:
            if "Nothing found on disk" in str(e):
                logger.warning("ChromaDB HNSW 인덱스 깨짐 — 컬렉션 재생성: %s", e)
                name = self._collection.name
                self._client.delete_collection(name)
                self._collection = self._client.get_or_create_collection(
                    name=name,
                    embedding_function=self._embed_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                return None
            raise

    def filter_unseen(
        self,
        items: list[T],
        text_fn: Callable[[T], str],
        threshold: float | None = None,
    ) -> list[T]:
        """중복이 아닌 항목만 반환.

        1. 각 항목에서 text_fn으로 텍스트 추출
        2. ChromaDB query로 기존 기사와 유사도 검색 (기간 간 중복 제거)
        3. 배치 내 유사 기사 제거 (같은 실행 내 중복 제거)
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

        distance_threshold = 1.0 - threshold
        self.last_filtered = []

        # 빈 텍스트 분리 (항상 통과, DB에 저장 안 함)
        empty_items: list[T] = []
        candidates: list[tuple[T, str]] = []
        for item, text in zip(items, [text_fn(i) for i in items]):
            if not text.strip():
                empty_items.append(item)
            else:
                candidates.append((item, text))

        if not candidates:
            return empty_items

        candidate_texts = [text for _, text in candidates]

        # Phase 1: 기존 DB와 비교 (기간 간 중복 제거)
        if self._collection.count() == 0:
            passing_indices = list(range(len(candidates)))
        else:
            results = self._safe_query(candidate_texts)
            if results is None:
                # DB 깨져서 재생성됨 — 전체 통과
                passing_indices = list(range(len(candidates)))
            else:
                all_distances = results.get("distances", [])
                passing_indices = []
                for i, (item, text) in enumerate(candidates):
                    distances = all_distances[i] if i < len(all_distances) else []
                    if distances and distances[0] < distance_threshold:
                        logger.info("중복 뉴스 필터링 (distance=%.4f): %s", distances[0], text[:80])
                        self.last_filtered.append(text[:100])
                    else:
                        passing_indices.append(i)

        # Phase 2: 배치 내 중복 제거 (같은 실행 내 유사 기사 제거)
        if len(passing_indices) > 1:
            try:
                passing_texts = [candidate_texts[i] for i in passing_indices]
                embeddings = self._embed_fn(passing_texts)

                final_passing: list[int] = []
                for idx, i in enumerate(passing_indices):
                    is_dup = False
                    for kept_idx in final_passing:
                        kept_embed_pos = passing_indices.index(kept_idx)
                        sim = _cosine_sim(embeddings[idx], embeddings[kept_embed_pos])
                        if sim >= threshold:
                            is_dup = True
                            logger.info(
                                "배치 내 중복 필터링 (sim=%.4f): %s",
                                sim, candidate_texts[i][:80],
                            )
                            self.last_filtered.append(candidate_texts[i][:100])
                            break
                    if not is_dup:
                        final_passing.append(i)
                passing_indices = final_passing
            except Exception:
                logger.warning("배치 내 중복 제거 실패, 스킵", exc_info=True)

        # Phase 3: 통과 항목을 DB에 추가
        if passing_indices:
            now = datetime.now().isoformat()
            self._collection.add(
                ids=[uuid.uuid4().hex for _ in passing_indices],
                documents=[candidate_texts[i] for i in passing_indices],
                metadatas=[{"added_at": now} for _ in passing_indices],
            )
            logger.info(
                "ChromaDB에 %d건 추가 (총 %d건)",
                len(passing_indices), self._collection.count(),
            )

        unseen = empty_items + [candidates[i][0] for i in passing_indices]
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
