import uuid
import pytest
from langgraph.types import Command

from portfolio import default_aggregator, NHBrokerAdapter
from rebalance import default_rebalancer
from agent import build_agent_graph
from broker import default_broker


def test_full_autonomous_rebalance_e2e_flow():
    """Layer 1(자산조회) -> Layer 3(리밸런싱 계산) -> Layer 4(가드검증 & HITL 실행) 전체 파이프라인 E2E 검증"""
    default_broker.dry_run = True
    # 1. Layer 1: 통합 자산 조회
    portfolio = default_aggregator.fetch_all()
    assert portfolio.total_net_worth > 0

    # 2. Layer 3: 리밸런싱 계획 도출 (삼성전자 줄이고 S&P500 확대)
    targets = {
        "005930": 0.10,  # 삼성전자 10%
        "360750": 0.25,  # TIGER 미국S&P500 25%
    }
    plan = default_rebalancer.calculate_plan(portfolio, targets)
    assert len(plan.proposals) >= 1
    memo = plan.natural_language_memo
    assert len(memo) > 5

    # 3. Layer 4: LangGraph 파이프라인에 자연어 메모 주입
    graph = build_agent_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 1단계 실행: parse -> risk_guard -> human_approval(interrupt)
    list(graph.stream({"raw_memo": memo}, config=config))

    state = graph.get_state(config)
    assert state.next == ("human_approval",)
    assert len(state.values["validated_orders"]) >= 1

    # 4. 사용자 명시적 승인 (HITL Command resume)
    list(graph.stream(Command(resume={"approved": True}), config=config))

    final_state = graph.get_state(config)
    assert final_state.next == ()  # 실행 완료

    exec_results = final_state.values["execution_results"]
    assert len(exec_results) >= 1
    assert all(r["status"] == "SUCCESS" for r in exec_results)
    assert all(r["order_no"].startswith("MOCK-") for r in exec_results)
