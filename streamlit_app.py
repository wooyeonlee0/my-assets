import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import uuid
from langgraph.types import Command

from portfolio import default_aggregator, UnifiedPortfolio
from portfolio.tracker import load_portfolio_history, record_portfolio_snapshot
from analyst import default_analyst, TargetAllocation
from rebalance import default_rebalancer, RebalancePlan
from agent import build_agent_graph

# ---------------------------------------------------------------------
# 1. 반응형 & 모바일 최적화 CSS 인젝션 (더리치 다크 테마 감성)
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Antigravity Wealth & Rebalancing Cockpit",
    page_icon="💎",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* 전체 폰트 및 배경 반응형 설정 */
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    * { font-family: 'Pretendard', sans-serif; }
    
    /* 카드형 컨테이너 스타일 */
    .metric-card {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 18px 22px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        backdrop-filter: blur(10px);
        margin-bottom: 12px;
    }
    .metric-title {
        font-size: 0.82rem;
        color: #94a3b8;
        font-weight: 500;
        letter-spacing: -0.01em;
        margin-bottom: 6px;
    }
    .metric-value {
        font-size: 1.55rem;
        font-weight: 700;
        color: #f8fafc;
        letter-spacing: -0.02em;
    }
    .metric-sub {
        font-size: 0.75rem;
        color: #38bdf8;
        margin-top: 4px;
    }

    /* 테이블 가로 스크롤 보호 (폭 줄었을 때 글자 깨짐 방지) */
    .stDataFrame {
        width: 100% !important;
        overflow-x: auto !important;
    }
    
    /* 탭 헤더 여백 및 텍스트 줄바꿈 방지 */
    button[data-baseweb="tab"] {
        white-space: nowrap !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 2. 데이터 수집 (통합 자산 및 시계열 트래킹 히스토리)
# ---------------------------------------------------------------------
portfolio: UnifiedPortfolio = default_aggregator.fetch_all()
history = load_portfolio_history()

# 헤더 타이틀
st.markdown("### 💎 포트폴리오 자산 트래커 & 리밸런싱 관제탑")
st.caption("더리치(The Rich) 앱 자산 연동 · 시계열 변동 추적 · Antigravity 맞춤 리밸런싱 파이프라인")

# ---------------------------------------------------------------------
# 3. 최상단 핵심 요약 지표 (반응형 카드 4분할)
# ---------------------------------------------------------------------
m_col1, m_col2, m_col3, m_col4 = st.columns([1.2, 1, 1, 1])

# 최근 자산 변동폭 계산
first_val = history[0]["total_net_worth"] if history else portfolio.total_net_worth
total_gain = portfolio.total_net_worth - first_val
gain_pct = (total_gain / first_val * 100) if first_val > 0 else 0.0

with m_col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">총 순자산가치 (Total NAV)</div>
        <div class="metric-value">₩{portfolio.total_net_worth:,.0f}</div>
        <div class="metric-sub">▲ +₩{total_gain:,.0f} (+{gain_pct:.1f}%) 추적 기간 누적</div>
    </div>
    """, unsafe_allow_html=True)

with m_col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">보유 현금 유동성 (예수금)</div>
        <div class="metric-value">₩{portfolio.total_cash:,.0f}</div>
        <div class="metric-sub">비중 {portfolio.cash_ratio * 100:.2f}% (원화 + USD)</div>
    </div>
    """, unsafe_allow_html=True)

with m_col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">연동 계좌 현황</div>
        <div class="metric-value">{len(portfolio.accounts)}개 연동 (2개 대기)</div>
        <div class="metric-sub">토스증권(실자산) / NH나무(API)</div>
    </div>
    """, unsafe_allow_html=True)

with m_col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">월 예상 배당금 (추정)</div>
        <div class="metric-value">₩350,000</div>
        <div class="metric-sub">연간 약 420만원 (시가배당률 0.6%)</div>
    </div>
    """, unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 4. 메인 뷰: [1] 자산 구성(더리치 뷰) / [2] 시계열 변동 추적 / [3] 전략 리밸런싱
# ---------------------------------------------------------------------
tab_rich, tab_history, tab_rebalance, tab_accounts = st.tabs([
    "🍩 더리치 자산 구성 (Asset Allocation)",
    "📈 기간별 자산 변동 추적 (History Trend)",
    "⚖️ 전략 리밸런싱 실행 (Cockpit)",
    "📑 계좌별 상세 포지션 (Accounts)",
])

