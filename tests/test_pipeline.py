import uuid
import pytest
from langgraph.types import Command
from agent import build_agent_graph
from broker import default_broker


def test_pipeline_approval_flow():
    """HITL 게이트에서 사용자가 승인(approved=True)했을 때 주문 실행 테스트"""
    default_broker.dry_run = True
    graph = build_agent_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    memo = "삼성전자 5주 60000원에 매수해줘."

    # 1단계: 실행 시작 -> human_approval 노드에서 interrupt 발생
    list(graph.stream({"raw_memo": memo}, config=config))

    state = graph.get_state(config)
    assert state.next == ("human_approval",)
    assert len(state.values["validated_orders"]) == 1
    assert state.values["validated_orders"][0]["stock_code"] == "005930"

    # 2단계: 승인 전송 (Command resume)
    events = list(graph.stream(Command(resume={"approved": True}), config=config))
    final_state = graph.get_state(config)

    assert final_state.next == ()  # 완료(END)
    assert len(final_state.values["execution_results"]) == 1
    assert final_state.values["execution_results"][0]["status"] == "SUCCESS"


def test_pipeline_rejection_flow():
    """HITL 게이트에서 사용자가 거절(approved=False)했을 때 주문 미실행 테스트"""
    graph = build_agent_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    memo = "삼성전자 5주 60000원에 매수해줘."

    # 1단계: 실행 -> interrupt
    list(graph.stream({"raw_memo": memo}, config=config))

    # 2단계: 거절 전송
    list(graph.stream(Command(resume={"approved": False}), config=config))
    final_state = graph.get_state(config)

    assert final_state.next == ()
    assert final_state.values.get("execution_results") is None or all(
        r.get("status") == "SKIPPED" for r in final_state.values.get("execution_results", [])
    )
