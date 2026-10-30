import pytest
from risk_guard import ISARiskGuard


@pytest.fixture
def risk_guard():
    # 300만원 한도로 설정된 가드
    return ISARiskGuard(single_order_limit=3000000)


def test_guard_1_ticker_valid(risk_guard):
    """정상 종목명(삼성전자, TIGER ETF 등) 매핑 및 통과 테스트"""
    orders = [
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 5, "order_type": "00", "price": 60000},
        {"stock_name": "TIGER 미국S&P500", "action": "BUY", "quantity": 10, "order_type": "01", "price": 0},
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 2
    assert len(rej) == 0
    assert val[0]["stock_code"] == "005930"
    assert val[1]["stock_code"] == "360750"


def test_guard_1_unknown_ticker_rejection(risk_guard):
    """마스터에 없는 가상/미상 종목 탈락 테스트"""
    orders = [
        {"stock_name": "알수없는가상코인회사", "action": "BUY", "quantity": 1, "order_type": "01", "price": 0}
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_1_TICKER"


def test_guard_2_foreign_stock_rejection(risk_guard):
    """중개형 ISA 해외 주식(AAPL, TSLA 등) 차단 테스트"""
    orders = [
        {"stock_name": "AAPL", "action": "BUY", "quantity": 1, "order_type": "01", "price": 0},
        {"stock_name": "TSLA", "action": "BUY", "quantity": 2, "order_type": "01", "price": 0},
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 2
    assert all(r["guard"] == "GUARD_2_ISA_CONSTRAINT" for r in rej)


def test_guard_2_credit_order_rejection(risk_guard):
    """중개형 ISA 신용/미수 주문 차단 테스트"""
    orders = [
        {
            "stock_name": "삼성전자",
            "action": "BUY",
            "quantity": 5,
            "order_type": "00",
            "price": 60000,
            "credit_type": "CREDIT",
        }
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_2_ISA_CONSTRAINT"
    assert "신용" in rej[0]["reason"]


def test_guard_3_amount_limit_exceeded(risk_guard):
    """300만원 단일 한도 초과 주문 차단 테스트"""
    orders = [
        # 70,000원 * 50주 = 3,500,000원 (> 3,000,000원)
        {"stock_name": "삼성전자", "action": "BUY", "quantity": 50, "order_type": "00", "price": 70000}
    ]
    val, rej = risk_guard.evaluate_orders(orders)
    assert len(val) == 0
    assert len(rej) == 1
    assert rej[0]["guard"] == "GUARD_3_AMOUNT_LIMIT"
    assert "3,500,000원" in rej[0]["reason"]
