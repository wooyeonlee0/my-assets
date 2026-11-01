#!/usr/bin/env python3
"""
Telegram AI Asset Assistant & Secure KIS Trading Bot
-----------------------------------------------------
- 1인 전용 화이트리스트 보안 기반 텔레그램 자산 관리 & 트레이딩 봇
- 기능:
  1) Gemini AI 자산비서 자연어 대화 & 포트폴리오 리밸런싱 상담
  2) 단일 종목 및 복합 배치(Basket / Rebalance) 인라인 버튼 자동 생성
  3) 🔐 2차 보안 PIN 가상 키패드 인증 (3회 오류 시 주문 영구 파기)
  4) Sell-First 정렬 & Rate Limit (0.5초) 보호 & 100주 하드 리밋
  5) 텔레그램 미니앱(Telegram Mini App, TWA) 상시 메뉴 버튼 연동
  6) 한국투자증권(KIS) GitHub Actions 서버리스 러너 트리거 & 체결 푸시
"""

import os
import sys
import json
import time
import uuid
import re
import html
import logging
from typing import Dict, Any, Optional, Tuple, List
import urllib.request
import urllib.error

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("TelegramTradingBot")

# core 모듈 임포트
try:
    from core.trading_core import (
        OrderItem,
        BatchOrder,
        validate_batch_risk_guard,
        parse_order_payload,
        format_batch_summary_html
    )
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from core.trading_core import (
        OrderItem,
        BatchOrder,
        validate_batch_risk_guard,
        parse_order_payload,
        format_batch_summary_html
    )

# 실자산 포트폴리오 기준 데이터
DEFAULT_PORTFOLIO_CONTEXT = """
[현재 보유 포트폴리오 요약 (실자산 기준)]
- 미국 주식: NVDA(28%), GOOGL(18%), TSLA(14%), AAPL(10%), MSFT(8%), AMZN(5%), CCL(3%), 기타(4%)
- 국내 주식: 삼성전자(12%), 기타(6%)
- 투자 성향: 안정적 장기 보유 및 성장주 분할 리밸런싱. 불필요한 단타 지양.
"""

# 단건(kis_order) 및 배치(kis_batch) 태그 정규식
ORDER_TAG_REGEX = re.compile(
    r":::(?:kis_order|kis_batch)\s*(?:```(?:json)?\s*)?(\{.*?\})(?:\s*```)?\s*:::",
    re.DOTALL
)
ORDER_TTL_SECONDS = 300 # 5분 유효시간
WEBAPP_URL = "https://wooyeonlee0.github.io/my-assets/"


