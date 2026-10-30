from typing import List, Optional, Literal, Dict, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


class ParsedOrder(BaseModel):
    """자연어 메모에서 추출된 단일 주문 정보"""

    stock_name: str = Field(
        ...,
        description="종목명 또는 단축코드 (예: 삼성전자, 카카오, 005930, TIGER 미국S&P500)",
    )
    action: Literal["BUY", "SELL"] = Field(
        ..., description="매매 구분 (BUY: 매수, SELL: 매도)"
    )
    quantity: int = Field(
        ..., gt=0, description="주문 수량 (1주 이상의 양의 정수)"
    )
    order_type: Literal["01", "00"] = Field(
        ...,
        description="호가/가격 유형 ('01': 시장가, '00': 지정가)",
    )
    price: Optional[int] = Field(
        default=0,
        description="주문 단가 (원 단위, 지정가('00')일 때 필수, 시장가('01')일 때는 0 또는 None)",
    )
    credit_type: Optional[str] = Field(
        default="CASH",
        description="결제 유형 (CASH: 현금, CREDIT: 신용/미수 등)",
    )
    notes: Optional[str] = Field(
        default=None, description="메모에서 언급된 매매 사유나 특이사항"
    )


class ParsedOrderList(BaseModel):
    """복수 주문을 포함할 수 있는 컨테이너 모델"""

    orders: List[ParsedOrder] = Field(
        default_factory=list,
        description="자연어 메모에서 추출된 주문 목록",
    )


class ValidatedOrder(BaseModel):
    """유효성 검사 및 티커 인리치먼트가 완료된 안전한 주문"""

    stock_name: str
    stock_code: str  # 6자리 KRX 표준 단축코드
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["01", "00"]  # '01': 시장가, '00': 지정가
    price: int  # 지정가 가격 (시장가인 경우 기준가 또는 0)
    estimated_amount: int  # 예상 총 주문 금액
    market_name: Optional[str] = None  # 코스피/코스닥/ETF 구분


class RejectedOrder(BaseModel):
    """Guard에 의해 탈락된 주문 및 탈락 사유"""

    order: Dict[str, Any]
    guard: str  # "GUARD_1_TICKER", "GUARD_2_ISA_CONSTRAINT", "GUARD_3_AMOUNT_LIMIT"
    reason: str


class ExecutionResult(BaseModel):
    """브로커 API 주문 실행 결과"""

    stock_name: str
    stock_code: str
    action: str
    quantity: int
    order_type: str
    price: int
    status: Literal["SUCCESS", "FAILED", "SKIPPED"]
    order_no: Optional[str] = None
    response_code: Optional[str] = None
    response_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class AgentState(TypedDict):
    """LangGraph 파이프라인의 전체 상태 (State Schema)"""

    raw_memo: str  # 사용자 입력 매매 메모
    parsed_orders: List[Dict[str, Any]]  # Pydantic 파싱 결과
    validated_orders: List[Dict[str, Any]]  # 티커 매핑 및 유효성 검사 완료된 주문
    rejected_orders: List[Dict[str, Any]]  # 유효성 검사 탈락 주문 및 탈락 사유
    approval_status: Optional[Dict[str, Any]]  # HITL 승인 결과
    execution_results: List[Dict[str, Any]]  # API 호출 응답 결과
