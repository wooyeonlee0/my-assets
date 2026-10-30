from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class TargetWeight(BaseModel):
    """개별 종목 또는 자산 목표 비중"""

    stock_code: str = Field(description="종목 코드 (KRX 6자리 또는 해외 티커 또는 'CASH')")
    stock_name: str = Field(description="종목명")
    target_weight: float = Field(ge=0.0, le=1.0, description="목표 비중 (0.0 ~ 1.0)")
    account_type: str = Field(default="ISA", description="대상 계좌 (ISA 또는 GENERAL/OVERSEAS)")


class OrderProposal(BaseModel):
    """리밸런싱을 위해 제안된 개별 매매 주문"""

    stock_code: str
    stock_name: str
    action: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0, description="1주 단위 정수 수량")
    price: int = Field(ge=0, description="기준 단가 (원)")
    estimated_amount: int = Field(ge=0, description="주문 총액 (원)")
    current_weight: float = Field(description="현재 포트폴리오 비중 (0.0 ~ 1.0)")
    target_weight: float = Field(description="목표 포트폴리오 비중 (0.0 ~ 1.0)")
    weight_diff: float = Field(description="비중 편차 (목표 - 현재)")
    target_account_type: str = Field(default="ISA")
    reason: str = Field(description="리밸런싱 제안 사유")


class RebalancePlan(BaseModel):
    """리밸런싱 계산 결과 계획안"""

    total_net_worth: float
    proposals: List[OrderProposal] = Field(default_factory=list)
    total_buy_amount: int = Field(default=0)
    total_sell_amount: int = Field(default=0)
    net_cash_flow: int = Field(default=0, description="순 현금 유출입 (매도총액 - 매수총액)")
    natural_language_memo: str = Field(description="Layer 4 안전 파이프라인으로 넘길 자연어 매매 메모")
