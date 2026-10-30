import pytest
from portfolio import PortfolioAggregator, NHBrokerAdapter
from rebalance import RebalanceEngine


@pytest.fixture
def sample_portfolio():
    # NH 단독 500만원 계좌 (삼전 180만, S&P500 152만, 현금 168만)
    agg = PortfolioAggregator([NHBrokerAdapter(dry_run=True)])
    return agg.fetch_all()


def test_rebalance_delta_calculation(sample_portfolio):
    """목표 비중에 맞춘 델타 주문 및 정수 수량 계산 검증"""
    engine = RebalanceEngine(threshold_band=0.01)

    # 목표 비중: 삼성전자 10% (50만원), S&P500 50% (250만원)
    targets = {
        "005930": 0.10,  # 현재 180만(36%) -> 매도 필요
        "360750": 0.50,  # 현재 152만(30.4%) -> 매수 필요
    }

    plan = engine.calculate_plan(sample_portfolio, targets)

    assert len(plan.proposals) == 2
    # 매도가 먼저 와야 함
    assert plan.proposals[0].action == "SELL"
    assert plan.proposals[0].stock_code == "005930"
    assert plan.proposals[0].quantity > 0

    assert plan.proposals[1].action == "BUY"
    assert plan.proposals[1].stock_code == "360750"
    assert plan.proposals[1].quantity > 0

    assert "삼성전자" in plan.natural_language_memo
    assert "TIGER 미국S&P500" in plan.natural_language_memo


def test_rebalance_threshold_filtering(sample_portfolio):
    """임계값(1.5%) 이내의 미세 변동은 거래를 건너뛰는지 검증"""
    engine = RebalanceEngine(threshold_band=0.05)  # 5% 밴드

    # 현재 비중: 삼전 36%, S&P500 30.4%
    # 목표 비중: 삼전 35% (-1%), S&P500 31% (+0.6%) -> 5% 이내이므로 주문 없어야 함
    targets = {
        "005930": 0.35,
        "360750": 0.31,
    }

    plan = engine.calculate_plan(sample_portfolio, targets)
    assert len(plan.proposals) == 0
    assert "추가 리밸런싱 주문이 필요 없습니다" in plan.natural_language_memo
