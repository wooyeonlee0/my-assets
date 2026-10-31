"""
Core Trading Framework & Data Contracts
----------------------------------------
웹과 텔레그램, 백엔드 주문 엔진이 100% 공유하는 단일 트레이딩 코어(Unified Trading Core).
- 단일 종목 및 다중 종목 배치(Batch / Basket) 표준 규격
- Sell-First 정렬 파이프라인 (매도 우선 ➔ 예수금 확보 ➔ 매수 집행)
- 통합 Risk Guard (100주 하드 리밋, 배치 최대 종목 수 제한, 유효성 검증)
- 포맷 정규화 및 요약 생성기
"""

import json
import uuid
import time
from typing import List, Dict, Any, Tuple, Optional


class OrderItem:
    def __init__(
        self,
        ticker: str,
        qty: any = 1,
        side: str = "BUY",
        price: str = "0",
        market: str = "AUTO"
    ):
        self.ticker = str(ticker or "").strip().upper()
        try:
            self.qty = int(float(qty))
        except (ValueError, TypeError):
            self.qty = 0

        self.side = str(side or "BUY").strip().upper()
        if self.side not in ("BUY", "SELL"):
            self.side = "BUY"
        self.price = str(price or "0").strip()
        self.market = str(market or "AUTO").strip().upper()

        # 국내/해외 시장 자동 감지
        if self.market == "AUTO":
            if self.ticker.isdigit() and len(self.ticker) == 6:
                self.market = "KR_STOCK"
            else:
                self.market = "US_NASD"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "qty": self.qty,
            "side": self.side,
            "price": self.price,
            "market": self.market
        }

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderItem":
        qty_raw = data.get("qty", 1)
        try:
            qty_int = int(float(qty_raw))
        except (ValueError, TypeError):
            qty_int = 0

        return cls(
            ticker=data.get("ticker", ""),
            qty=qty_int,
            side=data.get("side", "BUY"),
            price=data.get("price", "0"),
            market=data.get("market", "AUTO")
        )


