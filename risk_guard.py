import os
import re
import logging
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 6자리 KRX 표준 단축코드 정규식 (해외 티커 차단 및 형식 검증)
KRX_TICKER_REGEX = re.compile(r"^\d{6}$")

# 해외 주식 티커 패턴 (알파벳 1~5자리, 예: AAPL, TSLA, NVDA)
FOREIGN_TICKER_REGEX = re.compile(r"^[A-Za-z]{1,5}$")

# 대표 해외 유명 주식 한글 표기 블랙리스트 (중개형 ISA 규정 위반 방지)
KNOWN_FOREIGN_KOR_NAMES = {
    "애플", "테슬라", "엔비디아", "마이크로소프트", "알파벳", "구글", "아마존",
    "메타", "넷플릭스", "티에스엠씨", "tsmc", "브로드컴", "팔란티어", "코인베이스"
}


def get_krx_tick_size(price: int) -> int:
    """한국거래소(KRX) 유가증권/코스닥 시장 표준 호가 가격 단위(Tick Size) 산출"""
    if price < 2000:
        return 1
    elif price < 5000:
        return 5
    elif price < 20000:
        return 10
    elif price < 50000:
        return 50
    elif price < 200000:
        return 100
    elif price < 500000:
        return 500
    else:
        return 1000


def is_valid_krx_tick(price: int) -> bool:
    """지정가 가격이 KRX 호가 단위에 부합하는지 검증"""
    if price <= 0:
        return True
    tick = get_krx_tick_size(price)
    return (price % tick) == 0