# ---------------------------------------------------------------------
# 탭 1: 더리치 자산 구성 (도넛 차트 & 상세 비중)
# ---------------------------------------------------------------------
with tab_rich:
    c_chart, c_table = st.columns([1.1, 1])

    # 포지션 데이터 프레임 준비
    pos_data = []
    for p in portfolio.consolidated_positions:
        pos_data.append({
            "종목명": p.stock_name,
            "티커": p.stock_code,
            "평가금액": p.eval_amount,
            "비중(%)": round(p.eval_amount / portfolio.total_net_worth * 100, 2),
            "자산군": p.asset_class,
        })
    pos_df = pd.DataFrame(pos_data).sort_values(by="평가금액", ascending=False)

    with c_chart:
        st.markdown("##### 🍩 포트폴리오 도넛 비중 분석")
        
        # 더리치 스타일 인터랙티브 Plotly 도넛 차트
        fig_donut = px.pie(
            pos_df,
            values="평가금액",
            names="종목명",
            hole=0.55,
            color_discrete_sequence=px.colors.qualitative.Prism,
        )
        fig_donut.update_traces(
            textposition='inside',
            textinfo='percent+label',
            hovertemplate="<b>%{label}</b><br>평가액: ₩%{value:,.0f}<br>비중: %{percent:.1%}<extra></extra>",
        )
        fig_donut.update_layout(
            margin=dict(t=20, b=20, l=10, r=10),
            height=390,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with c_table:
        st.markdown("##### 📋 종목별 평가금액 및 보유 비중")
        display_df = pos_df[["종목명", "티커", "평가금액", "비중(%)"]].copy()
        display_df["평가금액"] = display_df["평가금액"].apply(lambda v: f"₩{v:,.0f}")
        display_df["비중(%)"] = display_df["비중(%)"].apply(lambda v: f"{v:.1f}%")
        st.dataframe(display_df, use_container_width=True, height=360)

# ---------------------------------------------------------------------
# 탭 2: 기간별 자산 변동 추적 (History Trend)
# ---------------------------------------------------------------------
with tab_history:
    st.markdown("##### 📈 시점별 총 순자산 변동 추이 (Net Worth Over Time)")
    
    hist_df = pd.DataFrame(history)
    hist_df["총자산(억원)"] = hist_df["total_net_worth"] / 100000000.0

    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=hist_df["timestamp"],
        y=hist_df["총자산(억원)"],
        mode='lines+markers+text',
        text=[f"{v:.2f}억" for v in hist_df["총자산(억원)"]],
        textposition="top center",
        line=dict(color='#38bdf8', width=3),
        marker=dict(size=8, color='#0284c7'),
        fill='tozeroy',
        fillcolor='rgba(56, 189, 248, 0.08)',
        hovertemplate="<b>시점: %{x}</b><br>총자산: %{y:.3f} 억원<extra></extra>",
    ))
    fig_line.update_layout(
        margin=dict(t=30, b=30, l=20, r=20),
        height=320,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.08)', title="억원 단위"),
    )
    st.plotly_chart(fig_line, use_container_width=True)

    # 신규 시점 자산 스냅샷 수동 기록 기능
    with st.expander("📸 현재 자산 상태를 새로운 스냅샷으로 저장/기록하기"):
        snapshot_note = st.text_input("기록 메모 (예: 11월 초 미국 대선 직전 포트폴리오)", value="정기 포트폴리오 기록")
        if st.button("💾 현재 자산 상태 히스토리에 기록"):
            record_portfolio_snapshot(
                total_net_worth=portfolio.total_net_worth,
                total_cash=portfolio.total_cash,
                cash_ratio=portfolio.cash_ratio,
                stock_weights=portfolio.stock_weights,
                note=snapshot_note,
            )
            st.success("새로운 시점의 자산 스냅샷이 히스토리에 영구 저장되었습니다! 페이지를 새로고침하면 반영됩니다.")

