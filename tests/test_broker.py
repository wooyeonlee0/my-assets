import pytest
from broker import NHBroker


def test_broker_dry_run_buy_order():
    """Dry-run 모드에서 매수 주문 전송 및 페이로드 규격 검증"""
    broker = NHBroker(dry_run=True, account_no="1234567801")
    result = broker.send_order(
        stock_code="005930",
        action="BUY",
        quantity=5,
        order_type="00",  # 지정가
        price=60000,
        estimated_amount=300000,
    )
    assert result["status"] == "SUCCESS"
    assert result["order_no"].startswith("MOCK-")
    assert result["endpoint"] == "/krstock/order/v1/cashBuy"
    assert result["payload"]["iem_cd"] == "005930"
    assert result["payload"]["orr_qty"] == 5
    assert result["payload"]["orr_pr"] == 60000
    assert result["payload"]["nmn_pr_tp_cd"] == "01"  # 보통가(지정가)


def test_broker_dry_run_sell_order():
    """Dry-run 모드에서 매도 주문 전송 검증"""
    broker = NHBroker(dry_run=True, account_no="1234567801")
    result = broker.send_order(
        stock_code="000660",
        action="SELL",
        quantity=2,
        order_type="01",  # 시장가
        price=0,
        estimated_amount=360000,
    )
    assert result["status"] == "SUCCESS"
    assert result["endpoint"] == "/krstock/order/v1/cashSell"
    assert result["payload"]["nmn_pr_tp_cd"] == "05"  # 시장가