class ISARiskGuard:
    """Taur-ai / TradingAgents 의 Risk Management Layer 콘셉트를 차용한
    중개형 ISA 주식 매매 안전 룰 엔진 (Risk Gate).

    LLM이 생성한 주문 파라미터를 시스템 레벨에서 엄격하게 가로채어
    ISA 규정 및 리스크 한도 위반 시 즉시 차단합니다.
    """

    def __init__(self, single_order_limit: Optional[int] = None):
        self.single_order_limit = single_order_limit or int(
            os.getenv("ORDER_AMOUNT_LIMIT", "3000000")
        )
        self._master_loaded = False
        self._name_to_code: Dict[str, str] = {}
        self._code_to_meta: Dict[str, Dict[str, Any]] = {}
        self._init_master()

    def _init_master(self) -> None:
        """nhplug.instruments.load_master('m_new_stock')를 로드하여 화이트리스트 구축"""
        if self._master_loaded:
            return

        try:
            import nhplug.instruments as ins

            df = ins.load_master("m_new_stock")
            for _, row in df.iterrows():
                code = str(row.get("sCode", "")).strip()
                if not KRX_TICKER_REGEX.match(code):
                    continue

                name = str(row.get("name", "")).strip()
                kor_name = str(row.get("sKorName", "")).strip().lstrip("*").strip()

                # 기준가(stck_sdpr)
                sdpr_str = str(row.get("stck_sdpr", "0")).strip()
                base_price = int(sdpr_str) if sdpr_str.isdigit() else 0

                meta = {
                    "code": code,
                    "name": name or kor_name,
                    "clean_name": kor_name,
                    "base_price": base_price,
                    "market": str(row.get("sMarket", "")).strip(),
                }
                self._code_to_meta[code] = meta

                for candidate in {name, kor_name}:
                    if candidate:
                        norm = self._normalize(candidate)
                        self._name_to_code[norm] = code

            self._master_loaded = True
            logger.info(
                f"[ISARiskGuard] KRX 마스터 인덱스 구축 완료: {len(self._code_to_meta):,}개 종목 등록됨."
            )
        except Exception as e:
            logger.warning(f"[ISARiskGuard] 마스터 로드 실패 (Fallback 적용): {e}")
            self._init_fallback()
            self._master_loaded = True

    def _init_fallback(self) -> None:
        """오프라인/테스트 환경용 기본 종목 테이블"""
        samples = [
            {"code": "005930", "name": "삼성전자", "base_price": 60000},
            {"code": "000660", "name": "SK하이닉스", "base_price": 180000},
            {"code": "035420", "name": "NAVER", "base_price": 170000},
            {"code": "035720", "name": "카카오", "base_price": 40000},
            {"code": "373220", "name": "LG에너지솔루션", "base_price": 400000},
            {"code": "360750", "name": "TIGER 미국S&P500", "base_price": 18000},
            {"code": "133690", "name": "TIGER 미국나스닥100", "base_price": 110000},
            {"code": "069500", "name": "KODEX 200", "base_price": 35000},
        ]
        for s in samples:
            self._code_to_meta[s["code"]] = s
            self._name_to_code[self._normalize(s["name"])] = s["code"]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[\s*]", "", text).lower()

    def resolve_code(self, identifier: str) -> Optional[str]:
        """종목명 또는 단축코드를 6자리 KRX 표준 코드로 변환"""
        clean_id = identifier.strip()
        if KRX_TICKER_REGEX.match(clean_id) and clean_id in self._code_to_meta:
            return clean_id

        norm = self._normalize(clean_id)
        if norm in self._name_to_code:
            return self._name_to_code[norm]

        # 부분 일치 검색
        for name_key, code in self._name_to_code.items():
            if norm == name_key or norm in name_key or name_key in norm:
                return code

        return None

    def evaluate_orders(
        self,
        parsed_orders: List[Dict[str, Any]],
        holdings: Optional[Dict[str, int]] = None,
        available_cash: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """주문 리스트에 대해 3대 하드 룰 + 잔고 무결성 검증을 수행하고 (통과 목록, 거절 목록)을 반환합니다.
        
        Args:
            parsed_orders: 파싱된 주문 원문 리스트
            holdings: 현재 계좌 보유 종목 수량 딕셔너리 (예: {"005930": 30}) -> 무차입 공매도 방지
            available_cash: 현재 계좌의 주문 가능 현금 예수금 -> 미수금 발생 방지
        """
        validated_orders: List[Dict[str, Any]] = []
        rejected_orders: List[Dict[str, Any]] = []
        cumulative_buy_amount = 0.0

        # 사전 점검: 동일 종목 상반된 매수/매도 동시 발주 (Self-Match / Wash Sale 충돌) 검사
        resolved_actions: Dict[str, set] = {}
        for ord_item in parsed_orders:
            s_name = ord_item.get("stock_name", "").strip()
            c = self.resolve_code(s_name) or s_name
            act = ord_item.get("action", "BUY").upper()
            if c not in resolved_actions:
                resolved_actions[c] = set()
            resolved_actions[c].add(act)

        conflicting_codes = {c for c, acts in resolved_actions.items() if len(acts) > 1}

        for order in parsed_orders:
            stock_name = order.get("stock_name", "").strip()
            action = order.get("action", "BUY")
            quantity = order.get("quantity", 0)
            order_type = order.get("order_type", "01")
            price = order.get("price") or 0
            credit_type = order.get("credit_type", "CASH")

            # -------------------------------------------------------------
            # Guard 0: 파라미터 무결성 검증 (0주 이하, 음수, 비정상적 대량 수량)
            # -------------------------------------------------------------
            if quantity <= 0:
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_0_INVALID_PARAM",
                    "reason": f"주문 수량 오류: 주문 수량은 반드시 1 이상의 양의 정수여야 합니다. (입력값: {quantity}주)",
                })
                continue

            # -------------------------------------------------------------
            # Guard 7: 동일 종목 상반된 매수/매도 동시 요청 차단 (자전거래 방지)
            # -------------------------------------------------------------
            temp_code = self.resolve_code(stock_name) or stock_name
            if temp_code in conflicting_codes:
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_7_CONFLICTING_ORDERS",
                    "reason": f"동일 종목 양방향 동시 발주 차단: '{stock_name}'에 대해 매수와 매도가 동시에 요청되었습니다. 순(Net) 수량으로 단일 주문해 주세요.",
                })
                continue

            if quantity > 1_000_000:
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_0_INVALID_PARAM",
                    "reason": f"비정상적 대량 수량 오류: 단일 주문 수량 100만 주 초과로 안전 차단되었습니다. (입력값: {quantity:,}주)",
                })
                continue

            # -------------------------------------------------------------
            # Guard 2: 중개형 ISA 제약 조건 (1: 신용/미수 거절, 2: 한글/영문 해외주식 거절)
            # -------------------------------------------------------------
            if credit_type != "CASH":
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_2_ISA_CONSTRAINT",
                    "reason": f"신용/미수/융자 주문('{credit_type}') 거절: 중개형 ISA는 100% 현금 주문만 허용됩니다.",
                })
                continue

            # 한글 해외 유명 종목 사전 차단 (예: 애플, 테슬라 등)
            norm_name = self._normalize(stock_name)
            if norm_name in KNOWN_FOREIGN_KOR_NAMES or any(k in norm_name for k in KNOWN_FOREIGN_KOR_NAMES):
                # 단, 'TIGER 미국S&P500' 등 국내 상장 ETF는 제외
                if not any(etf_tag in norm_name for etf_tag in ["tiger", "kodex", "ace", "sol", "rise", "etf"]):
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_2_ISA_CONSTRAINT",
                        "reason": f"해외 상장 주식('{stock_name}') 거절: 중개형 ISA 계좌는 국내 상장 주식 및 ETF만 매매 가능합니다.",
                    })
                    continue

            # -------------------------------------------------------------
            # Guard 1: 종목 코드 존재 및 6자리 KRX 표준 단축코드(^\d{6}$) 검증
            # (국내 마스터 우선 대조 후, 미존재 시 해외 티커 여부 판정)
            # -------------------------------------------------------------
            code = self.resolve_code(stock_name)

            if not code or not KRX_TICKER_REGEX.match(code):
                # KRX 마스터에 없는 종목 중 해외 티커 패턴인 경우 Guard 2로 특화
                if FOREIGN_TICKER_REGEX.match(stock_name):
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_2_ISA_CONSTRAINT",
                        "reason": f"해외 거래소 종목('{stock_name}') 거절: 중개형 ISA 계좌는 국내 상장 주식 및 ETF만 매매 가능합니다.",
                    })
                else:
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_1_TICKER",
                        "reason": f"KRX 마스터 미등록 종목 (입력값: '{stock_name}'): 유효한 6자리 표준 단축코드를 찾을 수 없습니다.",
                    })
                continue

            meta = self._code_to_meta.get(code, {})
            canonical_name = meta.get("name", stock_name)
            base_price = meta.get("base_price", 0)

            # -------------------------------------------------------------
            # Guard 3: 단일 주문 금액 한도(300만원) 초과 여부 확인
            # -------------------------------------------------------------
            if order_type == "00":  # 지정가
                if price <= 0:
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_3_AMOUNT_LIMIT",
                        "reason": "지정가 주문('00')에는 유효한 단가(>0)가 지정되어야 합니다.",
                    })
                    continue
                effective_price = price
            else:  # 시장가('01')
                effective_price = base_price if base_price > 0 else (price if price > 0 else 0)

            estimated_amount = quantity * effective_price

            if estimated_amount > self.single_order_limit:
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_3_AMOUNT_LIMIT",
                    "reason": (
                        f"단일 주문 한도 초과: 예상 금액 {estimated_amount:,}원이 "
                        f"설정된 주문 한도({self.single_order_limit:,}원)를 초과하였습니다."
                    ),
                })
                continue

            # -------------------------------------------------------------
            # Guard 6: KRX 호가 단위(Tick Size) 규격 준수 검증 (한도 이내 지정가 대상)
            # -------------------------------------------------------------
            if order_type == "00" and not is_valid_krx_tick(price):
                tick = get_krx_tick_size(price)
                rejected_orders.append({
                    "order": order,
                    "guard": "GUARD_6_INVALID_TICK_SIZE",
                    "reason": (
                        f"KRX 호가 단위 위반 오류: 단가 {price:,}원은 해당 가격대(5만원 이상 등)의 "
                        f"표준 호가 단위({tick:,}원) 단위가 아닙니다. (권장: {(price//tick)*tick:,}원 또는 {((price//tick)+1)*tick:,}원)"
                    ),
                })
                continue

            # -------------------------------------------------------------
            # Guard 4: 무차입 공매도 방지 (보유 수량 초과 매도 차단)
            # -------------------------------------------------------------
            if action.upper() == "SELL" and holdings is not None:
                current_holding = holdings.get(code, 0)
                if quantity > current_holding:
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_4_OVER_SELL_PROHIBITED",
                        "reason": (
                            f"보유 수량 초과 매도(공매도) 차단: 현재 계좌 보유 수량은 {current_holding}주이나, "
                            f"{quantity}주 매도를 요청하여 주문이 거절되었습니다."
                        ),
                    })
                    continue

            # -------------------------------------------------------------
            # Guard 5: 예수금 초과 매수 방지 (미수금 발생 차단)
            # -------------------------------------------------------------
            if action.upper() == "BUY" and available_cash is not None:
                if (cumulative_buy_amount + estimated_amount) > available_cash:
                    rejected_orders.append({
                        "order": order,
                        "guard": "GUARD_5_CASH_INSUFFICIENT",
                        "reason": (
                            f"예수금 부족(미수금 방지) 차단: 현재 주문가능 예수금은 {available_cash:,.0f}원이나, "
                            f"누적 매수 요청액이 {(cumulative_buy_amount + estimated_amount):,.0f}원으로 초과합니다."
                        ),
                    })
                    continue
                cumulative_buy_amount += estimated_amount

            # 3대 가드 통과
            validated_orders.append({
                "stock_name": canonical_name,
                "stock_code": code,
                "action": action,
                "quantity": quantity,
                "order_type": order_type,
                "price": price,
                "estimated_amount": estimated_amount,
            })

        return validated_orders, rejected_orders


# 기본 리스크 가드 싱글톤
default_risk_guard = ISARiskGuard()