# ---------------------------------------------------------------------
# 탭 3: 전략 리밸런싱 실행 (Cockpit)
# ---------------------------------------------------------------------
with tab_rebalance:
    st.markdown("##### ⚖️ 투자 계획서 기반 실전 리밸런싱 관제탑")

    default_plan_text = """2026년 11월 미국 중간선거 대응 실전 포트폴리오 운용 계획:
- 미국 헬스케어 ETF (XLV): 25% (양방향 방패)
- 미국 전력 인프라 (GEV): 20% (초당적 수혜)
- 미국 20년+ 국채 ETF (TLT): 25% (금리/유가 저평가)
- 한국 대형 수출주 삼성전자 (005930): 15% (관세 소멸 스윙)
- 현금성 유동성 (CASH): 15% (대기 자금)
기존 보유 중인 기타 종목(하이닉스, 네이버, 카니발 등)은 전량 매도하여 현금화."""

    plan_input = st.text_area("투자 계획서 전문 입력", value=default_plan_text, height=130)

    # 기본 중간선거 타겟 세팅
    default_targets = {
        "XLV": 0.25,
        "GEV": 0.20,
        "TLT": 0.25,
        "005930": 0.15,
        "CASH": 0.15,
    }

    if st.button("⚡ 7억 자산 스케일 1주 단위 리밸런싱 계산 실행", type="primary"):
        plan: RebalancePlan = default_rebalancer.calculate_plan(portfolio, default_targets)
        st.session_state["active_plan"] = plan

    if "active_plan" in st.session_state:
        plan: RebalancePlan = st.session_state["active_plan"]

        r1, r2, r3 = st.columns(3)
        r1.metric("총 매도 예정액 (현금 확보)", f"₩{plan.total_sell_amount:,.0f}")
        r2.metric("총 매수 예정액 (신규 진입)", f"₩{plan.total_buy_amount:,.0f}")
        r3.metric("순 현금 변동", f"{plan.net_cash_flow:+,.0f} 원")

        if plan.proposals:
            st.markdown("##### 📋 제안된 1주 단위 매매 계획표")
            prop_data = []
            for p in plan.proposals:
                route_badge = "🇰🇷 NH나무 ISA" if p.target_account_type == "ISA" else "🇺🇸 토스/삼성 해외위탁"
                prop_data.append({
                    "액션": "🔴 매도(SELL)" if p.action == "SELL" else "🔵 매수(BUY)",
                    "종목명": p.stock_name,
                    "티커": p.stock_code,
                    "주문수량": f"{p.quantity:,}주",
                    "단가": f"₩{p.price:,.0f}",
                    "예상총액": f"₩{p.estimated_amount:,.0f}",
                    "현재비중": f"{p.current_weight * 100:.1f}%",
                    "목표비중": f"{p.target_weight * 100:.1f}%",
                    "배정계좌": route_badge,
                    "사유": p.reason,
                })
            st.dataframe(pd.DataFrame(prop_data), use_container_width=True)

            st.info(f"📝 **생성된 매매 메모:** `{plan.natural_language_memo}`")

# ---------------------------------------------------------------------
# 탭 4: 계좌별 상세 포지션 (연동 vs 지원가능 증권사 구분)
# ---------------------------------------------------------------------
with tab_accounts:
    st.markdown("##### 🟢 실제 연동된 계좌 (Connected Accounts)")
    st.caption("실제 API 키 또는 사용자가 제공한 실데이터 포트폴리오가 연동되어 총자산에 반영되는 계좌입니다.")
    
    for acc in portfolio.accounts:
        acc_label = f"🏢 [{acc.broker_name}] {acc.account_no} ({acc.account_type}) - 총 ₩{acc.total_eval_amount:,.0f} (예수금 ₩{acc.deposit_cash:,.0f})"
        with st.expander(acc_label, expanded=True):
            if acc.positions:
                acc_rows = [
                    {
                        "종목코드": p.stock_code,
                        "종목명": p.stock_name,
                        "보유수량": f"{p.quantity:,}주",
                        "평가금액": f"₩{p.eval_amount:,.0f}",
                        "수익률": f"{p.profit_rate:+.1f}%",
                        "자산군": p.asset_class,
                    }
                    for p in acc.positions
                ]
                st.dataframe(pd.DataFrame(acc_rows), use_container_width=True)
            else:
                st.info("현재 보유 주식이 없거나, 증권사 전산 정책(중개형 ISA API 직접 조회 제한 등)으로 보유 주식을 불러올 수 없습니다.")

    st.markdown("---")
    st.markdown("##### ⚪ 시스템 지원 가능 증권사 (미연동 / Supported Brokers)")
    st.caption("시스템 코드로 어댑터가 완비되어 있으나, 아직 사용자님의 계좌나 API 키가 연동되지 않은 증권사입니다. (총자산 합산에서 제외)")

    sup_col1, sup_col2 = st.columns(2)
    with sup_col1:
        st.markdown("""
        <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 15px;">한국투자증권 (KIS Developers)</span>
                <span style="background-color: #3b82f6; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">이전 대기</span>
            </div>
            <div style="color: #94a3b8; font-size: 13px; margin-top: 6px;">
                • 중개형 ISA (<code>isa_yn='Y'</code>) 및 연금저축 전용 API 지원<br>
                • 계좌 개설 후 API Key 등록 시 즉시 실전 주문 연동 활성화
            </div>
        </div>
        """, unsafe_allow_html=True)

    with sup_col2:
        st.markdown("""
        <div style="background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-weight: 700; color: #f8fafc; font-size: 15px;">삼성증권 (Samsung Securities)</span>
                <span style="background-color: #64748b; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">미연동</span>
            </div>
            <div style="color: #94a3b8; font-size: 13px; margin-top: 6px;">
                • 일반 위탁 / 국내외 주식 스냅샷 및 잔고 연동 지원 가능<br>
                • 현재 등록된 계좌 정보 없음 (총자산 합산 제외)
            </div>
        </div>
        """, unsafe_allow_html=True)
