import pytest
from analyst import (
    MarketFeed,
    StrategyAnalystAgent,
    PRESET_STRATEGIES,
)


def test_market_feed_overview():
    """시장 지표 피더 데이터 형식 및 유효성 검증"""
    feed = MarketFeed.get_latest_overview()
    assert feed.kospi
    assert feed.us_sp500
    assert feed.usd_krw
    assert len(feed.headlines) >= 3


def test_preset_strategies_weights_validity():
    """모든 전략 프리셋의 목표 비중 합계가 1.0(100%)인지 검증"""
    for name, strat in PRESET_STRATEGIES.items():
        total_w = sum(strat.target_weights.values())
        assert 0.99 <= total_w <= 1.01, f"전략 {name}의 비중 합계 오류: {total_w}"
        assert "CASH" in strat.target_weights, f"전략 {name}에 현금 비중 미포함"


def test_strategy_analyst_user_preference_fallback():
    """사용자의 키워드('배당', '균형', '성장')에 따른 전략 자동 선택 검증"""
    analyst = StrategyAnalystAgent(api_key="mock-key")

    # 1) 배당 키워드
    div_alloc = analyst.analyze_and_propose("배당금 많이 나오는 안전한 주식으로 채워줘")
    assert "배당" in div_alloc.strategy_name or "인컴" in div_alloc.strategy_name

    # 2) 균형 키워드
    bal_alloc = analyst.analyze_and_propose("올웨더 스타일로 변동성 적게 분산해줘")
    assert "균형" in bal_alloc.strategy_name or "안정" in bal_alloc.strategy_name

    # 3) 기본 성장 키워드
    growth_alloc = analyst.analyze_and_propose("미국 빅테크 주식 위주로 공격적으로 가자")
    assert "성장" in growth_alloc.strategy_name
