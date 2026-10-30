from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field


class MacroIndicator(BaseModel):
    name: str
    current_value: str
    change: Optional[str] = None
    status: Optional[str] = None  # 상승, 하강, 중립


class MarketOverview(BaseModel):
    """현재 거시경제 및 주식 시장 현황 요약"""

    date: str
    kospi: str = "2,600.50 (+0.45%)"
    kosdaq: str = "750.20 (-0.12%)"
    us_sp500: str = "5,800.10 (+0.80%)"
    us_nasdaq: str = "18,500.30 (+1.10%)"
    usd_krw: str = "1,385.50 (+3.20원)"
    interest_rate: str = "한국 3.25% / 미국 4.75~5.00%"
    headlines: List[str] = Field(
        default_factory=lambda: [
            "美 빅테크 실적 발표 주간 도래, AI 인프라 투자 지속 확인",
            "원/달러 환율 1,380원대 박스권 지속, 수출주 우호적 환경",
            "국내 증시 반도체 및 밸류업 지수 관련주 선별적 반등",
            "중개형 ISA 절세 혜택 확대로 배당형 및 해외지수 ETF 자금 유입 가속",
        ]
    )


class StrategyProfile(BaseModel):
    """사용자가 선택 가능한 대표 전략 프로필"""

    name: str
    description: str
    target_weights: Dict[str, float]


class TargetAllocation(BaseModel):
    """마켓 분석 에이전트가 도출한 최종 목표 포트폴리오 비중"""

    strategy_name: str
    rationales: List[str] = Field(description="전략 선정 근거 및 시장 분석 의견")
    target_weights: Dict[str, float] = Field(
        description="종목명 또는 단축코드별 목표 비중 (총합 약 1.0, CASH 포함 가능)"
    )
    recommended_cash_ratio: float = Field(default=0.15, description="권장 현금 비중 (0.0~1.0)")
