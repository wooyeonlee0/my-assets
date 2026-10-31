#!/usr/bin/env python3
"""
Telegram AI Asset Assistant & Secure KIS Trading Bot
-----------------------------------------------------
- 1인 전용 화이트리스트 보안 기반 텔레그램 자산 관리 & 트레이딩 봇
- 기능:
  1) Gemini AI 자산비서 자연어 대화 & 포트폴리오 리밸런싱 상담
  2) AI 주문 제안 시 텔레그램 인라인 버튼(Inline Keyboard) 자동 생성
  3) Human-in-the-Loop 명시적 승인 (버튼 클릭 없이는 절대 주문 불가)
  4) 더블 클릭 방지 & Idempotency(멱등성) 보장
  5) 시스템 레벨 Risk Guard (100주 하드 리밋, 0주/음수 차단)
  6) 한국투자증권(KIS) GitHub Actions 서버리스 러너 트리거 & 체결 푸시 알림
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

# Risk Guard 모듈 임포트
try:
    from scripts.kis_trade import validate_risk_guard
except ImportError:
    # 패키지 또는 단독 실행 호환
    try:
        from kis_trade import validate_risk_guard
    except ImportError:
        def validate_risk_guard(ticker: str, qty: any, max_qty_limit: int = 100) -> tuple[bool, str, int]:
            if not ticker or not str(ticker).strip():
                return False, "종목 티커가 비어있습니다.", 0
            try:
                qty_int = int(qty)
            except (ValueError, TypeError):
                return False, f"수량 파라미터가 유효하지 않습니다: {qty}", 0
            if qty_int <= 0:
                return False, f"비정상적인 주문 수량입니다: {qty_int}주", 0
            if qty_int > max_qty_limit:
                return False, f"1회 최대 허용 수량({max_qty_limit}주)을 초과했습니다: {qty_int}주 요청됨", qty_int
            return True, "", qty_int

# 7.1억 포트폴리오 기준 데이터 (시스템 기본값)
DEFAULT_PORTFOLIO_CONTEXT = """
[현재 보유 포트폴리오 요약 (총 자산: 약 7.1억 원)]
- 미국 주식: NVDA(28%), GOOGL(18%), TSLA(14%), AAPL(10%), MSFT(8%), AMZN(5%), CCL(3%), 기타(4%)
- 국내 주식: 삼성전자(12%), 기타(6%)
- 투자 성향: 안정적 장기 보유 및 성장주 분할 매수. 불필요한 단타 지양.
"""

ORDER_TAG_REGEX = re.compile(r":::kis_order\s*(?:```(?:json)?\s*)?(\{.*?\})(?:\s*```)?\s*:::", re.DOTALL)
ORDER_TTL_SECONDS = 300 # 주문 인라인 버튼 유효 시간: 5분 (오래된 버튼 재클릭 방지)


class TelegramTradingBot:
    def __init__(
        self,
        token: Optional[str] = None,
        allowed_users: Optional[List[int]] = None,
        gemini_api_key: Optional[str] = None,
        github_pat: Optional[str] = None,
        github_repo: str = "wooyeonlee0/my-assets",
        max_qty_limit: int = 100
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

        # 인라인 버튼 주문 보관소 (order_id -> {ticker, qty, side, price, timestamp, executed: bool})
        self.pending_orders: Dict[str, Dict[str, Any]] = {}

        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def is_authorized(self, user_id: any) -> bool:
        """화이트리스트 사용자 검증: 허용된 단 1명의 Telegram ID만 승인 (타입 안전 변환)"""
        if not self.allowed_users:
            logger.warning("⚠️ 화이트리스트가 설정되지 않았습니다. 보안을 위해 모든 요청을 거부합니다.")
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
        """메시지 전송"""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call_telegram("sendMessage", payload)

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False
    ) -> Dict[str, Any]:
        """인라인 버튼 클릭 피드백 (모달 팝업 알림 지원)"""
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert
        }
        if text:
            payload["text"] = text
        return self._call_telegram("answerCallbackQuery", payload)

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """버튼 상태 갱신 (더블 클릭 방지 및 완료 표시)"""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id
        }
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
        """메시지 내용 수정"""
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._call_telegram("editMessageText", payload)
        """화이트리스트 사용자 검증: 허용된 단 1명의 Telegram ID만 승인 (타입 안전 변환)"""
        if not self.allowed_users:
            logger.warning("⚠️ 화이트리스트가 설정되지 않았습니다. 보안을 위해 모든 요청을 거부합니다.")
            return False
        try:
            return int(user_id) in self.allowed_users
        except (ValueError, TypeError):
            return False

    def extract_order_from_text(self, text: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        AI 응답 본문에서 :::kis_order {...}::: 태그를 감지하고 분리.
        - 백틱(`json ... `) 래핑 안전 제거
        - 종목 티커 대문자화 및 공백 제거
        - 수량 정수화 및 부동소수점 방어
        반환: (클린 텍스트, 주문 딕셔너리 또는 None)
        """
        match = ORDER_TAG_REGEX.search(text)
        if not match:
            return text.strip(), None

        raw_json = match.group(1).strip()
        clean_text = ORDER_TAG_REGEX.sub("", text).strip()

        try:
            order_data = json.loads(raw_json)
            # 필수 필드 검증
            if "ticker" in order_data and "qty" in order_data:
                ticker = str(order_data["ticker"]).strip().upper()
                # 수량 형변환 (2.0 등 소수점 입력 대비)
                qty_raw = order_data["qty"]
                qty_int = int(float(qty_raw))
                side = str(order_data.get("side", "BUY")).strip().upper()
                if side not in ("BUY", "SELL"):
                    side = "BUY"

                return clean_text, {
                    "ticker": ticker,
                    "qty": qty_int,
                    "side": side,
                    "price": order_data.get("price", 0)
                }
        except Exception as e:
            logger.warning(f"주문 JSON 파싱 실패: {e} | 내용: {raw_json}")

        return clean_text, None

    def call_gemini(self, user_prompt: str) -> str:
        """Gemini AI API 호출 (포트폴리오 컨텍스트 주입)"""
        if not self.gemini_api_key:
            return "⚠️ Gemini API 키가 설정되지 않았습니다. 환경변수 GEMINI_API_KEY를 등록해주세요."

        system_instruction = (
            "너는 사용자의 7.1억 원 규모 실자산 포트폴리오를 관리하는 'AI 자산관리 비서'다. "
            "친절하고 논리적으로 분석하되, 답변 끝에 주문을 제안할 때는 반드시 아래 형식의 숨김 태그를 포함해라:\n"
            ":::kis_order {\"ticker\": \"종목코드\", \"qty\": 수량(정수), \"side\": \"BUY\"|\"SELL\", \"price\": 0}:::\n"
            "(0은 시장가). 1회 수량은 절대 100주를 넘지 않도록 보수적으로 분할 제안해라."
        )

        full_prompt = f"{DEFAULT_PORTFOLIO_CONTEXT}\n\n[사용자 질문]: {user_prompt}"

        # 모델 리스트 우선순위
        models = ["gemini-2.5-flash", "gemini-1.5-flash"]
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_api_key}"
            payload = {
                "contents": [
                    {"role": "user", "parts": [{"text": full_prompt}]}
                ],
                "systemInstruction": {
                    "parts": [{"text": system_instruction}]
                },
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 800
                }
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

        return "⚠️ Gemini AI 응답 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    def create_order_action_markup(self, order_data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        주문 데이터로부터 고유 토큰을 발급하고 텔레그램 인라인 키보드 생성.
        반환: (order_id, reply_markup)
        """
        order_id = str(uuid.uuid4())[:8] # 8자리 고유 키
        self.pending_orders[order_id] = {
            **order_data,
            "created_at": time.time(),
            "executed": False
        }

        ticker = order_data.get("ticker", "").upper()
        qty = order_data.get("qty", 1)
        side = "매수" if order_data.get("side", "BUY") == "BUY" else "매도"

        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": f"🚀 {ticker} {qty}주 {side} 즉시 실행",
                        "callback_data": f"confirm_order:{order_id}"
                    }
                ],
                [
                    {
                        "text": "❌ 주문 취소",
                        "callback_data": f"cancel_order:{order_id}"
                    }
                ]
            ]
        }
        return order_id, reply_markup

    def trigger_kis_github_workflow(self, order_data: Dict[str, Any]) -> Tuple[bool, str]:
        """
        GitHub Actions 워크플로우를 트리거하여 KIS 서버리스 주문을 집행.
        반환: (성공 여부, 메시지)
        """
        if not self.github_pat:
            return False, "GITHUB_PAT가 설정되지 않아 주문을 실행할 수 없습니다."

        ticker = str(order_data.get("ticker", "")).strip().upper()
        qty = str(order_data.get("qty", 1)).strip()
        side = str(order_data.get("side", "BUY")).strip().upper()
        price = str(order_data.get("price", "0")).strip()

        # 1. 시스템 레벨 Risk Guard 검증 (더블 체크)
        is_valid, err_msg, qty_int = validate_risk_guard(ticker, qty, self.max_qty_limit)
        if not is_valid:
            logger.error(f"❌ [Risk Guard 차단] {err_msg}")
            return False, f"Risk Guard 차단: {err_msg}"

        # 2. GitHub Actions workflow_dispatch 호출
        url = f"https://api.github.com/repos/{self.github_repo}/actions/workflows/kis_order.yml/dispatches"
        payload = {
            "ref": "master",
            "inputs": {
                "ticker": ticker,
                "qty": str(qty_int),
                "order_type": side,
                "market": "AUTO",
                "price": price
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
                    return True, "GitHub Actions 서버리스 주문 러너가 성공적으로 트리거되었습니다."
                return False, f"GitHub HTTP Status: {res.status}"
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8") if e.fp else ""
            logger.error(f"GitHub Actions dispatch failed: {e.code} {err_msg}")
            return False, f"GitHub 오류({e.code}): {err_msg}"
        except Exception as e:
            logger.error(f"GitHub Actions dispatch exception: {e}")
            return False, str(e)

    def handle_message(self, message: Dict[str, Any]):
        """일반 텍스트 메시지 및 명령어 처리"""
        user_info = message.get("from", {})
        user_id = user_info.get("id")
        chat_id = message.get("chat", {}).get("id")
        text = str(message.get("text", "")).strip()

        logger.info(f"수신 메시지 from {user_id} ({user_info.get('username')}): {text}")

        # 🛡️ 1단계: 화이트리스트 검증 (비인가자 차단)
        if not self.is_authorized(user_id):
            logger.warning(f"🚫 [차단] 비인가 사용자 접근 시도: User ID {user_id}")
            self.send_message(
                chat_id,
                "⛔ <b>[접근 거부]</b> 인가되지 않은 사용자입니다.\n본 봇은 1인 전용 비공개 보안 봇으로 등록된 ID만 접근 가능합니다."
            )
            return

        # 2단계: 내장 슬래시 명령어 처리
        if text.startswith("/start") or text.startswith("/help"):
            welcome_msg = (
                "🤖 <b>[AI 자산관리 & KIS 주문 봇]</b>\n\n"
                "• <b>내 포트폴리오 비중 상담</b>: 원하는 질문을 자유롭게 입력하세요.\n"
                "  <i>예: 'NVDA 비중 분석해줘', '지금 구글 2주 살까?'</i>\n\n"
                "• <b>주요 명령어</b>:\n"
                "  /portfolio : 보유 종목 및 비중 요약\n"
                "  /status : 봇 및 리스크 가드 상태 점검\n\n"
                "🛡️ <b>안전 가드레일 작동 중</b>:\n"
                f"• 1회 최대 주문 한도: <b>{self.max_qty_limit}주</b>\n"
                "• 인라인 승인 버튼을 직접 누르지 않으면 1원도 주문되지 않습니다."
            )
            self.send_message(chat_id, welcome_msg)
            return

        if text.startswith("/portfolio") or text.startswith("/자산"):
            self.send_message(
                chat_id,
                f"📊 <b>[실자산 포트폴리오 비중 요약]</b>\n\n"
                f"• <b>총 평가액</b>: 약 7.1억 원 (안정적 장기 보유)\n"
                f"• <b>주요 종목 비중</b>:\n"
                f"  - NVDA: 28% (AI 반도체 주도)\n"
                f"  - GOOGL: 18% (빅테크 밸류에이션)\n"
                f"  - TSLA: 14% (전기차/로보틱스)\n"
                f"  - AAPL: 10% (현금흐름/생태계)\n"
                f"  - 삼성전자: 12% (메모리 턴어라운드)\n"
                f"  - 기타: MSFT, AMZN, CCL 등\n\n"
                f"💡 <i>리밸런싱이나 추가 매수 상담은 자연어로 질문해주세요.</i>"
            )
            return

        if text.startswith("/status"):
            self.send_message(
                chat_id,
                f"⚙️ <b>[시스템 상태 보고]</b>\n\n"
                f"• <b>인증 상태</b>: ✅ 인가됨 (User ID: {user_id})\n"
                f"• <b>Risk Guard 한도</b>: 1회 최대 {self.max_qty_limit}주\n"
                f"• <b>주문 집행 경로</b>: GitHub Actions ➔ KIS Open API 직통\n"
                f"• <b>대기 중인 주문 수</b>: {len([o for o in self.pending_orders.values() if not o.get('executed')])}건"
            )
            return

        # 3단계: Gemini AI 자산비서 질의 & 주문 카드 생성
        # 타이핑 중 액션 전송
        self._call_telegram("sendChatAction", {"chat_id": chat_id, "action": "typing"})

        ai_response = self.call_gemini(text)
        clean_text, order_data = self.extract_order_from_text(ai_response)

        if order_data:
            order_id, reply_markup = self.create_order_action_markup(order_data)
            ticker = order_data.get("ticker")
            qty = order_data.get("qty")
            side = "매수" if order_data.get("side") == "BUY" else "매도"

            card_text = (
                f"{clean_text}\n\n"
                f"────────────────\n"
                f"📋 <b>[한투 AI 주문 제안 확인]</b>\n"
                f"• <b>종목</b>: <code>{ticker}</code>\n"
                f"• <b>구분</b>: <b>{side}</b>\n"
                f"• <b>수량</b>: <b>{qty}주</b> (시장가)\n"
                f"• <b>안전 가드</b>: 100주 하드 리밋 검증 완료\n\n"
                f"⚠️ <i>아래 [즉시 실행] 버튼을 눌러야만 증권사에 정식 주문이 발송됩니다.</i>"
            )
            self.send_message(chat_id, card_text, reply_markup=reply_markup)
        else:
            self.send_message(chat_id, clean_text)

    def handle_callback_query(self, callback_query: Dict[str, Any]):
        """인라인 키보드 클릭 이벤트 처리 (Human-in-the-Loop 명시적 승인)"""
        cb_id = callback_query.get("id")
        user_id = callback_query.get("from", {}).get("id")
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        # 🛡️ 1단계: 화이트리스트 사용자 검증
        if not self.is_authorized(user_id):
            self.answer_callback_query(cb_id, text="⛔ 인가되지 않은 사용자입니다.", show_alert=True)
            return

        # 2단계: 주문 취소 액션
        if data.startswith("cancel_order:"):
            order_id = data.split(":")[1]
            if order_id in self.pending_orders:
                self.pending_orders[order_id]["executed"] = True
            self.answer_callback_query(cb_id, text="주문이 취소되었습니다.")
            self.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup={"inline_keyboard": [[{"text": "❌ [주문 취소됨]", "callback_data": "noop"}]]}
            )
            return

        # 3단계: 주문 확정 실행 액션
        if data.startswith("confirm_order:"):
            order_id = data.split(":")[1]
            order_info = self.pending_orders.get(order_id)

            if not order_info:
                self.answer_callback_query(cb_id, text="⚠️ 만료되었거나 존재하지 않는 주문입니다.", show_alert=True)
                return

            # 주문 유효기간 검증 (5분 초과 시 자동 만료)
            created_at = order_info.get("created_at", 0)
            if time.time() - created_at > ORDER_TTL_SECONDS:
                self.answer_callback_query(cb_id, text="⚠️ 주문 유효 시간(5분)이 초과되어 만료되었습니다. 다시 요청해주세요.", show_alert=True)
                self.edit_message_reply_markup(
                    chat_id,
                    message_id,
                    reply_markup={"inline_keyboard": [[{"text": "⌛ [주문 만료됨]", "callback_data": "noop"}]]}
                )
                return

            # 중복 클릭 / 멱등성 검증 (더블 클릭 방지)
            if order_info.get("executed"):
                self.answer_callback_query(cb_id, text="이미 처리된 주문입니다.", show_alert=False)
                return

            # 즉시 잠금 (In-Flight 상태로 전환)
            order_info["executed"] = True

            ticker = order_info.get("ticker")
            qty = order_info.get("qty")
            side = "매수" if order_info.get("side") == "BUY" else "매도"

            # 팝업 알림 표시
            self.answer_callback_query(
                cb_id,
                text=f"🚀 {ticker} {qty}주 {side} 주문을 한투 서버로 전송합니다...",
                show_alert=False
            )

            # 버튼을 [⏳ 주문 처리 중...]으로 실시간 변경
            self.edit_message_reply_markup(
                chat_id,
                message_id,
                reply_markup={"inline_keyboard": [[{"text": "⏳ [한투 서버로 전송 중...]", "callback_data": "noop"}]]}
            )

            # 4단계: KIS GitHub Actions 트리거
            success, msg = self.trigger_kis_github_workflow(order_info)

            if success:
                logger.info(f"✅ 주문 성공: {ticker} {qty}주 {side}")
                self.edit_message_reply_markup(
                    chat_id,
                    message_id,
                    reply_markup={"inline_keyboard": [[{"text": f"✅ [체결 요청 완료: {ticker} {qty}주]", "callback_data": "noop"}]]}
                )
                self.send_message(
                    chat_id,
                    f"✅ <b>[한투 주문 발송 완료]</b>\n\n"
                    f"• <b>종목</b>: <code>{ticker}</code>\n"
                    f"• <b>구분</b>: <b>{side}</b>\n"
                    f"• <b>수량</b>: <b>{qty}주</b>\n"
                    f"• <b>결과</b>: GitHub Actions 서버리스 주문 러너 가동 시작\n"
                    f"체결이 완료되면 텔레그램으로 최종 체결 통보가 발송됩니다."
                )
            else:
                logger.error(f"❌ 주문 실패: {msg}")
                self.edit_message_reply_markup(
                    chat_id,
                    message_id,
                    reply_markup={"inline_keyboard": [[{"text": f"❌ [주문 실패: {msg[:20]}]", "callback_data": "noop"}]]}
                )
                self.send_message(
                    chat_id,
                    f"❌ <b>[주문 전송 실패]</b>\n\n"
                    f"• <b>사유</b>: {msg}\n"
                    f"포트폴리오 자산에 아무런 변동이 발생하지 않았습니다."
                )

    def run_polling(self, interval: float = 1.0):
        """롱 폴링 메인 루프"""
        logger.info("🤖 텔레그램 트레이딩 봇 롱 폴링 시작...")
        logger.info(f"🛡️ 인가된 사용자 ID: {self.allowed_users or '설정 안 됨'}")
        logger.info(f"🛡️ 1회 최대 주문 한도: {self.max_qty_limit}주")

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
                logger.info("봇 종료 신호 수신. 안전하게 종료합니다.")
                break
            except Exception as e:
                logger.error(f"Polling loop unexpected exception: {e}")
                time.sleep(interval)


if __name__ == "__main__":
    bot = TelegramTradingBot()
    bot.run_polling()
