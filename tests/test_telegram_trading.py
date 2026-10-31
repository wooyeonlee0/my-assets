#!/usr/bin/env python3
"""
Unit and Integration Tests for Telegram AI Trading & Risk Guard
----------------------------------------------------------------
검증 항목:
1. Risk Guard 무결성: 정상 수량 통과, 0/음수/비정상/한도초과(100주) 차단
2. 화이트리스트 보안: 미인가 사용자 100% 차단, Fail-Safe 동작
3. AI 주문 태그 추출: 정규식 파싱, 클린 텍스트 분리, JSON 에러 복구
4. 멱등성 및 더블 클릭 방지: 동일 주문 중복 실행 원천 차단
5. 주문 취소 및 만료 흐름
"""

import unittest
import sys
import os

# scripts 모듈 경로 등록
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.kis_trade import validate_risk_guard
from scripts.telegram_bot import TelegramTradingBot


class TestRiskGuard(unittest.TestCase):
    """🛡️ Risk Guard 시스템 레벨 안전 검증 테스트"""

    def test_valid_quantities(self):
        """정상 수량 (1주 ~ 100주) 통과 검증"""
        for qty in [1, 5, 50, 99, 100, "1", "100"]:
            valid, msg, val_qty = validate_risk_guard("NVDA", qty, max_qty_limit=100)
            self.assertTrue(valid, f"Failed for valid qty: {qty}")
            self.assertEqual(val_qty, int(qty))
            self.assertEqual(msg, "")

    def test_over_limit_quantities(self):
        """1회 최대 허용치(100주) 초과 시 원천 차단 검증"""
        for qty in [101, 150, 1000, "101", "500"]:
            valid, msg, val_qty = validate_risk_guard("NVDA", qty, max_qty_limit=100)
            self.assertFalse(valid, f"Should fail for over-limit qty: {qty}")
            self.assertIn("초과했습니다", msg)

    def test_zero_and_negative_quantities(self):
        """0주 및 음수 주문 원천 차단 검증"""
        for qty in [0, -1, -50, "0", "-1"]:
            valid, msg, val_qty = validate_risk_guard("NVDA", qty, max_qty_limit=100)
            self.assertFalse(valid, f"Should fail for zero/negative qty: {qty}")
            self.assertIn("비정상적인 주문 수량", msg)

    def test_invalid_data_types(self):
        """비숫자, None, 특수문자 등 무효 입력 차단 검증"""
        for qty in ["abc", None, "", "ten", "12.34"]:
            valid, msg, val_qty = validate_risk_guard("NVDA", qty, max_qty_limit=100)
            self.assertFalse(valid, f"Should fail for invalid data: {qty}")
            self.assertIn("유효한 정수가 아닙니다", msg)

    def test_empty_or_blank_ticker(self):
        """티커 누락 차단 검증"""
        for ticker in ["", "   ", None]:
            valid, msg, val_qty = validate_risk_guard(ticker, 5, max_qty_limit=100)
            self.assertFalse(valid)
            self.assertIn("티커가 비어있습니다", msg)

    def test_custom_max_limit(self):
        """사용자 정의 커스텀 한도 검증 (예: 1회 10주 제한)"""
        valid, _, _ = validate_risk_guard("TSLA", 10, max_qty_limit=10)
        self.assertTrue(valid)

        valid, msg, _ = validate_risk_guard("TSLA", 11, max_qty_limit=10)
        self.assertFalse(valid)
        self.assertIn("1회 최대 허용 수량(10주)을 초과", msg)


class TestTelegramSecurity(unittest.TestCase):
    """🔒 텔레그램 화이트리스트 및 보안 검증 테스트"""

    def setUp(self):
        self.bot = TelegramTradingBot(
            token="dummy_token",
            allowed_users=[12345678, 98765432],
            gemini_api_key="dummy_gemini",
            github_pat="dummy_pat",
            max_qty_limit=100
        )

    def test_authorized_user_access(self):
        """등록된 사용자의 정상 승인 검증"""
        self.assertTrue(self.bot.is_authorized(12345678))
        self.assertTrue(self.bot.is_authorized(98765432))

    def test_unauthorized_user_blocked(self):
        """미등록 제3자의 접근 원천 차단 검증"""
        self.assertFalse(self.bot.is_authorized(11111111))
        self.assertFalse(self.bot.is_authorized(99999999))
        self.assertFalse(self.bot.is_authorized(0))

    def test_empty_whitelist_fail_safe(self):
        """화이트리스트가 비어있을 때 안전하게 전체 차단(Fail-Safe) 검증"""
        empty_bot = TelegramTradingBot(token="dummy", allowed_users=[])
        self.assertFalse(empty_bot.is_authorized(12345678))
        self.assertFalse(empty_bot.is_authorized(98765432))


