import json
import pytest
from pathlib import Path
from portfolio.broker_adapters import SamsungBrokerAdapter, TossBrokerAdapter


def test_samsung_adapter_custom_snapshot(tmp_path):
    """삼성증권 스냅샷 파일 저장 및 즉각 반영 검증"""
    custom_file = tmp_path / "test_samsung.json"
    adapter = SamsungBrokerAdapter(account_no="TEST-SAMSUNG-01", snapshot_file=custom_file)

    # 새로운 보유 현황 저장
    new_data = {
        "account_no": "TEST-SAMSUNG-01",
        "account_type": "GENERAL",
        "deposit_cash": 1200000.0,
        "positions": [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 20,
                "avg_buy_price": 65000,
                "current_price": 60000,
            }
        ],
    }
    adapter.save_snapshot(new_data)

    bal = adapter.fetch_balance()
    assert bal.deposit_cash == 1200000.0
    assert len(bal.positions) == 1
    assert bal.positions[0].stock_code == "005930"
    assert bal.positions[0].quantity == 20
    assert bal.total_eval_amount == (20 * 60000 + 1200000.0)


def test_toss_adapter_custom_snapshot(tmp_path):
    """토스증권 스냅샷 파일 저장 및 즉각 반영 검증"""
    custom_file = tmp_path / "test_toss.json"
    adapter = TossBrokerAdapter(account_no="TEST-TOSS-01", snapshot_file=custom_file)

    toss_data = {
        "account_no": "TEST-TOSS-01",
        "account_type": "OVERSEAS",
        "deposit_cash": 700000.0,
        "positions": [
            {
                "stock_code": "TSLA",
                "stock_name": "테슬라 (Tesla)",
                "quantity": 4,
                "avg_buy_price": 310000,
                "current_price": 330000,
                "asset_class": "FOREIGN_STOCK",
            }
        ],
    }
    adapter.save_snapshot(toss_data)

    bal = adapter.fetch_balance()
    assert bal.deposit_cash == 700000.0
    assert len(bal.positions) == 1
    assert bal.positions[0].stock_name == "테슬라 (Tesla)"
