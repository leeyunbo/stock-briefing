"""경제 상식 토픽 큐 — 부동산/경제/투자/세금/금융/글로벌/산업/암호화폐 시드 + 우선순위 기반 선택."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import async_session
from app.core.models import EconomyTopic

logger = logging.getLogger(__name__)

# ── 패턴 정의 ──

PATTERNS: dict[str, str] = {
    "economy_realestate": "{keyword} 뜻과 핵심 정리",
    "economy_concept": "{keyword} 쉽게 이해하기",
    "economy_invest": "{keyword} 완벽 정리",
    "economy_tax": "{keyword} 완벽 가이드",
    "economy_finance": "{keyword} 제대로 알기",
    "economy_global": "{keyword} 쉽게 이해하기",
    "economy_industry": "{keyword} 완벽 정리",
    "economy_crypto": "{keyword} 쉽게 이해하기",
}

# ── 시드 데이터 ──

REALESTATE_KEYWORDS = [
    "청약", "전세", "월세", "갭투자", "LTV",
    "DTI", "DSR", "재개발", "재건축", "분양가상한제",
    "전세사기", "역전세", "공시지가", "취득세", "양도소득세",
    "보유세", "종합부동산세", "임대차3법", "깡통전세", "전세보증보험",
    "주택담보대출", "역모기지론", "부동산 PF", "미분양", "입주권",
    "청약통장", "분양권", "오피스텔", "빌라 전세", "아파트 청약 가점",
    "토지거래허가구역", "재초환", "안전진단", "조합원 입주권", "지역주택조합",
    "소형 아파트 투자", "경매 부동산", "공매 부동산", "부동산 신탁", "전월세 전환율",
    "주택연금", "임대사업자", "단기임대", "상가 투자", "오피스 투자",
    "부동산 리츠", "건물주 되는 법", "다가구 vs 다세대", "분양대금 대출", "이주비 대출",
]

ECONOMY_KEYWORDS = [
    "인플레이션", "디플레이션", "스태그플레이션", "기준금리", "환율",
    "GDP", "CPI", "PPI", "무역수지", "경상수지",
    "양적완화", "테이퍼링", "긴축재정", "재정정책", "통화정책",
    "경기침체", "경기과열", "빅스텝", "자이언트스텝", "피벗",
    "달러 강세", "엔 캐리 트레이드", "글로벌 공급망", "리쇼어링", "프렌드쇼어링",
    "실업률", "고용지표", "소비자신뢰지수", "PMI 지수", "ISM 지수",
    "경상수지 흑자", "무역 적자", "국가 부채", "재정 적자", "국채 금리",
    "장단기 금리 역전", "경기선행지수", "경기동행지수", "경기후행지수", "버블 경제",
    "유동성 함정", "디레버리징", "금융위기", "구제금융", "베일인",
    "공급 측 경제학", "수요 측 경제학", "케인즈 경제학", "통화주의", "MMT 현대통화이론",
]

INVEST_KEYWORDS = [
    "PER", "PBR", "ROE", "배당수익률", "공매도",
    "ETF", "선물옵션", "IPO", "유상증자", "자사주매입",
    "CB 전환사채", "BW 신주인수권부사채", "스팩 SPAC", "리밸런싱", "분산투자",
    "가치투자", "성장주 투자", "배당주 투자", "인덱스 펀드", "적립식 투자",
    "포트폴리오 구성", "자산배분", "헤지펀드", "사모펀드", "TDF 펀드",
    "EPS 주당순이익", "ROA 총자산이익률", "부채비율", "유보율", "영업이익률",
    "기술적 분석", "기본적 분석", "이동평균선", "RSI 지표", "MACD 지표",
    "볼린저 밴드", "골든크로스", "데드크로스", "지지선 저항선", "피보나치 되돌림",
    "공모주 청약", "우선주 vs 보통주", "ADR 미국예탁증서", "해외주식 투자", "환헤지",
    "레버리지 ETF", "인버스 ETF", "채권 투자", "하이일드 채권", "국채 투자",
]

TAX_KEYWORDS = [
    "종합소득세", "연말정산", "IRP 개인형퇴직연금", "ISA 개인종합자산관리계좌", "증여세",
    "상속세", "양도소득세 절세", "부동산 세금", "금융투자소득세", "배당소득세",
    "근로소득공제", "인적공제", "소득공제 vs 세액공제", "의료비 세액공제", "교육비 세액공제",
    "월세 세액공제", "주택청약 소득공제", "연금저축 세액공제", "기부금 세액공제", "신용카드 소득공제",
    "프리랜서 세금", "사업소득세", "부가가치세", "원천징수", "세금 환급",
    "절세 통장", "비과세 한도", "분리과세", "종합과세", "해외주식 양도세",
    "가상자산 과세", "증여세 면제 한도", "상속세 공제", "취득세 감면", "재산세 절세",
]

FINANCE_KEYWORDS = [
    "예금자보호제도", "CMA 통장", "MMF 머니마켓펀드", "연금저축펀드", "퇴직연금 DC형 DB형",
    "파킹통장", "발행어음", "RP 환매조건부채권", "방카슈랑스", "변액보험",
    "실손보험", "종신보험", "정기보험", "CI보험", "암보험 가입 요령",
    "자동차보험 절약", "운전자보험", "화재보험", "풍수해보험", "단체보험",
    "신용점수 관리", "신용등급 올리는 법", "대출 금리 비교", "마이너스 통장", "신용대출 vs 담보대출",
    "햇살론", "새희망홀씨", "사잇돌대출", "보금자리론", "디딤돌대출",
    "P2P 투자", "크라우드펀딩", "소액투자", "금 투자", "달러 투자",
]

GLOBAL_KEYWORDS = [
    "미국 연준 Fed", "FOMC 회의", "달러인덱스 DXY", "위안화 환율", "엔화 환율",
    "브레튼우즈 체제", "페트로달러", "기축통화", "SDR 특별인출권", "IMF 구제금융",
    "세계은행 World Bank", "WTO 무역분쟁", "G7 G20 정상회의", "OECD 경제전망", "BIS 국제결제은행",
    "미중 무역전쟁", "관세 보복", "환율조작국", "경제 제재", "수출통제",
    "오일쇼크", "OPEC 감산", "유가 전망", "천연가스 가격", "원자재 슈퍼사이클",
    "신흥국 경제", "브릭스 BRICS", "아세안 경제", "유로존 위기", "영국 브렉시트",
    "글로벌 인플레이션", "달러 패권", "탈달러화", "디지털 위안화", "중앙은행 디지털화폐 CBDC",
]

INDUSTRY_KEYWORDS = [
    "밸류체인", "M&A 인수합병", "ESG 경영", "공급망 리스크", "반도체 사이클",
    "플랫폼 경제", "구독 경제", "긱 이코노미", "공유경제", "탄소중립",
    "탄소배출권", "RE100", "그린워싱", "지속가능경영", "ESG 투자",
    "4차 산업혁명", "AI 경제", "빅데이터 산업", "클라우드 시장", "반도체 공급망",
    "전기차 시장", "배터리 산업", "수소경제", "신재생에너지", "원자력 르네상스",
    "바이오 산업", "헬스케어 투자", "메타버스 경제", "NFT 시장", "로봇 자동화",
    "스타트업 생태계", "유니콘 기업", "IPO 시장", "벤처캐피털", "액셀러레이터",
]

CRYPTO_KEYWORDS = [
    "비트코인 반감기", "이더리움 업그레이드", "스테이블코인", "디파이 DeFi", "NFT",
    "블록체인 기술", "암호화폐 지갑", "콜드월렛 핫월렛", "거래소 CEX DEX", "스테이킹",
    "채굴 마이닝", "해시레이트", "비트코인 ETF", "알트코인", "밈코인",
    "리플 XRP", "솔라나", "폴리곤", "아발란체", "코스모스",
    "레이어1 레이어2", "브리지 해킹", "러그풀", "스마트컨트랙트", "오라클 문제",
    "중앙은행 디지털화폐 CBDC", "가상자산 규제", "트래블룰", "김치프리미엄", "공포탐욕지수",
    "비트코인 도미넌스", "알트시즌", "불장 베어장", "손익분기점 BEP", "포트폴리오 리밸런싱",
]


def _build_seed_rows() -> list[dict]:
    rows: list[dict] = []

    for keyword in REALESTATE_KEYWORDS:
        rows.append({
            "pattern_type": "economy_realestate",
            "keyword": keyword,
            "title_template": PATTERNS["economy_realestate"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 10,
            "source": "template",
        })

    for keyword in ECONOMY_KEYWORDS:
        rows.append({
            "pattern_type": "economy_concept",
            "keyword": keyword,
            "title_template": PATTERNS["economy_concept"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 10,
            "source": "template",
        })

    for keyword in INVEST_KEYWORDS:
        rows.append({
            "pattern_type": "economy_invest",
            "keyword": keyword,
            "title_template": PATTERNS["economy_invest"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 8,
            "source": "template",
        })

    for keyword in TAX_KEYWORDS:
        rows.append({
            "pattern_type": "economy_tax",
            "keyword": keyword,
            "title_template": PATTERNS["economy_tax"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 9,
            "source": "template",
        })

    for keyword in FINANCE_KEYWORDS:
        rows.append({
            "pattern_type": "economy_finance",
            "keyword": keyword,
            "title_template": PATTERNS["economy_finance"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 9,
            "source": "template",
        })

    for keyword in GLOBAL_KEYWORDS:
        rows.append({
            "pattern_type": "economy_global",
            "keyword": keyword,
            "title_template": PATTERNS["economy_global"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 8,
            "source": "template",
        })

    for keyword in INDUSTRY_KEYWORDS:
        rows.append({
            "pattern_type": "economy_industry",
            "keyword": keyword,
            "title_template": PATTERNS["economy_industry"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 8,
            "source": "template",
        })

    for keyword in CRYPTO_KEYWORDS:
        rows.append({
            "pattern_type": "economy_crypto",
            "keyword": keyword,
            "title_template": PATTERNS["economy_crypto"].format(keyword=keyword),
            "focus_keyword": keyword,
            "priority": 7,
            "source": "template",
        })

    return rows


async def seed_economy_topics() -> int:
    rows = _build_seed_rows()
    inserted = 0

    async with async_session() as db:
        for row in rows:
            stmt = sqlite_insert(EconomyTopic).values(**row).on_conflict_do_nothing(
                index_elements=["pattern_type", "keyword"],
            )
            result = await db.execute(stmt)
            inserted += result.rowcount
        await db.commit()

    logger.info("경제 상식 시드 토픽: %d건 삽입 (전체 %d건)", inserted, len(rows))
    return inserted


async def pick_next_economy_topic() -> EconomyTopic | None:
    async with async_session() as db:
        result = await db.execute(
            select(EconomyTopic)
            .where(EconomyTopic.status == "pending")
            .order_by(EconomyTopic.priority.desc(), EconomyTopic.id.asc())
            .limit(1)
        )
        topic = result.scalar_one_or_none()
        if topic:
            db.expunge(topic)
        return topic


async def mark_economy_published(topic_id: int, briefing_id: int, wp_post_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(EconomyTopic).where(EconomyTopic.id == topic_id))
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "published"
            topic.briefing_id = briefing_id
            topic.wp_post_id = wp_post_id
            topic.published_at = datetime.now(UTC)
            await db.commit()
            logger.info("경제 상식 토픽 발행: id=%d, keyword=%s", topic_id, topic.keyword)


async def mark_economy_skipped(topic_id: int) -> None:
    async with async_session() as db:
        result = await db.execute(select(EconomyTopic).where(EconomyTopic.id == topic_id))
        topic = result.scalar_one_or_none()
        if topic:
            topic.status = "skipped"
            await db.commit()
