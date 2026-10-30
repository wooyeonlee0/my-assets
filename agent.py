import os
import re
import logging
from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from broker import default_broker, NHBroker
from risk_guard import default_risk_guard, ISARiskGuard

logger = logging.getLogger(__name__)


# =====================================================================
# 1. Schemas & State Definition
# =====================================================================
class ParsedOrder(BaseModel):
    stock_name: str = Field(description="종목명 또는 단축코드")
    action: str = Field(description="'BUY'(매수) 또는 'SELL'(매도)")
    quantity: int = Field(gt=0, description="주문 수량 (주)")
    order_type: str = Field(description="'01'(시장가) 또는 '00'(지정가)")
    price: Optional[int] = Field(default=0, description="지정가 단가 (원)")
    credit_type: Optional[str] = Field(default="CASH", description="'CASH' 또는 'CREDIT'")
    notes: Optional[str] = Field(default=None, description="메모 부가설명")


class ParsedOrderList(BaseModel):
    orders: List[ParsedOrder] = Field(default_factory=list)


class AgentState(TypedDict):
    raw_memo: str
    parsed_orders: List[Dict[str, Any]]
    validated_orders: List[Dict[str, Any]]
    rejected_orders: List[Dict[str, Any]]
    approval_status: Optional[Dict[str, Any]]
    execution_results: List[Dict[str, Any]]


# =====================================================================
# 2. Pipeline Nodes
# =====================================================================
SYSTEM_PROMPT = """당신은 한국 주식 및 중개형 ISA 계좌 매매 메모를 분석하여 주문 데이터로 변환하는 금융 파싱 AI입니다.
사용자의 자연어 매매 메모에서 주문 정보를 추출하여 ParsedOrderList로 반환하세요:
- stock_name: 종목명 (예: 삼성전자, 카카오, TIGER 미국S&P500)
- action: 'BUY'(매수/사줘) 또는 'SELL'(매도/팔아줘)
- quantity: 주문 수량 (1 이상의 정수)
- order_type: '01'(시장가, 가격 명시 없음 등), '00'(지정가, 특정 가격 명시)
- price: 지정가 단가 (원 단위 정수). 시장가인 경우 0. (예: "7만원" -> 70000)
- credit_type: 'CASH'(현금) 또는 'CREDIT'(신용/미수/융자 언급 시)
- notes: 비고
"""


def _rule_based_fallback_parser(memo: str) -> List[Dict[str, Any]]:
    """OpenAI API 키 부재 또는 예외 시 동작하는 안전한 기본 파서"""
    orders = []
    # 쉼표, 마침표, 줄바꿈, '그리고', '하고', '~매수하고', '~매도하고' 등으로 정밀 분할
    chunks = re.split(r"[\n,\.]+|\s+그리고\s+|\s+하고\s+|(?<=[가-힣])하고\s+|(?<=매수)고\s+|(?<=매도)고\s+", memo)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        action = None
        if any(w in chunk for w in ["매수", "사줘", "사자", "구매", "추매", "담아"]):
            action = "BUY"
        elif any(w in chunk for w in ["매도", "팔아", "팔자", "익절", "손절", "정리"]):
            action = "SELL"
        if not action:
            continue

        qty_match = re.search(r"(\d+)\s*주", chunk)
        quantity = int(qty_match.group(1)) if qty_match else 1
        credit_type = "CREDIT" if any(w in chunk for w in ["신용", "미수", "융자"]) else "CASH"

        is_market = any(w in chunk for w in ["시장가", "현재가", "바로", "즉시"])
        order_type = "01" if is_market else "00"
        price = 0
        if not is_market:
            man_match = re.search(r"([\d\.]+)\s*만\s*원?", chunk)
            num_match = re.search(r"([\d,]+)\s*원", chunk)
            if man_match:
                price = int(float(man_match.group(1)) * 10000)
            elif num_match:
                price = int(num_match.group(1).replace(",", ""))
            else:
                order_type = "01"

        # 수량 및 가격 정보 제거 후 남은 텍스트에서 종목명 추출
        cleaned_chunk = chunk
        for kw in ["신용으로", "미수로", "시장가로", "지정가로", "시장가", "지정가", "현재가로", "바로", "즉시"]:
            cleaned_chunk = cleaned_chunk.replace(kw, " ")
        cleaned_chunk = re.sub(r"(\d+)\s*주", " ", cleaned_chunk)
        cleaned_chunk = re.sub(r"([\d\.]+)\s*만\s*원?", " ", cleaned_chunk)
        cleaned_chunk = re.sub(r"([\d,]+)\s*원", " ", cleaned_chunk)
        for act_kw in ["매수해줘", "매도해줘", "매수하자", "매도하자", "매수", "매도", "사줘", "사자", "팔아줘", "팔자", "구매", "추매", "익절", "손절", "정리"]:
            cleaned_chunk = cleaned_chunk.replace(act_kw, " ")

        stock_name = cleaned_chunk.strip()
        if not stock_name:
            stock_name = "미상"

        orders.append({
            "stock_name": stock_name,
            "action": action,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "credit_type": credit_type,
            "notes": chunk,
        })
    return orders