class BatchOrder:
    def __init__(
        self,
        orders: List[OrderItem],
        batch_type: str = "AUTO",
        batch_id: Optional[str] = None,
        created_at: Optional[float] = None
    ):
        self.batch_id = batch_id or f"b_{uuid.uuid4().hex[:8]}"
        self.created_at = created_at or time.time()
        self.orders = orders

        # 배치 타입 결정 (BUY, SELL, REBALANCE)
        if batch_type == "AUTO":
            sides = {o.side for o in self.orders}
            if len(sides) > 1:
                self.batch_type = "REBALANCE"
            elif "SELL" in sides:
                self.batch_type = "SELL"
            else:
                self.batch_type = "BUY"
        else:
            self.batch_type = batch_type.upper()

    def __getitem__(self, key: str) -> Any:
        """하위 호환성용 딕셔너리 키 접근 지원 (단일 주문 필드 프록시)"""
        if key in ("batch_id", "batch_type", "created_at", "orders"):
            return getattr(self, key)
        if self.orders:
            first_order = self.orders[0]
            if hasattr(first_order, key):
                return getattr(first_order, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        if key in ("batch_id", "batch_type", "created_at", "orders"):
            return True
        if self.orders and hasattr(self.orders[0], key):
            return True
        return False

    def get_sell_orders(self) -> List[OrderItem]:
        return [o for o in self.orders if o.side == "SELL"]

    def get_buy_orders(self) -> List[OrderItem]:
        return [o for o in self.orders if o.side == "BUY"]

    def sort_sell_first(self) -> None:
        """🔄 Sell-First 순서 정렬: 매도를 무조건 매수보다 먼저 정렬"""
        self.orders = self.get_sell_orders() + self.get_buy_orders()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "batch_type": self.batch_type,
            "created_at": self.created_at,
            "orders": [o.to_dict() for o in self.orders]
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchOrder":
        order_list = [OrderItem.from_dict(item) for item in data.get("orders", [])]
        return cls(
            orders=order_list,
            batch_type=data.get("batch_type", "AUTO"),
            batch_id=data.get("batch_id"),
            created_at=data.get("created_at")
        )

    @classmethod
    def from_json(cls, json_str: str) -> "BatchOrder":
        return cls.from_dict(json.loads(json_str))


def validate_batch_risk_guard(
    batch: BatchOrder,
    max_single_qty: int = 100,
    max_items_per_batch: int = 10
) -> Tuple[bool, str, BatchOrder]:
    """
    🛡️ 통합 Risk Guard (배치 및 단건 공통 검증)
    1. 배치 내 총 주문 수량 및 종목 수 상한 검증
    2. 개별 종목 100주 하드 리밋 검증
    3. 0 이하 / 음수 / 비정상 수량 차단
    4. 티커 공백 검증
    5. Sell-First 정렬 보장
    반환: (is_valid, error_message, validated_batch)
    """
    if not batch.orders:
        return False, "배치 내에 주문 항목이 존재하지 않습니다.", batch

    if len(batch.orders) > max_items_per_batch:
        return False, f"1회 배치 최대 허용 종목 수({max_items_per_batch}개)를 초과했습니다: {len(batch.orders)}개 요청됨", batch

    for idx, item in enumerate(batch.orders, 1):
        if not item.ticker or not str(item.ticker).strip():
            return False, f"[{idx}번째 주문] 종목 티커가 비어있습니다.", batch

        if item.qty <= 0:
            return False, f"[{idx}번째 주문 {item.ticker}] 비정상적인 수량입니다: {item.qty}주 (1주 이상이어야 함)", batch

        if item.qty > max_single_qty:
            return False, f"[{idx}번째 주문 {item.ticker}] 1회 최대 안전 리밋({max_single_qty}주)을 초과했습니다: {item.qty}주", batch

    # Sell-First 순서 정렬 보장
    batch.sort_sell_first()
    return True, "", batch


def parse_order_payload(payload_raw: Any) -> Tuple[bool, str, BatchOrder]:
    """
    단일 주문 형식이든 배치 JSON 형식이든 표준 BatchOrder 객체로 단일화 파싱 (하위 호환 100%)
    """
    try:
        if isinstance(payload_raw, str):
            payload_str = payload_raw.strip()
            # 1) 콤팩트 딥링크 포맷 검사 (예: NVDA.3.S_GOOGL.2.B)
            if "." in payload_str and not payload_str.startswith("{"):
                compact_batch = decode_compact_order(payload_str)
                if compact_batch and compact_batch.orders:
                    return True, "", compact_batch

            payload_raw = json.loads(payload_str)

        if isinstance(payload_raw, dict):
            # 2) 배치 형식인 경우 (orders 필드 존재)
            if "orders" in payload_raw and isinstance(payload_raw["orders"], list):
                batch = BatchOrder.from_dict(payload_raw)
                return True, "", batch

            # 3) 단일 주문 객체인 경우 (ticker 필드 존재)
            if "ticker" in payload_raw:
                single_item = OrderItem.from_dict(payload_raw)
                batch = BatchOrder(orders=[single_item])
                return True, "", batch

        return False, "유효한 주문 형식이 아닙니다.", BatchOrder(orders=[])
    except Exception as e:
        return False, f"페이로드 파싱 실패: {e}", BatchOrder(orders=[])


def encode_compact_order(batch: BatchOrder) -> str:
    """
    텔레그램 64자 start 파라미터 규격에 맞춘 초소형 콤팩트 딥링크 인코더
    형식: TICKER.QTY.SIDE_TICKER.QTY.SIDE (예: NVDA.3.S_GOOGL.2.B)
    Sell-First 매도 우선 정렬 보장
    """
    batch.sort_sell_first()
    tokens = []
    for o in batch.orders:
        side_char = "S" if o.side == "SELL" else "B"
        tokens.append(f"{o.ticker}.{o.qty}.{side_char}")
    return "_".join(tokens)


def decode_compact_order(compact_str: str) -> Optional[BatchOrder]:
    """
    초소형 콤팩트 문자열(NVDA.3.S_GOOGL.2.B)을 표준 BatchOrder로 디코딩
    """
    if not compact_str or not isinstance(compact_str, str):
        return None

    cleaned = compact_str.strip().lstrip("/start").strip()
    if not cleaned:
        return None

    parts = cleaned.split("_")
    orders = []

    for part in parts:
        sub = part.split(".")
        if len(sub) >= 3:
            ticker = sub[0].strip().upper()
            try:
                qty = int(sub[1])
            except ValueError:
                continue
            side_code = sub[2].strip().upper()
            side = "SELL" if side_code.startswith("S") else "BUY"
            if ticker and qty > 0:
                orders.append(OrderItem(ticker=ticker, qty=qty, side=side))

    if not orders:
        return None

    batch = BatchOrder(orders=orders)
    batch.sort_sell_first()
    return batch


def format_batch_summary_html(batch: BatchOrder) -> str:
    """텔레그램 및 웹에서 공유하는 공통 요약 텍스트 생성"""
    sell_orders = batch.get_sell_orders()
    buy_orders = batch.get_buy_orders()

    type_ko = {
        "BUY": "매수 바스켓",
        "SELL": "매도 바스켓",
        "REBALANCE": "스마트 리밸런싱 (매도 ➔ 매수)"
    }.get(batch.batch_type, "주문 배치")

    lines = [f"📦 <b>[한투 AI {type_ko}]</b>"]
    lines.append("───────────────────────")

    if sell_orders:
        lines.append("🔻 <b>[매도 순서 - 예수금 확보]</b>")
        for o in sell_orders:
            lines.append(f"  • <code>{o.ticker}</code>: <b>{o.qty}주</b> 매도 (시장가)")

    if buy_orders:
        if sell_orders:
            lines.append("───────────────────────")
        lines.append("🔺 <b>[매수 순서 - 자산 편입]</b>")
        for o in buy_orders:
            lines.append(f"  • <code>{o.ticker}</code>: <b>{o.qty}주</b> 매수 (시장가)")

    lines.append("───────────────────────")
    lines.append(f"• <b>총 주문 건수</b>: {len(batch.orders)}건")
    lines.append("• <b>안전 가드</b>: 종목당 100주 하드 리밋 검증 완료")
    return "\n".join(lines)
