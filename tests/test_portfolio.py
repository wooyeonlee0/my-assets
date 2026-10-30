import pytest
from portfolio import (
    NHBrokerAdapter,
    SamsungBrokerAdapter,
    TossBrokerAdapter,
    PortfolioAggregator,
)


def test_adapters_fetch_balance():
    """사용자 3대 증권사(나무, 삼성증권, 토스증권) 어댑터 잔고 조회 검증"""
    nh = NHBrokerAdapter(dry_run=True)
    nh_bal = nh.fetch_balance()
    assert nh_bal.broker_name == "NH투자증권(나무)"
    assert nh_bal.total_eval_amount > 0

    samsung = SamsungBrokerAdapter()
    samsung_bal = samsung.fetch_balance()
    assert samsung_bal.broker_name == "삼성증권"
    assert samsung_bal.total_eval_amount > 0

    toss = TossBrokerAdapter()
    toss_bal = toss.fetch_balance()
    assert toss_bal.broker_name == "토스증권"
    assert toss_bal.total_eval_amount > 0


def test_portfolio_aggregator_3_brokers():
    """나무 + 삼성 + 토스 3대 증권사 통합 자산 집계 및 비중 계산 검증"""
    agg = PortfolioAggregator([
        NHBrokerAdapter(dry_run=True),
        SamsungBrokerAdapter(),
        TossBrokerAdapter(),
    ])
    p = agg.fetch_all()

    # 전체 순자산 검증 (더리치 7억 자산 반영)
    assert p.total_net_worth > 10000000.0
    assert p.total_cash > 0
    assert 0.01 <= p.cash_ratio <= 0.40

    # 보유 종목 리스트 확인
    names = [pos.stock_name for pos in p.consolidated_positions]
    assert any("삼성전자" in n for n in names)
    assert any("S&P500" in n for n in names)
    assert any("SK하이닉스" in n for n in names)
    assert any("애플" in n for n in names)

    # 비중 총합 검증 (주식비중합 + 현금비중 = 1.0)
    total_weights = sum(p.stock_weights.values()) + p.cash_ratio
    assert 0.99 <= total_weights <= 1.01
