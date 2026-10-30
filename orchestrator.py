import logging
from typing import Dict, Any, Optional
from langgraph.types import Command

from portfolio import default_aggregator, UnifiedPortfolio
from analyst import default_analyst, TargetAllocation
from rebalance import default_rebalancer, RebalancePlan
from agent import build_agent_graph

logger = logging.getLogger(__name__)


class AutonomousWealthOrchestrator:
    """통합 자산조회(L1) -> 시장분석/전략(L2) -> 리밸런싱(L3) -> 안전실행(L4)을 연결하는 총괄 오케스트레이터"""

    def __init__(self):
        self.aggregator = default_aggregator
        self.analyst = default_analyst
        self.rebalancer = default_rebalancer
        self.execution_graph = build_agent_graph()

    def run_rebalance_cycle(
        self,
        strategy_preset: Optional[str] = "growth",
        user_preference: Optional[str] = None,
        custom_targets: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        리밸런싱 분석부터 주문 계획 생성까지 수행합니다.
        (HITL 승인 전 단계까지의 결과 요약 반환)
        """
        # 1. Layer 1: 통합 자산 조회
        portfolio: UnifiedPortfolio = self.aggregator.fetch_all()

        # 2. Layer 2: 목표 배분 전략 결정
        if custom_targets:
            target_alloc = TargetAllocation(
                strategy_name="사용자 커스텀 배분",
                rationales=["사용자가 직접 지정한 목표 포트폴리오 비중입니다."],
                target_weights=custom_targets,
            )
        elif user_preference:
            target_alloc = self.analyst.analyze_and_propose(
                user_preference,
                current_portfolio_summary=f"총자산 {portfolio.total_net_worth:,.0f}원, 현금비중 {portfolio.cash_ratio*100:.1f}%, 보유: {portfolio.stock_weights}",
            )
        else:
            target_alloc = self.analyst.get_preset_strategy(strategy_preset or "growth")

        # 3. Layer 3: 리밸런싱 델타 계산
        plan: RebalancePlan = self.rebalancer.calculate_plan(
            portfolio, target_alloc.target_weights
        )

        return {
            "portfolio": portfolio,
            "target_allocation": target_alloc,
            "rebalance_plan": plan,
            "natural_memo": plan.natural_language_memo,
        }


default_orchestrator = AutonomousWealthOrchestrator()
