import os
import uuid
import time
import hashlib
import logging
from typing import Dict, Any, Optional, Set
from dotenv import load_dotenv

from credentials import get_credential
from account_finder import get_default_isa_account

load_dotenv()

logger = logging.getLogger(__name__)


class NHBroker:
    """NH투자증권 나무 PLUG API (nhplug) 연동을 전담하는 브로커 계층 클래스.
    
    오픈소스 레퍼런스(rh-trading-agent)의 Broker Isolation 패턴을 차용하여,
    상위 에이전트나 리스크 가드가 증권사 저수준 통신 규격에 의존하지 않도록 격리합니다.
    """

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        account_no: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ):
        # Windows Credential Manager 우선 조회 -> 없으면 .env fallback
        self.app_key = app_key or get_credential("NHPLUG_APP_KEY")
        self.app_secret = app_secret or get_credential("NHPLUG_APP_SECRET")
        self.base_url = (
            base_url
            or os.getenv("NHPLUG_BASE_URL", "https://moapi.nhplug.com:8443")
        )
        # 계좌번호 미입력 시 NH 서버(/n2/acctinfo)에서 자동 긁어옴
        raw_act = account_no or get_credential("NH_ISA_ACCOUNT_NO")
        if not raw_act or raw_act in ("12345678-01", "1234567801", ""):
            auto_act = get_default_isa_account(self.app_key, self.app_secret)
            raw_act = auto_act or ""

        self.account_no = raw_act.replace("-", "").strip()

        # 환경변수 동기화 (nhplug 내부 get_base_url, get_token용)
        if self.app_key:
            os.environ["NHPLUG_APP_KEY"] = self.app_key
        if self.app_secret:
            os.environ["NHPLUG_APP_SECRET"] = self.app_secret
        if self.base_url:
            os.environ["NHPLUG_BASE_URL"] = self.base_url

        if dry_run is not None:
            self.dry_run = dry_run
        else:
            self.dry_run = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

        # 중복 주문(Double Submission) 방지를 위한 멱등성 해시 저장소 (최근 60초)
        self._recent_order_hashes: Dict[str, float] = {}

    def _generate_idempotency_key(self, stock_code: str, action: str, quantity: int, price: int) -> str:
        """주문 파라미터 기반 유일 멱등성 키 생성"""
        raw = f"{self.account_no}:{stock_code}:{action.upper()}:{quantity}:{price}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_configured(self) -> bool:
        """실제 API 호출에 필요한 인증키가 올바르게 설정되었는지 확인합니다."""
        return bool(
            self.app_key
            and self.app_secret
            and not self.app_key.startswith("your-")
        )

    def send_order(
        self,
        stock_code: str,
        action: str,  # 'BUY' | 'SELL'
        quantity: int,
        order_type: str,  # '01' (시장가) | '00' (지정가)
        price: int = 0,
        estimated_amount: int = 0,
    ) -> Dict[str, Any]:
        """국내 주식/ETF 주문을 전송하고 표준화된 실행 결과를 반환합니다.

        엔드포인트:
          - 현금 매수: /krstock/order/v1/cashBuy (또는 /buy)
          - 현금 매도: /krstock/order/v1/cashSell (또는 /sell)
        """
        # -----------------------------------------------------------------
        # 멱등성 검사: 동일 주문 30초 내 중복 전송 방어
        # -----------------------------------------------------------------
        now = time.time()
        order_key = self._generate_idempotency_key(stock_code, action, quantity, price)
        if order_key in self._recent_order_hashes:
            last_time = self._recent_order_hashes[order_key]
            if (now - last_time) < 30.0:
                logger.error(f"[NHBroker] 중복 주문 차단 (Double Submission Prevented): {stock_code} {action}")
                return {
                    "status": "FAILED",
                    "order_no": None,
                    "response_code": "DUPLICATE_ORDER",
                    "response_message": "이중 전송 방어: 동일한 주문이 직전(30초 이내)에 이미 실행되어 중복 주문이 차단되었습니다.",
                }
        self._recent_order_hashes[order_key] = now

        action_upper = action.upper()
        # NH PLUG 공식 엔드포인트
        endpoint = (
            "/krstock/order/v1/cashBuy"
            if action_upper == "BUY"
            else "/krstock/order/v1/cashSell"
        )

        # 호가유형코드:
        # NH 오픈 API: 01.보통가(지정가), 05.시장가
        if order_type == "01":  # 시장가
            nmn_pr_tp_cd = "05"
            order_price = 0
        else:  # 지정가
            nmn_pr_tp_cd = "01"
            order_price = price

        payload = {
            "act_no": self.account_no,
            "iem_cd": stock_code,
            "orr_qty": int(quantity),
            "orr_pr": order_price,
            "orr_amt": int(estimated_amount),
            "nmn_pr_tp_cd": nmn_pr_tp_cd,
            "orr_cnd_dit_cd": "00",  # 일반
            "ssl_nmn_pr_dit_cd": "00",  # 정상
            "rmt_mkt_cd": "KRX",  # KRX
            "sor_mkt_sli_yn": "N",
        }

        # Dry-run 모드이거나 인증키가 없는 경우 모의 실행 응답 반환
        if self.dry_run or not self.is_configured():
            mock_order_no = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
            logger.info(
                f"[NHBroker:DRY-RUN] 모의 주문 접수: {action_upper} {stock_code} {quantity}주 ({mock_order_no})"
            )
            return {
                "status": "SUCCESS",
                "order_no": mock_order_no,
                "response_code": "0000",
                "response_message": "[DRY-RUN / SIMULATED] 모의 주문이 정상 접수되었습니다.",
                "endpoint": endpoint,
                "payload": payload,
            }

        try:
            import nhplug

            logger.info(
                f"[NHBroker] API 전송 시작: {endpoint} -> {stock_code} {action_upper} {quantity}주"
            )
            response = nhplug.call(endpoint, input_0=payload, timeout=10)

            rsp_cd = response.get("rsp_cd") or response.get("code") or "200"
            rsp_msg = (
                response.get("rsp_msg")
                or response.get("message")
                or "주문이 정상 접수되었습니다."
            )

            output_0 = response.get("Output_0") or response.get("output") or {}
            order_no = (
                output_0.get("ord_no")
                or output_0.get("odno")
                or response.get("ord_no")
                or "SUBMITTED"
            )

            return {
                "status": "SUCCESS",
                "order_no": order_no,
                "response_code": rsp_cd,
                "response_message": rsp_msg,
                "endpoint": endpoint,
                "payload": payload,
                "raw": response,
            }

        except Exception as e:
            logger.error(f"[NHBroker] 주문 API 전송 오류 ({stock_code}): {e}")
            return {
                "status": "FAILED",
                "order_no": None,
                "response_code": "ERROR",
                "response_message": str(e),
                "endpoint": endpoint,
                "payload": payload,
            }


# 기본 브로커 인스턴스
default_broker = NHBroker()
