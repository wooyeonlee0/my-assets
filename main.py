import sys
import uuid
import subprocess
from langgraph.types import Command

from portfolio import default_aggregator, UnifiedPortfolio
from analyst import default_analyst, PRESET_STRATEGIES
from rebalance import default_rebalancer, RebalancePlan
from agent import build_agent_graph

# Windows 콘솔 UTF-8 인코딩 설정
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


def run_memo_pipeline(memo: str, auto_approve: bool = False):
    """자연어 메모를 전달받아 HITL 승인 및 브로커 전송 파이프라인을 실행합니다."""
    graph = build_agent_graph()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print("\n" + "=" * 65)
    print(f"📝 입력된 매매 메모: {memo}")
    print("=" * 65)

    events = graph.stream({"raw_memo": memo}, config=config, stream_mode="updates")

    interrupted = False
    interrupt_payload = None

    for event in events:
        for node_name, node_output in event.items():
            if node_name == "parse_memo":
                parsed = node_output.get("parsed_orders", [])
                print(f"\n[1/4 LLM 파싱 완료] 추출된 주문: {len(parsed)}건")
                for p in parsed:
                    print(f"  - {p.get('stock_name')} | {p.get('action')} {p.get('quantity')}주 | 유형:{p.get('order_type')} | 가격:{p.get('price'):,}원")

            elif node_name == "risk_guard":
                val = node_output.get("validated_orders", [])
                rej = node_output.get("rejected_orders", [])
                print(f"\n[2/4 리스크 가드 검증 완료] 통과: {len(val)}건, 차단: {len(rej)}건")
                for v in val:
                    print(f"  ✅ [통과] {v['stock_name']}({v['stock_code']}) {v['action']} {v['quantity']}주 (예상금액: {v['estimated_amount']:,}원)")
                for r in rej:
                    print(f"  ❌ [차단] {r.get('order', {}).get('stock_name')}: {r.get('reason')}")

    state_snapshot = graph.get_state(config)
    if state_snapshot.next and "human_approval" in state_snapshot.next:
        interrupted = True
        if state_snapshot.tasks:
            for task in state_snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_payload = task.interrupts[0].value
                    break

    if not interrupted:
        print("\nℹ️  실행 가능한 유효 주문이 없어 프로세스가 종료되었습니다.")
        return

    print("\n" + "-" * 65)
    print("🛑 [HITL Gate] 사람 승인 대기 (Human Approval Required)")
    if interrupt_payload and "prompt" in interrupt_payload:
        print(interrupt_payload["prompt"])
    print("-" * 65)

    if auto_approve:
        user_choice = "y"
        print(">> [자동 승인 모드] 승인(y)으로 진행합니다.")
    else:
        try:
            user_choice = input("\n위 주문을 NH투자증권 API로 전송하시겠습니까? (y/n, 기본 n): ").strip().lower()
        except EOFError:
            user_choice = "n"

    approved = user_choice in ("y", "yes", "true", "승인")
    print(f"\n>> 사용자 결정: {'승인 완료 (Approved)' if approved else '주문 취소/거절 (Rejected)'}")

    resume_events = graph.stream(
        Command(resume={"approved": approved}),
        config=config,
        stream_mode="updates",
    )

    for event in resume_events:
        for node_name, node_output in event.items():
            if node_name == "execute_broker":
                results = node_output.get("execution_results", [])
                print(f"\n[4/4 브로커 전송 결과] 총 {len(results)}건 처리됨")
                for r in results:
                    status = r.get("status")
                    order_no = r.get("order_no") or "-"
                    msg = r.get("response_message") or ""
                    code = r.get("response_code") or ""
                    print(f"  {'🎉' if status == 'SUCCESS' else '⚠️'} [{status}] {r.get('stock_name')} | 주문번호: {order_no} | 코드: {code} | 메시지: {msg}")

    print("\n" + "=" * 65)
    print("✨ 파이프라인 처리가 완료되었습니다.")
    print("=" * 65 + "\n")


