from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Position(BaseModel):
    """단일 보유 종목 포지션"""

    stock_code: str = Field(description="6자리 KRX 표준 단축코드 또는 해외 티커")
    stock_name: str = Field(description="종목명")
    quantity: int = Field(gt=0, description="보유 수량")
    avg_buy_price: float = Field(ge=0, description="매입 평균 단가 (원)")
    current_price: float = Field(ge=0, description="현재가 (원)")
    eval_amount: float = Field(ge=0, description="평가 금액 (원)")
    profit_loss: float = Field(default=0, description="평가 손익 (원)")
    profit_rate: float = Field(default=0.0, description="수익률 (%)")
    account_no: str = Field(description="소속 계좌번호")
    broker_name: str = Field(description="증권사 (NH, KIS, MANUAL 등)")
    account_type: str = Field(default="ISA", description="계좌 유형 (ISA, GENERAL, OVERSEAS)")
    asset_class: str = Field(default="DOMESTIC_STOCK", description="자산군 (DOMESTIC_STOCK, DOMESTIC_ETF, FOREIGN_STOCK, CASH)")


class AccountBalance(BaseModel):
    """단일 계좌 자산 현황"""

    broker_name: str
    account_no: str
    account_type: str  # ISA, GENERAL, PENSION 등
    total_eval_amount: float  # 총 평가금액 (보유주식 평가합 + 예수금)
    deposit_cash: float  # D+2 예수금 (현금)
    stock_eval_amount: float  # 주식 평가금액 합계
    positions: List[Position] = Field(default_factory=list)


class UnifiedPortfolio(BaseModel):
    """여러 계좌가 통합된 전체 포트폴리오 스냅샷"""

    total_net_worth: float = Field(description="전체 순자산 (Total NAV)")
    total_cash: float = Field(description="전체 보유 현금")
    cash_ratio: float = Field(description="현금 비중 (0.0 ~ 1.0)")
    accounts: List[AccountBalance] = Field(default_factory=list)
    consolidated_positions: List[Position] = Field(
        default_factory=list,
        description="종목별로 통합 합산된 포지션 목록",
    )
    asset_class_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="자산군별 비중 (예: {'DOMESTIC_ETF': 0.45, 'DOMESTIC_STOCK': 0.35, 'CASH': 0.20})",
    )
    stock_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="종목별 전체 포트폴리오 대비 비중",
    )