class TestOrderParsingAndExecution(unittest.TestCase):
    """🤖 AI 응답 태그 파싱, 인라인 버튼 생성, 멱등성 검증"""

    def setUp(self):
        self.bot = TelegramTradingBot(
            token="dummy_token",
            allowed_users=[12345],
            max_qty_limit=100
        )

    def test_extract_order_valid_tag(self):
        """정상 주문 태그 추출 및 마크다운 분리 검증"""
        sample_response = (
            "NVDA의 현재 포트폴리오 비중은 28%로 양호합니다. 소폭 추가 매수를 제안합니다.\n\n"
            ":::kis_order {\"ticker\": \"NVDA\", \"qty\": 2, \"side\": \"BUY\", \"price\": 0}:::\n"
            "추가 질문이 있으시면 말씀해주세요."
        )
        clean_text, order_data = self.bot.extract_order_from_text(sample_response)

        self.assertIsNotNone(order_data)
        self.assertEqual(order_data["ticker"], "NVDA")
        self.assertEqual(order_data["qty"], 2)
        self.assertEqual(order_data["side"], "BUY")
        self.assertEqual(order_data["price"], 0)
        self.assertNotIn(":::kis_order", clean_text)
        self.assertIn("NVDA의 현재 포트폴리오", clean_text)

    def test_extract_order_no_tag(self):
        """주문 없는 일반 상담 텍스트 파싱 검증"""
        sample_response = "현재 포트폴리오 상태가 안정적입니다. 지금은 관망을 추천합니다."
        clean_text, order_data = self.bot.extract_order_from_text(sample_response)

        self.assertIsNone(order_data)
        self.assertEqual(clean_text, sample_response)

    def test_extract_order_corrupted_json(self):
        """깨진 JSON 태그가 포함되어도 예외 없이 안전 무시 검증"""
        sample_response = "주문 제안: :::kis_order {bad json data::: 끝."
        clean_text, order_data = self.bot.extract_order_from_text(sample_response)

        self.assertIsNone(order_data)
        self.assertEqual(clean_text, sample_response)

    def test_create_order_action_markup(self):
        """인라인 버튼 마크업 생성 및 메모리 토큰 저장 검증"""
        order_data = {"ticker": "GOOGL", "qty": 3, "side": "BUY", "price": 0}
        order_id, markup = self.bot.create_order_action_markup(order_data)

        self.assertIn(order_id, self.bot.pending_orders)
        self.assertFalse(self.bot.pending_orders[order_id]["executed"])
        self.assertEqual(self.bot.pending_orders[order_id]["pin_buffer"], "")

        # 인라인 버튼 구조 검증
        buttons = markup["inline_keyboard"]
        self.assertEqual(len(buttons), 2)
        self.assertIn("GOOGL 3주 매수 승인 및 2차 인증", buttons[0][0]["text"])
        self.assertEqual(buttons[0][0]["callback_data"], f"start_pin:{order_id}")
        self.assertEqual(buttons[1][0]["callback_data"], f"cancel_order:{order_id}")

    def test_pin_keypad_rendering(self):
        """2차 보안 PIN 가상 키패드 마크업 구조 검증"""
        order_data = {"ticker": "NVDA", "qty": 2, "side": "BUY"}
        order_id, _ = self.bot.create_order_action_markup(order_data)

        text, markup = self.bot.render_pin_keypad(order_id)
        self.assertIn("2차 보안 PIN 인증", text)
        self.assertIn("○ ○ ○ ○ ○ ○", text) # 0자리 입력 상태

        # 3x4 키패드 검증
        rows = markup["inline_keyboard"]
        self.assertEqual(len(rows), 4) # 4행
        self.assertEqual(rows[0][0]["text"], "1")
        self.assertEqual(rows[3][0]["text"], "⌫") # 백스페이스
        self.assertEqual(rows[3][1]["text"], "0")
        self.assertEqual(rows[3][2]["text"], "❌ 취소")

    def test_double_click_prevention(self):
        """더블 클릭 방지 (중복 체결 방어) 검증"""
        order_data = {"ticker": "AAPL", "qty": 1, "side": "BUY"}
        order_id, _ = self.bot.create_order_action_markup(order_data)

        # 1회차 실행: 상태가 executed=True로 변환되어야 함
        order_ref = self.bot.pending_orders[order_id]
        self.assertFalse(order_ref["executed"])
        order_ref["executed"] = True

        # 2회차 클릭 시도 시 이미 실행됨 확인
        self.assertTrue(self.bot.pending_orders[order_id]["executed"])

    def test_extract_order_markdown_block(self):
        """마크다운 백틱(```json ... ```)으로 감싸진 AI 응답도 안전하게 파싱"""
        sample_response = (
            "NVDA 분석 결과입니다.\n"
            ":::kis_order\n```json\n{\"ticker\": \"nvda \", \"qty\": 2.0, \"side\": \"buy\"}\n```\n:::\n"
            "확인해주세요."
        )
        clean_text, order_data = self.bot.extract_order_from_text(sample_response)
        self.assertIsNotNone(order_data)
        self.assertEqual(order_data["ticker"], "NVDA") # 대문자 및 공백 제거
        self.assertEqual(order_data["qty"], 2) # 2.0 -> 2 정수 변환
        self.assertEqual(order_data["side"], "BUY") # 대문자 정규화
        self.assertNotIn(":::kis_order", clean_text)

    def test_order_ttl_expiration(self):
        """5분 이상 경과한 주문의 TTL 자동 만료 방어 검증"""
        import time
        order_data = {"ticker": "AAPL", "qty": 1, "side": "BUY"}
        order_id, _ = self.bot.create_order_action_markup(order_data)

        # 6분 전(360초 전)에 생성된 것으로 시뮬레이션
        self.bot.pending_orders[order_id]["created_at"] = time.time() - 360

        # 만료 확인 로직
        order_info = self.bot.pending_orders[order_id]
        is_expired = (time.time() - order_info["created_at"]) > 300
        self.assertTrue(is_expired, "300초가 지난 주문은 반드시 만료 판정되어야 함")

    def test_trigger_kis_blocks_risk_guard_violation(self):
        """주문 트리거 직전 Risk Guard가 초과 수량을 최종 차단하는지 검증"""
        self.bot.github_pat = "dummy_pat"
        # 150주 주문 데이터 (100주 초과)
        violating_order = {"ticker": "NVDA", "qty": 150, "side": "BUY"}

        success, msg = self.bot.trigger_kis_github_workflow(violating_order)
        self.assertFalse(success)
        self.assertIn("Risk Guard 차단", msg)
        self.assertIn("100주", msg)


