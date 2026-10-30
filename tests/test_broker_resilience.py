import pytest
from unittest.mock import patch
from broker import NHBroker


def test_broker_network_exception_handling():
    """증권사 서버 네트워크 장애 발생 시 시스템 충돌 없이 FAILED 안전 반환 검증"""
    broker = NHBroker(
        app_key="valid-test-key",
        app_secret="valid-secret",
        dry_run=False,
    )

    # nhplug.call 호출 시 네트워크 예외(ConnectionError) 모의 발생
    with patch("nhplug.call", side_effect=ConnectionError("증권사 서버 타임아웃 / 게이트웨이 오류")):
        res = broker.send_order(
            stock_code="005930",
            action="BUY",
            quantity=5,
            order_type="00",
            price=60000,
        )

        assert res["status"] == "FAILED"
        assert res["response_code"] == "ERROR"
        assert "증권사 서버 타임아웃" in res["response_message"]
        assert res["order_no"] is None


def test_broker_api_error_response_handling():
    """증권사 서버가 업무 에러(잔고 부족, 비정상 계좌 등)를 반환했을 때의 처리 검증"""
    broker = NHBroker(
        app_key="valid-test-key",
        app_secret="valid-secret",
        dry_run=False,
    )

    error_response = {
        "rsp_cd": "8888",
        "rsp_msg": "계좌 상태 이상(거래제한 계좌)",
        "Output_0": {},
    }

    with patch("nhplug.call", return_value=error_response):
        res = broker.send_order(
            stock_code="005930",
            action="BUY",
            quantity=5,
            order_type="00",
            price=60000,
        )
        assert res["status"] == "SUCCESS"  # HTTP 호출 자체는 성공했으나 응답 메시지에 오류 내용 포함
        assert res["response_code"] == "8888"
        assert "거래제한" in res["response_message"]