def run_full_rebalance_flow():
    """Layer 1 자산조회 -> Layer 2 전략 선택 -> Layer 3 리밸런싱 계산 -> Layer 4 주문 실행"""
    print("\n" + "=" * 65)
    print("  [Layer 1] 3대 증권사(나무, 삼성증권, 토스증권) 통합 자산 조회")
    print("=" * 65)

    portfolio: UnifiedPortfolio = default_aggregator.fetch_all()
    print(f"  총 순자산 (Total NAV): {portfolio.total_net_worth:,.0f}원")
    print(f"  보유 현금 (예수금):     {portfolio.total_cash:,.0f}원 (현금비중: {portfolio.cash_ratio*100:.1f}%)")

    print("\n[증권사별 계좌 현황]")
    for acc in portfolio.accounts:
        print(f"  🏢 [{acc.broker_name}] {acc.account_no} ({acc.account_type}): 총 {acc.total_eval_amount:,.0f}원 (현금: {acc.deposit_cash:,.0f}원)")

    print("\n[통합 보유 종목]")
    for p in portfolio.consolidated_positions:
        print(f"  - {p.stock_name}({p.stock_code}): {p.quantity}주 | 평가금 {p.eval_amount:,.0f}원 | 수익률 {p.profit_rate:+.1f}% (비중 {(p.eval_amount/portfolio.total_net_worth*100):.1f}%)")

    print("\n" + "=" * 65)
    print("  [Layer 2] 목표 배분 전략 선택")
    print("=" * 65)
    presets = list(PRESET_STRATEGIES.keys())
    for idx, k in enumerate(presets, 1):
        strat = PRESET_STRATEGIES[k]
        print(f"  {idx}. {strat.name} - {strat.description}")

    try:
        strat_choice = input("\n원하는 전략 번호를 선택하세요 (기본 1): ").strip()
    except EOFError:
        strat_choice = "1"

    key = presets[int(strat_choice) - 1] if strat_choice in ("1", "2", "3") else presets[0]
    target_weights = PRESET_STRATEGIES[key].target_weights

    print("\n" + "=" * 65)
    print("  [Layer 3] 리밸런싱 델타 및 1주 단위 주문 산출 중...")
    print("=" * 65)

    plan: RebalancePlan = default_rebalancer.calculate_plan(portfolio, target_weights)
    print(f"  총 매도 예정액: {plan.total_sell_amount:,.0f}원")
    print(f"  총 매수 예정액: {plan.total_buy_amount:,.0f}원")
    print(f"  순 현금 변동:   {plan.net_cash_flow:+,.0f}원")

    if not plan.proposals:
        print("\n💡 현재 포트폴리오가 목표 비중과 일치하여 추가 주문이 필요 없습니다.")
        return

    print("\n[제안된 주문]")
    for p in plan.proposals:
        print(f"  * {p.action} {p.stock_name} {p.quantity}주 (예상: {p.estimated_amount:,.0f}원) - {p.reason}")

    print(f"\n📝 자동 생성된 매매 메모: '{plan.natural_language_memo}'")

    # Layer 4 실행 파이프라인 호출
    run_memo_pipeline(plan.natural_language_memo)


def main():
    print("=" * 65)
    print("  NH투자증권 나무 PLUG API 기반 자산관리 & ISA 주식 매매 Agent")
    print("=" * 65)
    print("  1. 🔄 전체 통합 자산 조회 및 포트폴리오 자동 리밸런싱 실행 (전체 플로우)")
    print("  2. 📝 단일 자연어 매매 메모 입력 및 안전 주문 실행 (Layer 4 단독)")
    print("  3. 🌐 Streamlit 웹 대시보드 브라우저 실행")
    print("=" * 65)

    try:
        mode = input("\n실행할 모드를 선택하세요 (기본 1): ").strip()
    except EOFError:
        mode = "1"

    if mode == "2":
        sample_memos = [
            "삼성전자 5주 시장가로 매수하고, TIGER 미국S&P500 10주 사줘.",
            "카카오 10주 신용으로 매수해줘.",
            "애플 AAPL 10주 매수해줘.",
            "삼성전자 100주 75000원에 매수해줘.",
        ]
        print("\n[샘플 메모 목록]")
        for i, s in enumerate(sample_memos, 1):
            print(f"  {i}. {s}")
        print("  0. 직접 메모 입력")
        try:
            choice = input("\n원하는 번호를 선택하세요 (기본 1): ").strip()
        except EOFError:
            choice = "1"
        memo = sample_memos[int(choice) - 1] if choice in ("1", "2", "3", "4") else (input("메모 입력: ").strip() if choice == "0" else sample_memos[0])
        run_memo_pipeline(memo)

    elif mode == "3":
        print("\n🌐 Streamlit 웹 대시보드를 브라우저에서 실행합니다...")
        print("실행 명령: streamlit run streamlit_app.py")
        subprocess.run(["streamlit", "run", "streamlit_app.py"])

    else:
        run_full_rebalance_flow()


if __name__ == "__main__":
    main()
