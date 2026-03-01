"""뉴스 시맨틱 중복 제거 테스트.

ChromaDB 기본 임베딩(all-MiniLM-L6-v2)으로 테스트한다.
Gemini API 호출 없이 로컬에서 실행 가능.
"""

import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

import chromadb

from app.collector.dedup import NewsDedup, CHROMA_DIR


@dataclass(frozen=True)
class FakeNews:
    title: str
    summary: str


@pytest.fixture
def dedup(tmp_path):
    """임시 디렉토리에 ChromaDB를 생성하고 기본 임베딩을 사용하는 NewsDedup."""
    with patch("app.collector.dedup.CHROMA_DIR", tmp_path):
        d = NewsDedup.__new__(NewsDedup)
        d._client = chromadb.PersistentClient(path=str(tmp_path))
        d._collection = d._client.get_or_create_collection(
            name="test_news",
            metadata={"hnsw:space": "cosine"},
        )
        yield d


def _text_fn(n: FakeNews) -> str:
    return f"{n.title} {n.summary}"


class TestFilterUnseen:
    def test_empty_list(self, dedup):
        """빈 리스트는 그대로 반환."""
        result = dedup.filter_unseen([], _text_fn, threshold=0.92)
        assert result == []

    def test_first_run_all_pass(self, dedup):
        """첫 실행 시 모든 항목이 통과한다."""
        news = [
            FakeNews("삼성전자 실적 발표", "영업이익 12조원 달성"),
            FakeNews("현대차 전기차 출시", "아이오닉 9 공개"),
        ]
        result = dedup.filter_unseen(news, _text_fn, threshold=0.92)
        assert len(result) == 2

    def test_exact_duplicate_filtered(self, dedup):
        """동일한 뉴스를 두 번 넣으면 두 번째는 필터링된다."""
        news = [FakeNews("삼성전자 실적 발표", "영업이익 12조원 달성")]

        # 첫 번째 실행
        result1 = dedup.filter_unseen(news, _text_fn, threshold=0.92)
        assert len(result1) == 1

        # 두 번째 실행 (동일 뉴스)
        result2 = dedup.filter_unseen(news, _text_fn, threshold=0.92)
        assert len(result2) == 0

    def test_similar_news_filtered(self, dedup):
        """같은 사건을 다르게 보도한 뉴스도 필터링된다."""
        news1 = [FakeNews(
            "Samsung Electronics Reports Record Q4 Earnings",
            "Operating profit reaches 12 trillion won in fourth quarter"
        )]
        news2 = [FakeNews(
            "Samsung Q4 Earnings Beat Expectations",
            "Samsung Electronics operating profit hits 12T won"
        )]

        result1 = dedup.filter_unseen(news1, _text_fn, threshold=0.85)
        assert len(result1) == 1

        result2 = dedup.filter_unseen(news2, _text_fn, threshold=0.85)
        assert len(result2) == 0

    def test_different_topic_passes(self, dedup):
        """전혀 다른 주제의 뉴스는 통과한다."""
        news1 = [FakeNews("삼성전자 실적 발표", "영업이익 12조원 달성")]
        news2 = [FakeNews("현대차 전기차 출시", "아이오닉 9 공개, 1회 충전 620km")]

        dedup.filter_unseen(news1, _text_fn, threshold=0.92)
        result = dedup.filter_unseen(news2, _text_fn, threshold=0.92)
        assert len(result) == 1

    def test_items_added_to_db(self, dedup):
        """통과한 항목이 DB에 추가된다."""
        news = [
            FakeNews("뉴스 A", "내용 A"),
            FakeNews("뉴스 B", "내용 B"),
        ]
        dedup.filter_unseen(news, _text_fn, threshold=0.92)
        assert dedup._collection.count() == 2

    def test_empty_text_passes(self, dedup):
        """빈 텍스트 항목은 필터링하지 않고 통과시킨다."""
        news = [FakeNews("", "")]
        result = dedup.filter_unseen(news, _text_fn, threshold=0.92)
        assert len(result) == 1
        assert dedup._collection.count() == 0  # DB에는 추가되지 않음


class TestCleanup:
    def test_cleanup_removes_old_entries(self, dedup):
        """N일 이전 항목이 삭제된다."""
        # 오래된 항목 직접 추가
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        dedup._collection.add(
            ids=["old1", "old2"],
            documents=["오래된 뉴스 1", "오래된 뉴스 2"],
            metadatas=[{"added_at": old_date}, {"added_at": old_date}],
        )
        # 최근 항목 추가
        new_date = datetime.now().isoformat()
        dedup._collection.add(
            ids=["new1"],
            documents=["최근 뉴스"],
            metadatas=[{"added_at": new_date}],
        )

        assert dedup._collection.count() == 3
        deleted = dedup.cleanup(days=7)
        assert deleted == 2
        assert dedup._collection.count() == 1

    def test_cleanup_empty_collection(self, dedup):
        """빈 컬렉션에서 cleanup은 0을 반환한다."""
        deleted = dedup.cleanup(days=7)
        assert deleted == 0

    def test_cleanup_nothing_old(self, dedup):
        """TTL 내 항목만 있으면 삭제 없음."""
        now = datetime.now().isoformat()
        dedup._collection.add(
            ids=["recent1"],
            documents=["최근 뉴스"],
            metadatas=[{"added_at": now}],
        )
        deleted = dedup.cleanup(days=7)
        assert deleted == 0
        assert dedup._collection.count() == 1
