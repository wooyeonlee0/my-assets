import pytest
from broker import NHBroker
from risk_guard import ISARiskGuard
from rebalance import RebalanceEngine
from portfolio.models import UnifiedPortfolio, Position


@pytest.fixture
def risk_guard():
    return ISARiskGuard(single_order_limit=3000000)


def test_reject_korean_foreign_stock(risk_guard):
    """위험 1: 한글로 된 해외 주식('애플', '테슬라', '엔비디아') 차단 검증"""
    orders = [
        {"stock_name": "애플", "action": "BUY", "quantity": 5, "order_type": "01", "price": 0},
        {"stock_name": "테슬라", "action": "BUY", "quantity": 2, "order_type": "01", "price": 0},
        {"stock_name": "엔비디아", "action": "BUY", "quantity": 1, "order_type": "01", "price": 0},
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 3
    assert all(r["guard"] == "GUARD_2_ISA_CONSTRAINT" for r in rej)


def test_reject_zero_or_negative_quantity(risk_guard):
    """위험 2: 0주 이하 또는 음수 수량 주문 차단 검증"""
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 0, "order_type": "01", "price": 0},
        {"stock_name": "삼성전자", "action": "BUY", "quantity": -5, "order_type": "01", "price": 0},
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 2
    assert all(r["guard"] == "GUARD_0_INVALID_PARAM" for r in rej)


def test_reject_absurdly_huge_quantity(risk_guard):
    """위험 3: 100만 주를 초과하는 비정상적 주문 수량 차단 검증"""
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 5000000, "order_type": "01", "price": 0}
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_0_INVALID_PARAM"


def test_reject_naked_short_selling(risk_guard):
    """위험 4: 무차입 공매도(보유 수량 초과 매도) 차단 검증"""
    current_holdings = {"005930": 10}
    orders = [
        {"stock_name": "삼성전자", "action": "SELL", "quantity": 15, "order_type": "00", "price": 60000}
    ]
    val, rej = risk_guard.evaluate_orders(orders, holdings=current_holdings)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_4_OVER_SELL_PROHIBITED"
    assert "10주이나" in rej[0]["reason"]


def test_reject_insufficient_cash_buy(risk_guard):
    """위험 5: 계좌 예수금을 초과하는 매수 주문(미수금 발생) 차단 검증"""
    available_cash = 1000000.0
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 20, "order_type": "00", "price": 60000}
    ]
    val, rej = risk_guard.evaluate_orders(orders, available_cash=available_cash)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_5_CASH_INSUFFICIENT"


def test_boundary_amount_limit():
    """위험 6: 단일 한도 300만원 경계값 정확성 검증"""
    guard = ISARiskGuard(single_order_limit=3000000)
    orders_exact = [{"stock_name": "삼성전자", "action": "BUY", "quantity": 50, "order_type": "00", "price": 60000}]
    val, rej = guard.evaluate_orders(orders_exact)
    assert len(val) == 1

    orders_over = [{"stock_name": "삼성전자", "action": "BUY", "quantity": 1, "order_type": "00", "price": 3000001}]
    val2, rej2 = guard.evaluate_orders(orders_over)
    assert len(val2) == 0
    assert len(rej2) == 1
    assert rej2[0]["guard"] == "GUARD_3_AMOUNT_LIMIT"


def test_rebalance_with_abnormal_weights():
    """위험 7: 리밸런싱 목표 비중 총합이 150%로 비정상일 때 안전 자동 정규화 검증"""
    engine = RebalanceEngine()
    portfolio = UnifiedPortfolio(
        total_net_worth=10000000,
        total_cash=2000000,
        cash_ratio=0.20,
        accounts=[],
        consolidated_positions=[],
        asset_class_weights={},
        stock_weights={},
    )
    abnormal_targets = {"005930": 0.90, "360750": 0.60}
    plan = engine.calculate_plan(portfolio, abnormal_targets)
    assert len(plan.proposals) >= 1
    assert plan.total_buy_amount < 10000000


def test_rebalance_zero_nav_safety():
    """위험 8: 잔고가 0원인 신규/빈 계좌일 때 무한루프나 에러 없이 안전 리턴 검증"""
    engine = RebalanceEngine()
    empty_portfolio = UnifiedPortfolio(
        total_net_worth=0,
        total_cash=0,
        cash_ratio=0.0,
        accounts=[],
        consolidated_positions=[],
        asset_class_weights={},
        stock_weights={},
    )
    plan = engine.calculate_plan(empty_portfolio, {"005930": 0.5})
    assert len(plan.proposals) == 0
    assert "보유 자산이 없어" in plan.natural_language_memo


# =====================================================================
# 제3자 감사관 지적사항 반영 신규 테스트 (9, 10, 11)
# =====================================================================
def test_reject_invalid_krx_tick_size(risk_guard):
    """위험 9: KRX 호가 단위 위반 (삼성전자 60,000원대는 100원 단위여야 함. 60,050원 거절)"""
    # 60,000원은 100원 단위여야 하므로 60,050원은 호가단위 오류로 거절되어야 함
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 10, "order_type": "00", "price": 60050}
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_6_INVALID_TICK_SIZE"
    assert "100원" in rej[0]["reason"]


def test_reject_conflicting_wash_sale_orders(risk_guard):
    """위험 10: 동일 종목 상반된 매수/매도 동시 요청(자전거래/충돌) 차단 검증"""
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 10, "order_type": "01", "price": 0},
        {"stock_name": "삼성전자", "action": "SELL", "quantity": 5, "order_type": "01", "price": 0},
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 2
    assert all(r["guard"] == "GUARD_7_CONFLICTING_ORDERS" for r in rej)


def test_prevent_double_submission():
    """위험 11: 30초 이내 동일 주문 연타(Double Submission) 시 브로커 멱등성 차단 검증"""
    broker = NHBroker(dry_run=True, account_no="1234567801")

    # 1회차 주문: 정상 접수
    res1 = broker.send_order("005930", "BUY", 5, "00", price=60000)
    assert res1["status"] == "SUCCESS"

    # 2회차 즉시 중복 전송: 멱등성 가드에 의해 차단되어야 함
    res2 = broker.send_order("005930", "BUY", 5, "00", price=60000)
    assert res2["status"] == "FAILED"
    assert res2["response_code"] == "DUPLICATE_ORDER"
    assert "이중 전송 방어" in res2["response_message"]
