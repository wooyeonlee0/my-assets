import os
import logging
from typing import Dict, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from analyst.models import MarketOverview, StrategyProfile, TargetAllocation
from analyst.market_feed import MarketFeed

logger = logging.getLogger(__name__)

PRESET_STRATEGIES: Dict[str, StrategyProfile] = {
    "growth": StrategyProfile(
        name="미국 지수 & 테크 성장형 (Tech & Index Growth)",
        description="미국 핵심 지수 ETF(S&P500, 나스닥100) 중심에 국내 반도체 대형주를 결합한 성장 지향형 배분",
        target_weights={
            "360750": 0.45,  # TIGER 미국S&P500 (45%)
            "133690": 0.25,  # TIGER 미국나스닥100 (25%)
            "005930": 0.15,  # 삼성전자 (15%)
            "CASH": 0.15,    # 현금 버퍼 (15%)
        },
    ),
    "balanced": StrategyProfile(
        name="올웨더 중립 균형형 (All-Weather Balanced)",
        description="시장 변동성을 줄이고 지수 성장과 현금 비중을 고르게 분산한 안정형 배분",
        target_weights={
            "360750": 0.35,  # TIGER 미국S&P500 (35%)
            "005930": 0.20,  # 삼성전자 (20%)
            "133690": 0.15,  # TIGER 미국나스닥100 (15%)
            "CASH": 0.30,    # 현금 비중 (30%)
        },
    ),
    "dividend": StrategyProfile(
        name="ISA 고배당 & 인컴형 (Dividend & Value)",
        description="중개형 ISA의 비과세 혜택을 극대화하기 위한 배당 및 가치주 중심 배분",
        target_weights={
            "360750": 0.30,  # TIGER 미국S&P500 (30%)
            "005930": 0.25,  # 삼성전자 (25%)
            "000660": 0.20,  # SK하이닉스 (20%)
            "CASH": 0.25,    # 현금 비중 (25%)
        },
    ),
}


class StrategyAnalystAgent:
    """마켓 분석 정보와 사용자 대화를 기반으로 최적의 Target Allocation을 도출하는 에이전트"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    def get_market_overview(self) -> MarketOverview:
        return MarketFeed.get_latest_overview()

    def get_preset_strategy(self, preset_key: str = "growth") -> TargetAllocation:
        """사전 정의된 대표 전략 프로필 반환"""
        profile = PRESET_STRATEGIES.get(preset_key, PRESET_STRATEGIES["growth"])
        cash_ratio = profile.target_weights.get("CASH", 0.15)
        return TargetAllocation(
            strategy_name=profile.name,
            rationales=[
                profile.description,
                f"현재 거시 환경에 맞춘 권장 현금 비중: {cash_ratio*100:.0f}%",
            ],
            target_weights=profile.target_weights,
            recommended_cash_ratio=cash_ratio,
        )

    def analyze_and_propose(
        self,
        user_preference: str,
        current_portfolio_summary: Optional[str] = None,
    ) -> TargetAllocation:
        """사용자의 투자 생각/선호도를 분석하여 맞춤형 목표 배분을 생성"""
        market = self.get_market_overview()

        # LLM 사용 가능 시 정밀 분석
        if self.api_key and not self.api_key.startswith("your-"):
            try:
                llm = ChatOpenAI(model="gpt-4o", temperature=0.2, api_key=self.api_key)
                structured_llm = llm.with_structured_output(TargetAllocation)

                system_msg = SystemMessage(
                    content=(
                        "당신은 금융공학 및 포트폴리오 자산배분 수석 애널리스트입니다.\n"
                        "중개형 ISA 계좌의 특성(국내 상장 주식 및 국내 상장 해외ETF만 허용, 비과세 절세 계좌)을 고려하여,\n"
                        "현재 거시 시장 지표와 사용자의 요구사항을 분석해 가장 합리적인 목표 포트폴리오 비중(TargetAllocation)을 제안하세요.\n"
                        "목표 비중 합계는 1.0(100%)이어야 하며, 현금(CASH) 비중을 10%~30% 사이로 포함하세요."
                    )
                )

                user_content = (
                    f"## [최신 시장 지표]\n"
                    f"- KOSPI: {market.kospi}, KOSDAQ: {market.kosdaq}\n"
                    f"- S&P500: {market.us_sp500}, NASDAQ: {market.us_nasdaq}\n"
                    f"- 환율: {market.usd_krw}, 금리: {market.interest_rate}\n"
                    f"- 헤드라인: {'; '.join(market.headlines)}\n\n"
                    f"## [현재 포트폴리오 요약]\n{current_portfolio_summary or '미제공'}\n\n"
                    f"## [사용자 요구 및 투자 메모]\n{user_preference}"
                )

                result = structured_llm.invoke([system_msg, HumanMessage(content=user_content)])
                return result

            except Exception as e:
                logger.warning(f"[StrategyAnalystAgent] GPT-4o 분석 실패 -> Fallback 프리셋 사용: {e}")

        # Fallback 휴리스틱
        pref_lower = user_preference.lower()
        if any(w in pref_lower for w in ["배당", "안전", "인컴", "안정"]):
            return self.get_preset_strategy("dividend")
        elif any(w in pref_lower for w in ["균형", "올웨더", "방어", "분산"]):
            return self.get_preset_strategy("balanced")
        else:
            return self.get_preset_strategy("growth")


default_analyst = StrategyAnalystAgent()