class TelegramTradingBot:
    def __init__(
        self,
        token: Optional[str] = None,
        allowed_users: Optional[List[int]] = None,
        gemini_api_key: Optional[str] = None,
        github_pat: Optional[str] = None,
        github_repo: str = "wooyeonlee0/my-assets",
        max_qty_limit: int = 100,
        trading_pin: Optional[str] = None
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        # 화이트리스트 사용자 ID 파싱
        allowed_env = os.getenv("TELEGRAM_ALLOWED_USERS") or os.getenv("TELEGRAM_CHAT_ID", "")
        if allowed_users is not None:
            self.allowed_users = set(allowed_users)
        elif allowed_env:
            self.allowed_users = {int(uid.strip()) for uid in allowed_env.split(",") if uid.strip().lstrip("-").isdigit()}
        else:
            self.allowed_users = set()

        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.github_pat = github_pat or os.getenv("GITHUB_PAT", "").strip()
        self.github_repo = github_repo
        self.max_qty_limit = int(os.getenv("MAX_ORDER_QTY", str(max_qty_limit)))
        self.trading_pin = str(trading_pin or os.getenv("TRADING_PIN", "123456")).strip()

        # 인라인 주문 보관소 (batch_id -> {batch: BatchOrder, created_at, executed, pin_buffer, fail_attempts})
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def is_authorized(self, user_id: any) -> bool:
        """화이트리스트 사용자 검증"""
        if not self.allowed_users:
            logger.warning("⚠️ 화이트리스트가 설정되지 않았습니다. 모든 요청을 거부합니다.")
            return False
        try:
            return int(user_id) in self.allowed_users
        except (ValueError, TypeError):
            return False

    def _call_telegram(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """텔레그램 Bot API HTTP 요청 헬퍼"""
        if not self.token:
            return {"ok": False, "description": "Token not configured"}

        url = f"{self.base_url}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"Telegram API HTTP error {e.code}: {err_body}")
            return {"ok": False, "error_code": e.code, "description": err_body}
        except Exception as e:
            logger.error(f"Telegram API exception: {e}")
            return {"ok": False, "description": str(e)}

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Dict[str, Any]:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call_telegram("sendMessage", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Dict[str, Any]:
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        return self._call_telegram("answerCallbackQuery", payload)

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call_telegram("editMessageReplyMarkup", payload)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> Dict[str, Any]:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call_telegram("editMessageText", payload)

    def extract_order_from_text(self, text: str) -> Tuple[str, Optional[BatchOrder]]:
        """AI 응답 본문에서 단건/배치 주문 태그를 감지하고 표준 BatchOrder로 추출"""
        match = ORDER_TAG_REGEX.search(text)
        if not match:
            return text.strip(), None

        raw_json = match.group(1).strip()
        clean_text = ORDER_TAG_REGEX.sub("", text).strip()

        success, err, batch = parse_order_payload(raw_json)
        if success and batch.orders:
            return clean_text, batch

        return clean_text, None

    def call_gemini(self, user_prompt: str) -> str:
        """Gemini AI API 호출 (배치 리밸런싱 지원 프롬프트)"""
        if not self.gemini_api_key:
            return "⚠️ Gemini API 키가 설정되지 않았습니다."

        system_instruction = (
            "너는 사용자의 7.1억 원 규모 실자산 포트폴리오를 관리하는 'AI 자산관리 비서'다. "
            "친절하고 논리적으로 분석하되, 주문을 제안할 때는 단일 종목이든 여러 종목 리밸런싱이든 "
            "반드시 아래의 표준 배치 태그를 사용해라:\n"
            ":::kis_batch {\"type\": \"REBALANCE|BUY|SELL\", \"orders\": [{\"ticker\": \"종목코드\", \"qty\": 수량(정수), \"side\": \"BUY\"|\"SELL\"}]}:::\n"
            "종목당 1회 수량은 절대 100주를 넘지 마라."
        )

        full_prompt = f"{DEFAULT_PORTFOLIO_CONTEXT}\n\n[사용자 질문]: {user_prompt}"

        # ⚡ 3.8-Flash 이상 최상위 모델만 한정 순회
        models = ["gemini-3.8-flash", "gemini-4-argon"]
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_api_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": full_prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=12) as res:
                    res_json = json.loads(res.read().decode("utf-8"))
                    candidates = res_json.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"]
            except Exception as e:
                logger.warning(f"모델 {model} 호출 실패: {e}")
                continue

        return "⚠️ Gemini AI 응답 생성 중 오류가 발생했습니다."

    def create_order_action_markup(self, batch_or_order: Any) -> Tuple[str, Dict[str, Any]]:
        """표준 BatchOrder 등록 및 인라인 승인 키보드 생성"""
        if isinstance(batch_or_order, BatchOrder):
            batch = batch_or_order
        else:
            # 딕셔너리 호환
            _, _, batch = parse_order_payload(batch_or_order)

        order_id = batch.batch_id
        self.pending_orders[order_id] = {
            "batch": batch,
            "orders": batch.orders,
            "created_at": time.time(),
            "executed": False,
            "pin_buffer": "",
            "fail_attempts": 0
        }

        total_orders = len(batch.orders)
        if total_orders == 1:
            o = batch.orders[0]
            side_ko = "매수" if o.side == "BUY" else "매도"
            btn_text = f"🚀 {o.ticker} {o.qty}주 {side_ko} 승인 및 2차 PIN 인증"
        else:
            btn_text = f"🚀 배치 {total_orders}건 일괄 승인 및 2차 PIN 인증"

        reply_markup = {
            "inline_keyboard": [
                [{"text": btn_text, "callback_data": f"start_pin:{order_id}"}],
                [{"text": "❌ 주문 취소", "callback_data": f"cancel_order:{order_id}"}]
            ]
        }
        return order_id, reply_markup

    def render_pin_keypad(self, order_id: str) -> Tuple[str, Dict[str, Any]]:
        """🔐 2차 보안 PIN 입력 가상 키패드 렌더링"""
        order_info = self.pending_orders.get(order_id, {})
        batch: BatchOrder = order_info.get("batch")
        pin_buffer = order_info.get("pin_buffer", "")
        attempts = order_info.get("fail_attempts", 0)

        masked_slots = " ".join(["●" if i < len(pin_buffer) else "○" for i in range(6)])
        summary_title = f"{batch.orders[0].ticker} 외 {len(batch.orders)-1}건" if len(batch.orders) > 1 else f"{batch.orders[0].ticker} {batch.orders[0].qty}주"

        text = (
            f"🔐 <b>[한투 주문 2차 보안 PIN 인증]</b>\n\n"
            f"• <b>대상</b>: <code>{summary_title}</code> (총 {len(batch.orders)}건)\n"
            f"• <b>인증 상태</b>: [ {masked_slots} ]\n"
            f"• <b>남은 기회</b>: {3 - attempts}회\n\n"
            f"안전을 위해 <b>6자리 보안 PIN</b>을 키패드로 입력해주세요:"
        )

        keyboard = [
            [{"text": "1", "callback_data": f"pin:{order_id}:1"}, {"text": "2", "callback_data": f"pin:{order_id}:2"}, {"text": "3", "callback_data": f"pin:{order_id}:3"}],
            [{"text": "4", "callback_data": f"pin:{order_id}:4"}, {"text": "5", "callback_data": f"pin:{order_id}:5"}, {"text": "6", "callback_data": f"pin:{order_id}:6"}],
            [{"text": "7", "callback_data": f"pin:{order_id}:7"}, {"text": "8", "callback_data": f"pin:{order_id}:8"}, {"text": "9", "callback_data": f"pin:{order_id}:9"}],
            [{"text": "⌫", "callback_data": f"pin:{order_id}:back"}, {"text": "0", "callback_data": f"pin:{order_id}:0"}, {"text": "❌ 취소", "callback_data": f"cancel_order:{order_id}"}]
        ]
        return text, {"inline_keyboard": keyboard}

    def trigger_kis_github_workflow(self, batch_or_dict: Any) -> Tuple[bool, str]:
        """GitHub Actions 서버리스 러너를 트리거하여 KIS 주문을 집행"""
        if not self.github_pat:
            return False, "GITHUB_PAT가 설정되지 않았습니다."

        if isinstance(batch_or_dict, BatchOrder):
            batch = batch_or_dict
        else:
            _, _, batch = parse_order_payload(batch_or_dict)

        # Risk Guard 및 Sell-First 순서 정렬 재검증
        is_valid, err_msg, validated_batch = validate_batch_risk_guard(batch, max_single_qty=self.max_qty_limit)
        if not is_valid:
            logger.error(f"❌ [Risk Guard 차단] {err_msg}")
            return False, f"Risk Guard 차단: {err_msg}"

        url = f"https://api.github.com/repos/{self.github_repo}/actions/workflows/kis_order.yml/dispatches"
        payload = {
            "ref": "master",
            "inputs": {
                "batch_json": validated_batch.to_json(),
                # 하위 호환성용 단건 파라미터 (첫 번째 주문 기준)
                "ticker": validated_batch.orders[0].ticker,
                "qty": str(validated_batch.orders[0].qty),
                "order_type": validated_batch.orders[0].side,
                "market": "AUTO",
                "price": validated_batch.orders[0].price
            }
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.github_pat}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Telegram-Trading-Bot"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as res:
                if res.status in (200, 204):
                    return True, "GitHub Actions 서버리스 주문 러너 가동 성공"
                return False, f"GitHub HTTP Status: {res.status}"
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"GitHub Actions dispatch failed: {e.code} {err_msg}")
            return False, f"GitHub 오류({e.code}): {err_msg}"
        except Exception as e:
            logger.error(f"GitHub Actions dispatch exception: {e}")
            return False, str(e)

    def get_twa_main_keyboard(self) -> Dict[str, Any]:
        """텔레그램 미니앱(Telegram Mini App, TWA) 상시 메뉴 버튼"""
        return {
            "keyboard": [
                [
                    {
                        "text": "📱 실자산 대시보드 & 바스켓 열기",
                        "web_app": {"url": WEBAPP_URL}
                    }
                ],
                [
                    {"text": "/portfolio"},
                    {"text": "/status"}
                ]
            ],
            "resize_keyboard": True,
            "is_persistent": True
        }

    def handle_message(self, message: Dict[str, Any]):
        """일반 텍스트 및 AI 대화 처리"""
        user_info = message.get("from", {})
        user_id = user_info.get("id")
        chat_id = message.get("chat", {}).get("id")
        text = str(message.get("text", "")).strip()

        logger.info(f"수신 메시지 from {user_id} ({user_info.get('username')}): {text}")

        if not self.is_authorized(user_id):
            logger.warning(f"🚫 [차단] 비인가 사용자 접근: {user_id}")
            self.send_message(chat_id, "⛔ <b>[접근 거부]</b> 1인 전용 비공개 봇입니다.")
            return

        # 2단계: 텔레그램 딥링크 주문 수신 (/start NVDA.3.S_GOOGL.2.B 등)
        if text.startswith("/start "):
            deeplink_param = text[7:].strip()
            success, _, batch = parse_order_payload(deeplink_param)
            if success and batch.orders:
                order_id, reply_markup = self.create_order_action_markup(batch)
                summary_html = format_batch_summary_html(batch)
                card_text = (
                    f"✨ <b>[Gemini AI Pro(Argon) 딥링크 주문 감지]</b>\n\n"
                    f"{summary_html}\n\n"
                    f"🔒 <b>안전 확인</b>: 아래 버튼을 터치하고 6자리 보안 PIN을 입력하면 한투 서버로 주문이 집행됩니다."
                )
                self.send_message(chat_id, card_text, reply_markup=reply_markup)
                return

        if text.startswith("/start") or text.startswith("/help"):
            welcome_msg = (
                "🤖 <b>[AI 자산관리 & KIS 주문 봇]</b>\n\n"
                "• <b>내 포트폴리오 비중 상담</b>: 원하는 질문을 자유롭게 입력하세요.\n"
                "  <i>예: 'NVDA 비중 줄이고 구글 채워줘', '월 적립식 매수 바스켓 짜줘'</i>\n\n"
                "📱 <b>텔레그램 미니앱 연동</b>:\n"
                "하단의 <b>[📱 7.1억 자산 대시보드 열기]</b> 버튼을 누르면 메신저 안에서 풀버전 차트와 바스켓을 바로 열 수 있습니다."
            )
            self.send_message(chat_id, welcome_msg, reply_markup=self.get_twa_main_keyboard())
            return

        if text.startswith("/portfolio") or text.startswith("/자산"):
            self.send_message(
                chat_id,
                f"📊 <b>[실자산 포트폴리오 비중 요약]</b>\n\n"
                f"• <b>총 평가액</b>: 약 7.1억 원 (안정적 장기 보유)\n"
                f"• <b>주요 종목 비중</b>:\n"
                f"  - NVDA: 28% | GOOGL: 18% | TSLA: 14%\n"
                f"  - AAPL: 10% | 삼성전자: 12% | 기타: 18%\n\n"
                f"💡 <i>리밸런싱이나 바스켓 주문은 자연어로 말씀해주세요.</i>",
                reply_markup=self.get_twa_main_keyboard()
            )
            return

        if text.startswith("/status"):
            self.send_message(
                chat_id,
                f"⚙️ <b>[시스템 상태 보고]</b>\n\n"
                f"• <b>인증 상태</b>: ✅ 인가됨 (User ID: {user_id})\n"
                f"• <b>Risk Guard 한도</b>: 종목당 최대 {self.max_qty_limit}주\n"
                f"• <b>파이프라인</b>: Sell-First 매도 우선 체결 보장\n"
                f"• <b>대기 중인 주문 수</b>: {len([o for o in self.pending_orders.values() if not o.get('executed')])}건"
            )
            return

        # AI 질의응답
        self._call_telegram("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        ai_response = self.call_gemini(text)
        clean_text, batch = self.extract_order_from_text(ai_response)

        if batch:
            order_id, reply_markup = self.create_order_action_markup(batch)
            summary_html = format_batch_summary_html(batch)
            card_text = (
                f"{clean_text}\n\n"
                f"{summary_html}\n\n"
                f"⚠️ <i>아래 [일괄 승인] 버튼을 누르고 6자리 PIN을 입력해야 증권사로 정식 발송됩니다.</i>"
            )
            self.send_message(chat_id, card_text, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, clean_text, reply_markup=self.get_twa_main_keyboard())

    def handle_callback_query(self, callback_query: Dict[str, Any]):
        """인라인 키보드 및 PIN 키패드 처리"""
        cb_id = callback_query.get("id")
        user_id = callback_query.get("from", {}).get("id")
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if not self.is_authorized(user_id):
            self.answer_callback_query(cb_id, text="⛔ 인가되지 않은 사용자입니다.", show_alert=True)
            return

        if data.startswith("cancel_order:"):
            order_id = data.split(":")[1]
            if order_id in self.pending_orders:
                self.pending_orders[order_id]["executed"] = True
            self.answer_callback_query(cb_id, text="주문이 취소되었습니다.")
            self.edit_message_reply_markup(chat_id, message_id, reply_markup={"inline_keyboard": [[{"text": "❌ [주문 취소됨]", "callback_data": "noop"}]]})
            return

        if data.startswith("start_pin:") or data.startswith("confirm_order:"):
            order_id = data.split(":")[1]
            order_info = self.pending_orders.get(order_id)

            if not order_info:
                self.answer_callback_query(cb_id, text="⚠️ 만료되었거나 존재하지 않는 주문입니다.", show_alert=True)
                return

            if time.time() - order_info.get("created_at", 0) > ORDER_TTL_SECONDS:
                self.answer_callback_query(cb_id, text="⚠️ 5분이 초과되어 주문이 만료되었습니다.", show_alert=True)
                self.edit_message_reply_markup(chat_id, message_id, reply_markup={"inline_keyboard": [[{"text": "⌛ [주문 만료됨]", "callback_data": "noop"}]]})
                return

            if order_info.get("executed"):
                self.answer_callback_query(cb_id, text="이미 처리된 주문입니다.", show_alert=False)
                return

            text, markup = self.render_pin_keypad(order_id)
            self.answer_callback_query(cb_id, text="🔐 6자리 보안 PIN을 입력해주세요.")
            self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
            return

        if data.startswith("pin:"):
            parts = data.split(":")
            if len(parts) < 3:
                return
            order_id, action = parts[1], parts[2]
            order_info = self.pending_orders.get(order_id)

            if not order_info or order_info.get("executed"):
                self.answer_callback_query(cb_id, text="이미 처리되었거나 유효하지 않은 주문입니다.", show_alert=False)
                return

            if action == "back":
                order_info["pin_buffer"] = order_info.get("pin_buffer", "")[:-1]
                text, markup = self.render_pin_keypad(order_id)
                self.answer_callback_query(cb_id)
                self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
                return

            if action in "0123456789":
                pin_buf = order_info.get("pin_buffer", "")
                if len(pin_buf) < 6:
                    pin_buf += action
                    order_info["pin_buffer"] = pin_buf

                if len(pin_buf) < 6:
                    self.answer_callback_query(cb_id)
                    text, markup = self.render_pin_keypad(order_id)
                    self.edit_message_text(chat_id, message_id, text, reply_markup=markup)
                    return

                # 6자리 완성 시 검증
                if pin_buf == self.trading_pin:
                    order_info["executed"] = True
                    batch: BatchOrder = order_info["batch"]
                    self.answer_callback_query(cb_id, text=f"✅ PIN 인증 성공! 총 {len(batch.orders)}건 주문을 전송합니다.")
                    self.edit_message_text(
                        chat_id,
                        message_id,
                        f"🔐 <b>[2차 보안 PIN 인증 완료]</b>\n\n"
                        f"• <b>대상</b>: 총 {len(batch.orders)}건 (타입: {batch.batch_type})\n"
                        f"⏳ 한투 서버리스 러너로 전송 중입니다...",
                        reply_markup={"inline_keyboard": [[{"text": "⏳ [한투 서버로 전송 중...]", "callback_data": "noop"}]]}
                    )

                    success, msg = self.trigger_kis_github_workflow(batch)
                    if success:
                        self.edit_message_reply_markup(chat_id, message_id, reply_markup={"inline_keyboard": [[{"text": f"✅ [배치 {len(batch.orders)}건 요청 완료]", "callback_data": "noop"}]]})
                        self.send_message(
                            chat_id,
                            f"✅ <b>[한투 배치 주문 발송 완료]</b>\n\n"
                            f"• <b>총 주문 건수</b>: <b>{len(batch.orders)}건</b>\n"
                            f"• <b>파이프라인</b>: Sell-First 매도 우선 순차 체결\n"
                            f"• <b>결과</b>: GitHub Actions 가동 시작\n\n"
                            f"체결이 완료되면 텔레그램으로 최종 결과가 통보됩니다."
                        )
                    else:
                        self.edit_message_reply_markup(chat_id, message_id, reply_markup={"inline_keyboard": [[{"text": f"❌ [주문 실패: {msg[:20]}]", "callback_data": "noop"}]]})
                        self.send_message(chat_id, f"❌ <b>[주문 전송 실패]</b>: {msg}")
                else:
                    order_info["fail_attempts"] = order_info.get("fail_attempts", 0) + 1
                    order_info["pin_buffer"] = ""
                    attempts = order_info["fail_attempts"]

                    if attempts >= 3:
                        order_info["executed"] = True
                        self.answer_callback_query(cb_id, text="⛔ 3회 연속 PIN 오류로 주문이 취소되었습니다.", show_alert=True)
                        self.edit_message_text(
                            chat_id,
                            message_id,
                            "⛔ <b>[주문 강제 취소]</b>\n3회 연속 보안 PIN 오류로 주문이 파기되었습니다.",
                            reply_markup={"inline_keyboard": [[{"text": "❌ [보안 잠금됨]", "callback_data": "noop"}]]}
                        )
                    else:
                        self.answer_callback_query(cb_id, text=f"❌ PIN 불일치! (남은 기회: {3 - attempts}회)", show_alert=True)
                        text, markup = self.render_pin_keypad(order_id)
                        self.edit_message_text(chat_id, message_id, text, reply_markup=markup)

    def run_polling(self, interval: float = 1.0):
        """롱 폴링 메인 루프"""
        logger.info("🤖 통합 트레이딩 코어 텔레그램 봇 가동 시작...")
        logger.info(f"🛡️ 인가된 사용자 ID: {self.allowed_users or '설정 안 됨'}")
        logger.info(f"🛡️ 종목당 최대 주문 한도: {self.max_qty_limit}주")

        offset = 0
        while True:
            try:
                updates_res = self._call_telegram("getUpdates", {"offset": offset, "timeout": 20})
                if not updates_res.get("ok"):
                    time.sleep(interval)
                    continue

                for update in updates_res.get("result", []):
                    offset = max(offset, update.get("update_id", 0) + 1)
                    if "message" in update:
                        self.handle_message(update["message"])
                    elif "callback_query" in update:
                        self.handle_callback_query(update["callback_query"])
            except KeyboardInterrupt:
                logger.info("봇 종료 신호 수신. 안전 종료합니다.")
                break
            except Exception as e:
                logger.error(f"Polling loop exception: {e}")
                time.sleep(interval)


if __name__ == "__main__":
    bot = TelegramTradingBot()
    bot.run_polling()