def parse_memo_node(state: AgentState) -> Dict[str, Any]:
    """자연어 메모에서 주문 파라미터 추출 노드"""
    memo = state.get("raw_memo", "")
    api_key = os.getenv("OPENAI_API_KEY", "")

    if api_key and not api_key.startswith("your-"):
        try:
            llm = ChatOpenAI(model="gpt-4o", temperature=0.0, api_key=api_key)
            structured_llm = llm.with_structured_output(ParsedOrderList)
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=memo),
            ]
            result = structured_llm.invoke(messages)
            parsed_orders = [o.model_dump() for o in result.orders]
            return {"parsed_orders": parsed_orders}
        except Exception as e:
            logger.warning(f"[parse_memo_node] LLM 파싱 오류 -> Fallback: {e}")

    # Fallback
    fallback_orders = _rule_based_fallback_parser(memo)
    return {"parsed_orders": fallback_orders}


def risk_guard_node(state: AgentState) -> Dict[str, Any]:
    """Taur-ai / TradingAgents 콘셉트: 3대 안전 가드(티커, ISA제약, 금액한도) 검증 노드"""
    parsed_orders = state.get("parsed_orders", [])
    validated, rejected = default_risk_guard.evaluate_orders(parsed_orders)
    return {
        "validated_orders": validated,
        "rejected_orders": rejected,
    }


def human_approval_node(state: AgentState) -> Dict[str, Any]:
    """LoganYangBo / rh-trading-agent & LangGraph 공식 HITL 콘셉트: 주문 직전 승인 인터럽트 노드"""
    validated_orders = state.get("validated_orders", [])
    rejected_orders = state.get("rejected_orders", [])

    if not validated_orders:
        return {
            "approval_status": {
                "approved": False,
                "reason": "검증을 통과한 유효 주문이 없습니다.",
            }
        }

    # 사용자 프롬프트 구성
    summary = ["\n[HITL Gate] 주문 실행 전 사용자 승인 요청"]
    for idx, o in enumerate(validated_orders, 1):
        type_str = "시장가" if o["order_type"] == "01" else f"지정가({o['price']:,}원)"
        summary.append(
            f"  {idx}. {o['stock_name']}({o['stock_code']}) | {o['action']} {o['quantity']}주 | {type_str} | 예상: {o['estimated_amount']:,}원"
        )
    if rejected_orders:
        summary.append("  [차단된 주문]")
        for r in rejected_orders:
            summary.append(f"  - {r.get('order', {}).get('stock_name')}: {r.get('reason')}")

    # LangGraph interrupt로 실행 일시정지
    approval_resp = interrupt({
        "prompt": "\n".join(summary),
        "validated_orders": validated_orders,
        "rejected_orders": rejected_orders,
    })

    # resume 값 처리
    is_approved = False
    if isinstance(approval_resp, dict):
        is_approved = bool(approval_resp.get("approved", False))
    elif isinstance(approval_resp, bool):
        is_approved = approval_resp
    elif isinstance(approval_resp, str):
        is_approved = approval_resp.strip().lower() in ("y", "yes", "true", "승인")

    return {
        "approval_status": {
            "approved": is_approved,
        }
    }


def execute_broker_node(state: AgentState) -> Dict[str, Any]:
    """승인된 주문을 NH투자증권 브로커(broker.py)로 전송하는 노드"""
    approval = state.get("approval_status") or {}
    if not approval.get("approved"):
        return {"execution_results": [{"status": "SKIPPED", "reason": "사용자 미승인"}]}

    validated_orders = state.get("validated_orders", [])
    results = []

    for order in validated_orders:
        res = default_broker.send_order(
            stock_code=order["stock_code"],
            action=order["action"],
            quantity=order["quantity"],
            order_type=order["order_type"],
            price=order["price"],
            estimated_amount=order["estimated_amount"],
        )
        res["stock_name"] = order["stock_name"]
        results.append(res)

    return {"execution_results": results}


# =====================================================================
# 3. LangGraph Workflow DAG
# =====================================================================
def route_after_risk_guard(state: AgentState) -> str:
    """통과된 주문이 없으면 바로 종료"""
    if not state.get("validated_orders"):
        return END
    return "human_approval"


def route_after_approval(state: AgentState) -> str:
    """사용자가 승인한 경우에만 브로커 실행 노드로 진입"""
    approval = state.get("approval_status") or {}
    if approval.get("approved"):
        return "execute_broker"
    return END


def build_agent_graph(checkpointer: Optional[MemorySaver] = None):
    """LangGraph 기반 ISA 주식 매매 보조 에이전트 생성"""
    if checkpointer is None:
        checkpointer = MemorySaver()

    builder = StateGraph(AgentState)

    builder.add_node("parse_memo", parse_memo_node)
    builder.add_node("risk_guard", risk_guard_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("execute_broker", execute_broker_node)

    builder.add_edge(START, "parse_memo")
    builder.add_edge("parse_memo", "risk_guard")
    builder.add_conditional_edges("risk_guard", route_after_risk_guard, ["human_approval", END])
    builder.add_conditional_edges("human_approval", route_after_approval, ["execute_broker", END])
    builder.add_edge("execute_broker", END)

    return builder.compile(checkpointer=checkpointer)


# 기본 그래프
app_graph = build_agent_graph()
