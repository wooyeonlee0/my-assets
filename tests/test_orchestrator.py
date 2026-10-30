import pytest
from orchestrator import AutonomousWealthOrchestrator


def test_orchestrator_default_rebalance_cycle():
    """오케스트레이터의 기본 리밸런싱 사이클 동작 검증"""
    orchestrator = AutonomousWealthOrchestrator()
    res = orchestrator.run_rebalance_cycle(strategy_preset="growth")

    assert "portfolio" in res
    assert "target_allocation" in res
    assert "rebalance_plan" in res
    assert "natural_memo" in res

    assert res["portfolio"].total_net_worth > 0
    assert len(res["natural_memo"]) > 0


def test_orchestrator_custom_targets():
    """사용자 지정 커스텀 목표 비중을 주었을 때의 오케스트레이션 검증"""
    orchestrator = AutonomousWealthOrchestrator()
    custom_targets = {"005930": 0.20, "360750": 0.50, "CASH": 0.30}

    res = orchestrator.run_rebalance_cycle(custom_targets=custom_targets)
    assert res["target_allocation"].strategy_name == "사용자 커스텀 배분"
    assert res["target_allocation"].target_weights == custom_targets
    assert len(res["rebalance_plan"].proposals) >= 1
