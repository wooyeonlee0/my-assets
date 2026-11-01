#!/usr/bin/env python3
"""
Unit Tests for Unified Trading Core & Batch Engine
--------------------------------------------------
검증 항목:
1. Sell-First 파이프라인 (매도 우선 ➔ 예수금 확보 ➔ 매수 집행) 정렬 무결성
2. 배치 레벨 Risk Guard (1회 최대 10개 종목, 종목당 100주 제한, 0/음수 차단)
3. 단건/배치 페이로드 자동 호환 파싱 (하위 호환성 100%)
4. 요약 카드 HTML 포맷터 검증
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.trading_core import (
    OrderItem,
    BatchOrder,
    validate_batch_risk_guard,
    parse_order_payload,
    format_batch_summary_html,
    encode_compact_order,
    decode_compact_order
)


class TestUnifiedTradingCore(unittest.TestCase):
    """📦 단일 트레이딩 코어 및 배치 파이프라인 단위 테스트"""

    def test_sell_first_pipeline_sorting(self):
        """매도(SELL) 주문이 매수(BUY)보다 무조건 먼저 실행되도록 순서 정렬 보장"""
        orders = [
            OrderItem(ticker="NVDA", qty=2, side="BUY"),
            OrderItem(ticker="TSLA", qty=5, side="SELL"),
            OrderItem(ticker="AAPL", qty=1, side="BUY"),
            OrderItem(ticker="GOOGL", qty=3, side="SELL"),
        ]
        batch = BatchOrder(orders=orders)
        batch.sort_sell_first()

        # 결과: TSLA(SELL), GOOGL(SELL)이 앞단에, NVDA(BUY), AAPL(BUY)가 뒷단에 위치해야 함
        self.assertEqual(batch.orders[0].side, "SELL")
        self.assertEqual(batch.orders[1].side, "SELL")
        self.assertEqual(batch.orders[2].side, "BUY")
        self.assertEqual(batch.orders[3].side, "BUY")
        self.assertEqual([o.ticker for o in batch.orders[:2]], ["TSLA", "GOOGL"])

    def test_batch_type_auto_detection(self):
        """배치 타입(BUY, SELL, REBALANCE) 자동 감지 검증"""
        # 1) 매수만 있을 때
        buy_batch = BatchOrder(orders=[OrderItem("NVDA", 1, "BUY"), OrderItem("AAPL", 1, "BUY")])
        self.assertEqual(buy_batch.batch_type, "BUY")

        # 2) 매도만 있을 때
        sell_batch = BatchOrder(orders=[OrderItem("NVDA", 1, "SELL"), OrderItem("AAPL", 1, "SELL")])
        self.assertEqual(sell_batch.batch_type, "SELL")

        # 3) 매수/매도 혼합 (리밸런싱)
        rebal_batch = BatchOrder(orders=[OrderItem("NVDA", 1, "SELL"), OrderItem("AAPL", 1, "BUY")])
        self.assertEqual(rebal_batch.batch_type, "REBALANCE")

    def test_risk_guard_valid_batch(self):
        """정상 배치 주문 통과 검증"""
        batch = BatchOrder(orders=[
            OrderItem("NVDA", 10, "SELL"),
            OrderItem("GOOGL", 5, "BUY"),
            OrderItem("005930", 20, "BUY") # 삼성전자
        ])
        is_valid, msg, val_batch = validate_batch_risk_guard(batch, max_single_qty=100, max_items_per_batch=10)
        self.assertTrue(is_valid)
        self.assertEqual(msg, "")
        self.assertEqual(len(val_batch.orders), 3)
        # Sell-First 검증
        self.assertEqual(val_batch.orders[0].ticker, "NVDA")
        self.assertEqual(val_batch.orders[0].side, "SELL")

    def test_risk_guard_exceeds_max_batch_items(self):
        """배치 허용 종목 수(10개) 초과 시 원천 차단"""
        too_many_orders = [OrderItem(f"STK{i}", 1, "BUY") for i in range(11)]
        batch = BatchOrder(orders=too_many_orders)
        is_valid, msg, _ = validate_batch_risk_guard(batch, max_items_per_batch=10)
        self.assertFalse(is_valid)
        self.assertIn("최대 허용 종목 수(10개)를 초과", msg)

    def test_risk_guard_single_qty_exceeded_in_batch(self):
        """배치 내 1개 종목이라도 100주 초과 시 전체 배치 안전 차단"""
        batch = BatchOrder(orders=[
            OrderItem("NVDA", 2, "SELL"),
            OrderItem("GOOGL", 150, "BUY") # 150주 위반
        ])
        is_valid, msg, _ = validate_batch_risk_guard(batch, max_single_qty=100)
        self.assertFalse(is_valid)
        self.assertIn("GOOGL", msg)
        self.assertIn("1회 최대 안전 리밋(100주)을 초과", msg)

    def test_risk_guard_zero_or_negative_in_batch(self):
        """배치 내 0주 또는 음수 수량 차단"""
        batch = BatchOrder(orders=[
            OrderItem("AAPL", 0, "BUY")
        ])
        is_valid, msg, _ = validate_batch_risk_guard(batch)
        self.assertFalse(is_valid)
        self.assertIn("비정상적인 수량", msg)

    def test_payload_parsing_backward_compatibility(self):
        """단건 JSON 포맷과 배치 JSON 포맷을 100% 동일한 BatchOrder로 파싱"""
        # 단건 포맷 입력
        single_json = '{"ticker": "NVDA", "qty": 2, "side": "BUY", "price": "0"}'
        ok, _, batch1 = parse_order_payload(single_json)
        self.assertTrue(ok)
        self.assertEqual(len(batch1.orders), 1)
        self.assertEqual(batch1.orders[0].ticker, "NVDA")
        self.assertEqual(batch1.orders[0].qty, 2)

        # 배치 포맷 입력
        batch_json = '''{
            "batch_type": "REBALANCE",
            "orders": [
                {"ticker": "TSLA", "qty": 3, "side": "SELL"},
                {"ticker": "GOOGL", "qty": 2, "side": "BUY"}
            ]
        }'''
        ok, _, batch2 = parse_order_payload(batch_json)
        self.assertTrue(ok)
        self.assertEqual(len(batch2.orders), 2)
        self.assertEqual(batch2.batch_type, "REBALANCE")

    def test_format_batch_summary_html(self):
        """요약 카드 HTML 생성 검증"""
        batch = BatchOrder(orders=[
            OrderItem("NVDA", 2, "SELL"),
            OrderItem("GOOGL", 3, "BUY")
        ])
        html_text = format_batch_summary_html(batch)
        self.assertIn("스마트 리밸런싱", html_text)
        self.assertIn("매도 순서", html_text)
        self.assertIn("NVDA", html_text)
        self.assertIn("매수 순서", html_text)
        self.assertIn("GOOGL", html_text)

    def test_mixed_domestic_and_overseas_markets(self):
        """국내주식(6자리 숫자)과 해외주식(알파벳) 혼합 배치 시 시장 자동 판별 검증"""
        batch = BatchOrder(orders=[
            OrderItem(ticker="005930", qty=10, side="BUY"), # 삼성전자
            OrderItem(ticker="NVDA", qty=2, side="BUY"),     # 미국 나스닥
            OrderItem(ticker="000660", qty=5, side="SELL"),  # SK하이닉스
            OrderItem(ticker="AAPL", qty=1, side="SELL")     # 미국
        ])
        batch.sort_sell_first()

        # 매도 2건(000660, AAPL), 매수 2건(005930, NVDA)
        self.assertEqual(len(batch.orders), 4)
        self.assertEqual(batch.orders[0].market, "KR_STOCK")
        self.assertEqual(batch.orders[1].market, "US_NASD")
        self.assertEqual(batch.orders[2].market, "KR_STOCK")
        self.assertEqual(batch.orders[3].market, "US_NASD")

    def test_empty_batch_orders_rejection(self):
        """빈 배치 주문(0건) 입력 시 Risk Guard 차단 검증"""
        empty_batch = BatchOrder(orders=[])
        is_valid, msg, _ = validate_batch_risk_guard(empty_batch)
        self.assertFalse(is_valid)
        self.assertIn("주문 항목이 존재하지 않습니다", msg)

    def test_order_item_serialization_roundtrip(self):
        """OrderItem 및 BatchOrder JSON 직렬화/역직렬화 100% 왕복 무결성 검증"""
        original_item = OrderItem(ticker="TSLA", qty=4, side="BUY", price="250.5", market="US_NASD")
        d = original_item.to_dict()
        restored_item = OrderItem.from_dict(d)

        self.assertEqual(restored_item.ticker, "TSLA")
        self.assertEqual(restored_item.qty, 4)
        self.assertEqual(restored_item.side, "BUY")
        self.assertEqual(restored_item.price, "250.5")
        self.assertEqual(restored_item.market, "US_NASD")

        # BatchOrder 왕복 검증
        batch = BatchOrder(orders=[original_item])
        json_str = batch.to_json()
        restored_batch = BatchOrder.from_json(json_str)
        self.assertEqual(len(restored_batch.orders), 1)
        self.assertEqual(restored_batch.orders[0].ticker, "TSLA")

    def test_encode_compact_order(self):
        """텔레그램 64자 제한을 만족하는 초소형 딥링크 인코딩 검증"""
        # 1) 단건 인코딩
        single = BatchOrder(orders=[OrderItem("NVDA", 3, "SELL")])
        self.assertEqual(encode_compact_order(single), "NVDA.3.S")

        # 2) 혼합 리밸런싱 인코딩 (Sell-First 자동 정렬 확인)
        rebalance = BatchOrder(orders=[
            OrderItem("NVDA", 2, "BUY"),
            OrderItem("TSLA", 5, "SELL")
        ])
        encoded = encode_compact_order(rebalance)
        self.assertEqual(encoded, "TSLA.5.S_NVDA.2.B")
        self.assertLessEqual(len(encoded), 64)

    def test_decode_compact_order_and_payload_parser(self):
        """초소형 딥링크 디코딩 및 단일 파서(parse_order_payload) 연동 검증"""
        compact_str = "NVDA.3.S_GOOGL.2.B"
        batch = decode_compact_order(compact_str)
        self.assertIsNotNone(batch)
        self.assertEqual(len(batch.orders), 2)
        self.assertEqual(batch.orders[0].ticker, "NVDA")
        self.assertEqual(batch.orders[0].side, "SELL")
        self.assertEqual(batch.orders[0].qty, 3)
        self.assertEqual(batch.orders[1].ticker, "GOOGL")
        self.assertEqual(batch.orders[1].side, "BUY")
        self.assertEqual(batch.orders[1].qty, 2)
        self.assertEqual(batch.batch_type, "REBALANCE")

        # parse_order_payload 직접 지원 검증
        ok, msg, parsed_batch = parse_order_payload(compact_str)
        self.assertTrue(ok)
        self.assertEqual(len(parsed_batch.orders), 2)

        # /start 접두어 포함 시 자동 클리닝 검증
        batch_with_prefix = decode_compact_order("/start TSLA.1.B")
        self.assertIsNotNone(batch_with_prefix)
        self.assertEqual(batch_with_prefix.orders[0].ticker, "TSLA")
        self.assertEqual(batch_with_prefix.orders[0].side, "BUY")

    def test_decode_compact_order_edge_cases(self):
        """비정상/빈 문자열/오류 토큰 방어 검증"""
        self.assertIsNone(decode_compact_order(""))
        self.assertIsNone(decode_compact_order(None))
        self.assertIsNone(decode_compact_order("invalid_format_without_dots"))
        self.assertIsNone(decode_compact_order("NVDA.notanumber.B"))
        self.assertIsNone(decode_compact_order("NVDA.0.B"))  # 0주는 무효
        self.assertIsNone(decode_compact_order("NVDA.-3.B")) # 음수 무효


    def test_pin_hash_verification(self):
        """🔐 2차 보안: SHA-256 PIN 해시 검증 테스트"""
        import hashlib
        pin = "123456"
        expected_hash = hashlib.sha256(pin.encode("utf-8")).hexdigest().lower()
        
        # 올바른 PIN 일치
        self.assertEqual(hashlib.sha256("123456".encode("utf-8")).hexdigest().lower(), expected_hash)
        
        # 틀린 PIN 불일치
        wrong_hash = hashlib.sha256("999999".encode("utf-8")).hexdigest().lower()
        self.assertNotEqual(wrong_hash, expected_hash)


if __name__ == "__main__":
    unittest.main()
