import logging
from typing import Dict, List, Optional
from portfolio.models import UnifiedPortfolio, Position
from rebalance.models import OrderProposal, RebalancePlan
from risk_guard import default_risk_guard

logger = logging.getLogger(__name__)


class RebalanceEngine:
    """목표 포트폴리오 비중과 현재 통합 자산 상태를 비교하여
    최소 거래 단위(1주 정수화) 리밸런싱 주문을 도출하는 엔진
    """

    def __init__(self, threshold_band: float = 0.015):
        """
        Args:
            threshold_band: 불필요한 잦은 매매를 막기 위한 리밸런싱 오차 임계값 (기본 1.5% = 0.015)
        """
        self.threshold_band = threshold_band

    def calculate_plan(
        self,
        portfolio: UnifiedPortfolio,
        target_weights: Dict[str, float],
    ) -> RebalancePlan:
        """
        Args:
            portfolio: 현재 통합 자산 스냅샷
            target_weights: 종목코드(또는 종목명)를 키로 하고 목표 비중(0.0~1.0)을 값으로 하는 딕셔너리
        """
        total_nav = portfolio.total_net_worth
        if total_nav <= 0:
            return RebalancePlan(
                total_net_worth=0,
                proposals=[],
                natural_language_memo="보유 자산이 없어 리밸런싱을 진행할 수 없습니다.",
            )

        # 현재 포지션 룩업 테이블
        pos_by_code: Dict[str, Position] = {
            p.stock_code: p for p in portfolio.consolidated_positions
        }
        pos_by_name: Dict[str, Position] = {
            p.stock_name: p for p in portfolio.consolidated_positions
        }

        # 목표 비중 키를 6자리 표준 코드로 정규화 및 비중 합계 검증
        raw_targets: Dict[str, float] = {}
        total_target_sum = 0.0

        for key, weight in target_weights.items():
            if key.upper() == "CASH":
                continue
            w = max(0.0, float(weight))  # 음수 비중 차단
            code = default_risk_guard.resolve_code(key) or key
            raw_targets[code] = w
            total_target_sum += w

        # 만약 주식 목표 비중 총합이 1.0(100%)을 초과하면 비율대로 안전 정규화 (현금 최소 5% 보존)
        normalized_targets: Dict[str, float] = {}
        max_allowed_stock_weight = 0.95  # 최소 5% 현금 버퍼
        if total_target_sum > max_allowed_stock_weight:
            logger.warning(
                f"[RebalanceEngine] 주식 목표 비중 합계({total_target_sum*100:.1f}%)가 {max_allowed_stock_weight*100:.0f}%를 초과하여 자동 정규화합니다."
            )
            scale = max_allowed_stock_weight / total_target_sum
            for code, w in raw_targets.items():
                normalized_targets[code] = w * scale
        else:
            normalized_targets = raw_targets

        proposals: List[OrderProposal] = []
        all_codes = set(pos_by_code.keys()).union(set(normalized_targets.keys()))

        for code in all_codes:
            pos = pos_by_code.get(code)
            current_val = pos.eval_amount if pos else 0.0
            current_weight = (current_val / total_nav) if total_nav > 0 else 0.0
            target_weight = normalized_targets.get(code, 0.0)

            weight_diff = target_weight - current_weight

            # 임계값 미만 차이는 수수료 방지를 위해 무시
            if abs(weight_diff) < self.threshold_band:
                continue

            # 가격 결정
            stock_name = pos.stock_name if pos else ""
            if not stock_name:
                meta = default_risk_guard._code_to_meta.get(code, {})
                stock_name = meta.get("name", code)

            price = 0
            if pos and pos.current_price > 0:
                price = int(pos.current_price)
            else:
                meta = default_risk_guard._code_to_meta.get(code, {})
                price = int(meta.get("base_price", 0))

            if price <= 0:
                logger.warning(f"[RebalanceEngine] {stock_name}({code})의 단가를 찾을 수 없어 건너뜁니다.")
                continue

            diff_val = (target_weight * total_nav) - current_val

            if diff_val > 0:
                # 매수(BUY)
                action = "BUY"
                raw_qty = diff_val / price
                qty = int(raw_qty)  # 1주 단위 정수 절삭
                if qty <= 0:
                    continue
                est_amount = qty * price
                reason = f"목표 비중({target_weight*100:.1f}%) 대비 부족(+{weight_diff*100:.1f}%)"

            else:
                # 매도(SELL)
                action = "SELL"
                raw_qty = abs(diff_val) / price
                qty = int(raw_qty)
                # 보유 수량 이상 매도 방지 (클리핑)
                cur_qty = pos.quantity if pos else 0
                qty = min(qty, cur_qty)
                if qty <= 0:
                    continue
                est_amount = qty * price
                reason = f"목표 비중({target_weight*100:.1f}%) 대비 초과({weight_diff*100:.1f}%)"

            account_type = pos.account_type if pos else "ISA"
            # 국내 종목/ETF는 ISA 대상
            if default_risk_guard.resolve_code(code):
                account_type = "ISA"

            prop = OrderProposal(
                stock_code=code,
                stock_name=stock_name,
                action=action,
                quantity=qty,
                price=price,
                estimated_amount=est_amount,
                current_weight=round(current_weight, 4),
                target_weight=round(target_weight, 4),
                weight_diff=round(weight_diff, 4),
                target_account_type=account_type,
                reason=reason,
            )
            proposals.append(prop)

        # 매도 주문을 먼저 실행하여 현금을 확보한 후 매수 주문을 하도록 정렬 (매도 -> 매수)
        proposals.sort(key=lambda p: 0 if p.action == "SELL" else 1)

        total_buy = sum(p.estimated_amount for p in proposals if p.action == "BUY")
        total_sell = sum(p.estimated_amount for p in proposals if p.action == "SELL")
        net_cash_flow = total_sell - total_buy

        # Layer 4가 즉시 이해할 수 있는 자연어 매매 메모 생성
        memo_sentences = []
        for p in proposals:
            action_kor = "매도" if p.action == "SELL" else "매수"
            memo_sentences.append(f"{p.stock_name} {p.quantity}주 시장가로 {action_kor}")

        if memo_sentences:
            natural_memo = ", ".join(memo_sentences) + "해줘."
        else:
            natural_memo = "현재 포트폴리오가 목표 비중과 일치하여 추가 리밸런싱 주문이 필요 없습니다."

        return RebalancePlan(
            total_net_worth=total_nav,
            proposals=proposals,
            total_buy_amount=total_buy,
            total_sell_amount=total_sell,
            net_cash_flow=net_cash_flow,
            natural_language_memo=natural_memo,
        )


default_rebalancer = RebalanceEngine()