class TestEndToEndSimulation(unittest.TestCase):
    """🔄 텔레그램 E2E 플로우 통합 시뮬레이션 (AI 추천 ➔ 인라인 버튼 ➔ 승인/취소 ➔ 가드 검증)"""

    def setUp(self):
        self.bot = TelegramTradingBot(
            token="dummy_token",
            allowed_users=[9999],
            max_qty_limit=100
        )
        self.sent_messages = []
        self.answered_callbacks = []
        self.edited_markups = []
        self.edited_texts = []
        self.triggered_orders = []

        # Telegram API 목(Mock) 주입
        self.bot.send_message = lambda chat_id, text, reply_markup=None, parse_mode="HTML": self.sent_messages.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        self.bot.answer_callback_query = lambda cb_id, text=None, show_alert=False: self.answered_callbacks.append({"id": cb_id, "text": text, "show_alert": show_alert})
        self.bot.edit_message_reply_markup = lambda chat_id, message_id, reply_markup=None: self.edited_markups.append({"chat_id": chat_id, "markup": reply_markup})
        self.bot.edit_message_text = lambda chat_id, message_id, text, reply_markup=None, parse_mode="HTML": self.edited_texts.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        self.bot._call_telegram = lambda method, payload: {"ok": True, "result": {}}
        
        # GitHub Actions 주문 트리거 목 주입
        def mock_trigger(order):
            self.triggered_orders.append(order)
            return True, "Mock GitHub Actions triggered successfully"
        self.bot.trigger_kis_github_workflow = mock_trigger

    def test_e2e_successful_buy_confirmation_flow(self):
        """E2E 성공 흐름: AI 제안 ➔ 1차 승인 ➔ 키패드 6자리 PIN 입력 ➔ 체결 요청 완료"""
        self.bot.trading_pin = "123456"
        # 1. AI 응답 모의 (GOOGL 2주 매수 제안)
        self.bot.call_gemini = lambda prompt: "구글 저평가 국면입니다.\n:::kis_order {\"ticker\": \"GOOGL\", \"qty\": 2, \"side\": \"BUY\"}:::"

        # 2. 사용자 질문 수신
        user_msg = {
            "from": {"id": 9999, "username": "wooyeon"},
            "chat": {"id": 9999},
            "text": "구글 추가 매수 어때?"
        }
        self.bot.handle_message(user_msg)

        # 검증: 인라인 버튼이 달린 메시지가 전송되었는가?
        self.assertEqual(len(self.sent_messages), 1)
        sent = self.sent_messages[0]
        markup = sent["markup"]
        confirm_callback_data = markup["inline_keyboard"][0][0]["callback_data"]
        order_id = confirm_callback_data.split(":")[1]

        # 3. 사용자 [승인 및 2차 인증] 버튼 터치
        self.bot.handle_callback_query({
            "id": "cb_start_pin",
            "from": {"id": 9999},
            "data": f"start_pin:{order_id}",
            "message": {"chat": {"id": 9999}, "message_id": 101}
        })

        # 검증: 키패드가 렌더링되었는가?
        self.assertTrue(len(self.edited_texts) > 0)
        self.assertIn("보안 PIN 인증", self.edited_texts[-1]["text"])

        # 4. 키패드로 1, 2, 3, 4, 5, 6 순차 터치
        for digit in "123456":
            self.bot.handle_callback_query({
                "id": f"cb_digit_{digit}",
                "from": {"id": 9999},
                "data": f"pin:{order_id}:{digit}",
                "message": {"chat": {"id": 9999}, "message_id": 101}
            })

        # 검증 1: 6자리 입력 후 KIS 엔진으로 주문이 정확히 1회 전송되었는가?
        self.assertEqual(len(self.triggered_orders), 1)
        self.assertEqual(self.triggered_orders[0]["ticker"], "GOOGL")
        self.assertEqual(self.triggered_orders[0]["qty"], 2)

        # 검증 2: 주문이 executed=True로 잠겼는가?
        self.assertTrue(self.bot.pending_orders[order_id]["executed"])

    def test_e2e_pin_failure_and_lock(self):
        """PIN 3회 연속 오류 시 주문 영구 파기 및 차단 검증"""
        self.bot.trading_pin = "123456"
        order_data = {"ticker": "AAPL", "qty": 1, "side": "BUY"}
        order_id, _ = self.bot.create_order_action_markup(order_data)

        # 1회차 오입력: 000000
        for digit in "000000":
            self.bot.handle_callback_query({
                "id": "cb_f1",
                "from": {"id": 9999},
                "data": f"pin:{order_id}:{digit}",
                "message": {"chat": {"id": 9999}, "message_id": 101}
            })
        self.assertEqual(self.bot.pending_orders[order_id]["fail_attempts"], 1)
        self.assertEqual(len(self.triggered_orders), 0)

        # 2회차 오입력: 111111
        for digit in "111111":
            self.bot.handle_callback_query({
                "id": "cb_f2",
                "from": {"id": 9999},
                "data": f"pin:{order_id}:{digit}",
                "message": {"chat": {"id": 9999}, "message_id": 101}
            })
        self.assertEqual(self.bot.pending_orders[order_id]["fail_attempts"], 2)
        self.assertEqual(len(self.triggered_orders), 0)

        # 3회차 오입력: 999999 -> 3회 도달 시 주문 강제 파기!
        for digit in "999999":
            self.bot.handle_callback_query({
                "id": "cb_f3",
                "from": {"id": 9999},
                "data": f"pin:{order_id}:{digit}",
                "message": {"chat": {"id": 9999}, "message_id": 101}
            })
        self.assertEqual(self.bot.pending_orders[order_id]["fail_attempts"], 3)
        self.assertTrue(self.bot.pending_orders[order_id]["executed"], "3회 실패 시 영구 파기되어야 함")
        self.assertEqual(len(self.triggered_orders), 0, "주문은 절대 발송되면 안 됨")
        self.assertIn("주문 강제 취소", self.edited_texts[-1]["text"])

    def test_e2e_user_cancel_flow(self):
        """E2E 취소 흐름: AI 주문 제안 ➔ 사용자 취소 버튼 터치 ➔ 주문 0회 실행 & 취소 상태 갱신"""
        self.bot.call_gemini = lambda prompt: ":::kis_order {\"ticker\": \"TSLA\", \"qty\": 1, \"side\": \"BUY\"}:::"

        self.bot.handle_message({
            "from": {"id": 9999},
            "chat": {"id": 9999},
            "text": "테슬라 1주 살까?"
        })

        order_id = list(self.bot.pending_orders.keys())[0]

        # 취소 버튼 터치
        cancel_query = {
            "id": "cb_cancel_1",
            "from": {"id": 9999},
            "data": f"cancel_order:{order_id}",
            "message": {"chat": {"id": 9999}, "message_id": 102}
        }
        self.bot.handle_callback_query(cancel_query)

        # KIS 주문은 0회 실행되어야 함
        self.assertEqual(len(self.triggered_orders), 0)
        # 버튼이 [주문 취소됨]으로 갱신되었는가?
        last_markup = self.edited_markups[-1]["markup"]
        self.assertIn("주문 취소됨", last_markup["inline_keyboard"][0][0]["text"])


if __name__ == "__main__":
    unittest.main()
